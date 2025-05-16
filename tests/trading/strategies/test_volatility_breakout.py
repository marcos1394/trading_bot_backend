# tests/trading/strategies/test_volatility_breakout.py
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone

from trading.strategies.volatility_breakout import VolatilityBreakoutStrategy
from schemas.strategy import StrategyConfig

# --- Datos de Prueba ---
# Simular un squeeze y luego un breakout
dates_vb = pd.to_datetime([
    '2023-02-01 10:00:00', '2023-02-01 11:00:00', # 0, 1: Normal Vol
    '2023-02-01 12:00:00', '2023-02-01 13:00:00', # 2, 3: Squeeze (Ancho BB < Factor * ATR)
    '2023-02-01 14:00:00', # 4: Breakout Arriba (Close > Upper BB) -> Señal Buy
    '2023-02-01 15:00:00', '2023-02-01 16:00:00', # 5, 6: Normal Vol
    '2023-02-01 17:00:00', '2023-02-01 18:00:00', # 7, 8: Squeeze
    '2023-02-01 19:00:00', # 9: Breakout Abajo (Close < Lower BB) -> Señal Sell
], utc=True)

# Simplificamos poniendo directamente valores de BB y ATR
# Necesitamos BB_L, BB_U, ATR
data_vb = {
    'open': 100, 'high': 105, 'low': 95, 'close': 101, 'volume': 10, # OHLCV base
    f'BB_20_2.0_L': [98, 98.5, 99.5, 99.8, 99.5, 98, 97, 97.5, 97.8, 97.2], # Lower BB
    f'BB_20_2.0_U': [102, 101.5, 100.5, 100.2, 103, 102, 103, 102.5, 102.2, 101.8], # Upper BB
    f'ATR_14':      [2.0, 1.8, 0.8, 0.7, 3.0, 2.5, 2.8, 0.9, 0.8, 3.5] # ATR
}
# Añadir precios de cierre para causar breakouts
data_vb['close'] = [100, 100, 100, 100, 104, 101, 100, 100, 100, 96] # Breakout en índices 4 y 9

mock_df_vb = pd.DataFrame(data_vb, index=dates_vb)

# --- Configuración de Prueba ---
vol_break_config_dict = {
    "id": "TEST_VOL_BREAK", "name": "Test Vol Break", "strategy_type": "volatility_breakout",
    "exchange": "test", "pair": "TEST/USDT", "timeframe": "1h",
    "parameters": {
         "bb_period": 20, "bb_stddev": 2.0, "atr_period": 14,
         "squeeze_threshold_atr_factor": 0.8, # Squeeze si AnchoBB < 0.8 * ATR
         "atr_multiplier_sl": 1.5, "risk_reward_ratio": 2.0
        },
    "is_active": True
}
vol_break_config = StrategyConfig(**vol_break_config_dict)

# --- Pruebas ---
def test_vol_breakout_buy_signal():
    """Verifica señal de compra (1) en breakout alcista post-squeeze."""
    strategy = VolatilityBreakoutStrategy(config=vol_break_config.model_dump())
    result_df = strategy.calculate_signals(mock_df_vb.copy())

    buy_signal_time = pd.Timestamp('2023-02-01 14:00:00', tz='UTC')
    # Verificar Squeeze en vela anterior (índice 3):
    # AnchoBB = 100.2 - 99.8 = 0.4. ATR = 0.7. Umbral = 0.8 * 0.7 = 0.56. -> 0.4 < 0.56 (Squeeze=True)
    # Verificar Breakout en vela actual (índice 4):
    # Close = 104. UpperBB = 103. -> Close > UpperBB (Breakout=True)
    assert not result_df.empty
    assert result_df.loc[buy_signal_time, 'signal'] == 1
    assert not np.isnan(result_df.loc[buy_signal_time, 'sl_price']) # SL = BB_L - mult*ATR
    assert not np.isnan(result_df.loc[buy_signal_time, 'tp_price']) # TP = R:R

def test_vol_breakout_sell_signal():
    """Verifica señal de venta (-1) en breakout bajista post-squeeze."""
    strategy = VolatilityBreakoutStrategy(config=vol_break_config.model_dump())
    result_df = strategy.calculate_signals(mock_df_vb.copy())

    sell_signal_time = pd.Timestamp('2023-02-01 19:00:00', tz='UTC')
     # Verificar Squeeze en vela anterior (índice 8):
    # AnchoBB = 102.2 - 97.8 = 4.4. ATR = 0.8. Umbral = 0.8 * 0.8 = 0.64. -> 4.4 NO < 0.64 (Squeeze=False)
    # <<< CORRECCIÓN EN DATOS DE PRUEBA ARRIBA O LÓGICA >>>
    # Ajustemos los datos para que sí haya squeeze en índice 8
    mock_df_vb_adjusted = mock_df_vb.copy()
    mock_df_vb_adjusted.loc[pd.Timestamp('2023-02-01 18:00:00', tz='UTC'), f'BB_20_2.0_L'] = 99.0
    mock_df_vb_adjusted.loc[pd.Timestamp('2023-02-01 18:00:00', tz='UTC'), f'BB_20_2.0_U'] = 99.5
    # Ahora AnchoBB = 0.5. ATR = 0.8. Umbral = 0.64. -> 0.5 < 0.64 (Squeeze=True)

    result_df_adjusted = strategy.calculate_signals(mock_df_vb_adjusted)

    # Verificar Breakout en vela actual (índice 9):
    # Close = 96. LowerBB = 97.2. -> Close < LowerBB (Breakout=True)
    assert not result_df_adjusted.empty
    assert result_df_adjusted.loc[sell_signal_time, 'signal'] == -1
    assert not np.isnan(result_df_adjusted.loc[sell_signal_time, 'sl_price']) # SL = BB_U + mult*ATR
    assert not np.isnan(result_df_adjusted.loc[sell_signal_time, 'tp_price']) # TP = R:R

def test_vol_breakout_no_signal_if_no_squeeze():
    """Verifica que no haya señal si hay breakout pero no hubo squeeze previo."""
    strategy = VolatilityBreakoutStrategy(config=vol_break_config.model_dump())
    # Usar datos originales donde NO había squeeze en índice 8
    result_df = strategy.calculate_signals(mock_df_vb.copy())
    # Aunque hay breakout bajista en índice 9, no debería haber señal
    no_sell_signal_time = pd.Timestamp('2023-02-01 19:00:00', tz='UTC')
    assert result_df.loc[no_sell_signal_time, 'signal'] == 0

# Añadir más pruebas (sin breakout, etc.)