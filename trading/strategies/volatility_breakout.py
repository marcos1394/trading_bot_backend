# trading/strategies/volatility_breakout.py
import pandas as pd
import numpy as np
import logging
from .base_strategy import BaseStrategy
from typing import Dict, Any

# --- CAMBIO: Usamos 'ta' para Bandas de Bollinger y ATR ---
from ta.volatility import BollingerBands, AverageTrueRange
# ----------------------------------------------------------

logger = logging.getLogger(__name__)

class VolatilityBreakoutStrategy(BaseStrategy):
    """
    Estrategia que busca breakouts después de periodos de baja volatilidad (Squeeze).
    Usa Bandas de Bollinger y ATR.
    Señales: 1 (Entrada Long), -1 (Entrada Short)
    SL/TP basados en ATR y R:R Ratio.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        params = config.get("parameters", {})
        self.bb_period = int(params.get("bb_period", 20))
        self.bb_stddev = float(params.get("bb_stddev", 2.0))
        self.atr_period = int(params.get("atr_period", 14))
        self.squeeze_threshold_atr_factor = float(params.get("squeeze_threshold_factor", 0.8))
        self.atr_multiplier_sl = float(params.get("atr_multiplier_sl", 1.5))
        self.rr_ratio = float(params.get("risk_reward_ratio", 2.0))

        # Validaciones
        if not (self.bb_period > 0 and self.bb_stddev > 0 and self.atr_period > 0 and \
                self.squeeze_threshold_atr_factor > 0 and self.atr_multiplier_sl > 0 and self.rr_ratio > 0):
            raise ValueError(f"Parámetros inválidos para {self.config.get('id')}: {params}")

        self._name = f"VOL_BREAK_BB{self.bb_period}_{self.bb_stddev}_ATR{self.atr_period}_SQ{self.squeeze_threshold_atr_factor}_SL{self.atr_multiplier_sl}_RR{self.rr_ratio}"
        logger.info(f"Estrategia {self.name} (ID: {self.config.get('id')}) inicializada.")

    @property
    def name(self) -> str:
        return self._name

    def calculate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(df, pd.DataFrame) or df.empty or not all(c in df.columns for c in ['open','high','low','close','volume']):
            logger.warning(f"{self.name}: DataFrame vacío o inválido recibido.")
            return pd.DataFrame(columns=['signal', 'sl_price', 'tp_price'])

        df_copy = df.copy()

        # --- 1. Gestión de ATR (Debe venir del manager, o lo calculamos aquí) ---
        atr_col = f'ATR_{self.atr_period}'
        if atr_col not in df_copy.columns:
            logger.debug(f"{self.name}: Calculando {atr_col} on-the-fly...")
            atr_ind = AverageTrueRange(high=df_copy['high'], low=df_copy['low'], close=df_copy['close'], window=self.atr_period)
            df_copy[atr_col] = atr_ind.average_true_range().bfill().ffill()

        # --- 2. Calcular Bandas de Bollinger con 'ta' ---
        # Instanciar el indicador
        indicator_bb = BollingerBands(close=df_copy['close'], window=self.bb_period, window_dev=self.bb_stddev)

        # Definir nombres de columnas temporales
        bb_upper_col = f'BB_Upper_{self.bb_period}'
        bb_lower_col = f'BB_Lower_{self.bb_period}'
        
        # Obtener los valores (Series)
        df_copy[bb_upper_col] = indicator_bb.bollinger_hband()
        df_copy[bb_lower_col] = indicator_bb.bollinger_lband()

        # Rellenar NaNs iniciales
        cols_to_fill = [bb_upper_col, bb_lower_col, atr_col]
        df_copy[cols_to_fill] = df_copy[cols_to_fill].bfill().ffill()

        if df_copy[cols_to_fill].isnull().values.any():
             logger.warning(f"{self.name}: Aún hay NaNs después de rellenar indicadores.")

        # --- 3. Generar Señales (Squeeze + Breakout) ---
        
        # Ancho de las bandas
        bb_width_abs = df_copy[bb_upper_col] - df_copy[bb_lower_col]
        
        # Condición de Squeeze: ¿Están las bandas "apretadas" comparadas con el ATR?
        cond_squeeze = bb_width_abs < (self.squeeze_threshold_atr_factor * df_copy[atr_col])

        # Breakout Alcista: Precio rompe banda superior Y veníamos de un squeeze
        cond_buy_breakout = (df_copy['close'] > df_copy[bb_upper_col]) & cond_squeeze.shift(1)
        
        # Breakout Bajista: Precio rompe banda inferior Y veníamos de un squeeze
        cond_sell_breakout = (df_copy['close'] < df_copy[bb_lower_col]) & cond_squeeze.shift(1)

        df_copy['signal'] = 0
        df_copy.loc[cond_buy_breakout, 'signal'] = 1
        df_copy.loc[cond_sell_breakout, 'signal'] = -1

        # --- 4. Calcular SL y TP ---
        df_copy['sl_price'] = np.nan
        df_copy['tp_price'] = np.nan

        # Longs
        entry_long_indices = df_copy[df_copy['signal'] == 1].index
        if not entry_long_indices.empty:
            entry_prices = df_copy.loc[entry_long_indices, 'close']
            atr_vals = df_copy.loc[entry_long_indices, atr_col]
            bb_low_vals = df_copy.loc[entry_long_indices, bb_lower_col]
            
            # SL en la banda inferior menos un margen de ATR
            sl_long = bb_low_vals - (self.atr_multiplier_sl * atr_vals)
            tp_long = entry_prices + self.rr_ratio * (entry_prices - sl_long)
            
            df_copy.loc[entry_long_indices, 'sl_price'] = sl_long
            df_copy.loc[entry_long_indices, 'tp_price'] = tp_long

        # Shorts
        entry_short_indices = df_copy[df_copy['signal'] == -1].index
        if not entry_short_indices.empty:
            entry_prices = df_copy.loc[entry_short_indices, 'close']
            atr_vals = df_copy.loc[entry_short_indices, atr_col]
            bb_high_vals = df_copy.loc[entry_short_indices, bb_upper_col]
            
            # SL en la banda superior más un margen de ATR
            sl_short = bb_high_vals + (self.atr_multiplier_sl * atr_vals)
            tp_short = entry_prices - self.rr_ratio * (sl_short - entry_prices)
            
            df_copy.loc[entry_short_indices, 'sl_price'] = sl_short
            df_copy.loc[entry_short_indices, 'tp_price'] = tp_short

        return df_copy[['signal', 'sl_price', 'tp_price']]