# trading/strategies/ema_crossover.py
import pandas as pd
import numpy as np
import logging
from .base_strategy import BaseStrategy
from typing import Dict, Any

# --- CAMBIO CRÍTICO: Usamos 'ta' en lugar de 'pandas_ta' ---
from ta.trend import EMAIndicator
# -----------------------------------------------------------

logger = logging.getLogger(__name__)

class EmaCrossoverStrategy(BaseStrategy):
    """
    Estrategia basada en el cruce de dos EMAs, con SL/TP basados en ATR.
    Señales: 1 (Entrada Long), -1 (Entrada Short), 2 (Salida Long), -2 (Salida Short)
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        params = config.get("parameters", {})
        self.short_ema_period = int(params.get("ema_short", 12))
        self.long_ema_period = int(params.get("ema_long", 26))
        self.atr_period = int(params.get("atr_period", 14))
        self.atr_multiplier = float(params.get("atr_multiplier", 1.5))
        self.rr_ratio = float(params.get("risk_reward_ratio", 2.0))

        if not (0 < self.short_ema_period < self.long_ema_period and \
                self.atr_period > 0 and self.atr_multiplier > 0 and self.rr_ratio > 0):
            raise ValueError(f"Parámetros inválidos para {self.config.get('id')}: {params}")

        self._name = f"EMA_Cross_{self.short_ema_period}_{self.long_ema_period}_ATR_{self.atr_period}_{self.atr_multiplier}_RR_{self.rr_ratio}"
        logger.info(f"Estrategia {self.name} (ID: {self.config.get('id')}) inicializada.")

    @property
    def name(self) -> str:
        return self._name

    def calculate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        # Validación básica
        if not isinstance(df, pd.DataFrame) or df.empty or not all(c in df.columns for c in ['open','high','low','close','volume']):
            logger.warning(f"{self.name}: DataFrame inválido.")
            return pd.DataFrame(columns=['signal', 'sl_price', 'tp_price'])

        # Verificar ATR (El realtime_manager ya debió calcularlo con 'ta')
        atr_col = f'ATR_{self.atr_period}'
        if atr_col not in df.columns:
            # Intento de emergencia de calcular ATR si no viene del manager
            from ta.volatility import AverageTrueRange
            logger.warning(f"{self.name}: {atr_col} no encontrado. Calculando on-the-fly...")
            atr_ind = AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=self.atr_period)
            df[atr_col] = atr_ind.average_true_range().bfill().ffill()

        df_copy = df.copy()

        # --- CÁLCULO DE INDICADORES CON LIBRERÍA 'ta' ---
        ema_short_col = f'EMA_{self.short_ema_period}'
        ema_long_col = f'EMA_{self.long_ema_period}'

        # 1. EMA Corta
        ema_short_ind = EMAIndicator(close=df_copy['close'], window=self.short_ema_period)
        df_copy[ema_short_col] = ema_short_ind.ema_indicator()

        # 2. EMA Larga
        ema_long_ind = EMAIndicator(close=df_copy['close'], window=self.long_ema_period)
        df_copy[ema_long_col] = ema_long_ind.ema_indicator()
        # ------------------------------------------------

        # Rellenar NaNs iniciales de las EMAs
        cols_to_fill = [ema_short_col, ema_long_col]
        df_copy[cols_to_fill] = df_copy[cols_to_fill].bfill().ffill()

        # --- Generar Señales (Lógica idéntica a tu original) ---
        cond_cruce_alcista = (df_copy[ema_short_col] > df_copy[ema_long_col]) & \
                             (df_copy[ema_short_col].shift(1) <= df_copy[ema_long_col].shift(1))
        
        cond_cruce_bajista = (df_copy[ema_short_col] < df_copy[ema_long_col]) & \
                             (df_copy[ema_short_col].shift(1) >= df_copy[ema_long_col].shift(1))
        
        cond_salida_long = (df_copy[ema_short_col] < df_copy[ema_long_col]) & \
                           (df_copy[ema_short_col].shift(1) >= df_copy[ema_long_col].shift(1))
        
        cond_salida_short = (df_copy[ema_short_col] > df_copy[ema_long_col]) & \
                            (df_copy[ema_short_col].shift(1) <= df_copy[ema_long_col].shift(1))

        df_copy['signal'] = 0
        df_copy.loc[cond_cruce_alcista, 'signal'] = 1
        df_copy.loc[cond_cruce_bajista, 'signal'] = -1
        df_copy.loc[cond_salida_long, 'signal'] = 2
        df_copy.loc[cond_salida_short, 'signal'] = -2

        # --- Calcular SL y TP (Lógica idéntica a tu original) ---
        df_copy['sl_price'] = np.nan
        df_copy['tp_price'] = np.nan

        # Longs
        entry_long_indices = df_copy[df_copy['signal'] == 1].index
        if not entry_long_indices.empty:
            entry_prices = df_copy.loc[entry_long_indices, 'close']
            atr_values = df_copy.loc[entry_long_indices, atr_col]
            sl = entry_prices - self.atr_multiplier * atr_values
            tp = entry_prices + self.rr_ratio * (entry_prices - sl)
            df_copy.loc[entry_long_indices, 'sl_price'] = sl
            df_copy.loc[entry_long_indices, 'tp_price'] = tp

        # Shorts
        entry_short_indices = df_copy[df_copy['signal'] == -1].index
        if not entry_short_indices.empty:
            entry_prices = df_copy.loc[entry_short_indices, 'close']
            atr_values = df_copy.loc[entry_short_indices, atr_col]
            sl = entry_prices + self.atr_multiplier * atr_values
            tp = entry_prices - self.rr_ratio * (sl - entry_prices)
            df_copy.loc[entry_short_indices, 'sl_price'] = sl
            df_copy.loc[entry_short_indices, 'tp_price'] = tp

        return df_copy[['signal', 'sl_price', 'tp_price']]