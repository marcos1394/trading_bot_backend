# trading/strategies/ema_crossover.py
import pandas as pd
import pandas_ta as ta # type: ignore
import numpy as np # Necesario para NaN
import logging
from .base_strategy import BaseStrategy
from typing import Dict, Any

logger = logging.getLogger(__name__)

class EmaCrossoverStrategy(BaseStrategy):
    """
    Estrategia basada en el cruce de dos EMAs, con SL/TP basados en ATR.
    Señales: 1 (Entrada Long), -1 (Entrada Short), 2 (Salida Long), -2 (Salida Short)
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config) # Llama al init de la clase base
        # Extraer parámetros específicos de la configuración con valores por defecto
        params = config.get("parameters", {})
        self.short_ema_period = int(params.get("ema_short", 12))
        self.long_ema_period = int(params.get("ema_long", 26))
        self.atr_period = int(params.get("atr_period", 14))
        self.atr_multiplier = float(params.get("atr_multiplier", 1.5)) # Multiplicador para SL
        self.rr_ratio = float(params.get("risk_reward_ratio", 2.0)) # Ratio Riesgo:Recompensa para TP

        # Validaciones
        if not (0 < self.short_ema_period < self.long_ema_period and \
                self.atr_period > 0 and self.atr_multiplier > 0 and self.rr_ratio > 0):
            raise ValueError(f"Parámetros inválidos para {self.config.get('id')}: {params}")

        self._name = f"EMA_Cross_{self.short_ema_period}_{self.long_ema_period}_ATR_{self.atr_period}_{self.atr_multiplier}_RR_{self.rr_ratio}"
        logger.info(f"Estrategia {self.name} (ID: {self.config.get('id')}) inicializada con parámetros: {params}")

    @property
    def name(self) -> str:
        return self._name

    def calculate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula EMAs, señales de cruce, SL y TP usando ATR del DataFrame de entrada.
        Devuelve solo signal, sl_price, tp_price.
        """
        if not isinstance(df, pd.DataFrame) or df.empty or not all(c in df.columns for c in ['open','high','low','close','volume']):
            logger.warning(f"{self.name}: DataFrame vacío o inválido recibido.")
            return pd.DataFrame(columns=['signal', 'sl_price', 'tp_price']) # Devolver DF vacío con columnas

        # Nombre esperado de la columna ATR (basado en los parámetros de esta estrategia)
        atr_col = f'ATR_{self.atr_period}'
        if atr_col not in df.columns:
            logger.error(f"{self.name}: La columna requerida '{atr_col}' no se encontró en el DataFrame de entrada.")
            # Fallar si falta el ATR necesario para SL/TP
            raise ValueError(f"Columna ATR '{atr_col}' faltante en los datos de entrada para {self.name}")

        df_copy = df.copy()

        # --- Calcular Indicadores (SOLO los necesarios para la señal) ---
        ema_short_col = f'EMA_{self.short_ema_period}'
        ema_long_col = f'EMA_{self.long_ema_period}'

        df_copy.ta.ema(length=self.short_ema_period, append=True, col_names=(ema_short_col,))
        df_copy.ta.ema(length=self.long_ema_period, append=True, col_names=(ema_long_col,))
        # <<< NO se calcula ATR aquí >>>

        # Rellenar NaNs iniciales (solo para EMAs)
        # Asegurarse de no rellenar la columna ATR original por accidente si no se recalcula
        cols_to_fill = [ema_short_col, ema_long_col]
        df_copy[cols_to_fill] = df_copy[cols_to_fill].fillna(method='bfill')
        df_copy[cols_to_fill] = df_copy[cols_to_fill].fillna(method='ffill')
        # Rellenar ATR por si tuviera NaNs iniciales del cálculo externo
        df_copy[atr_col] = df_copy[atr_col].fillna(method='bfill')
        df_copy[atr_col] = df_copy[atr_col].fillna(method='ffill')

        if df_copy[[ema_short_col, ema_long_col, atr_col]].isnull().values.any():
             logger.warning(f"{self.name}: Aún hay NaNs después de rellenar indicadores/ATR.")
             # Podría causar problemas en SL/TP, el backtester debería ser robusto

        # --- Generar Señales de Entrada y Salida ---
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

        # --- Calcular SL y TP solo en las velas de ENTRADA ---
        df_copy['sl_price'] = np.nan
        df_copy['tp_price'] = np.nan

        # Calcular SL/TP para entradas Long (signal == 1)
        entry_long_indices = df_copy[df_copy['signal'] == 1].index
        if not entry_long_indices.empty:
            entry_prices_long = df_copy.loc[entry_long_indices, 'close']
            # Usar ATR del DataFrame de entrada (df_copy)
            atr_values_long = df_copy.loc[entry_long_indices, atr_col]
            sl_long = entry_prices_long - self.atr_multiplier * atr_values_long
            tp_long = entry_prices_long + self.rr_ratio * (entry_prices_long - sl_long)
            df_copy.loc[entry_long_indices, 'sl_price'] = sl_long
            df_copy.loc[entry_long_indices, 'tp_price'] = tp_long

        # Calcular SL/TP para entradas Short (signal == -1)
        entry_short_indices = df_copy[df_copy['signal'] == -1].index
        if not entry_short_indices.empty:
            entry_prices_short = df_copy.loc[entry_short_indices, 'close']
            # Usar ATR del DataFrame de entrada (df_copy)
            atr_values_short = df_copy.loc[entry_short_indices, atr_col]
            sl_short = entry_prices_short + self.atr_multiplier * atr_values_short
            tp_short = entry_prices_short - self.rr_ratio * (sl_short - entry_prices_short)
            df_copy.loc[entry_short_indices, 'sl_price'] = sl_short
            df_copy.loc[entry_short_indices, 'tp_price'] = tp_short

        # ... (logging sin cambios) ...

        # --- LÍNEA MODIFICADA ---
        # Devolver solo las columnas de decisión
        return df_copy[['signal', 'sl_price', 'tp_price']]
        # -----------------------