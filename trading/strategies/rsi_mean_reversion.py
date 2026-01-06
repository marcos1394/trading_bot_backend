# trading/strategies/rsi_mean_reversion.py
import pandas as pd
import numpy as np
import logging
from .base_strategy import BaseStrategy
from typing import Dict, Any

# --- CAMBIO: Importamos indicadores específicos de la librería 'ta' ---
from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator, SMAIndicator
from ta.volatility import AverageTrueRange
# --------------------------------------------------------------------

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
        self.adx_period = int(params.get("adx_period", 14))
        self.adx_threshold = int(params.get("adx_threshold", 25))
        self.atr_period = int(params.get("atr_period", 14))
        self.atr_multiplier = float(params.get("atr_multiplier", 2.0))
        self.tp_sma_period = int(params.get("tp_sma_period", 20))

        # Validaciones
        if not (0 < self.rsi_os < self.rsi_ob < 100 and self.rsi_period > 0 and \
                self.adx_period > 0 and self.adx_threshold > 0 and \
                self.atr_period > 0 and self.atr_multiplier > 0 and self.tp_sma_period > 0):
            raise ValueError(f"Parámetros inválidos para {self.config.get('id')}: {params}")

        self._name = f"RSI_MR_{self.rsi_period}_{self.rsi_ob}_{self.rsi_os}_ADX{self.adx_period}_{self.adx_threshold}_ATR{self.atr_period}_{self.atr_multiplier}_SMATP{self.tp_sma_period}"
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

        # --- 2. Gestión de SMA para Take Profit ---
        sma_tp_col = f'SMA_{self.tp_sma_period}'
        if sma_tp_col not in df_copy.columns:
            # Usar SMAIndicator de 'ta'
            sma_ind = SMAIndicator(close=df_copy['close'], window=self.tp_sma_period)
            df_copy[sma_tp_col] = sma_ind.sma_indicator()
            # Rellenar
            df_copy[sma_tp_col] = df_copy[sma_tp_col].bfill().ffill()

        # --- 3. Calcular Indicadores de la Estrategia (RSI, ADX) ---
        rsi_col = f'RSI_{self.rsi_period}'
        adx_col = f'ADX_{self.adx_period}'

        # RSI
        rsi_ind = RSIIndicator(close=df_copy['close'], window=self.rsi_period)
        df_copy[rsi_col] = rsi_ind.rsi()

        # ADX
        adx_ind = ADXIndicator(high=df_copy['high'], low=df_copy['low'], close=df_copy['close'], window=self.adx_period)
        df_copy[adx_col] = adx_ind.adx()

        # Rellenar NaNs iniciales generados por RSI/ADX
        cols_to_fill = [rsi_col, adx_col]
        df_copy[cols_to_fill] = df_copy[cols_to_fill].bfill().ffill()

        if df_copy[cols_to_fill].isnull().values.any():
             logger.warning(f"{self.name}: Aún hay NaNs después de rellenar indicadores.")

        # --- 4. Lógica de Señales (Idéntica a la original) ---
        cond_rango = df_copy[adx_col] < self.adx_threshold
        
        # Cruce alcista del nivel Oversold (30) hacia arriba
        cond_buy_entry = cond_rango & (df_copy[rsi_col] > self.rsi_os) & (df_copy[rsi_col].shift(1) <= self.rsi_os)
        
        # Cruce bajista del nivel Overbought (70) hacia abajo
        cond_sell_entry = cond_rango & (df_copy[rsi_col] < self.rsi_ob) & (df_copy[rsi_col].shift(1) >= self.rsi_ob)
        
        cond_long_exit = df_copy[rsi_col] > 50
        cond_short_exit = df_copy[rsi_col] < 50

        df_copy['signal'] = 0
        df_copy.loc[cond_buy_entry, 'signal'] = 1
        df_copy.loc[cond_sell_entry, 'signal'] = -1
        
        # Convertir salidas a códigos 2 / -2
        # (Nota: en pandas moderno es mejor hacerlo directo que con replace sobre slice)
        mask_long_exit = (df_copy['signal'] == 0) & cond_long_exit
        df_copy.loc[mask_long_exit, 'signal'] = 2
        
        mask_short_exit = (df_copy['signal'] == 0) & cond_short_exit
        df_copy.loc[mask_short_exit, 'signal'] = -2

        # --- 5. Calcular SL y TP (Idéntico a original) ---
        df_copy['sl_price'] = np.nan
        df_copy['tp_price'] = np.nan

        # Longs
        entry_long_indices = df_copy[df_copy['signal'] == 1].index
        if not entry_long_indices.empty:
            entry_prices = df_copy.loc[entry_long_indices, 'close']
            atr_vals = df_copy.loc[entry_long_indices, atr_col]
            sma_vals = df_copy.loc[entry_long_indices, sma_tp_col]
            
            df_copy.loc[entry_long_indices, 'sl_price'] = entry_prices - (self.atr_multiplier * atr_vals)
            df_copy.loc[entry_long_indices, 'tp_price'] = sma_vals # Target es la media móvil

        # Shorts
        entry_short_indices = df_copy[df_copy['signal'] == -1].index
        if not entry_short_indices.empty:
            entry_prices = df_copy.loc[entry_short_indices, 'close']
            atr_vals = df_copy.loc[entry_short_indices, atr_col]
            sma_vals = df_copy.loc[entry_short_indices, sma_tp_col]
            
            df_copy.loc[entry_short_indices, 'sl_price'] = entry_prices + (self.atr_multiplier * atr_vals)
            df_copy.loc[entry_short_indices, 'tp_price'] = sma_vals

        return df_copy[['signal', 'sl_price', 'tp_price']]