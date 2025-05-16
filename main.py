# main.py
from fastapi import FastAPI
from contextlib import asynccontextmanager # <<< NUEVO: Para lifespan
import logging
import asyncio # <<< NUEVO: Para crear tareas

# Importar configuración, router principal, y dependencias de ciclo de vida
from core.config import settings
from api.api_v1.api import api_router
from schemas.live_order import LiveOrderBase
from trading.exchange_service import startup_exchange_service, shutdown_exchange_service
from db.session import check_db_connection
from models.strategy_config_model import Base as StrategyConfigBase
from models.live_position_model import Base as LivePositionBase # <<< AÑADIR
from models.live_order_model import Base as LiveOrderBase # <<< AÑADIR IMPORT

# --- NUEVO: Importar las funciones de tarea ---
from core.realtime_manager import listen_market_data, trading_loop
# -------------------------------------------

# --- NUEVO: Configuración de logging (mover aquí para mejor control) ---
logging.basicConfig(
    level=logging.INFO, # Cambia a DEBUG para ver más detalles
    format='%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING) # Silenciar logs de asyncio si son muy verbosos
# --------------------------------------------------------------------

# --- NUEVO: Usar Lifespan en lugar de eventos startup/shutdown ---
# Lifespan es la forma moderna recomendada en FastAPI para gestionar inicio/apagado
# y lanzar tareas de fondo persistentes.

background_tasks = set() # Para mantener referencia a las tareas

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Código que se ejecuta ANTES de que la aplicación empiece a aceptar peticiones (Startup)
    logger = logging.getLogger("main.lifespan")
    logger.info("=== Aplicación Iniciando (Lifespan) ===")

    # Crear tablas DB (si aún no existen)
    # Importar aquí para evitar imports circulares potenciales a nivel de módulo
    from db.session import engine
    from models.strategy_config_model import Base as StrategyConfigBase
    def create_db_tables():
        logger.info("Creando/Verificando tablas de base de datos...")
        try:
            StrategyConfigBase.metadata.create_all(bind=engine)
            LivePositionBase.metadata.create_all(bind=engine) # <<< AÑADIR
            LiveOrderBase.metadata.create_all(bind=engine) # <<< AÑADIR CREATE_ALL

            logger.info("Tablas verificadas/creadas.")
        except Exception as e: logger.error(f"Error creando tablas: {e}", exc_info=True)
    create_db_tables()

    # Verificar conexión BD
    logger.info("Verificando conexión a BD...")
    if not check_db_connection(): logger.warning("La conexión inicial a la base de datos falló.")

    # Preparar servicio de exchange
    await startup_exchange_service()

    # --- Lanzar Tareas de Fondo ---
    logger.info("Lanzando tareas de fondo (Listener de Mercado, Bucle Trading)...")
    # Crear tareas asyncio
    # Guardar referencia para poder cancelarlas al apagar
    listener_task = asyncio.create_task(listen_market_data())
    background_tasks.add(listener_task)
    trader_task = asyncio.create_task(trading_loop())
    background_tasks.add(trader_task)
    # --------------------------

    logger.info("=== Startup vía Lifespan Finalizado ===")

    yield # La aplicación se ejecuta aquí

    # Código que se ejecuta DESPUÉS de que la aplicación termine (Shutdown)
    logger.info("=== Iniciando Cierre (Lifespan) ===")
    # Cancelar tareas de fondo
    logger.info("Cancelando tareas de fondo...")
    for task in background_tasks:
        task.cancel()
        try:
            # Esperar brevemente a que la tarea maneje la cancelación
            await asyncio.wait_for(task, timeout=5.0)
        except asyncio.CancelledError:
            logger.info(f"Tarea {task.get_name()} cancelada limpiamente.")
        except asyncio.TimeoutError:
            logger.warning(f"Timeout esperando la cancelación de la tarea {task.get_name()}.")
        except Exception:
            logger.exception(f"Excepción al cancelar/esperar tarea {task.get_name()}")

    # Cerrar cliente de exchange
    await shutdown_exchange_service()
    logger.info("=== Cierre vía Lifespan Finalizado ===")


# Crear la aplicación FastAPI usando el lifespan manager
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    version="0.2.0", # Incrementar versión
    lifespan=lifespan # <<< Usar lifespan
)

# Incluir routers API (sin cambios)
app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/")
async def root():
    # Mantener ruta raíz simple
    return {"message": f"Welcome to {settings.PROJECT_NAME} - v0.2.0. Bot Status: {bot_status if 'bot_status' in globals() else 'UNKNOWN'}"} # type: ignore

# Ya NO necesitamos los decoradores @app.on_event("startup") / @app.on_event("shutdown")

# La sección if __name__ == "__main__": sigue siendo opcional para depuración directa