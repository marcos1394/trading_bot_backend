# tests/api/api_v1/test_status_endpoint.py
import pytest
from httpx import AsyncClient # Cliente HTTP asíncrono para FastAPI
from fastapi import status # Para códigos de estado HTTP

# Importar la app FastAPI principal
# La ruta puede necesitar ajuste según cómo corras pytest desde la raíz
from main import app

# Marcar las pruebas como asíncronas para pytest-asyncio
@pytest.mark.asyncio
async def test_get_status_ok():
    """Prueba que el endpoint /api/v1/status responde OK."""
    # Usar AsyncClient para hacer peticiones a la app FastAPI
    # 'base_url' simula el servidor corriendo
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/v1/status")

    # Verificar código de estado
    assert response.status_code == status.HTTP_200_OK

    # Verificar contenido básico de la respuesta
    json_response = response.json()
    assert json_response["status"] == "ok"
    assert "timestamp" in json_response
    # La conexión a BD podría fallar si no hay BD de prueba,
    # podríamos mockear 'check_db_connection' o solo verificar que la clave existe
    assert "db_connection_ok" in json_response

# --- Añadir más pruebas para API ---
# - Probar endpoints de portfolio (requiere mockear ExchangeService o BD test)
# - Probar endpoints de strategies (usa config, más fácil de probar)
# - Probar endpoints de optimización/validación (requiere mockear servicios o tareas)
# ------------------------------------