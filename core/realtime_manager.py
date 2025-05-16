# core/realtime_manager.py
import asyncio
import logging
import json
from typing import Dict, List, Optional                     # <<< Para parsear mensajes JSON de WS
import websockets               # <<< Librería para conexión WS directa
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK # <<< Excepciones específicas
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

# Dependencias del proyecto
from core.config import settings
from db.session import SessionLocal
from services.strategy_service import StrategyService
from trading.exchange_service import exchange_service_instance # Aún lo usamos para _apply_slippage y órdenes
from trading.strategies.base_strategy import BaseStrategy
from services.backtesting_service import STRATEGY_MAP, ATR_COL_FOR_SLIPPAGE, INITIAL_CAPITAL, DEFAULT_RISK_PER_TRADE
from db.live_position_repository import LivePositionRepository
from schemas.live_position import LivePositionCreate, PositionSideSchema

logger = logging.getLogger(__name__)

# --- Estado Global y Constantes ---
recent_market_data: Dict[str, pd.DataFrame] = {}
bot_status: str = "STOPPED"
MAX_RECENT_CANDLES: int = 500 # Número de velas a mantener en memoria
MIN_ORDER_SIZE_USDT: float = 10.0
BINANCE_SPOT_WS_BASE = "wss://stream.binance.com:9443/ws" # URL base para Spot streams
RECONNECT_DELAY_SECONDS = 10 # Tiempo de espera antes de reintentar conexión WS
# -----------------------------------

