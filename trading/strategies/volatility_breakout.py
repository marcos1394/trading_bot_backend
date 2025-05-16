# trading/strategies/volatility_breakout.py
import pandas as pd
import pandas_ta as ta # type: ignore
import numpy as np
import logging
from .base_strategy import BaseStrategy
from typing import Dict, Any

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
        self.atr_period = int(params.get("atr_period", 14)) # Usaremos ATR para Squeeze y SL/TP
        self.squeeze_threshold_atr_factor = float(params.get("squeeze_threshold_factor", 0.8)) # Umbral de Squeeze: Ancho BB < Factor * ATR
        self.atr_multiplier_sl = float(params.get("atr_multiplier_sl", 1.5)) # Multiplicador ATR para SL
        self.rr_ratio = float(params.get("risk_reward_ratio", 2.0)) # Ratio Riesgo:Recompensa para TP
        # Nota: Parámetros 'squeeze_lookback' y 'volume_factor' de la config no se usan en esta implementación simple

        # Validaciones
        if not (self.bb_period > 0 and self.bb_stddev > 0 and self.atr_period > 0 and \
                self.squeeze_threshold_atr_factor > 0 and self.atr_multiplier_sl > 0 and self.rr_ratio > 0):
            raise ValueError(f"Parámetros inválidos para {self.config.get('id')}: {params}")

        self._name = f"VOL_BREAK_BB{self.bb_period}_{self.bb_stddev}_ATR{self.atr_period}_SQ{self.squeeze_threshold_atr_factor}_SL{self.atr_multiplier_sl}_RR{self.rr_ratio}"
        logger.info(f"Estrategia {self.name} (ID: {self.config.get('id')}) inicializada con parámetros: {params}")

    @property
    def name(self) -> str:
        return self._name

    # Dentro de la clase VolatilityBreakoutStrategy en volatility_breakout.py
    def calculate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula BBands, detecta Squeeze y genera señales de breakout, SL y TP
        usando ATR del DataFrame de entrada. Devuelve solo signal, sl_price, tp_price.
        """
        if not isinstance(df, pd.DataFrame) or df.empty or not all(c in df.columns for c in ['open','high','low','close','volume']):
            logger.warning(f"{self.name}: DataFrame vacío o inválido recibido.")
            return pd.DataFrame(columns=['signal', 'sl_price', 'tp_price'])

        # Nombre esperado de la columna ATR
        atr_col = f'ATR_{self.atr_period}'
        if atr_col not in df.columns:
            raise ValueError(f"Columna ATR '{atr_col}' faltante en los datos de entrada para {self.name}")

        df_copy = df.copy()

        # --- Calcular Indicadores (SOLO BBands) ---
        # <<< NO se calcula ATR aquí >>>
        bb_name = f"BB_{self.bb_period}_{self.bb_stddev}"
        df_copy.ta.bbands(length=self.bb_period, std=self.bb_stddev, append=True,
                        col_names=(f'{bb_name}_L', f'{bb_name}_M', f'{bb_name}_U', f'{bb_name}_B', f'{bb_name}_P'))

        bb_lower_col = f'{bb_name}_L'
        bb_upper_col = f'{bb_name}_U'
        bb_middle_col = f'{bb_name}_M' # Podría usarse para SL alternativo

        # Rellenar NaNs iniciales (BBands y ATR pre-calculado)
        cols_to_fill = [bb_lower_col, bb_middle_col, bb_upper_col, atr_col]
        df_copy[cols_to_fill] = df_copy[cols_to_fill].fillna(method='bfill')
        df_copy[cols_to_fill] = df_copy[cols_to_fill].fillna(method='ffill')
        if df_copy[cols_to_fill].isnull().values.any():
             logger.warning(f"{self.name}: Aún hay NaNs después de rellenar indicadores/ATR.")

        # --- Generar Señales ---
        bb_width_abs = df_copy[bb_upper_col] - df_copy[bb_lower_col]
        # Usar ATR del DataFrame de entrada para el umbral del squeeze
        cond_squeeze = bb_width_abs < (self.squeeze_threshold_atr_factor * df_copy[atr_col])

        cond_buy_breakout = (df_copy['close'] > df_copy[bb_upper_col]) & cond_squeeze.shift(1)
        cond_sell_breakout = (df_copy['close'] < df_copy[bb_lower_col]) & cond_squeeze.shift(1)

        df_copy['signal'] = 0
        df_copy.loc[cond_buy_breakout, 'signal'] = 1
        df_copy.loc[cond_sell_breakout, 'signal'] = -1

        # --- Calcular SL y TP solo en las velas de ENTRADA ---
        df_copy['sl_price'] = np.nan
        df_copy['tp_price'] = np.nan

        entry_long_indices = df_copy[df_copy['signal'] == 1].index
        if not entry_long_indices.empty:
            entry_prices_long = df_copy.loc[entry_long_indices, 'close']
            # Usar ATR del DataFrame de entrada
            atr_values_long = df_copy.loc[entry_long_indices, atr_col]
            sl_long = df_copy.loc[entry_long_indices, bb_lower_col] - (self.atr_multiplier_sl * atr_values_long)
            tp_long = entry_prices_long + self.rr_ratio * (entry_prices_long - sl_long) # R:R basado en SL
            df_copy.loc[entry_long_indices, 'sl_price'] = sl_long
            df_copy.loc[entry_long_indices, 'tp_price'] = tp_long

        entry_short_indices = df_copy[df_copy['signal'] == -1].index
        if not entry_short_indices.empty:
            entry_prices_short = df_copy.loc[entry_short_indices, 'close']
            # Usar ATR del DataFrame de entrada
            atr_values_short = df_copy.loc[entry_short_indices, atr_col]
            sl_short = df_copy.loc[entry_short_indices, bb_upper_col] + (self.atr_multiplier_sl * atr_values_short)
            tp_short = entry_prices_short - self.rr_ratio * (sl_short - entry_prices_short) # R:R basado en SL
            df_copy.loc[entry_short_indices, 'sl_price'] = sl_short
            df_copy.loc[entry_short_indices, 'tp_price'] = tp_short

        # ... (logging sin cambios) ...

        # --- LÍNEA MODIFICADA ---
        return df_copy[['signal', 'sl_price', 'tp_price']]
        # -----------------------