# tests/services/test_strategy_service.py
import pytest
from unittest.mock import patch # Para mockear settings
from typing import List, Dict, Any

# Importar lo que necesitamos probar
from services.strategy_service import StrategyService
from schemas.strategy import StrategyConfig

# --- Datos Mock para settings.STRATEGIES ---
MOCK_VALID_STRATEGIES: List[Dict[str, Any]] = [
    {
        "id": "VALID_1", "name": "Valid Strategy 1", "strategy_type": "ema_crossover",
        "exchange": "binance", "pair": "BTC/USDT", "timeframe": "1h",
        "parameters": {"ema_short": 10, "ema_long": 20}, "is_active": True
    },
    {
        "id": "VALID_2", "name": "Valid Strategy 2", "strategy_type": "rsi_mean_reversion",
        "exchange": "binance", "pair": "ETH/USDT", "timeframe": "4h",
        "parameters": {"rsi_period": 14, "rsi_lower": 25}, "is_active": False # is_active False es válido
    }
]

MOCK_INVALID_STRATEGIES: List[Dict[str, Any]] = [
    {"id": "INVALID_1", "name": "Missing Type"}, # Falta strategy_type (requerido)
    {
        "id": "VALID_1", "name": "Duplicate ID", "strategy_type": "ema_crossover", # ID Duplicado
        "exchange": "binance", "pair": "LTC/USDT", "timeframe": "1h", "parameters": {}, "is_active": True
    },
    MOCK_VALID_STRATEGIES[0] # Añadir uno válido para probar mezcla
]

# --- Pruebas ---
# Usar patch para reemplazar settings.STRATEGIES durante la prueba
@patch('services.strategy_service.settings.STRATEGIES', MOCK_VALID_STRATEGIES)
def test_strategy_service_load_valid_configs():
    """Prueba que el servicio carga correctamente configuraciones válidas."""
    service = StrategyService() # __init__ llamará a _load_configs con el mock
    assert len(service.strategy_configs) == 2
    assert "VALID_1" in service.strategy_configs
    assert "VALID_2" in service.strategy_configs
    assert isinstance(service.strategy_configs["VALID_1"], StrategyConfig)

@patch('services.strategy_service.settings.STRATEGIES', MOCK_INVALID_STRATEGIES)
def test_strategy_service_load_invalid_configs(caplog): # caplog es fixture de pytest para capturar logs
    """Prueba que el servicio maneja configs inválidas y duplicados."""
    service = StrategyService()
    # Esperamos solo 1 config válida (la última, MOCK_VALID_STRATEGIES[0])
    # La inválida se ignora, la duplicada se ignora.
    assert len(service.strategy_configs) == 1
    assert "VALID_1" in service.strategy_configs # El último VALID_1 debe estar
    assert "INVALID_1" not in service.strategy_configs

    # Verificar logs (opcional pero útil)
    assert "Error al validar la configuración de la estrategia #1" in caplog.text
    assert "ID de estrategia duplicado encontrado y omitido: 'VALID_1'" in caplog.text

@patch('services.strategy_service.settings.STRATEGIES', MOCK_VALID_STRATEGIES)
def test_list_strategies():
    """Prueba el método list_strategies."""
    service = StrategyService()
    strategy_list = service.list_strategies()
    assert isinstance(strategy_list, list)
    assert len(strategy_list) == 2
    assert all(isinstance(s, StrategyConfig) for s in strategy_list)
    assert {s.id for s in strategy_list} == {"VALID_1", "VALID_2"}

@patch('services.strategy_service.settings.STRATEGIES', MOCK_VALID_STRATEGIES)
def test_get_strategy_config():
    """Prueba el método get_strategy_config."""
    service = StrategyService()
    # Encontrado
    config1 = service.get_strategy_config("VALID_1")
    assert config1 is not None
    assert config1.id == "VALID_1"
    assert config1.parameters["ema_short"] == 10

    # No encontrado
    config_none = service.get_strategy_config("NON_EXISTENT")
    assert config_none is None