async def _direct_websocket_listener(symbol: str, timeframe: str):
    """
    Listener asíncrono que conecta directamente al stream kline de Binance
    usando la librería 'websockets'. Mantiene 'recent_market_data' actualizado.
    (Versión Corregida para ValueError en log f-string)
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
                                if len(df_for_ta) >= 14: # O el periodo ATR
                                    if ATR_COL_FOR_SLIPPAGE in df_for_ta.columns: df_for_ta[ATR_COL_FOR_SLIPPAGE] = np.nan
                                    df_for_ta.ta.atr(length=14, append=True, col_names=(ATR_COL_FOR_SLIPPAGE,))
                                    df_for_ta[ATR_COL_FOR_SLIPPAGE] = df_for_ta[ATR_COL_FOR_SLIPPAGE].bfill().ffill()
                                else:
                                     df_for_ta[ATR_COL_FOR_SLIPPAGE] = np.nan

                                recent_market_data[pair_tf_key] = df_for_ta

                                # --- Loguear info de la vela cerrada (CORREGIDO) ---
                                if is_closed:
                                    # Acceder a la última fila del DataFrame que tiene ATR
                                    last_closed_candle_data = df_for_ta.loc[candle_ts]
                                    atr_val = last_closed_candle_data.get(ATR_COL_FOR_SLIPPAGE, np.nan)
                                    close_p = last_closed_candle_data['close']

                                    # --- Crear string formateado para ATR ANTES del f-string ---
                                    if pd.isna(atr_val):
                                        atr_str = 'N/A' # O '-' o cualquier indicador de que no hay valor
                                    else:
                                        try:
                                            atr_str = f"{atr_val:.4f}" # Formatear a 4 decimales si es un número válido
                                        except (TypeError, ValueError):
                                            atr_str = 'ErrFmt' # Indicar error de formato si no es numérico
                                    # ----------------------------------------------------------

                                    # Usar la variable atr_str en el f-string, SIN formato adicional
                                    logger.info(f"-> {pair_tf_key} | Vela CERRADA (Direct WS): {candle_ts} | C:{close_p:.4f} | ATR:{atr_str}") # Ajustado C a 4 decimales también
                                # -------------------------------------------------------------

                    except json.JSONDecodeError: logger.warning(f"Listener Directo {pair_tf_key}: Mensaje WS no JSON: {message[:100]}")
                    except Exception as e_parse: logger.error(f"Listener Directo {pair_tf_key}: Error procesando mensaje: {e_parse}", exc_info=True)

        except (ConnectionClosedError, ConnectionClosedOK) as e_closed: logger.warning(f"Listener Directo {pair_tf_key}: Conexión WS cerrada (Code: {e_closed.code}). Reconectando {RECONNECT_DELAY_SECONDS}s..."); await asyncio.sleep(RECONNECT_DELAY_SECONDS)
        except asyncio.CancelledError: logger.info(f"Listener Directo {pair_tf_key}: Cancelado."); break
        except websockets.exceptions.InvalidURI: logger.error(f"Listener Directo {pair_tf_key}: URI inválida: {ws_uri}. Deteniendo."); bot_status = f"ERROR_WS_URI_{symbol.replace('/','-')}"; break
        except Exception as e: logger.error(f"Listener Directo {pair_tf_key}: Error inesperado WS ({type(e).__name__}: {e}). Reconectando {RECONNECT_DELAY_SECONDS * 2}s.", exc_info=True); await asyncio.sleep(RECONNECT_DELAY_SECONDS * 2)

    logger.info(f"Listener Directo para {pair_tf_key}: Bucle terminado.")


async def listen_market_data():
    """
    Tarea principal que obtiene configuraciones activas y lanza un listener
    directo de WebSocket para cada par/timeframe necesario.
    """
    global bot_status
    logger.info("Iniciando Gestor de Listeners de datos (Direct WS)...")
    bot_status = "STARTING_WS_LISTENERS"

    # 1. Obtener Estrategias Activas y Pares/Timeframes necesarios
    symbols_to_watch_map: Dict[str, List[str]] = {}
    db = SessionLocal()
    try:
        strategy_service = StrategyService(db=db)
        active_configs = strategy_service.get_active_strategy_configs()
        if not active_configs:
            logger.warning("Gestor Listeners: No hay estrategias activas. No se iniciarán listeners.")
            bot_status = "STOPPED_NO_STRAT"; db.close(); return

        for config in active_configs:
            if config.timeframe not in symbols_to_watch_map: symbols_to_watch_map[config.timeframe] = []
            if config.pair not in symbols_to_watch_map[config.timeframe]: symbols_to_watch_map[config.timeframe].append(config.pair)
    except Exception as e:
         logger.error(f"Gestor Listeners: Error obteniendo configs activas: {e}", exc_info=True)
         bot_status = "ERROR_CONFIG"; db.close(); return
    finally:
         db.close()

    if not symbols_to_watch_map:
         logger.warning("Gestor Listeners: No hay pares/timeframes válidos para escuchar.")
         bot_status = "STOPPED_NO_SYMBOLS"; return

    # 2. Lanzar una tarea listener para CADA par/timeframe
    listener_tasks = []
    bot_status = "RUNNING_LISTENERS" # Actualizar estado ANTES de lanzar tareas
    logger.info(f"Gestor Listeners: Lanzando listeners directos para {symbols_to_watch_map}...")
    for timeframe, symbols in symbols_to_watch_map.items():
        for symbol in symbols:
            # Lanzar la tarea que usa websockets directamente
            listener_tasks.append(asyncio.create_task(_direct_websocket_listener(symbol, timeframe)))

    # 3. Esperar a que terminen (si alguna falla, gather puede lanzar excepción)
    if listener_tasks:
        try:
            # Esperar a que todas las tareas terminen (normalmente no lo harán a menos que haya error o cancelación)
            await asyncio.gather(*listener_tasks, return_exceptions=False)
        except Exception as e_gather:
             logger.error(f"Gestor Listeners: Una o más tareas listener fallaron críticamente: {e_gather}", exc_info=True)
             bot_status = "ERROR_LISTENER_FATAL" # Indicar un fallo grave en los listeners

    logger.info("Gestor Listeners: Todas las tareas han terminado (esto no debería pasar en operación normal).")
    bot_status = "STOPPED_LISTENERS_DONE"


async def trading_loop():
    """
    Bucle principal de toma de decisiones. Lee de recent_market_data
    (poblado por los listeners directos) y simula/ejecuta órdenes.
    (Contenido interno de esta función no necesita cambios mayores respecto a la última versión,
     ya que depende de recent_market_data y los servicios/repositorios existentes)
    """
    global bot_status, recent_market_data
    logger.info("Iniciando bucle de trading...")
    await asyncio.sleep(20) # Espera inicial

    while True:
        if not bot_status.startswith("RUNNING"):
            logger.warning(f"Bucle Trading: Estado del bot no es RUNNING ({bot_status}). Esperando 15s...")
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
                logger.debug("Bucle Trading: No hay estrategias activas.")
                await asyncio.sleep(settings.TRADING_LOOP_INTERVAL_SECONDS if hasattr(settings, 'TRADING_LOOP_INTERVAL_SECONDS') else 60)
                db.close(); continue

            trading_halted_for_now = False # Placeholder DD global real

            for config in active_strategies:
                pair_tf_key = f"{config.pair}_{config.timeframe}"
                strategy_id = config.id
                market_df = recent_market_data.get(pair_tf_key)
                if market_df is None or market_df.empty or len(market_df) < 50: continue # Saltar si no hay datos suficientes

                data_for_signals = market_df.iloc[:-1].copy()
                latest_candle = market_df.iloc[-1].copy()
                if data_for_signals.empty: continue

                logger.debug(f"Bucle Trading ({strategy_id}): Procesando {config.pair}. Última cerrada: {data_for_signals.index[-1]}")

                strategy_instance = STRATEGY_MAP[config.strategy_type](config=config.model_dump())
                # Asegurar ATR para la estrategia (ya debería estar calculado por el listener)
                atr_col_strategy = f'ATR_{config.parameters.get("atr_period", 14)}'
                if atr_col_strategy not in data_for_signals.columns:
                    logger.warning(f"Calculando {atr_col_strategy} en Trading Loop (debería estar en listener)...")
                    data_for_signals.ta.atr(length=config.parameters.get("atr_period", 14), append=True, col_names=(atr_col_strategy,))
                    data_for_signals.bfill(inplace=True); data_for_signals.ffill(inplace=True)

                signal_df = strategy_instance.calculate_signals(data_for_signals)
                if signal_df.empty or signal_df.iloc[-1].get('signal') is None: continue

                last_signal_row = signal_df.iloc[-1]
                signal = int(last_signal_row['signal'])
                signal_sl = last_signal_row['sl_price']
                signal_tp = last_signal_row['tp_price']
                atr_for_slippage = latest_candle.get(ATR_COL_FOR_SLIPPAGE)

                current_pos_db = position_repo.get_by_strategy_and_pair(strategy_id, config.pair)

                # --- Lógica de Salida (Exactamente igual que antes) ---
                if current_pos_db:
                    exit_reason = None; exit_price_base = np.nan
                    exit_side = 'SELL' if current_pos_db.side == PositionSideSchema.LONG else 'BUY'
                    # ... (Chequeo SL/TP/Signal usando latest_candle['low']/['high']/['close']) ...
                    if current_pos_db.side == PositionSideSchema.LONG:
                        if current_pos_db.current_sl_price and latest_candle['low'] <= current_pos_db.current_sl_price: exit_price_base = current_pos_db.current_sl_price; exit_reason = 'SL_LIVE'
                        elif current_pos_db.initial_tp_price and latest_candle['high'] >= current_pos_db.initial_tp_price: exit_price_base = current_pos_db.initial_tp_price; exit_reason = 'TP_LIVE'
                        elif signal == 2: exit_price_base = latest_candle['close']; exit_reason = 'SIGNAL_LIVE_EXIT'
                    elif current_pos_db.side == PositionSideSchema.SHORT:
                        if current_pos_db.current_sl_price and latest_candle['high'] >= current_pos_db.current_sl_price: exit_price_base = current_pos_db.current_sl_price; exit_reason = 'SL_LIVE'
                        elif current_pos_db.initial_tp_price and latest_candle['low'] <= current_pos_db.initial_tp_price: exit_price_base = current_pos_db.initial_tp_price; exit_reason = 'TP_LIVE'
                        elif signal == -2: exit_price_base = latest_candle['close']; exit_reason = 'SIGNAL_LIVE_EXIT'

                    if exit_reason:
                        simulated_exit_price = exchange_service_instance._apply_slippage(exit_price_base, exit_side, atr_for_slippage)
                        log_msg_prefix = "EJECUCIÓN CIERRE" if settings.EXECUTE_LIVE_ORDERS else "SIMULACIÓN CIERRE"
                        logger.info(f"{log_msg_prefix} ({strategy_id}/{config.pair}): {current_pos_db.side.value} en ~{simulated_exit_price:.4f} (Base:{exit_price_base:.4f}). Razón: {exit_reason}")
                        if settings.EXECUTE_LIVE_ORDERS:
                            try: # Intento de orden real
                                order_result = await exchange_service_instance.create_market_order(config.pair, exit_side.lower(), current_pos_db.size)
                                if order_result and order_result.get('id'): logger.info(f"  ORDEN CIERRE COLOCADA: ID {order_result.get('id')}"); position_repo.delete(strategy_id, config.pair)
                                else: logger.error(f"  FALLO orden CIERRE: {order_result}")
                            except Exception as e_order: logger.error(f"  EXCEPCIÓN orden CIERRE: {e_order}", exc_info=True)
                        else: position_repo.delete(strategy_id, config.pair) # Simular cierre en BD

                # --- Lógica de Entrada (Exactamente igual que antes) ---
                elif not current_pos_db and not trading_halted_for_now:
                    intended_side: Optional[PositionSideSchema] = None
                    if signal == 1: intended_side = PositionSideSchema.LONG
                    elif signal == -1: intended_side = PositionSideSchema.SHORT
                    if intended_side and not pd.isna(signal_sl) and signal_sl > 0:
                        if not config.pair.endswith('/USDT'): logger.warning(f"Sizing para {config.pair} no /USDT simplificado.");
                        entry_price_base = latest_candle['close']
                        entry_price_with_slippage = exchange_service_instance._apply_slippage(entry_price_base, 'BUY' if intended_side == PositionSideSchema.LONG else 'SELL', atr_for_slippage)
                        sl_distance = abs(entry_price_with_slippage - signal_sl)
                        if sl_distance > 1e-9:
                            risk_percent = config.parameters.get('risk_per_trade', DEFAULT_RISK_PER_TRADE)
                            num_active = len(active_strategies) if active_strategies else 1
                            pseudo_strategy_capital = INITIAL_CAPITAL / num_active # Placeholder
                            if pseudo_strategy_capital <= 0: logger.warning(f"Capital para {strategy_id} <=0"); continue
                            risk_usdt = pseudo_strategy_capital * risk_percent
                            position_size = risk_usdt / sl_distance
                            if position_size * entry_price_with_slippage < MIN_ORDER_SIZE_USDT: logger.warning(f"Tamaño orden ({position_size * entry_price_with_slippage:.2f} USDT) < mínimo ({MIN_ORDER_SIZE_USDT} USDT)"); continue
                            log_msg_prefix = "EJECUCIÓN ENTRADA" if settings.EXECUTE_LIVE_ORDERS else "SIMULACIÓN ENTRADA"
                            logger.info(f"{log_msg_prefix} ({strategy_id}/{config.pair}): {intended_side.value} en ~{entry_price_with_slippage:.4f} (Base:{entry_price_base:.4f}), Size: {position_size:.6f}, SL: {signal_sl:.4f}, TP: {signal_tp}")
                            if settings.EXECUTE_LIVE_ORDERS:
                                try: # Intento de orden real
                                    order_result = await exchange_service_instance.create_market_order(config.pair, intended_side.value.lower(), position_size)
                                    if order_result and order_result.get('id'):
                                        logger.info(f"  ORDEN ENTRADA COLOCADA: ID {order_result.get('id')}")
                                        actual_entry_price = float(order_result.get('average', entry_price_with_slippage))
                                        actual_size = float(order_result.get('filled', position_size))
                                        position_repo.create(LivePositionCreate(strategy_id=strategy_id, pair=config.pair, side=intended_side, entry_price=actual_entry_price, size=actual_size, entry_timestamp=latest_candle.name, initial_sl_price=signal_sl, initial_tp_price=signal_tp if not pd.isna(signal_tp) else None, current_sl_price=signal_sl ))
                                    else: logger.error(f"  FALLO orden ENTRADA: {order_result}")
                                except Exception as e_order: logger.error(f"  EXCEPCIÓN orden ENTRADA: {e_order}", exc_info=True)
                            else: # Simulación
                                position_repo.create(LivePositionCreate(strategy_id=strategy_id, pair=config.pair, side=intended_side, entry_price=entry_price_with_slippage, size=position_size, entry_timestamp=latest_candle.name, initial_sl_price=signal_sl, initial_tp_price=signal_tp if not pd.isna(signal_tp) else None, current_sl_price=signal_sl))
                        else: logger.warning(f"Distancia SL cero para {strategy_id}/{config.pair}")

        except Exception as e:
            logger.error(f"Error en el bucle de trading principal: {e}", exc_info=True)
            bot_status = "ERROR_TRADING_LOOP"
        finally:
            db.close() # Cerrar sesión DB del ciclo
        
        # Espera para el siguiente ciclo
        loop_interval = 15 # Segundos por defecto
        if hasattr(settings, 'TRADING_LOOP_INTERVAL_SECONDS'):
             loop_interval = int(settings.TRADING_LOOP_INTERVAL_SECONDS)
        await asyncio.sleep(loop_interval)