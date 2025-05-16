# services/backtesting_service.py
import logging
import math
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Type, List
from sqlalchemy.orm import Session
import random # Para slippage aleatorio

# Dependencias de FastAPI y SQLAlchemy
from fastapi import Depends # Necesario para la función de dependencia final

# Dependencias de otros módulos del proyecto
from core.config import settings
from services.strategy_service import StrategyService, get_strategy_service # Importar servicio y dependencia
from db.ohlcv_repository import OHLCVRepository
from db.session import get_db # Importar dependencia para obtener sesión DB
from schemas.strategy import StrategyConfig
from schemas.trade import Trade
# Usaremos PortfolioBacktestResult para ambos tipos por simplicidad de respuesta API
from schemas.backtest_results import PortfolioBacktestResult, BacktestMetrics

# Importar las CLASES de las estrategias implementadas
from trading.strategies.base_strategy import BaseStrategy
from trading.strategies.ema_crossover import EmaCrossoverStrategy
from trading.strategies.rsi_mean_reversion import RsiMeanReversionStrategy
from trading.strategies.volatility_breakout import VolatilityBreakoutStrategy

logger = logging.getLogger(__name__) # Obtener logger para este módulo

# Mapeo de 'strategy_type' (string desde config) a la clase Python real
STRATEGY_MAP: Dict[str, Type[BaseStrategy]] = {
    "ema_crossover": EmaCrossoverStrategy,
    "rsi_mean_reversion": RsiMeanReversionStrategy,
    "volatility_breakout": VolatilityBreakoutStrategy,
    # Añade aquí otras estrategias que implementes
}

# --- Constantes de Simulación ---
INITIAL_CAPITAL = 10000.0
COMMISSION_PCT = 0.00075 # Comisión por trade (ej. 0.075% Binance taker)
DEFAULT_RISK_PER_TRADE = 0.01 # 1% riesgo por defecto si no está en config estrategia
MAX_GLOBAL_DRAWDOWN_PCT = 0.10 # 10% drawdown límite para el portfolio
# --- Configuración de Slippage ---
SLIPPAGE_ATR_FACTOR_MIN = 0.01 # Mínimo 1% del ATR como slippage
SLIPPAGE_ATR_FACTOR_MAX = 0.10 # Máximo 10% del ATR como slippage
APPLY_SLIPPAGE = True # Flag para activar/desactivar slippage
# -----------------------------------------
# Constante para nombre de columna ATR (debe coincidir con lo devuelto por estrategias)
# Usamos ATR 14 como un estándar asumido si la estrategia no lo devuelve explícitamente
ATR_COL_FOR_SLIPPAGE = 'ATR_14'


