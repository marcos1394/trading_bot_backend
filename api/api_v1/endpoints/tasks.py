# api/api_v1/endpoints/tasks.py
from fastapi import APIRouter, HTTPException, status as http_status
from celery.result import AsyncResult
import logging

# Importar la instancia de la app Celery para consultar resultados
from core.celery_app import celery_app
# Importar los schemas de respuesta
from schemas.task_results import TaskStatus, TaskResult

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get(
    "/{task_id}/status",
    response_model=TaskStatus,
    summary="Consultar Estado de Tarea Asíncrona",
    description="Obtiene el estado actual (PENDING, STARTED, SUCCESS, FAILURE...) de una tarea Celery por su ID."
)
async def get_task_status(task_id: str):
    """Consulta el estado de una tarea encolada."""
    logger.debug(f"Consultando estado para task_id: {task_id}")
    try:
        # Usar AsyncResult para obtener información de la tarea desde el backend (Redis)
        task_result = AsyncResult(task_id, app=celery_app)

        progress_info = None
        # Si el estado es PROGRESS, intentar obtener la información 'meta'
        if task_result.state == 'PROGRESS' and isinstance(task_result.info, dict):
            progress_info = task_result.info

        return TaskStatus(
            task_id=task_id,
            status=task_result.state,
            progress=progress_info
        )
    except Exception as e:
        # Podría haber errores si el task_id es inválido o hay problemas con Redis
        logger.exception(f"Error al consultar estado de tarea {task_id}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al obtener estado de la tarea: {e}"
        )

@router.get(
    "/{task_id}/result",
    response_model=TaskResult,
    summary="Consultar Resultado de Tarea Asíncrona",
    description="Obtiene el resultado de una tarea Celery completada (SUCCESS) o el error si falló (FAILURE)."
)
async def get_task_result(task_id: str):
    """Consulta el resultado o error de una tarea."""
    logger.debug(f"Consultando resultado para task_id: {task_id}")
    try:
        task_result = AsyncResult(task_id, app=celery_app)

        response_data = {
            "task_id": task_id,
            "status": task_result.state,
            "result": None,
            "error": None,
            "traceback": None,
        }

        if task_result.successful(): # Equivalente a state == 'SUCCESS'
            response_data["result"] = task_result.result # Obtener el resultado guardado
        elif task_result.failed():
            # Obtener información del error si falló
            # task_result.result o task_result.info pueden contener la excepción
            # task_result.traceback contiene el traceback formateado
            response_data["error"] = str(task_result.result) # El resultado en caso de fallo suele ser la excepción
            # response_data["traceback"] = task_result.traceback # Descomentar si quieres incluir el traceback
        # Para otros estados (PENDING, STARTED, RETRY), result y error serán None

        return TaskResult(**response_data)

    except Exception as e:
        logger.exception(f"Error al consultar resultado de tarea {task_id}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al obtener resultado de la tarea: {e}"
        )