# core/celery_app.py
from celery import Celery
import os
from dotenv import load_dotenv

load_dotenv() # Cargar .env para posibles configuraciones futuras

# URL de conexión a Redis (Broker y Backend)
# Usa localhost si Redis corre localmente o el nombre del host/IP si es remoto/docker en red diferente
REDIS_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")

# Crear instancia de Celery
# El primer argumento es el nombre del módulo actual, útil para tareas automáticas
# Le decimos dónde está el broker y dónde guardar resultados
celery_app = Celery(
    "worker", # Nombre de la aplicación Celery
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[ # Lista de módulos donde Celery buscará tareas (@celery_app.task)
        "services.optimization_service",
        "services.validation_service",
        # Añade otros módulos con tareas aquí si los creas
        ]
)

# Configuración opcional de Celery (puedes añadir más según necesites)
celery_app.conf.update(
    task_serializer='json', # Usar JSON para serializar argumentos/resultados
    accept_content=['json'],  # Aceptar solo contenido JSON
    result_serializer='json', # Guardar resultados como JSON
    timezone=os.getenv("TZ", "UTC"), # Usar UTC o la timezone del sistema
    enable_utc=True,
    # Podrías configurar aquí colas específicas, límites de reintento, etc.
    # task_track_started=True, # Para que el estado 'STARTED' se reporte (útil)
    # result_expires=timedelta(days=7), # Tiempo que guarda resultados en Redis
)

# Opcional: Cargar configuración desde un objeto settings de Django/Flask (no aplica aquí)
# celery_app.config_from_object('django.conf:settings', namespace='CELERY')

# Opcional: Autodiscover tasks (no usado si especificamos 'include')
# celery_app.autodiscover_tasks()

if __name__ == '__main__':
    # Esto permite ejecutar el worker directamente con: python -m core.celery_app worker ...
    celery_app.start()