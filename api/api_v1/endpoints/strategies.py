# api/api_v1/endpoints/strategies.py
from fastapi import APIRouter, Depends, HTTPException, status as http_status
import logging
from typing import List

# Importar schemas y servicio
from schemas.strategy import StrategyConfig, StrategyListResponse, StrategyConfigCreate, StrategyConfigUpdate
from services.strategy_service import StrategyService, get_strategy_service # Dependencia sin cambios

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get(
    "",
    response_model=StrategyListResponse,
    summary="Listar Todas las Configuraciones de Estrategias",
    description="Devuelve la lista de todas las estrategias configuradas en la base de datos."
)
async def list_strategies(
    strategy_service: StrategyService = Depends(get_strategy_service)
):
    logger.info("Endpoint GET /strategies llamado.")
    try:
        configs = strategy_service.list_strategies()
        return StrategyListResponse(strategies=configs)
    except Exception as e:
        logger.exception("Error inesperado al listar estrategias")
        raise HTTPException(status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error interno al listar estrategias.")

@router.get(
    "/{strategy_id}",
    response_model=StrategyConfig,
    summary="Obtener Configuración de Estrategia Específica",
    responses={404: {"description": "Estrategia no encontrada"}}
)
async def get_strategy(
    strategy_id: str,
    strategy_service: StrategyService = Depends(get_strategy_service)
):
    logger.info(f"Endpoint GET /strategies/{strategy_id} llamado.")
    try:
        config = strategy_service.get_strategy_config(strategy_id)
        if config is None:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=f"Estrategia '{strategy_id}' no encontrada.")
        return config
    except HTTPException as http_exc:
         raise http_exc
    except Exception as e:
        logger.exception(f"Error inesperado al obtener estrategia {strategy_id}")
        raise HTTPException(status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error interno al obtener {strategy_id}.")


# --- NUEVOS ENDPOINTS CRUD ---
@router.post(
    "",
    response_model=StrategyConfig,
    status_code=http_status.HTTP_201_CREATED,
    summary="Crear Nueva Configuración de Estrategia",
    responses={400: {"description": "ID de estrategia ya existe o datos inválidos"}}
)
async def create_strategy(
    config_in: StrategyConfigCreate,
    strategy_service: StrategyService = Depends(get_strategy_service)
):
    logger.info(f"Endpoint POST /strategies llamado para crear: {config_in.id}")
    try:
        # Validar que el strategy_type sea uno conocido por el STRATEGY_MAP (opcional aquí, o en servicio)
        # from services.backtesting_service import STRATEGY_MAP # Evitar import circular
        # if config_in.strategy_type not in STRATEGY_MAP:
        #     raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=f"Tipo de estrategia '{config_in.strategy_type}' no soportado.")

        created_config = strategy_service.create_strategy_config(config_in)
        if not created_config:
            # Esto podría ser por ID duplicado o error de BD
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=f"No se pudo crear la estrategia '{config_in.id}'. ¿ID ya existe o datos inválidos?")
        return created_config
    except Exception as e:
        logger.exception(f"Error inesperado al crear estrategia {config_in.id}")
        raise HTTPException(status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error interno al crear estrategia.")


@router.put(
    "/{strategy_id}",
    response_model=StrategyConfig,
    summary="Actualizar Configuración de Estrategia",
    responses={404: {"description": "Estrategia no encontrada"}}
)
async def update_strategy(
    strategy_id: str,
    config_in: StrategyConfigUpdate,
    strategy_service: StrategyService = Depends(get_strategy_service)
):
    logger.info(f"Endpoint PUT /strategies/{strategy_id} llamado.")
    try:
        updated_config = strategy_service.update_strategy_config(strategy_id, config_in)
        if not updated_config:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=f"Estrategia '{strategy_id}' no encontrada para actualizar.")
        return updated_config
    except HTTPException as http_exc:
         raise http_exc
    except Exception as e:
        logger.exception(f"Error inesperado al actualizar estrategia {strategy_id}")
        raise HTTPException(status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error interno al actualizar estrategia.")


@router.delete(
    "/{strategy_id}",
    status_code=http_status.HTTP_204_NO_CONTENT, # No devuelve contenido en éxito
    summary="Eliminar Configuración de Estrategia",
    responses={404: {"description": "Estrategia no encontrada"}}
)
async def delete_strategy(
    strategy_id: str,
    strategy_service: StrategyService = Depends(get_strategy_service)
):
    logger.info(f"Endpoint DELETE /strategies/{strategy_id} llamado.")
    try:
        deleted = strategy_service.delete_strategy_config(strategy_id)
        if not deleted:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=f"Estrategia '{strategy_id}' no encontrada para eliminar.")
        return # Respuesta 204 no tiene cuerpo
    except HTTPException as http_exc:
         raise http_exc
    except Exception as e:
        logger.exception(f"Error inesperado al eliminar estrategia {strategy_id}")
        raise HTTPException(status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error interno al eliminar estrategia.")