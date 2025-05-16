# trading/strategies/rsi_mean_reversion.py
import pandas as pd
import pandas_ta as ta # type: ignore
import numpy as np
import logging
from .base_strategy import BaseStrategy
from typing import Dict, Any

logger = logging.getLogger(__name__)

class RsiMeanReversionStrategy(BaseStrategy):
    """
    Estrategia de reversión a la media usando RSI, filtro ADX, SL/TP basados en ATR/SMA.
    Señales: 1 (Entrada Long), -1 (Entrada Short), 2 (Salida Long), -2 (Salida Short)
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        params = config.get("parameters", {})
        self.rsi_period = int(params.get("rsi_period", 14))
        self.rsi_ob = int(params.get("rsi_upper", 70)) # Overbought
        self.rsi_os = int(params.get("rsi_lower", 30)) # Oversold
        self.adx_period = int(params.get("adx_period", 14)) # Usamos periodo separado para ADX
        self.adx_threshold = int(params.get("adx_threshold", 25))
        self.atr_period = int(params.get("atr_period", 14))
        self.atr_multiplier = float(params.get("atr_multiplier", 2.0)) # Multiplicador SL
        self.tp_sma_period = int(params.get("tp_sma_period", 20)) # Periodo SMA para TP

        # Validaciones
        if not (0 < self.rsi_os < self.rsi_ob < 100 and self.rsi_period > 0 and \
                self.adx_period > 0 and self.adx_threshold > 0 and \
                self.atr_period > 0 and self.atr_multiplier > 0 and self.tp_sma_period > 0):
            raise ValueError(f"Parámetros inválidos para {self.config.get('id')}: {params}")

        self._name = f"RSI_MR_{self.rsi_period}_{self.rsi_ob}_{self.rsi_os}_ADX{self.adx_period}_{self.adx_threshold}_ATR{self.atr_period}_{self.atr_multiplier}_SMATP{self.tp_sma_period}"
        logger.info(f"Estrategia {self.name} (ID: {self.config.get('id')}) inicializada con parámetros: {params}")

    @property
    def name(self) -> str:
        return self._name

    # Dentro de la clase RsiMeanReversionStrategy en rsi_mean_reversion.py
    def calculate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula RSI, ADX, SMA y genera señales MR, SL y TP usando ATR/SMA del DF de entrada.
        Devuelve solo signal, sl_price, tp_price.
        """
        if not isinstance(df, pd.DataFrame) or df.empty or not all(c in df.columns for c in ['open','high','low','close','volume']):
            logger.warning(f"{self.name}: DataFrame vacío o inválido recibido.")
            return pd.DataFrame(columns=['signal', 'sl_price', 'tp_price'])

        # Nombres esperados de columnas ATR y SMA (basados en parámetros)
        atr_col = f'ATR_{self.atr_period}'
        sma_tp_col = f'SMA_{self.tp_sma_period}'
        if atr_col not in df.columns:
            raise ValueError(f"Columna ATR '{atr_col}' faltante en los datos de entrada para {self.name}")
        # Calcular SMA para TP aquí si no viene del backtester (o asumir que viene)
        if sma_tp_col not in df.columns:
            logger.debug(f"{self.name}: Calculando columna SMA '{sma_tp_col}' que faltaba...")
            # Calcular sobre la copia para no modificar el original en el backtester
            df_temp_sma = df.copy() # Usar el original para calcular SMA
            df_temp_sma.ta.sma(length=self.tp_sma_period, append=True, col_names=(sma_tp_col,))
            # Añadir la columna SMA calculada al DataFrame principal de entrada df
            # Asegurarse de alinear índices y manejar NaNs
            df[sma_tp_col] = df_temp_sma[sma_tp_col].reindex(df.index)
            df[sma_tp_col] = df[sma_tp_col].fillna(method='bfill')
            df[sma_tp_col] = df[sma_tp_col].fillna(method='ffill')
            del df_temp_sma # Liberar memoria

        df_copy = df.copy()

        # --- Calcular Indicadores (SOLO RSI, ADX) ---
        rsi_col = f'RSI_{self.rsi_period}'
        adx_col = f'ADX_{self.adx_period}'

        df_copy.ta.rsi(length=self.rsi_period, append=True, col_names=(rsi_col,))
        df_copy.ta.adx(length=self.adx_period, append=True, col_names=(adx_col, f'DMP_{self.adx_period}', f'DMN_{self.adx_period}'))
        # <<< NO se calcula ATR ni SMA aquí >>>

        # Rellenar NaNs iniciales (RSI, ADX, y los pre-calculados ATR, SMA)
        cols_to_fill = [rsi_col, adx_col, atr_col, sma_tp_col]
        df_copy[cols_to_fill] = df_copy[cols_to_fill].fillna(method='bfill')
        df_copy[cols_to_fill] = df_copy[cols_to_fill].fillna(method='ffill')
        if df_copy[cols_to_fill].isnull().values.any():
             logger.warning(f"{self.name}: Aún hay NaNs después de rellenar indicadores/ATR/SMA.")

        # --- Generar Señales de Entrada y Salida ---
        cond_rango = df_copy[adx_col] < self.adx_threshold
        cond_buy_entry = cond_rango & (df_copy[rsi_col] > self.rsi_os) & (df_copy[rsi_col].shift(1) <= self.rsi_os)
        cond_sell_entry = cond_rango & (df_copy[rsi_col] < self.rsi_ob) & (df_copy[rsi_col].shift(1) >= self.rsi_ob)
        cond_long_exit = df_copy[rsi_col] > 50
        cond_short_exit = df_copy[rsi_col] < 50

        df_copy['signal'] = 0
        df_copy.loc[cond_buy_entry, 'signal'] = 1
        df_copy.loc[cond_sell_entry, 'signal'] = -1
        df_copy.loc[cond_long_exit, 'signal'] = df_copy.loc[cond_long_exit, 'signal'].replace(0, 2)
        df_copy.loc[cond_short_exit, 'signal'] = df_copy.loc[cond_short_exit, 'signal'].replace(0, -2)

        # --- Calcular SL y TP solo en las velas de ENTRADA ---
        df_copy['sl_price'] = np.nan
        df_copy['tp_price'] = np.nan

        entry_long_indices = df_copy[df_copy['signal'] == 1].index
        if not entry_long_indices.empty:
            entry_prices_long = df_copy.loc[entry_long_indices, 'close']
            # Usar ATR del DataFrame de entrada
            atr_values_long = df_copy.loc[entry_long_indices, atr_col]
            sl_long = entry_prices_long - self.atr_multiplier * atr_values_long
            # Usar SMA del DataFrame de entrada
            tp_long = df_copy.loc[entry_long_indices, sma_tp_col]
            df_copy.loc[entry_long_indices, 'sl_price'] = sl_long
            df_copy.loc[entry_long_indices, 'tp_price'] = tp_long

        entry_short_indices = df_copy[df_copy['signal'] == -1].index
        if not entry_short_indices.empty:
            entry_prices_short = df_copy.loc[entry_short_indices, 'close']
            # Usar ATR del DataFrame de entrada
            atr_values_short = df_copy.loc[entry_short_indices, atr_col]
            sl_short = entry_prices_short + self.atr_multiplier * atr_values_short
            # Usar SMA del DataFrame de entrada
            tp_short = df_copy.loc[entry_short_indices, sma_tp_col]
            df_copy.loc[entry_short_indices, 'sl_price'] = sl_short
            df_copy.loc[entry_short_indices, 'tp_price'] = tp_short

        # ... (logging sin cambios) ...

        # --- LÍNEA MODIFICADA ---
        return df_copy[['signal', 'sl_price', 'tp_price']]
        # -----------------------