# tests/services/test_backtesting_service.py
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch # Para mocking

# Clases a probar y sus dependencias/schemas
from services.backtesting_service import BacktestingService, INITIAL_CAPITAL, COMMISSION_PCT, ATR_COL_FOR_SLIPPAGE
from services.strategy_service import StrategyService
from db.ohlcv_repository import OHLCVRepository
from schemas.strategy import StrategyConfig
from schemas.trade import Trade
from schemas.backtest_results import PortfolioBacktestResult, BacktestMetrics
from trading.strategies.base_strategy import BaseStrategy # Para mockear

# --- Fixtures de Pytest y Datos Mock ---
@pytest.fixture
def mock_db_session():
    return MagicMock() # Mock simple para la sesión de BD

@pytest.fixture
def mock_strategy_service(mocker): # mocker es fixture de pytest-mock
    mock = mocker.MagicMock(spec=StrategyService)
    # Configurar get_strategy_config para devolver configs de prueba
    test_config_ema = StrategyConfig(
        id="TEST_EMA_1H", name="Test EMA 1H", strategy_type="ema_crossover",
        exchange="binance", pair="BTC/USDT", timeframe="1h",
        parameters={"ema_short": 10, "ema_long": 20, "atr_period": 14, "atr_multiplier": 1.5, "risk_reward_ratio": 2.0, "risk_per_trade": 0.01},
        is_active=True
    )
    test_config_rsi = StrategyConfig(
        id="TEST_RSI_1H", name="Test RSI 1H", strategy_type="rsi_mean_reversion",
        exchange="binance", pair="ETH/USDT", timeframe="1h",
        parameters={"rsi_period": 14, "rsi_lower": 30, "rsi_upper": 70, "atr_period":14, "risk_per_trade": 0.01},
        is_active=True
    )
    # Simular que get_strategy_config devuelve la config correcta por ID
    def get_config_side_effect(strategy_id):
        if strategy_id == "TEST_EMA_1H": return test_config_ema
        if strategy_id == "TEST_RSI_1H": return test_config_rsi
        return None
    mock.get_strategy_config.side_effect = get_config_side_effect
    # Simular list_strategies si es necesario
    mock.list_strategies.return_value = [test_config_ema, test_config_rsi]
    return mock

@pytest.fixture
def mock_ohlcv_repo(mocker):
    mock = mocker.MagicMock(spec=OHLCVRepository)
    return mock

@pytest.fixture
def backtesting_service(mock_db_session, mock_strategy_service):
    # Sobreescribir la instanciación de OHLCVRepository dentro del servicio
    # si no queremos mockearlo globalmente
    with patch('services.backtesting_service.OHLCVRepository') as MockRepo:
         # Instanciar el servicio con dependencias mockeadas
         service = BacktestingService(db=mock_db_session, strategy_service=mock_strategy_service)
         # Guardar la instancia mockeada del repo para usarla en tests si es necesario
         service.ohlcv_repo = MockRepo.return_value # MockRepo() ya fue llamado en __init__
         return service

# --- Datos OHLCV y Señales Mock ---
def create_mock_ohlcv_df(start_iso: str, periods: int, freq: str = '1H'):
    start_dt = datetime.fromisoformat(start_iso.replace('Z', '+00:00'))
    index = pd.date_range(start=start_dt, periods=periods, freq=freq, name='timestamp')
    data = {
        'open': np.linspace(100, 100 + periods -1, periods),
        'high': np.linspace(102, 102 + periods -1, periods),
        'low': np.linspace(98, 98 + periods -1, periods),
        'close': np.linspace(101, 101 + periods -1, periods),
        'volume': np.linspace(1000, 1000 + periods*10, periods),
        ATR_COL_FOR_SLIPPAGE: np.full(periods, 1.5) # ATR constante para slippage
    }
    # Columna ATR específica de estrategia (si la estrategia la espera)
    # Por ejemplo, si atr_period es 14
    # data[f'ATR_{14}'] = np.full(periods, 1.5)
    return pd.DataFrame(data, index=index)

