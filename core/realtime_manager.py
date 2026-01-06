# core/realtime_manager.py
import asyncio
import logging
import json
from typing import Dict, List, Optional
import websockets
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

# --- CAMBIO: Usar librería 'ta' estándar en lugar de 'pandas-ta' ---
from ta.volatility import AverageTrueRange
# ------------------------------------------------------------------

from core.config import settings
from db.session import SessionLocal
from services.strategy_service import StrategyService
from trading.exchange_service import exchange_service_instance
# Nota: Asegúrate de que BaseStrategy no importe pandas-ta dentro
from trading.strategies.base_strategy import BaseStrategy
from services.backtesting_service import STRATEGY_MAP, ATR_COL_FOR_SLIPPAGE, INITIAL_CAPITAL, DEFAULT_RISK_PER_TRADE
from db.live_position_repository import LivePositionRepository
from schemas.live_position import LivePositionCreate, PositionSideSchema

logger = logging.getLogger(__name__)

# --- Estado Global y Constantes ---
recent_market_data: Dict[str, pd.DataFrame] = {}
bot_status: str = "STOPPED"
MAX_RECENT_CANDLES: int = 500
MIN_ORDER_SIZE_USDT: float = 10.0
BINANCE_SPOT_WS_BASE = "wss://stream.binance.com:9443/ws"
RECONNECT_DELAY_SECONDS = 10

async def _direct_websocket_listener(symbol: str, timeframe: str):
    """
    Listener optimizado usando librería 'ta' estándar.
    """
    global recent_market_data, bot_status
    ws_symbol = symbol.replace('/', '').lower()
    stream_name = f"{ws_symbol}@kline_{timeframe}"
    ws_uri = f"{BINANCE_SPOT_WS_BASE}/{stream_name}"
    pair_tf_key = f"{symbol}_{timeframe}"
    logger.info(f"Listener Directo {pair_tf_key}: Iniciando conexión a {ws_uri}...")

    while bot_status.startswith("RUNNING"):
        try:
            async with websockets.connect(ws_uri, ping_interval=20, ping_timeout=10) as websocket:
                logger.info(f"Listener Directo {pair_tf_key}: Conectado exitosamente.")
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        if data.get('e') == 'kline':
                            kline_data = data.get('k')
                            if kline_data:
                                is_closed = kline_data.get('x', False)
                                timestamp_ms = int(kline_data.get('t'))
                                candle_ts = pd.to_datetime(timestamp_ms, unit='ms', utc=True)

                                new_candle = pd.DataFrame([{
                                    'open': float(kline_data.get('o')),
                                    'high': float(kline_data.get('h')),
                                    'low': float(kline_data.get('l')),
                                    'close': float(kline_data.get('c')),
                                    'volume': float(kline_data.get('v'))
                                }], index=[candle_ts])
                                new_candle.index.name = 'timestamp'

                                current_df = recent_market_data.get(pair_tf_key)
                                updated_df = pd.concat([current_df, new_candle]) if current_df is not None else new_candle
                                updated_df = updated_df[~updated_df.index.duplicated(keep='last')].sort_index()
                                updated_df = updated_df.iloc[-MAX_RECENT_CANDLES:]

                                df_for_ta = updated_df.copy()
                                
                                # --- LÓGICA REEMPLAZADA PARA USAR LIBRERÍA 'ta' ---
                                if len(df_for_ta) >= 14:
                                    try:
                                        # Instanciar indicador ATR
                                        atr_indicator = AverageTrueRange(
                                            high=df_for_ta['high'], 
                                            low=df_for_ta['low'], 
                                            close=df_for_ta['close'], 
                                            window=14
                                        )
                                        # Asignar columna
                                        df_for_ta[ATR_COL_FOR_SLIPPAGE] = atr_indicator.average_true_range()
                                        # Rellenar NaNs iniciales
                                        df_for_ta[ATR_COL_FOR_SLIPPAGE] = df_for_ta[ATR_COL_FOR_SLIPPAGE].bfill().ffill()
                                    except Exception as e_ta:
                                        logger.error(f"Error calculando ATR: {e_ta}")
                                        df_for_ta[ATR_COL_FOR_SLIPPAGE] = np.nan
                                else:
                                     df_for_ta[ATR_COL_FOR_SLIPPAGE] = np.nan
                                # --------------------------------------------------

                                recent_market_data[pair_tf_key] = df_for_ta

                                if is_closed:
                                    last_closed_candle_data = df_for_ta.loc[candle_ts]
                                    atr_val = last_closed_candle_data.get(ATR_COL_FOR_SLIPPAGE, np.nan)
                                    close_p = last_closed_candle_data['close']

                                    if pd.isna(atr_val):
                                        atr_str = 'N/A'
                                    else:
                                        try:
                                            atr_str = f"{atr_val:.4f}"
                                        except (TypeError, ValueError):
                                            atr_str = 'ErrFmt'
                                    
                                    logger.info(f"-> {pair_tf_key} | Vela CERRADA: {candle_ts} | C:{close_p:.4f} | ATR:{atr_str}")

                    except json.JSONDecodeError: logger.warning(f"Listener {pair_tf_key}: Mensaje WS no JSON.")
                    except Exception as e_parse: logger.error(f"Listener {pair_tf_key}: Error procesando mensaje: {e_parse}", exc_info=True)

        except (ConnectionClosedError, ConnectionClosedOK) as e_closed: 
            logger.warning(f"Listener {pair_tf_key}: Conexión cerrada (Code: {e_closed.code}). Reconectando {RECONNECT_DELAY_SECONDS}s...")
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)
        except asyncio.CancelledError: 
            logger.info(f"Listener {pair_tf_key}: Cancelado."); break
        except Exception as e: 
            logger.error(f"Listener {pair_tf_key}: Error inesperado WS ({type(e).__name__}: {e}). Reconectando.", exc_info=True)
            await asyncio.sleep(RECONNECT_DELAY_SECONDS * 2)

    logger.info(f"Listener Directo para {pair_tf_key}: Bucle terminado.")


