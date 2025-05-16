# tests/trading/strategies/test_rsi_mean_reversion.py
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone

from trading.strategies.rsi_mean_reversion import RsiMeanReversionStrategy
from schemas.strategy import StrategyConfig

# --- Datos de Prueba más elaborados ---
# Necesitamos simular RSI bajo/alto y ADX bajo/alto
dates_mr = pd.to_datetime([
    '2023-01-10 10:00:00', '2023-01-10 11:00:00', '2023-01-10 12:00:00', # 0, 1, 2: Normal
    '2023-01-10 13:00:00', '2023-01-10 14:00:00', '2023-01-10 15:00:00', # 3, 4, 5: RSI cae a OS (<30), ADX bajo (<25) -> Señal BUY en 5 al salir
    '2023-01-10 16:00:00', '2023-01-10 17:00:00', '2023-01-10 18:00:00', # 6, 7, 8: RSI sube (sale OS), ADX bajo -> Salida LONG (signal 2) en 6? o 7?
    '2023-01-10 19:00:00', '2023-01-10 20:00:00', '2023-01-10 21:00:00', # 9, 10, 11: RSI sube a OB (>70), ADX bajo -> Señal SELL en 11 al salir
    '2023-01-10 22:00:00', '2023-01-10 23:00:00', '2023-01-11 00:00:00', # 12, 13, 14: RSI cae (sale OB), ADX bajo -> Salida SHORT (signal -2)
    '2023-01-11 01:00:00', '2023-01-11 02:00:00', '2023-01-11 03:00:00', # 15, 16, 17: RSI cae a OS, pero ADX ALTO (>25) -> SIN SEÑAL BUY
], utc=True)

# Simplificamos: Pondremos directamente valores simulados de RSI/ADX/ATR/SMA
# En pruebas reales, podrías generar OHLCV que *produzcan* estos valores
data_mr = {
    'open': 100, 'high': 102, 'low': 98, 'close': 101, 'volume': 10, # Datos OHLCV base (no se usan directamente aquí)
    f'RSI_{14}': [50, 55, 45, 35, 25, 35, 55, 65, 75, 80, 65, 55, 45, 35, 25, 20, 25, 40], # Valores RSI simulados
    f'ADX_{14}': [20, 22, 23, 24, 22, 21, 20, 22, 24, 23, 22, 21, 23, 24, 26, 28, 30, 32], # Valores ADX simulados
    f'ATR_{14}': [1.5] * 18, # ATR constante para simplificar SL
    f'SMA_{20}': [100] * 18 # SMA constante para simplificar TP
}
mock_df_mr = pd.DataFrame(data_mr, index=dates_mr)

# --- Configuración de Prueba ---
rsi_mr_config_dict = {
    "id": "TEST_RSI_MR", "name": "Test RSI MR", "strategy_type": "rsi_mean_reversion",
    "exchange": "test", "pair": "TEST/USDT", "timeframe": "1h",
    "parameters": { # Usar parámetros que coincidan con los datos simulados
         "rsi_period": 14, "rsi_lower": 30, "rsi_upper": 70,
         "adx_period": 14, "adx_threshold": 25,
         "atr_period": 14, "atr_multiplier": 2.0, "tp_sma_period": 20
         },
    "is_active": True
}
rsi_mr_config = StrategyConfig(**rsi_mr_config_dict)

# --- Pruebas ---
def test_rsi_mr_buy_signal():
    """Verifica señal de compra (1) cuando RSI sale de sobreventa con ADX bajo."""
    strategy = RsiMeanReversionStrategy(config=rsi_mr_config.model_dump())
    result_df = strategy.calculate_signals(mock_df_mr.copy())

    buy_signal_time = pd.Timestamp('2023-01-10 15:00:00', tz='UTC') # Vela donde RSI(14)=35 (salió de 25), ADX(14)=21 (<25)
    assert not result_df.empty
    assert result_df.loc[buy_signal_time, 'signal'] == 1
    assert not np.isnan(result_df.loc[buy_signal_time, 'sl_price']) # SL=entry-(mult*ATR)
    assert not np.isnan(result_df.loc[buy_signal_time, 'tp_price']) # TP=SMA

def test_rsi_mr_sell_signal():
    """Verifica señal de venta (-1) cuando RSI sale de sobrecompra con ADX bajo."""
    strategy = RsiMeanReversionStrategy(config=rsi_mr_config.model_dump())
    result_df = strategy.calculate_signals(mock_df_mr.copy())

    sell_signal_time = pd.Timestamp('2023-01-10 21:00:00', tz='UTC') # Vela donde RSI(14)=65 (salió de 80), ADX(14)=22 (<25)
    assert not result_df.empty
    assert result_df.loc[sell_signal_time, 'signal'] == -1
    assert not np.isnan(result_df.loc[sell_signal_time, 'sl_price']) # SL=entry+(mult*ATR)
    assert not np.isnan(result_df.loc[sell_signal_time, 'tp_price']) # TP=SMA

def test_rsi_mr_adx_filter():
    """Verifica que NO haya señal de compra si ADX está alto (> umbral)."""
    strategy = RsiMeanReversionStrategy(config=rsi_mr_config.model_dump())
    result_df = strategy.calculate_signals(mock_df_mr.copy())

    # En timestamp '2023-01-11 03:00:00', RSI=40 (salió de 25) PERO ADX=32 (>25)
    no_buy_signal_time = pd.Timestamp('2023-01-11 03:00:00', tz='UTC')
    assert not result_df.empty
    assert result_df.loc[no_buy_signal_time, 'signal'] == 0 # Esperamos 0 (Hold)

# Añadir pruebas para señales de salida (2, -2) y otros casos borde.