def create_mock_signals_df(index: pd.DatetimeIndex, signal_candle_index: int = 5, side: int = 1,
                           sl_offset: float = 2.0, tp_offset: float = 4.0):
    signals = pd.DataFrame(index=index, columns=['signal', 'sl_price', 'tp_price'])
    signals['signal'] = 0
    signals['sl_price'] = np.nan
    signals['tp_price'] = np.nan

    if 0 <= signal_candle_index < len(index):
        entry_price = index.to_series().iloc[signal_candle_index] # Usar timestamp como pseudo precio para test
        # Usar el close del OHLCV mockeado en esa vela para SL/TP
        # Asumimos que mock_ohlcv_df está disponible o que el backtester lo une
        # Para test unitario de backtester, el ohlcv_df viene del mock_ohlcv_repo

        # Esta función mockearía lo que devuelve strategy.calculate_signals()
        # En este caso, el backtester une esto con el OHLCV que ya tiene ATR
        # Las estrategias ya no devuelven ATR
        pass # SL/TP se calculan en la estrategia, esta función mockea el resultado

    return signals


# --- Pruebas para BacktestingService ---
def test_run_single_strategy_backtest_no_trades(backtesting_service, mock_ohlcv_repo, mock_strategy_service):
    """Prueba un backtest individual donde la estrategia no genera señales."""
    start_dt = datetime(2023, 1, 1, tzinfo=timezone.utc)
    end_dt = datetime(2023, 1, 10, tzinfo=timezone.utc)
    test_config = mock_strategy_service.get_strategy_config("TEST_EMA_1H")

    # Configurar mock de OHLCVRepo para devolver datos
    mock_data = create_mock_ohlcv_df("2022-11-01T00:00:00Z", periods=1000, freq='1H')
    mock_ohlcv_repo.get_ohlcv_data.return_value = mock_data

    # Configurar mock de la instancia de ESTRATEGIA para que no devuelva señales
    mock_strategy_instance = MagicMock(spec=BaseStrategy)
    mock_signals = create_mock_signals_df(mock_data.index) # Sin señales activas
    mock_signals.loc[:, ['signal', 'sl_price', 'tp_price']] = 0, np.nan, np.nan # Forzar
    mock_strategy_instance.calculate_signals.return_value = mock_signals
    mock_strategy_instance.name = "Mocked EMA Strategy"

    # Patch _get_strategy_instance para devolver nuestro mock
    with patch.object(backtesting_service, '_get_strategy_instance', return_value=mock_strategy_instance):
        result = backtesting_service.run_single_strategy_backtest(test_config, start_dt, end_dt)

    assert result.error is None
    assert result.metrics.total_trades == 0
    assert result.metrics.total_return_pct == 0.0
    assert result.metrics.final_portfolio_value == INITIAL_CAPITAL
    mock_ohlcv_repo.get_ohlcv_data.assert_called_once()
    mock_strategy_instance.calculate_signals.assert_called_once()

