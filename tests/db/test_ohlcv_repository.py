# tests/db/test_ohlcv_repository.py
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch # Para mockear la sesión de BD y pd.read_sql

# Importar la clase a probar
from db.ohlcv_repository import OHLCVRepository
# Importar Session de sqlalchemy.orm solo para type hinting
from sqlalchemy.orm import Session

# --- Mock Data ---
# Un DataFrame de ejemplo que simula lo que devolvería pd.read_sql
mock_dates = pd.to_datetime(['2023-01-01 00:00:00', '2023-01-01 01:00:00'], utc=True)
mock_sql_return_df = pd.DataFrame({
    # 'timestamp' se convertirá en índice por index_col='timestamp'
    'open': [100.0, 101.0],
    'high': [102.0, 101.5],
    'low': [99.0, 100.5],
    'close': [101.0, 101.2],
    'volume': [1000.0, 1200.0]
}, index=mock_dates)
# Renombrar índice para que coincida con la columna original antes de set_index
mock_sql_return_df.index.name = 'timestamp'

# --- Tests ---
@pytest.fixture
def mock_db_session(mocker): # mocker es fixture de pytest-mock
    """Crea un mock para la sesión de SQLAlchemy."""
    mock_session = MagicMock(spec=Session)
    # Mockear el método connection() que usa pd.read_sql
    mock_session.connection.return_value = MagicMock()
    return mock_session

# Usar patch para reemplazar pd.read_sql GLOBALMENTE durante esta prueba
@patch('pandas.read_sql')
def test_get_ohlcv_data_success(mock_read_sql, mock_db_session):
    """Prueba la obtención exitosa de datos."""
    # Configurar el mock de pd.read_sql para devolver nuestro DF de ejemplo
    mock_read_sql.return_value = mock_sql_return_df.copy() # Devolver copia

    repo = OHLCVRepository(db=mock_db_session)
    start = datetime(2023, 1, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2023, 1, 1, 1, 0, tzinfo=timezone.utc)

    result_df = repo.get_ohlcv_data("binance", "BTC/USDT", "1h", start, end)

    # Verificar que pd.read_sql fue llamado (una vez)
    mock_read_sql.assert_called_once()
    # Verificar (opcionalmente) partes de la query SQL o los parámetros pasados
    args, kwargs = mock_read_sql.call_args
    sql_query = str(args[0]) # El primer argumento es la sentencia SQL (objeto text)
    params = kwargs.get('params', {})
    assert "FROM ohlcv_1h" in sql_query
    assert "exchange = :exchange" in sql_query and params.get('exchange') == 'binance'
    assert "pair = :pair" in sql_query and params.get('pair') == 'BTC/USDT'
    assert "timestamp >= :start_dt" in sql_query and params.get('start_dt') == start
    assert "timestamp <= :end_dt" in sql_query and params.get('end_dt') == end
    assert "ORDER BY timestamp ASC" in sql_query

    # Verificar el resultado
    assert isinstance(result_df, pd.DataFrame)
    assert not result_df.empty
    assert len(result_df) == 2
    assert result_df.index.name == 'timestamp'
    assert pd.api.types.is_datetime64_any_dtype(result_df.index)
    assert result_df.index.tz == timezone.utc # Asegurar que el índice es UTC
    assert 'close' in result_df.columns

@patch('pandas.read_sql')
def test_get_ohlcv_data_limit(mock_read_sql, mock_db_session):
    """Prueba la obtención con límite y sin fechas."""
    mock_read_sql.return_value = mock_sql_return_df.iloc[::-1].copy() # Simular DESC order

    repo = OHLCVRepository(db=mock_db_session)
    result_df = repo.get_ohlcv_data("binance", "ETH/USDT", "5m", limit=100)

    mock_read_sql.assert_called_once()
    args, kwargs = mock_read_sql.call_args
    sql_query = str(args[0])
    params = kwargs.get('params', {})
    assert "FROM ohlcv_5m" in sql_query
    assert "timestamp >=" not in sql_query # Sin filtro de fecha
    assert "ORDER BY timestamp DESC LIMIT :limit" in sql_query # Orden DESC y LIMIT
    assert params.get('limit') == 100

    assert isinstance(result_df, pd.DataFrame)
    # Verificar que el resultado final SÍ está ordenado ASC (el repo lo reordena)
    assert result_df.index.is_monotonic_increasing

@patch('pandas.read_sql')
def test_get_ohlcv_data_empty(mock_read_sql, mock_db_session):
    """Prueba el caso donde la consulta no devuelve filas."""
    mock_read_sql.return_value = pd.DataFrame() # Devolver DF vacío

    repo = OHLCVRepository(db=mock_db_session)
    result_df = repo.get_ohlcv_data("binance", "ADA/USDT", "1d")

    mock_read_sql.assert_called_once()
    assert result_df is None # Esperamos None si no hay datos

@patch('pandas.read_sql')
def test_get_ohlcv_data_db_error(mock_read_sql, mock_db_session):
    """Prueba el caso donde pd.read_sql lanza una excepción."""
    mock_read_sql.side_effect = Exception("Simulated DB Error!") # Simular error

    repo = OHLCVRepository(db=mock_db_session)
    result_df = repo.get_ohlcv_data("binance", "SOL/USDT", "4h")

    mock_read_sql.assert_called_once()
    assert result_df is None # Esperamos None si hay error

# Añadir prueba para tabla inexistente (requiere mockear la excepción específica)