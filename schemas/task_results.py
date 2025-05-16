# schemas/task_results.py
from pydantic import BaseModel
from typing import Optional, Any, Dict

class TaskResponse(BaseModel):
    """Respuesta simple al encolar una tarea."""
    task_id: str
    message: str

class TaskStatus(BaseModel):
    """Respuesta al consultar el estado de una tarea."""
    task_id: str
    status: str # Ej: PENDING, STARTED, SUCCESS, FAILURE, RETRY, REVOKED
    progress: Optional[Dict[str, Any]] = None # Información de progreso (ej. {'current': 5, 'total': 27})

class TaskResult(BaseModel):
    """Respuesta al consultar el resultado de una tarea."""
    task_id: str
    status: str
    result: Optional[Any] = None # El resultado devuelto por la tarea (ej. el dict OptimizationSummary)
    error: Optional[str] = None # Mensaje de error si falló
    traceback: Optional[str] = None # Traceback si falló (opcional)