class BacktestingService:
    def __init__(self, db: Session, strategy_service: StrategyService):
        self.db = db
        self.strategy_service = strategy_service
        self.ohlcv_repo = OHLCVRepository(db=self.db)

    def _get_strategy_instance(self, config: StrategyConfig) -> Optional[BaseStrategy]:
        """Instancia la clase de estrategia correcta basada en la configuración."""
        strategy_class = STRATEGY_MAP.get(config.strategy_type)
        if not strategy_class:
            logger.error(f"Tipo de estrategia desconocido: '{config.strategy_type}' para ID '{config.id}'")
            return None
        try:
            # Pasa la configuración completa al constructor de la estrategia
            instance = strategy_class(config=config.model_dump()) # Usar model_dump() para Pydantic v2
            return instance
        except Exception as e:
            logger.error(f"Error al instanciar estrategia '{config.id}' de tipo '{config.strategy_type}': {e}", exc_info=True)
            return None

    def _apply_slippage(self, price: float, side: str, atr: Optional[float]) -> float:
        """
        Aplica un slippage aleatorio al precio, basado en un % del ATR.
        El slippage siempre empeora el precio de ejecución.
        """
        if not APPLY_SLIPPAGE or atr is None or np.isnan(atr) or atr <= 1e-9:
            return price # No aplicar si está desactivado o ATR no es válido

        slippage_factor = random.uniform(SLIPPAGE_ATR_FACTOR_MIN, SLIPPAGE_ATR_FACTOR_MAX)
        slippage_amount = slippage_factor * atr

        adjusted_price: float
        if side == 'BUY': # Peor precio para comprar es más ALTO
            adjusted_price = price + slippage_amount
        elif side == 'SELL': # Peor precio para vender es más BAJO
            adjusted_price = price - slippage_amount
        else:
            adjusted_price = price # Caso inesperado

        # Asegurar que el precio no sea negativo
        return max(adjusted_price, 1e-9)

    # ==============================================================
    # --- MÉTODO: Backtest para Estrategia Individual (Refactorizado) ---
    # ==============================================================
    def run_single_strategy_backtest(self,
                                     config: StrategyConfig, # Recibe el objeto config completo
                                     start_dt: datetime,
                                     end_dt: datetime) -> PortfolioBacktestResult: # Reutilizamos schema Portfolio
        """Ejecuta el backtest para UNA única estrategia."""

        logger.info(f"Iniciando backtest INDIVIDUAL para Strategy ID: {config.id} | Rango: {start_dt} -> {end_dt}")

        # 1. Instanciar Estrategia
        strategy = self._get_strategy_instance(config)
        if not strategy:
             return PortfolioBacktestResult(strategy_ids=[config.id], strategy_configs=[config], start_date=start_dt, end_date=end_dt,
                                            metrics=BacktestMetrics(initial_portfolio_value=INITIAL_CAPITAL, final_portfolio_value=INITIAL_CAPITAL),
                                            error=f"No se pudo instanciar la estrategia tipo '{config.strategy_type}'.")

        # 2. Obtener Datos Históricos (con buffer)
        buffer_days = 60
        fetch_start_dt = start_dt - timedelta(days=buffer_days)
        logger.info(f"Obteniendo datos para {config.pair}/{config.timeframe} desde {config.exchange}...")
        ohlcv_df_full = self.ohlcv_repo.get_ohlcv_data(config.exchange, config.pair, config.timeframe, fetch_start_dt, end_dt)

        if ohlcv_df_full is None or ohlcv_df_full.empty:
             return PortfolioBacktestResult(strategy_ids=[config.id], strategy_configs=[config], start_date=start_dt, end_date=end_dt,
                                            metrics=BacktestMetrics(initial_portfolio_value=INITIAL_CAPITAL, final_portfolio_value=INITIAL_CAPITAL),
                                            error=f"No se encontraron datos OHLCV para {config.pair}/{config.timeframe}.", trades=[])

        # Calcular ATR para slippage si no viene del repo/estrategia
        if ATR_COL_FOR_SLIPPAGE not in ohlcv_df_full.columns:
            logger.debug(f"Calculando {ATR_COL_FOR_SLIPPAGE} para {config.pair} (slippage)...")
            # Usamos una longitud estándar (ej. 14) si no está definido explícitamente para slippage
            ohlcv_df_full.ta.atr(length=14, append=True, col_names=(ATR_COL_FOR_SLIPPAGE,))
            ohlcv_df_full.bfill(inplace=True)
            ohlcv_df_full.ffill(inplace=True)

        # 3. Calcular Señales
        logger.info(f"Calculando señales para {strategy.name}...")
        try:
            signals_df = strategy.calculate_signals(ohlcv_df_full.copy()) # Pasar copia
            # Unir señales/niveles/ATR al DF principal
            data_df_full = ohlcv_df_full.join(signals_df, how='left')
            # Rellenar NaNs en columnas clave que vienen de la estrategia
            cols_from_strategy = ['signal', 'sl_price', 'tp_price']
            atr_col_strategy_name = ATR_COL_FOR_SLIPPAGE # Asumir nombre estándar si no se devuelve
            # Verificar si la estrategia devolvió una columna ATR y usarla
            for col in signals_df.columns:
                 if col.startswith('ATR_'):
                      atr_col_strategy_name = col
                      if col not in cols_from_strategy:
                           cols_from_strategy.append(col)
                      break # Usar la primera que encuentre

            # Asegurar que todas las columnas esperadas existan después del join
            for col in cols_from_strategy:
                 if col not in data_df_full.columns:
                      data_df_full[col] = np.nan # Añadir columna con NaN si falta

            # Reindexar al índice completo (incluyendo buffer) y rellenar NaNs
            data_df_full = data_df_full.reindex(ohlcv_df_full.index)
            data_df_full[cols_from_strategy] = data_df_full[cols_from_strategy].fillna({'signal': 0, 'sl_price': np.nan, 'tp_price': np.nan})
            data_df_full[atr_col_strategy_name] = data_df_full[atr_col_strategy_name].fillna(0)


        except Exception as e:
             logger.error(f"Error al calcular señales para {strategy.name}: {e}", exc_info=True)
             return PortfolioBacktestResult(strategy_ids=[config.id], strategy_configs=[config], start_date=start_dt, end_date=end_dt,
                                            metrics=BacktestMetrics(initial_portfolio_value=INITIAL_CAPITAL, final_portfolio_value=INITIAL_CAPITAL),
                                            error=f"Error durante el cálculo de señales: {e}", trades=[])

        # Filtrar para el rango de backtest real (después de calcular señales con buffer)
        data_df = data_df_full[data_df_full.index >= start_dt].copy()
        if data_df.empty:
              return PortfolioBacktestResult(strategy_ids=[config.id], strategy_configs=[config], start_date=start_dt, end_date=end_dt,
                                             metrics=BacktestMetrics(initial_portfolio_value=INITIAL_CAPITAL, final_portfolio_value=INITIAL_CAPITAL),
                                             error=f"No quedaron datos después de filtrar por fecha de inicio {start_dt}.", trades=[])

        logger.info(f"Datos listos para simulación individual ({len(data_df)} velas).")

        # 4. Bucle de Backtesting Individual
        trades: List[Trade] = []
        capital = INITIAL_CAPITAL # Usar capital inicial global para pruebas individuales
        cash = capital # Empezar con todo en cash
        position_side: Optional[str] = None
        entry_price: float = 0.0
        position_size: float = 0.0
        active_sl: Optional[float] = None
        active_tp: Optional[float] = None
        entry_timestamp: Optional[datetime] = None
        commission_entry_value: float = 0.0
        risk_per_trade = config.parameters.get('risk_per_trade', DEFAULT_RISK_PER_TRADE)

        equity_curve_data = {'timestamp': [data_df.index[0] - pd.Timedelta(seconds=1)], 'equity': [capital]}
        total_commission = 0.0

        for timestamp, row in data_df.iterrows():
            # Calcular equity Mark-to-Market al inicio de la vela
            current_equity = cash
            if position_side == 'LONG':
                current_equity += position_size * row['close'] # Valorar al cierre actual

            exit_reason = None; pnl_abs = 0.0; commission_trade = 0.0; position_closed = False

            # --- Lógica de Salida ---
            if position_side:
                pos_side_current = position_side
                exit_price_base = np.nan
                exit_side = 'SELL' if pos_side_current == 'LONG' else 'BUY'
                atr_for_slippage = row.get(atr_col_strategy_name) # Usar ATR de la señal si existe

                # Chequeo SL/TP/Señal (igual que en portfolio)
                if pos_side_current == 'LONG':
                    if active_sl and row['low'] <= active_sl: exit_price_base = active_sl; exit_reason = 'SL'
                    elif active_tp and row['high'] >= active_tp: exit_price_base = active_tp; exit_reason = 'TP'
                    elif int(row['signal']) == 2: exit_price_base = row['close']; exit_reason = 'SIGNAL'
                elif pos_side_current == 'SHORT':
                    if active_sl and row['high'] >= active_sl: exit_price_base = active_sl; exit_reason = 'SL'
                    elif active_tp and row['low'] <= active_tp: exit_price_base = active_tp; exit_reason = 'TP'
                    elif int(row['signal']) == -2: exit_price_base = row['close']; exit_reason = 'SIGNAL'

                if exit_reason:
                    exit_price = self._apply_slippage(exit_price_base, exit_side, atr_for_slippage)
                    if pos_side_current == 'LONG': pnl_abs = (exit_price - entry_price) * position_size
                    else: pnl_abs = (entry_price - exit_price) * position_size
                    commission_exit = abs(exit_price * position_size * COMMISSION_PCT)
                    commission_trade = commission_entry_value + commission_exit
                    total_commission += commission_exit
                    net_pnl = pnl_abs - commission_exit
                    cash += net_pnl # <<< CORRECCIÓN: Actualizar cash con PnL Neto

                    trades.append(Trade(strategy_id=config.id, pair=config.pair, entry_timestamp=entry_timestamp, exit_timestamp=timestamp,
                                        entry_price=entry_price, exit_price=exit_price, position_side=pos_side_current,
                                        size=position_size, pnl_abs=pnl_abs, pnl_pct=(pnl_abs / abs(entry_price * position_size)) if entry_price * position_size != 0 else 0,
                                        entry_signal_type=1 if pos_side_current == 'LONG' else -1,
                                        exit_reason=exit_reason, commission=commission_trade))
                    logger.debug(f"{timestamp} - {config.id}: Cerrado {pos_side_current} en {exit_price:.4f}. Razón: {exit_reason}. PnL Neto: {net_pnl:.2f}. Cash: {cash:.2f}")
                    position_side = None; active_sl = None; active_tp = None; entry_timestamp = None; commission_entry_value = 0.0; position_size = 0.0; entry_price = 0.0;
                    position_closed = True


            # --- Lógica de Entrada ---
            if position_side is None and not position_closed:
                entry_signal = int(row['signal'])
                sl = row['sl_price']
                tp = row['tp_price']
                intended_side = None
                atr_for_slippage = row.get(atr_col_strategy_name)

                if entry_signal == 1: intended_side = 'LONG'
                elif entry_signal == -1: intended_side = 'SHORT'

                if intended_side and not np.isnan(sl) and sl > 0:
                    if not config.pair.endswith('/USDT'):
                         logger.error(f"{timestamp} - {config.id}: Señal {entry_signal} ignorada. Sizing solo soporta /USDT. Par: {config.pair}")
                         continue
                    entry_price_base = row['close']
                    entry_price = self._apply_slippage(entry_price_base, 'BUY' if intended_side == 'LONG' else 'SELL', atr_for_slippage)
                    sl_distance = abs(entry_price - sl)

                    if sl_distance > 1e-9:
                        available_cash = cash # Usar el cash actual de esta simulación
                        if available_cash <= 0:
                            logger.warning(f"{timestamp} - {config.id}: Señal {entry_signal} ignorada. No hay cash ({available_cash:.2f}).")
                            continue

                        risk_usdt = available_cash * risk_per_trade
                        position_size = risk_usdt / sl_distance

                        min_trade_size = 1e-5
                        if position_size < min_trade_size:
                            logger.warning(f"{timestamp} - {config.id}: Señal {entry_signal} ignorada. Tamaño ({position_size:.8f}) < mínimo ({min_trade_size}).")
                            continue

                        commission_entry = abs(entry_price * position_size * COMMISSION_PCT)

                        # --- CORRECCIÓN: Actualizar Cash en Entrada ---
                        can_afford = False
                        if intended_side == 'LONG':
                             # Para Long, necesitamos cash para la comisión. El costo 'virtualmente' reduce equity.
                             if available_cash >= commission_entry:
                                  cash -= commission_entry # Deducir solo comisión
                                  can_afford = True
                        elif intended_side == 'SHORT':
                             # Simplificación: Solo deducir comisión para Short simulado
                             if available_cash >= commission_entry:
                                  cash -= commission_entry
                                  can_afford = True

                        if can_afford:
                             total_commission += commission_entry
                             commission_entry_value = commission_entry

                             position_side = intended_side
                             active_sl = sl
                             active_tp = tp if not np.isnan(tp) else None
                             entry_timestamp = timestamp
                             logger.debug(f"{timestamp} - {config.id}: Abierto {intended_side} en {entry_price:.4f} (Base:{entry_price_base:.4f}). Size: {position_size:.6f}. SL: {sl:.4f}, TP: {active_tp}. Cash: {cash:.2f}")
                        else:
                             logger.warning(f"{timestamp} - {config.id}: Señal {entry_signal} ignorada. Cash insuficiente ({available_cash:.2f}) para comisión ({commission_entry:.2f}).")
                    else:
                        logger.warning(f"{timestamp} - {config.id}: Señal entrada {entry_signal} ignorada. Distancia SL cero (Entry={entry_price}, SL={sl}).")

            # Registrar equity al final de la vela
            current_portfolio_value_eod = cash
            if position_side == 'LONG':
                 current_portfolio_value_eod += position_size * row['close']

            equity_curve_data['timestamp'].append(timestamp)
            equity_curve_data['equity'].append(current_portfolio_value_eod)

        # --- Fin Bucle Backtesting Individual ---
        logger.info(f"Bucle de simulación individual para {config.id} finalizado.")

        # Cerrar posición si queda abierta al final
        final_timestamp = data_df.index[-1]
        final_price_base = data_df['close'].iloc[-1]
        final_atr = data_df[atr_col_strategy_name].iloc[-1] if atr_col_strategy_name in data_df.columns and not data_df[atr_col_strategy_name].isnull().all() else data_df[ATR_COL_FOR_SLIPPAGE].iloc[-1]

        if position_side:
            pos_side_current = position_side
            exit_price_base = final_price_base
            exit_reason = 'END'
            exit_side = 'SELL' if pos_side_current == 'LONG' else 'BUY'
            exit_price = self._apply_slippage(exit_price_base, exit_side, final_atr)

            if pos_side_current == 'LONG': pnl_abs = (exit_price - entry_price) * position_size
            else: pnl_abs = (entry_price - exit_price) * position_size

            commission_exit = abs(exit_price * position_size * COMMISSION_PCT)
            commission_trade = commission_entry_value + commission_exit
            total_commission += commission_exit
            net_pnl = pnl_abs - commission_exit
            cash += net_pnl # <<< CORRECCIÓN: Actualizar cash con PnL Neto

            trades.append(Trade(strategy_id=config.id, pair=config.pair, entry_timestamp=entry_timestamp, exit_timestamp=final_timestamp,
                                entry_price=entry_price, exit_price=exit_price, position_side=pos_side_current,
                                size=position_size, pnl_abs=pnl_abs, pnl_pct=(pnl_abs / abs(entry_price * position_size)) if entry_price * position_size != 0 else 0,
                                entry_signal_type=1 if pos_side_current == 'LONG' else -1,
                                exit_reason=exit_reason, commission=commission_trade))
            logger.debug(f"{final_timestamp} - {config.id}: Cerrado Forzoso {pos_side_current} al final en {exit_price:.4f}. PnL Neto: {net_pnl:.2f}. Cash Final: {cash:.2f}")

        # Crear DataFrame de equity y calcular métricas
        equity_df = pd.DataFrame(equity_curve_data).set_index('timestamp')
        metrics = self._calculate_metrics(equity_df, trades, total_commission, cash, is_portfolio=False)

        result = PortfolioBacktestResult( # Reutilizamos schema
            strategy_ids=[config.id],
            strategy_configs=[config],
            start_date=start_dt,
            end_date=end_dt,
            metrics=metrics,
            trades=trades,
            stopped_by_drawdown_rule=False # No aplica
        )
        logger.info(f"Backtest individual finalizado para {config.id}. Trades: {metrics.total_trades}, Retorno: {metrics.total_return_pct:.2f}%, Max DD: {metrics.max_drawdown_pct:.2f}%")
        return result


    # ==============================================================
    # --- MÉTODO Portfolio Backtest (EXISTENTE, CON CORRECCIONES ANTERIORES) ---
    # ==============================================================
    def run_portfolio_backtest(self,
                               strategy_ids: List[str],
                               start_dt: datetime,
                               end_dt: datetime) -> PortfolioBacktestResult:
        """Ejecuta el backtest para un portfolio de estrategias con slippage y sizing corregido."""
        # Esta función se mantiene como estaba en el paso anterior,
        # con la lógica de portfolio, asignación de capital, y chequeo de DD global.
        # Asegúrate de tener la versión corregida que te pasé antes (con slippage y sizing/cash fixes).

        logger.info(f"Iniciando backtest de PORTFOLIO para IDs: {strategy_ids} | Rango: {start_dt} -> {end_dt}")

        # --- Validación de Entrada ---
        if not strategy_ids:
            return PortfolioBacktestResult(strategy_ids=[], strategy_configs=[], start_date=start_dt, end_date=end_dt, metrics=BacktestMetrics(initial_portfolio_value=INITIAL_CAPITAL, final_portfolio_value=INITIAL_CAPITAL), error="No se proporcionaron IDs de estrategia.")

        # --- 1. Obtener Configuraciones y Instanciar Estrategias ---
        strategy_configs: List[StrategyConfig] = []
        strategies: Dict[str, BaseStrategy] = {}
        pairs_needed = set()
        timeframes_needed = set()
        active_strategy_ids = []
        configs_used_dict: Dict[str, StrategyConfig] = {} # Para fácil acceso después

        for s_id in strategy_ids:
            config = self.strategy_service.get_strategy_config(s_id)
            if not config:
                 return PortfolioBacktestResult(strategy_ids=strategy_ids, strategy_configs=strategy_configs, start_date=start_dt, end_date=end_dt, metrics=BacktestMetrics(initial_portfolio_value=INITIAL_CAPITAL, final_portfolio_value=INITIAL_CAPITAL), error=f"Configuración para estrategia ID '{s_id}' no encontrada.")
            strategy_configs.append(config)
            if not config.is_active:
                 logger.warning(f"Estrategia '{s_id}' no está activa, se omitirá.")
                 continue
            instance = self._get_strategy_instance(config)
            if not instance:
                return PortfolioBacktestResult(strategy_ids=strategy_ids, strategy_configs=strategy_configs, start_date=start_dt, end_date=end_dt, metrics=BacktestMetrics(initial_portfolio_value=INITIAL_CAPITAL, final_portfolio_value=INITIAL_CAPITAL), error=f"No se pudo instanciar la estrategia '{s_id}'.")

            strategies[s_id] = instance
            active_strategy_ids.append(s_id)
            configs_used_dict[s_id] = config
            pairs_needed.add(config.pair)
            timeframes_needed.add(config.timeframe)

        if not strategies:
             return PortfolioBacktestResult(strategy_ids=strategy_ids, strategy_configs=strategy_configs, start_date=start_dt, end_date=end_dt, metrics=BacktestMetrics(initial_portfolio_value=INITIAL_CAPITAL, final_portfolio_value=INITIAL_CAPITAL), error="Ninguna estrategia válida o activa encontrada para ejecutar.")

        # --- Simplificación Timeframe y Exchange ---
        if len(timeframes_needed) > 1:
            logger.warning(f"Múltiples timeframes detectados: {timeframes_needed}. Usando el del primer config activo: {configs_used_dict[active_strategy_ids[0]].timeframe}")
        master_timeframe = configs_used_dict[active_strategy_ids[0]].timeframe
        exchange_name = configs_used_dict[active_strategy_ids[0]].exchange

        # --- 2. Obtener y Preparar Datos Históricos ---
        all_data_dict: Dict[str, pd.DataFrame] = {}
        combined_index = None
        buffer_days = 60
        fetch_start_dt = start_dt - timedelta(days=buffer_days)

        for pair in pairs_needed:
            logger.info(f"Obteniendo datos para {pair}/{master_timeframe} desde {exchange_name}...")
            df = self.ohlcv_repo.get_ohlcv_data(exchange_name, pair, master_timeframe, fetch_start_dt, end_dt)
            if df is None or df.empty:
                 return PortfolioBacktestResult(strategy_ids=strategy_ids, strategy_configs=strategy_configs, start_date=start_dt, end_date=end_dt, metrics=BacktestMetrics(initial_portfolio_value=INITIAL_CAPITAL, final_portfolio_value=INITIAL_CAPITAL), error=f"No se encontraron datos OHLCV para {pair}/{master_timeframe}.", trades=[])

            # Calcular ATR_14 aquí si no existe
            if ATR_COL_FOR_SLIPPAGE not in df.columns:
                 logger.debug(f"Calculando {ATR_COL_FOR_SLIPPAGE} para {pair} (slippage)...")
                 df.ta.atr(length=14, append=True, col_names=(ATR_COL_FOR_SLIPPAGE,))
                 df.bfill(inplace=True); df.ffill(inplace=True)
            all_data_dict[pair] = df

            if combined_index is None: combined_index = df.index
            else: combined_index = combined_index.union(df.index)

        if combined_index is None or combined_index.empty: return PortfolioBacktestResult(strategy_ids=strategy_ids, strategy_configs=strategy_configs, start_date=start_dt, end_date=end_dt, metrics=BacktestMetrics(initial_portfolio_value=INITIAL_CAPITAL, final_portfolio_value=INITIAL_CAPITAL), error="No se pudo construir índice temporal.", trades=[])

        full_range_index = combined_index[combined_index >= start_dt].sort_values()
        if full_range_index.empty:
             return PortfolioBacktestResult(strategy_ids=strategy_ids, strategy_configs=strategy_configs, start_date=start_dt, end_date=end_dt, metrics=BacktestMetrics(initial_portfolio_value=INITIAL_CAPITAL, final_portfolio_value=INITIAL_CAPITAL), error="No hay datos en el rango solicitado después del calentamiento.", trades=[])

        master_data_aligned: Dict[str, pd.DataFrame] = {}
        for pair, df_pair in all_data_dict.items():
             master_data_aligned[pair] = df_pair.reindex(combined_index.union(df_pair.index), method='ffill')
             master_data_aligned[pair].index.name = 'timestamp'

        logger.info(f"Datos históricos preparados. Rango efectivo: {full_range_index.min()} -> {full_range_index.max()}")

        # --- 3. Calcular Señales ---
        signals_all: Dict[str, pd.DataFrame] = {}
        for s_id in active_strategy_ids:
            instance = strategies[s_id]
            config = configs_used_dict[s_id]
            pair_data_full = master_data_aligned.get(config.pair)
            if pair_data_full is None: continue

            logger.info(f"Calculando señales para {instance.name} (ID: {s_id})...")
            try:
                signals_df = instance.calculate_signals(pair_data_full.copy())
                cols_from_strategy = ['signal', 'sl_price', 'tp_price']
                atr_col_strategy_name = ATR_COL_FOR_SLIPPAGE
                for col in signals_df.columns:
                     if col.startswith('ATR_'):
                          atr_col_strategy_name = col
                          if col not in cols_from_strategy: cols_from_strategy.append(col)
                          break
                if atr_col_strategy_name not in signals_df.columns:
                     signals_df[atr_col_strategy_name] = np.nan

                signals_all[s_id] = signals_df.reindex(full_range_index)[cols_from_strategy]
                signals_all[s_id].fillna({'signal': 0, 'sl_price': np.nan, 'tp_price': np.nan}, inplace=True)
                signals_all[s_id][atr_col_strategy_name] = signals_all[s_id][atr_col_strategy_name].fillna(0)

            except Exception as e:
                 logger.error(f"Error calculando señales para {instance.name}: {e}", exc_info=True)
                 return PortfolioBacktestResult(strategy_ids=strategy_ids, strategy_configs=strategy_configs, start_date=start_dt, end_date=end_dt, metrics=BacktestMetrics(initial_portfolio_value=INITIAL_CAPITAL, final_portfolio_value=INITIAL_CAPITAL), error=f"Error calculando señales para {instance.name}: {e}", trades=[])


        # --- 4. Bucle de Backtesting de Portfolio ---
        logger.info(f"Iniciando bucle de simulación de portfolio ({len(full_range_index)} velas)...")
        num_active_strategies = len(active_strategy_ids)
        portfolio_capital = INITIAL_CAPITAL
        capital_per_strategy: Dict[str, float] = {s_id: portfolio_capital / num_active_strategies for s_id in active_strategy_ids}
        cash_per_strategy: Dict[str, float] = capital_per_strategy.copy()

        positions: Dict[str, Dict[str, Any]] = {}
        trades: List[Trade] = []
        equity_curve_data = {'timestamp': [full_range_index[0] - pd.Timedelta(seconds=1)], 'equity': [portfolio_capital]}
        peak_equity = portfolio_capital
        max_drawdown = 0.0
        trading_halted = False
        total_commission = 0.0

        for timestamp in full_range_index:
            # Calcular valor del portfolio al INICIO de la vela
            current_portfolio_value = sum(cash_per_strategy.values())
            for s_id_pos, position in positions.items():
                 config_pos = configs_used_dict[s_id_pos]; pair_pos = config_pos.pair
                 prev_ts_idx = master_data_aligned[pair_pos].index.get_loc(timestamp) - 1
                 market_price = master_data_aligned[pair_pos]['close'].iloc[prev_ts_idx] if prev_ts_idx >= 0 else position['entry_price']
                 if position['side'] == 'LONG': current_portfolio_value += position['size'] * market_price

            # Check Regla Global Drawdown
            peak_equity = max(peak_equity, current_portfolio_value)
            current_drawdown = (current_portfolio_value - peak_equity) / peak_equity if peak_equity > 0 else 0
            max_drawdown = min(max_drawdown, current_drawdown)

            if not trading_halted and current_drawdown <= -MAX_GLOBAL_DRAWDOWN_PCT:
                 trading_halted = True
                 logger.warning(f"¡REGLA GLOBAL DRAWDOWN ACTIVADA! TS: {timestamp}, DD: {current_drawdown*100:.2f}%, Equity: {current_portfolio_value:.2f}.")

            # Iterar sobre estrategias activas
            for s_id in active_strategy_ids:
                 config = configs_used_dict[s_id]; pair = config.pair
                 current_data = master_data_aligned[pair].loc[timestamp]
                 current_signal_data = signals_all[s_id].loc[timestamp]
                 signal = int(current_signal_data['signal']); signal_sl = current_signal_data['sl_price']; signal_tp = current_signal_data['tp_price']
                 atr_col_signal = [c for c in current_signal_data.index if c.startswith('ATR_')]
                 current_signal_atr = current_signal_data[atr_col_signal[0]] if atr_col_signal else None
                 current_pos = positions.get(s_id)
                 exit_reason = None; pnl_abs = 0.0; commission_trade = 0.0; position_closed = False

                 # --- Lógica de Salida ---
                 if current_pos:
                      pos_side = current_pos['side']; entry_price = current_pos['entry_price']; pos_size = current_pos['size']
                      active_sl = current_pos['sl']; active_tp = current_pos['tp']; entry_ts = current_pos['entry_timestamp']
                      exit_price_base = np.nan; exit_side = 'SELL' if pos_side == 'LONG' else 'BUY'

                      if pos_side == 'LONG':
                           if active_sl and current_data['low'] <= active_sl: exit_price_base = active_sl; exit_reason = 'SL'
                           elif active_tp and current_data['high'] >= active_tp: exit_price_base = active_tp; exit_reason = 'TP'
                           elif signal == 2: exit_price_base = current_data['close']; exit_reason = 'SIGNAL'
                      elif pos_side == 'SHORT':
                           if active_sl and current_data['high'] >= active_sl: exit_price_base = active_sl; exit_reason = 'SL'
                           elif active_tp and current_data['low'] <= active_tp: exit_price_base = active_tp; exit_reason = 'TP'
                           elif signal == -2: exit_price_base = current_data['close']; exit_reason = 'SIGNAL'

                      if exit_reason:
                           exit_price = self._apply_slippage(exit_price_base, exit_side, current_signal_atr)
                           if pos_side == 'LONG': pnl_abs = (exit_price - entry_price) * pos_size
                           else: pnl_abs = (entry_price - exit_price) * pos_size
                           commission_exit = abs(exit_price * pos_size * COMMISSION_PCT)
                           commission_trade = current_pos['commission_entry'] + commission_exit
                           total_commission += commission_exit
                           net_profit_or_loss = pnl_abs - commission_exit
                           cash_per_strategy[s_id] += net_profit_or_loss # <<< Actualización de cash corregida

                           trades.append(Trade(strategy_id=s_id, pair=pair, entry_timestamp=entry_ts, exit_timestamp=timestamp,
                                               entry_price=entry_price, exit_price=exit_price, position_side=pos_side, size=pos_size,
                                               pnl_abs=pnl_abs, pnl_pct=(pnl_abs / abs(entry_price * pos_size)) if entry_price * pos_size != 0 else 0,
                                               entry_signal_type=1 if pos_side == 'LONG' else -1, exit_reason=exit_reason, commission=commission_trade))
                           logger.debug(f"{timestamp} - {s_id}: Cerrado {pos_side} en {exit_price:.4f} (Base:{exit_price_base:.4f}). Razón: {exit_reason}. PnL Neto: {net_profit_or_loss:.2f}. Cash Estr: {cash_per_strategy[s_id]:.2f}")
                           positions.pop(s_id); position_closed = True


                 # --- Lógica de Entrada ---
                 if not current_pos and not position_closed and not trading_halted:
                      entry_signal = signal; sl = signal_sl; tp = signal_tp; intended_side = None
                      if entry_signal == 1: intended_side = 'LONG'
                      elif entry_signal == -1: intended_side = 'SHORT'

                      if intended_side and not np.isnan(sl) and sl > 0:
                           if not pair.endswith('/USDT'): logger.error(f"{timestamp} - {s_id}: Sizing solo soporta /USDT. Par: {pair}"); continue
                           entry_price_base = current_data['close']
                           entry_price = self._apply_slippage(entry_price_base, 'BUY' if intended_side == 'LONG' else 'SELL', current_signal_atr)
                           sl_distance = abs(entry_price - sl)

                           if sl_distance > 1e-9:
                                available_cash_strategy = cash_per_strategy[s_id]
                                if available_cash_strategy <= 0: logger.warning(f"{timestamp} - {s_id}: Señal {entry_signal} ignorada. No hay cash ({available_cash_strategy:.2f})."); continue
                                risk_percent = config.parameters.get('risk_per_trade', DEFAULT_RISK_PER_TRADE)
                                risk_usdt = available_cash_strategy * risk_percent
                                position_size = risk_usdt / sl_distance
                                min_trade_size = 1e-5
                                if position_size < min_trade_size: logger.warning(f"{timestamp} - {s_id}: Señal {entry_signal} ignorada. Tamaño ({position_size:.8f}) < mínimo ({min_trade_size})."); continue

                                commission_entry = abs(entry_price * position_size * COMMISSION_PCT)
                                # --- CORRECCIÓN: Actualización de Cash en Entrada ---
                                can_afford = False
                                if intended_side == 'LONG':
                                     required_total = (entry_price * position_size) + commission_entry
                                     if available_cash_strategy >= required_total:
                                          cash_per_strategy[s_id] -= required_total
                                          can_afford = True
                                elif intended_side == 'SHORT':
                                     if available_cash_strategy >= commission_entry:
                                          cash_per_strategy[s_id] -= commission_entry
                                          can_afford = True
                                # --------------------------------------------
                                if can_afford:
                                     total_commission += commission_entry
                                     positions[s_id] = {'side': intended_side, 'entry_price': entry_price, 'size': position_size, 'sl': sl, 'tp': tp if not np.isnan(tp) else None, 'entry_timestamp': timestamp, 'commission_entry': commission_entry}
                                     logger.debug(f"{timestamp} - {s_id}: Abierto {intended_side} en {entry_price:.4f} (Base:{entry_price_base:.4f}). Size: {position_size:.6f}. SL: {sl:.4f}, TP: {positions[s_id]['tp']}. Cash Estr: {cash_per_strategy[s_id]:.2f}")
                                else:
                                     required_total_log = (entry_price * position_size) + commission_entry if intended_side == 'LONG' else commission_entry
                                     logger.warning(f"{timestamp} - {s_id}: Señal {entry_signal} ignorada. Cash insuficiente ({available_cash_strategy:.2f}) para costo/comisión ({required_total_log:.2f}).")
                           else: logger.warning(f"{timestamp} - {s_id}: Señal entrada {entry_signal} ignorada. Distancia SL cero (Entry={entry_price}, SL={sl}).")

            # Calcular valor total del portfolio al final de la vela
            portfolio_value_eod = sum(cash_per_strategy.values())
            for s_id_eod, position_eod in positions.items():
                 config_eod = configs_used_dict[s_id_eod]; pair_eod = config_eod.pair
                 market_price_eod = master_data_aligned[pair_eod]['close'].loc[timestamp]
                 if position_eod['side'] == 'LONG': portfolio_value_eod += position_eod['size'] * market_price_eod

            equity_curve_data['timestamp'].append(timestamp)
            equity_curve_data['equity'].append(portfolio_value_eod)

        # --- Fin del bucle de tiempo ---
        logger.info(f"Bucle de simulación de portfolio finalizado.")

        # Cerrar posiciones abiertas al final
        final_timestamp = full_range_index[-1]
        final_prices = {pair: master_data_aligned[pair]['close'].iloc[-1] for pair in pairs_needed}
        for s_id, position in list(positions.items()):
             config = configs_used_dict[s_id]; pair = config.pair
             exit_price_base = final_prices.get(pair, position['entry_price'])
             exit_reason = 'END'; pos_side = position['side']
             entry_price = position['entry_price']; pos_size = position['size']; entry_ts = position['entry_timestamp']
             last_atr_col = [c for c in signals_all[s_id].columns if c.startswith('ATR_')]
             last_atr = signals_all[s_id][last_atr_col[0]].iloc[-1] if last_atr_col and not signals_all[s_id][last_atr_col[0]].isnull().all() else master_data_aligned[pair].get(ATR_COL_FOR_SLIPPAGE, pd.Series(0)).iloc[-1]
             exit_price = self._apply_slippage(exit_price_base, 'SELL' if pos_side=='LONG' else 'BUY', last_atr)
             if pos_side == 'LONG': pnl_abs = (exit_price - entry_price) * pos_size
             else: pnl_abs = (entry_price - exit_price) * pos_size
             commission_exit = abs(exit_price * pos_size * COMMISSION_PCT)
             commission_trade = position['commission_entry'] + commission_exit
             total_commission += commission_exit
             # --- CORRECCIÓN: Actualizar Cash Final con PnL Neto ---
             net_profit_or_loss = pnl_abs - commission_exit
             cash_per_strategy[s_id] += net_profit_or_loss
             # ----------------------------------------------------
             trades.append(Trade(strategy_id=s_id, pair=pair, entry_timestamp=entry_ts, exit_timestamp=final_timestamp,
                                 entry_price=entry_price, exit_price=exit_price, position_side=pos_side, size=pos_size,
                                 pnl_abs=pnl_abs, pnl_pct=(pnl_abs / abs(entry_price * pos_size)) if entry_price * pos_size != 0 else 0,
                                 entry_signal_type=1 if pos_side == 'LONG' else -1, exit_reason=exit_reason, commission=commission_trade))
             logger.debug(f"{final_timestamp} - {s_id}: Cerrado Forzoso {pos_side} al final en {exit_price:.4f}. PnL Neto: {net_profit_or_loss:.2f}. Cash Estr: {cash_per_strategy[s_id]:.2f}")

        # 5. Calcular Métricas Finales del Portfolio
        final_portfolio_value = sum(cash_per_strategy.values())
        equity_df = pd.DataFrame(equity_curve_data).set_index('timestamp')
        metrics = self._calculate_metrics(equity_df, trades, total_commission, final_portfolio_value, is_portfolio=True) # Pasar is_portfolio=True

        # 6. Crear Objeto de Resultado
        result = PortfolioBacktestResult(
            strategy_ids=active_strategy_ids,
            strategy_configs=[configs_used_dict[s_id] for s_id in active_strategy_ids],
            start_date=start_dt,
            end_date=end_dt,
            metrics=metrics,
            trades=trades,
            stopped_by_drawdown_rule=trading_halted
        )
        logger.info(f"Backtest de portfolio finalizado. Trades: {metrics.total_trades}, Retorno: {metrics.total_return_pct:.2f}%, Max DD: {metrics.max_drawdown_pct:.2f}%")
        return result


    # ==============================================================
    # --- MÉTODO DE MÉTRICAS (Adaptado) ---
    # ==============================================================
    def _calculate_metrics(self, equity_df: pd.DataFrame, trades: List[Trade],
                           total_commission: float, final_equity: float,
                           is_portfolio: bool) -> BacktestMetrics: # <<< Añadido is_portfolio flag
        """Calcula métricas básicas del backtest (adaptado para single o portfolio)."""
        if equity_df.empty or len(equity_df) < 2:
             initial = INITIAL_CAPITAL # Usar constante global si no hay curva
             return BacktestMetrics(initial_portfolio_value=initial, final_portfolio_value=final_equity if final_equity else initial)

        # Usar el primer valor de la curva como inicial
        initial_equity = equity_df['equity'].iloc[0]
        total_trades = len(trades)
        total_return_pct = ((final_equity / initial_equity) - 1) * 100 if initial_equity > 0 else 0

        winning_trades = [t for t in trades if t.pnl_abs is not None and t.pnl_abs > 0]
        losing_trades = [t for t in trades if t.pnl_abs is not None and t.pnl_abs <= 0]
        win_rate_pct = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0

        total_profit = sum(t.pnl_abs for t in winning_trades)
        total_loss = abs(sum(t.pnl_abs for t in losing_trades))
        profit_factor = total_profit / total_loss if total_loss > 0 else np.inf

        peak = equity_df['equity'].expanding(min_periods=1).max()
        drawdown = (equity_df['equity'] - peak) / peak
        drawdown = drawdown.replace([np.inf, -np.inf], np.nan).fillna(0)
        max_drawdown_pct = (drawdown.min() * 100) if not drawdown.empty and drawdown.min() < 0 else 0.0