async def listen_market_data():
    """
    Gestor de Listeners (Sin cambios mayores, solo logs).
    """
    global bot_status
    logger.info("Iniciando Gestor de Listeners...")
    bot_status = "STARTING_WS_LISTENERS"

    symbols_to_watch_map: Dict[str, List[str]] = {}
    db = SessionLocal()
    try:
        strategy_service = StrategyService(db=db)
        active_configs = strategy_service.get_active_strategy_configs()
        if not active_configs:
            logger.warning("Gestor Listeners: No hay estrategias activas.")
            bot_status = "STOPPED_NO_STRAT"; db.close(); return

        for config in active_configs:
            if config.timeframe not in symbols_to_watch_map: symbols_to_watch_map[config.timeframe] = []
            if config.pair not in symbols_to_watch_map[config.timeframe]: symbols_to_watch_map[config.timeframe].append(config.pair)
    except Exception as e:
         logger.error(f"Gestor Listeners: Error configs: {e}", exc_info=True)
         bot_status = "ERROR_CONFIG"; db.close(); return
    finally:
         db.close()

    if not symbols_to_watch_map:
         logger.warning("Gestor Listeners: No hay pares válidos.")
         bot_status = "STOPPED_NO_SYMBOLS"; return

    listener_tasks = []
    bot_status = "RUNNING_LISTENERS"
    logger.info(f"Gestor Listeners: Lanzando listeners para {symbols_to_watch_map}...")
    for timeframe, symbols in symbols_to_watch_map.items():
        for symbol in symbols:
            listener_tasks.append(asyncio.create_task(_direct_websocket_listener(symbol, timeframe)))

    if listener_tasks:
        try:
            await asyncio.gather(*listener_tasks, return_exceptions=False)
        except Exception as e_gather:
             logger.error(f"Gestor Listeners: Fallo crítico: {e_gather}", exc_info=True)
             bot_status = "ERROR_LISTENER_FATAL"

    logger.info("Gestor Listeners: Tareas terminadas.")
    bot_status = "STOPPED_LISTENERS_DONE"