def test_run_single_strategy_one_winning_trade(backtesting_service, mock_ohlcv_repo, mock_strategy_service):
    """Prueba un backtest individual con un solo trade ganador."""
    start_dt = datetime(2023, 1, 1, 0, 0, tzinfo=timezone.utc)
    end_dt = datetime(2023, 1, 1, 10, 0, tzinfo=timezone.utc) # Periodo corto
    test_config = mock_strategy_service.get_strategy_config("TEST_EMA_1H")

    # Datos para 15 velas (suficiente para buffer + algunas de backtest)
    mock_data = create_mock_ohlcv_df("2023-01-01T00:00:00Z", periods=15, freq='1H')
    mock_ohlcv_repo.get_ohlcv_data.return_value = mock_data.copy()

    # Mock de la estrategia para generar una señal de compra y luego salida por TP
    mock_strategy_instance = MagicMock(spec=BaseStrategy)
    signals = pd.DataFrame(index=mock_data.index, columns=['signal', 'sl_price', 'tp_price'])
    signals['signal'] = 0
    signals['sl_price'] = np.nan
    signals['tp_price'] = np.nan

    # Señal de compra en la vela con índice (timestamp) 2023-01-01 02:00:00+00:00 (es la vela 3, índice 2)
    # Asumimos que el backtest real empieza en 2023-01-01 00:00:00+00:00
    # por lo que esta señal está dentro del rango de backtest.
    buy_signal_idx = mock_data[mock_data.index >= start_dt].index[2]
    entry_price_base = mock_data.loc[buy_signal_idx, 'close']
    atr_val = mock_data.loc[buy_signal_idx, ATR_COL_FOR_SLIPPAGE]

    signals.loc[buy_signal_idx, 'signal'] = 1
    signals.loc[buy_signal_idx, 'sl_price'] = entry_price_base - 1.5 * atr_val # SL ejemplo
    signals.loc[buy_signal_idx, 'tp_price'] = entry_price_base + 3.0 * atr_val # TP ejemplo (R:R de 2:1)

    mock_strategy_instance.calculate_signals.return_value = signals
    mock_strategy_instance.name = "Mocked Win Strategy"

    with patch.object(backtesting_service, '_get_strategy_instance', return_value=mock_strategy_instance):
        result = backtesting_service.run_single_strategy_backtest(test_config, start_dt, end_dt)

    assert result.error is None
    assert result.metrics.total_trades == 1
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.position_side == "LONG"
    assert trade.exit_reason == "TP" # Asumiendo que el TP se alcanza con los datos de prueba
    assert trade.pnl_abs > 0 # Ganador
    assert result.metrics.win_rate_pct == 100.0
    assert result.metrics.total_return_pct > 0.0

# --- Añadir más pruebas para BacktestingService ---
# - Un trade perdedor (sale por SL)
# - Múltiples trades (combinación de ganadores y perdedores)
# - Salida por señal de la estrategia (signal = 2 o -2)
# - Salida por final de backtest ('END')
# - Errores (datos no encontrados, error en cálculo de señales de estrategia mockeada)
# - Pruebas para run_portfolio_backtest (más complejas de mockear):
#   - Con una estrategia activa, con múltiples
#   - Verificando la regla de drawdown global
#   - Verificando la asignación de capital
# -------------------------------------------------

# Pruebas para _calculate_metrics
def test_calculate_metrics_no_trades(backtesting_service):
    equity_df = pd.DataFrame({'equity': [INITIAL_CAPITAL, INITIAL_CAPITAL]},
                             index=pd.to_datetime(['2023-01-01', '2023-01-02'], utc=True))
    metrics = backtesting_service._calculate_metrics(equity_df, [], 0.0, INITIAL_CAPITAL, "1d", False)
    assert metrics.total_trades == 0
    assert metrics.total_return_pct == 0.0
    assert metrics.sharpe_ratio is None # O 0.0 si se devuelve eso por convención y std_dev es 0

def test_calculate_metrics_with_profit(backtesting_service):
    start_capital = 10000.0
    final_capital = 11000.0
    equity_values = np.linspace(start_capital, final_capital, 100) # Curva de equity simple
    equity_df = pd.DataFrame({'equity': equity_values},
                             index=pd.date_range(start='2023-01-01', periods=100, freq='1D', tz='UTC'))

    # Simular un trade ganador
    mock_trade = Trade(
        strategy_id="test", pair="TEST/USDT",
        entry_timestamp=datetime(2023,1,1, tzinfo=timezone.utc),
        exit_timestamp=datetime(2023,1,2, tzinfo=timezone.utc),
        entry_price=100, exit_price=110,
        position_side="LONG", size=10,
        pnl_abs=100, pnl_pct=0.1, commission=1.0,
        entry_signal_type=1, exit_reason="TP"
    )

    metrics = backtesting_service._calculate_metrics(equity_df, [mock_trade], 1.0, final_capital, "1d", False)
    assert metrics.total_trades == 1
    assert metrics.total_return_pct == pytest.approx(10.0)
    assert metrics.win_rate_pct == 100.0
    assert metrics.profit_factor == pytest.approx(999.99) # Infinito
    assert metrics.sharpe_ratio is not None # Debería calcularse