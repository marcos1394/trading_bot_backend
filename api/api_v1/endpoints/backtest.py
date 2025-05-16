# api/api_v1/endpoints/backtest.py
from fastapi import APIRouter, Depends, HTTPException, status as http_status, Body
from datetime import datetime, timezone # Asegurar timezone
import logging
from pydantic import BaseModel, Field
from typing import List # Importar List

# Importar el servicio y la dependencia
from services.backtesting_service import BacktestingService, get_backtesting_service
# Importar el NUEVO schema de resultados
from schemas.backtest_results import PortfolioBacktestResult

router = APIRouter()
logger = logging.getLogger(__name__)

# Modelo para el cuerpo de la petición POST para portfolio
class PortfolioBacktestRequest(BaseModel): # <<< Nuevo schema request
    strategy_ids: List[str] = Field(..., description="Lista de IDs de estrategias a incluir en el portfolio.", example=["ETHUSDT_RSI_MR_1H", "SOLUSDT_VOL_BREAK_1H"])
    start_date: datetime = Field(..., description="Fecha de inicio (ISO 8601 UTC)", example="2023-01-01T00:00:00Z")
    end_date: datetime = Field(..., description="Fecha de fin (ISO 8601 UTC)", example="2023-01-31T23:59:59Z")
    # Podríamos añadir aquí initial_capital, allocation_method, etc.

@router.post(
    "/portfolio", # <<< Cambiado path
    response_model=PortfolioBacktestResult, # <<< Cambiado schema respuesta
    summary="Ejecutar Backtest para un Portfolio de Estrategias", # <<< Cambiado summary
    description="Lanza una simulación de backtesting para un conjunto de estrategias especificadas en el rango de fechas dado, aplicando reglas de portfolio.", # <<< Cambiado desc
    responses={ # Documentación de errores posibles
        404: {"description": "Alguna estrategia no encontrada o datos históricos no encontrados"},
        400: {"description": "Parámetros de petición inválidos (ej. fechas)"},
        500: {"description": "Error interno durante el backtest"}
    }
)
async def run_portfolio_backtest( # <<< Cambiado nombre función
    # Obtener datos del cuerpo de la petición usando el nuevo schema
    request_body: PortfolioBacktestRequest = Body(...),
    # Inyectar el servicio de backtesting
    backtesting_service: BacktestingService = Depends(get_backtesting_service)
):
    """
    Endpoint para iniciar una ejecución de backtest de portfolio.
    """
    logger.info(f"Endpoint POST /backtest/portfolio llamado con IDs: {request_body.strategy_ids}, Rango: {request_body.start_date} -> {request_body.end_date}")

    # Validar y asegurar UTC en fechas
    if request_body.start_date.tzinfo is None: request_body.start_date = request_body.start_date.replace(tzinfo=timezone.utc)
    elif request_body.start_date.tzinfo != timezone.utc: request_body.start_date = request_body.start_date.astimezone(timezone.utc)

    if request_body.end_date.tzinfo is None: request_body.end_date = request_body.end_date.replace(tzinfo=timezone.utc)
    elif request_body.end_date.tzinfo != timezone.utc: request_body.end_date = request_body.end_date.astimezone(timezone.utc)


    if request_body.start_date >= request_body.end_date:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="La fecha de inicio debe ser anterior a la fecha de fin.")
    if not request_body.strategy_ids:
         raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="Se debe proporcionar al menos un ID de estrategia.")


    try:
        # Ejecutar el backtest de portfolio
        # Asegúrate que el método en el servicio se llame igual o ajústalo
        result = backtesting_service.run_portfolio_backtest(
            strategy_ids=request_body.strategy_ids,
            start_dt=request_body.start_date,
            end_dt=request_body.end_date
        )

        # Manejar errores reportados por el servicio de backtesting
        if result.error:
             # Determinar código de estado basado en el error
             status_code = http_status.HTTP_500_INTERNAL_SERVER_ERROR # Default
             if "no encontrada" in result.error.lower() or "no se encontraron datos" in result.error.lower():
                  status_code = http_status.HTTP_404_NOT_FOUND
             # Podríamos tener otros códigos para errores específicos
             raise HTTPException(status_code=status_code, detail=result.error)

        # Devolver el resultado completo
        return result

    except HTTPException as http_exc:
         raise http_exc # Re-lanzar excepciones HTTP ya manejadas
    except Exception as e:
        logger.exception(f"Error crítico inesperado al ejecutar backtest de portfolio para {request_body.strategy_ids}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno del servidor durante la ejecución del backtest de portfolio."
        )