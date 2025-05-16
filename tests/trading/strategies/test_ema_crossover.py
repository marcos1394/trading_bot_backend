# tests/trading/strategies/test_ema_crossover.py
import pytest # Framework de pruebas
import pandas as pd
import numpy as np
from datetime import datetime, timezone

# Importar la clase que queremos probar
from trading.strategies.ema_crossover import EmaCrossoverStrategy
from schemas.strategy import StrategyConfig # Necesario para instanciar

# --- Datos de Prueba ---
# Crear un DataFrame de ejemplo simple con un cruce EMA(3) sobre EMA(5)
# Las fechas son importantes para el índice DatetimeIndex
dates = pd.to_datetime([
    '2023-01-01 00:00:00', '2023-01-01 01:00:00', '2023-01-01 02:00:00',
    '2023-01-01 03:00:00', '2023-01-01 04:00:00', '2023-01-01 05:00:00',
    '2023-01-01 06:00:00', '2023-01-01 07:00:00', '2023-01-01 08:00:00',
    '2023-01-01 09:00:00'
], utc=True)

# Datos OHLCV simples + ATR precalculado (la estrategia lo espera)
data = {
    'open':  [100, 101, 102, 101, 100, 99, 100, 102, 104, 103],
    'high':  [101, 102, 103, 102, 101, 100, 101, 103, 105, 104],
    'low':   [99,  100, 101, 100, 99,  98,  99, 101, 103, 102],
    'close': [101, 102, 101, 100, 99, 100, 101, 103, 104, 102],
    'volume':[10,  11,  12,  11,  10,  9,   10,  12,  13,  11],
    'ATR_14':[1.5, 1.6, 1.5, 1.4, 1.5, 1.6, 1.5, 1.6, 1.7, 1.6] # Ejemplo ATR
}
mock_df = pd.DataFrame(data, index=dates)

# --- Pruebas ---
# Usar decorador @pytest.mark.parametrize si quieres probar múltiples configs
def test_ema_crossover_bullish_signal():
    """Verifica que se genere una señal de compra (1) en un cruce alcista."""
    # Configuración simple para la prueba
    test_config_dict = {
        "id": "TEST_EMA", "name": "Test EMA", "strategy_type": "ema_crossover",
        "exchange": "test", "pair": "TEST/USDT", "timeframe": "1h",
        "parameters": {"ema_short": 3, "ema_long": 5, "atr_period": 14, "atr_multiplier": 1.5, "risk_reward_ratio": 2.0},
        "is_active": True
    }
    config = StrategyConfig(**test_config_dict)
    strategy = EmaCrossoverStrategy(config=config.model_dump())

    # Calcular señales
    result_df = strategy.calculate_signals(mock_df.copy()) # Pasar copia

    # Verificar la señal esperada
    # Con EMA 3/5 y los datos de ejemplo, el cruce alcista ocurre en el índice 6 (timestamp '2023-01-01 06:00:00')
    # Nota: Las señales se calculan sobre datos históricos, la decisión se toma al cierre de la vela.
    expected_signal_time = pd.Timestamp('2023-01-01 06:00:00', tz='UTC')

    # Asegurarse que el DataFrame resultado no esté vacío y contenga la columna 'signal'
    assert not result_df.empty
    assert 'signal' in result_df.columns

    # Verificar que la señal en el momento esperado sea 1 (Compra)
    assert result_df.loc[expected_signal_time, 'signal'] == 1

    # Verificar que otras señales sean 0 (Hold) antes y después (excepto posibles salidas)
    assert result_df.loc[pd.Timestamp('2023-01-01 05:00:00', tz='UTC'), 'signal'] == 0
    # Podría haber señal de salida después, no la verificamos aquí por simplicidad

    # Verificar columnas SL/TP (opcionalmente chequear que no sean NaN en la señal de entrada)
    assert 'sl_price' in result_df.columns
    assert 'tp_price' in result_df.columns
    assert not np.isnan(result_df.loc[expected_signal_time, 'sl_price'])
    assert not np.isnan(result_df.loc[expected_signal_time, 'tp_price'])

def test_ema_crossover_no_signal():
    """Verifica que no se genere señal si no hay cruce."""
    # Usar solo las primeras 5 velas donde no hay cruce EMA 3/5
    no_cross_df = mock_df.iloc[:5].copy()
    test_config_dict = {
        "id": "TEST_EMA", "name": "Test EMA", "strategy_type": "ema_crossover",
        "exchange": "test", "pair": "TEST/USDT", "timeframe": "1h",
        "parameters": {"ema_short": 3, "ema_long": 5, "atr_period": 14, "atr_multiplier": 1.5, "risk_reward_ratio": 2.0},
        "is_active": True
    }
    config = StrategyConfig(**test_config_dict)
    strategy = EmaCrossoverStrategy(config=config.model_dump())

    result_df = strategy.calculate_signals(no_cross_df)

    # Verificar que todas las señales sean 0 (o quizás NaN al principio si no se rellenan)
    assert not result_df.empty
    assert 'signal' in result_df.columns
    assert (result_df['signal'] == 0).all()

# --- Añadir más pruebas ---
# - test_ema_crossover_bearish_signal(): Con datos que provoquen cruce bajista.
# - test_ema_crossover_with_nans(): Pasando DF con NaNs para ver si los maneja.
# - test_ema_crossover_edge_cases(): Con periodos EMA inválidos (esperar ValueError).
# ---------------------------