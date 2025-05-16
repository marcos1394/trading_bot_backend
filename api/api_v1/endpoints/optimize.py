# api/api_v1/endpoints/optimize.py
from fastapi import APIRouter, Depends, HTTPException, status as http_status, Body
import logging
from datetime import datetime, timezone

# --- CAMBIO: Importar la TAREA Celery ---
from services.optimization_service import run_grid_search_task
# Ya no necesitamos importar el servicio ni la dependencia get_optimization_service
# -----------------------------------------
# Importar schema de request y nuevo schema de respuesta de tarea
from schemas.optimization_results import OptimizationRequest
from schemas.task_results import TaskResponse # type: ignore # <<< Importar nuevo schema (lo crearemos después)

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post(
    "/grid/{strategy_id}",
    response_model=TaskResponse, # <<< CAMBIO: Devolver TaskResponse
    status_code=http_status.HTTP_202_ACCEPTED, # <<< CAMBIO: Indicar Aceptado
    summary="Lanzar Optimización Grid Search (Asíncrona)",
    description="Inicia una tarea en segundo plano para ejecutar la optimización Grid Search. Devuelve un ID de tarea para consultar estado/resultado.",
    responses={
        202: {"description": "Tarea de optimización aceptada y encolada."},
        400: {"description": "Parámetros de petición inválidos"},
        # La validación de Strategy ID ahora ocurre dentro de la tarea
        # 500: {"description": "Error interno al iniciar la tarea"} # Opcional
    }
)
async def trigger_grid_search_optimization( # Cambiado nombre
    strategy_id: str,
    request: OptimizationRequest = Body(...),
    # Ya no necesitamos inyectar servicios aquí, solo la tarea
):
    """
    Endpoint para iniciar una optimización Grid Search en segundo plano.
    """
    logger.info(f"Endpoint POST /optimize/grid/{strategy_id} llamado (Async Trigger).")

    # Validaciones rápidas de entrada (Pydantic ya validó tipos)
    try:
        # Asegurar fechas UTC (aunque la tarea también lo hace)
        start_dt_iso = request.start_date.isoformat()
        end_dt_iso = request.end_date.isoformat()
        if request.start_date >= request.end_date:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="Fecha inicio debe ser anterior a fecha fin.")
        if not request.parameter_space:
             raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="Se requiere 'parameter_space'.")
    except AttributeError:
        # Capturar si las fechas no son objetos datetime válidos
         raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="Formato de fecha inválido.")

    try:
        # --- CAMBIO: Llamar a la tarea Celery con .delay() ---
        # Pasamos argumentos serializables (primitivos, dicts, lists)
        task = run_grid_search_task.delay(
            strategy_id=strategy_id,
            param_space=request.parameter_space,
            start_dt_iso=start_dt_iso, # Pasar como string ISO
            end_dt_iso=end_dt_iso,     # Pasar como string ISO
            optimize_metric=request.optimize_metric,
            top_n=request.top_n
        )
        # --------------------------------------------------

        logger.info(f"Tarea de optimización para {strategy_id} encolada con ID: {task.id}")
        # Devolver el ID de la tarea al cliente
        return TaskResponse(task_id=task.id, message="Tarea de optimización iniciada.")

    except Exception as e:
        # Error al *intentar* encolar la tarea (ej. Redis no disponible, error de serialización)
        logger.exception(f"Error al encolar la tarea de optimización para {strategy_id}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al iniciar la tarea de optimización: {e}"
        )