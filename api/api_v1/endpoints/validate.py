# api/api_v1/endpoints/validate.py
from fastapi import APIRouter, Depends, HTTPException, status as http_status, Body
import logging
from datetime import datetime, timezone

# --- CAMBIO: Importar la TAREA Celery ---
from services.validation_service import run_walk_forward_task
# Ya no importamos ValidationService ni get_validation_service
# -----------------------------------------
from schemas.validation_results import WalkForwardRequest, WalkForwardSummary # Mantener schema de request
from schemas.task_results import TaskResponse # Para la respuesta con Task ID

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post(
    "/walkforward",
    response_model=TaskResponse, # <<< CAMBIO: Devolver TaskResponse
    status_code=http_status.HTTP_202_ACCEPTED, # <<< CAMBIO: Indicar Aceptado
    summary="Lanzar Validación Walk-Forward (Asíncrona)",
    description="Inicia una tarea en segundo plano para ejecutar Walk-Forward Optimization.",
    responses={ # Documentar respuestas
        202: {"description": "Tarea de validación Walk-Forward aceptada y encolada."},
        400: {"description": "Parámetros de petición inválidos"},
        500: {"description": "Error interno al iniciar la tarea"}
    }
)
async def trigger_walk_forward_validation( # Cambiado nombre
    # El request body ahora es directamente el WalkForwardRequest
    request: WalkForwardRequest = Body(...)
    # Ya no necesitamos inyectar servicios aquí
):
    """
    Endpoint para iniciar una validación Walk-Forward en segundo plano.
    """
    logger.info(f"Endpoint POST /validate/walkforward llamado (Async Trigger) para strategy ID: {request.strategy_id}")

    # Validaciones básicas de entrada (Pydantic ya hizo la mayoría)
    try:
        start_dt_iso = request.full_start_date.isoformat()
        end_dt_iso = request.full_end_date.isoformat()
        if request.full_start_date >= request.full_end_date:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="Fecha inicio debe ser anterior a fecha fin.")
        if not request.parameter_space:
             raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="Se requiere 'parameter_space'.")
    except AttributeError:
         raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="Formato de fecha inválido en la petición.")


    try:
        # --- CAMBIO: Llamar a la tarea Celery con .delay() ---
        task = run_walk_forward_task.delay(
            strategy_id=request.strategy_id,
            full_start_date_iso=start_dt_iso,
            full_end_date_iso=end_dt_iso,
            in_sample_period_str=request.in_sample_period,
            out_of_sample_period_str=request.out_of_sample_period,
            parameter_space=request.parameter_space,
            optimize_metric=request.optimize_metric
        )
        # --------------------------------------------------

        logger.info(f"Tarea de Walk-Forward para {request.strategy_id} encolada con ID: {task.id}")
        return TaskResponse(task_id=task.id, message="Tarea de Validación Walk-Forward iniciada.")

    except Exception as e:
        logger.exception(f"Error al encolar la tarea de Walk-Forward para {request.strategy_id}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al iniciar la tarea de Walk-Forward: {e}"
        )