async def trading_loop():
    """
    Bucle de trading refactorizado para usar librería 'ta'.
    """
    global bot_status, recent_market_data
    logger.info("Iniciando bucle de trading...")
    await asyncio.sleep(20)

    while True:
        if not bot_status.startswith("RUNNING"):
            logger.warning(f"Bucle Trading: Estado {bot_status}. Esperando...")
            await asyncio.sleep(15)
            continue

        bot_status = "RUNNING_TRADING_LOOP"
        logger.debug("--- Tick del Bucle de Trading ---")
        db = SessionLocal()
        try:
            strategy_service = StrategyService(db=db)
            position_repo = LivePositionRepository(db=db)
            active_strategies = strategy_service.get_active_strategy_configs()

            if not active_strategies:
                await asyncio.sleep(60) # Intervalo por defecto
                db.close(); continue

            for config in active_strategies:
                pair_tf_key = f"{config.pair}_{config.timeframe}"
                strategy_id = config.id
                market_df = recent_market_data.get(pair_tf_key)
                
                # Check básico de datos
                if market_df is None or market_df.empty or len(market_df) < 50: continue

                data_for_signals = market_df.iloc[:-1].copy()
                latest_candle = market_df.iloc[-1].copy()
                if data_for_signals.empty: continue

                # Instanciar Estrategia
                strategy_instance = STRATEGY_MAP[config.strategy_type](config=config.model_dump())
                
                # --- CORRECCIÓN ATR EN BUCLE ---
                atr_period = config.parameters.get("atr_period", 14)
                atr_col_strategy = f'ATR_{atr_period}'
                
                if atr_col_strategy not in data_for_signals.columns:
                    # Usar librería 'ta'
                    atr_indicator = AverageTrueRange(
                        high=data_for_signals['high'], 
                        low=data_for_signals['low'], 
                        close=data_for_signals['close'], 
                        window=atr_period
                    )
                    data_for_signals[atr_col_strategy] = atr_indicator.average_true_range()
                    data_for_signals.bfill(inplace=True)
                    data_for_signals.ffill(inplace=True)
                # -------------------------------

                # Calcular Señales (OJO: Asegúrate que strategy_instance NO use pandas-ta internamente)
                signal_df = strategy_instance.calculate_signals(data_for_signals)
                
                if signal_df.empty or signal_df.iloc[-1].get('signal') is None: continue

                last_signal_row = signal_df.iloc[-1]
                signal = int(last_signal_row['signal'])
                signal_sl = last_signal_row.get('sl_price', np.nan)
                signal_tp = last_signal_row.get('tp_price', np.nan)
                atr_for_slippage = latest_candle.get(ATR_COL_FOR_SLIPPAGE)

                current_pos_db = position_repo.get_by_strategy_and_pair(strategy_id, config.pair)

                # --- Lógica de SALIDA ---
                if current_pos_db:
                    exit_reason = None; exit_price_base = np.nan
                    exit_side = 'SELL' if current_pos_db.side == PositionSideSchema.LONG else 'BUY'
                    
                    if current_pos_db.side == PositionSideSchema.LONG:
                        if current_pos_db.current_sl_price and latest_candle['low'] <= current_pos_db.current_sl_price: 
                            exit_price_base = current_pos_db.current_sl_price; exit_reason = 'SL_LIVE'
                        elif current_pos_db.initial_tp_price and latest_candle['high'] >= current_pos_db.initial_tp_price: 
                            exit_price_base = current_pos_db.initial_tp_price; exit_reason = 'TP_LIVE'
                        elif signal == 2: 
                            exit_price_base = latest_candle['close']; exit_reason = 'SIGNAL_LIVE_EXIT'
                    
                    elif current_pos_db.side == PositionSideSchema.SHORT:
                        if current_pos_db.current_sl_price and latest_candle['high'] >= current_pos_db.current_sl_price: 
                            exit_price_base = current_pos_db.current_sl_price; exit_reason = 'SL_LIVE'
                        elif current_pos_db.initial_tp_price and latest_candle['low'] <= current_pos_db.initial_tp_price: 
                            exit_price_base = current_pos_db.initial_tp_price; exit_reason = 'TP_LIVE'
                        elif signal == -2: 
                            exit_price_base = latest_candle['close']; exit_reason = 'SIGNAL_LIVE_EXIT'

                    if exit_reason:
                        simulated_exit_price = exchange_service_instance._apply_slippage(exit_price_base, exit_side, atr_for_slippage)
                        log_msg = f"SALIDA ({strategy_id}): {current_pos_db.side.value} @ {simulated_exit_price:.2f} ({exit_reason})"
                        logger.info(log_msg)
                        
                        if settings.EXECUTE_LIVE_ORDERS:
                            # Aquí iría la llamada real al exchange
                            await exchange_service_instance.create_market_order(config.pair, exit_side.lower(), current_pos_db.size)
                        
                        position_repo.delete(strategy_id, config.pair)

                # --- Lógica de ENTRADA ---
                elif not current_pos_db:
                    intended_side = None
                    if signal == 1: intended_side = PositionSideSchema.LONG
                    elif signal == -1: intended_side = PositionSideSchema.SHORT
                    
                    if intended_side:
                        entry_price_base = latest_candle['close']
                        entry_price_with_slippage = exchange_service_instance._apply_slippage(entry_price_base, 'BUY' if intended_side == PositionSideSchema.LONG else 'SELL', atr_for_slippage)
                        
                        # Cálculo simple de posición (Fixed Risk)
                        risk_percent = config.parameters.get('risk_per_trade', DEFAULT_RISK_PER_TRADE)
                        sl_distance = abs(entry_price_with_slippage - signal_sl) if (signal_sl and signal_sl > 0) else 0
                        
                        if sl_distance > 0:
                            position_size = (INITIAL_CAPITAL * risk_percent) / sl_distance
                            
                            if position_size * entry_price_with_slippage >= MIN_ORDER_SIZE_USDT:
                                logger.info(f"ENTRADA ({strategy_id}): {intended_side.value} @ {entry_price_with_slippage:.2f} Size:{position_size:.4f}")
                                
                                if settings.EXECUTE_LIVE_ORDERS:
                                    await exchange_service_instance.create_market_order(config.pair, intended_side.value.lower(), position_size)
                                    # Crear en DB con datos reales...
                                
                                position_repo.create(LivePositionCreate(
                                    strategy_id=strategy_id, pair=config.pair, side=intended_side, 
                                    entry_price=entry_price_with_slippage, size=position_size, 
                                    entry_timestamp=latest_candle.name, 
                                    initial_sl_price=signal_sl, current_sl_price=signal_sl
                                ))

        except Exception as e:
            logger.error(f"Error en Trading Loop: {e}", exc_info=True)
            bot_status = "ERROR_TRADING_LOOP"
        finally:
            db.close()
        
        await asyncio.sleep(15)