# --- NUEVO: Calcular Sharpe Ratio ---
        sharpe_ratio = None
        try:
            # Calcular retornos periódicos (ej. diarios, horarios según timeframe)
            # Necesitamos la frecuencia del índice para anualizar correctamente
            time_diff = equity_df.index.to_series().diff().median() # Frecuencia media
            if time_diff is not None and time_diff > pd.Timedelta(0):
                # Calcular retornos porcentuales
                returns = equity_df['equity'].pct_change().dropna()
                if len(returns) > 1:
                    # Calcular desviación estándar de los retornos periódicos
                    std_dev = returns.std()
                    if std_dev is not None and std_dev > 1e-9: # Evitar división por cero
                        # Calcular retorno promedio periódico
                        mean_return = returns.mean()
                        # Anualizar: Calcular periodos por año
                        # Asumimos mercado 24/7 para cripto
                        periods_per_year = pd.Timedelta(days=365) / time_diff
                        # Sharpe Ratio (Risk-Free Rate = 0)
                        sharpe_ratio = (mean_return / std_dev) * math.sqrt(periods_per_year)
                        logger.debug(f"Cálculo Sharpe: Mean Ret={mean_return:.6f}, StdDev={std_dev:.6f}, Periods/Year={periods_per_year:.1f}, Sharpe={sharpe_ratio:.2f}")
                    else:
                        logger.warning("Desviación estándar de retornos es cero o inválida, no se puede calcular Sharpe Ratio.")
                else:
                    logger.warning("No hay suficientes retornos para calcular Sharpe Ratio.")
            else:
                logger.warning("No se pudo determinar la frecuencia para anualizar Sharpe Ratio.")
        except Exception as e:
            logger.error(f"Error calculando Sharpe Ratio: {e}", exc_info=True)
        # ------------------------------------


        return BacktestMetrics(
            initial_portfolio_value=round(initial_equity, 2),
            final_portfolio_value=round(final_equity, 2),
            total_return_pct=round(total_return_pct, 2),
            max_drawdown_pct=round(max_drawdown_pct, 2),
            win_rate_pct=round(win_rate_pct, 2),
            profit_factor=round(profit_factor, 2) if profit_factor != np.inf else 999.99,
            total_trades=total_trades,
            total_commission_paid=round(total_commission, 4),
            sharpe_ratio=round(sharpe_ratio, 2) if sharpe_ratio is not None else None # <<< AÑADIR
        )

# --- Dependencia para FastAPI (sin cambios) ---
def get_backtesting_service(
    db: Session = Depends(get_db),
    strategy_service: StrategyService = Depends(get_strategy_service)
) -> BacktestingService:
    return BacktestingService(db=db, strategy_service=strategy_service)