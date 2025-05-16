# services/strategy_service.py
import logging
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session # Para inyectar la sesión de BD
from fastapi import Depends # Para inyectar dependencias

# Importar el repositorio y el modelo de BD
from db.strategy_config_repository import StrategyConfigRepository # type: ignore
from models.strategy_config_model import StrategyConfigModel # Para el seeding
# Importar schemas Pydantic
from schemas.strategy import StrategyConfig, StrategyConfigCreate, StrategyConfigUpdate
# Importar la sesión de BD
from db.session import get_db
# Importar settings para el seeding inicial desde config.py
from core.config import settings

logger = logging.getLogger(__name__)

class StrategyService:
    def __init__(self, db: Session): # <<< CAMBIO: Inyectar Session
        self.db = db
        self.repo = StrategyConfigRepository(db=self.db)
        # El __init__ ya no carga de settings.STRATEGIES, se hará bajo demanda o se puede cachear
        # self.strategy_configs: Dict[str, StrategyConfig] = self._load_configs_from_db()
        self._seed_initial_strategies_if_needed() # <<< NUEVO: Seeding inicial
    
    def _seed_initial_strategies_if_needed(self):
        """
        Si la tabla de configs está vacía, intenta poblarla con las estrategias
        definidas en core/config.py (si existen allí).
        """
        if not self.repo.get_all(limit=1): # Si no hay ninguna config en la BD
            logger.info("Base de datos de configuraciones de estrategia vacía. Intentando seeding inicial...")

            # --- CAMBIO AQUÍ: Usar getattr para acceder de forma segura a settings.STRATEGIES ---
            initial_strategies_from_config = getattr(settings, 'STRATEGIES', []) # Devuelve [] si STRATEGIES no existe
            # ------------------------------------------------------------------------------------

            if not initial_strategies_from_config:
                logger.info("No se encontraron STRATEGIES hardcodeadas en core/config.py para el seeding inicial. La tabla permanecerá vacía.")
                return # No hay nada que sembrar

            logger.info(f"Encontradas {len(initial_strategies_from_config)} estrategias en config.py para seeding.")
            seeded_count = 0
            for config_dict in initial_strategies_from_config:
                try:
                    # Verificar si ya existe por ID antes de intentar crear (más robusto)
                    existing_config = self.repo.get_by_id(config_dict.get("id"))
                    if existing_config:
                         logger.info(f"Configuración para ID '{config_dict.get('id')}' ya existe en BD. Omitiendo seeding.")
                         continue

                    create_schema = StrategyConfigCreate(**config_dict)
                    self.repo.create(create_schema)
                    seeded_count +=1
                except Exception as e:
                    logger.error(f"Error haciendo seeding para config: {config_dict.get('id')}. Error: {e}", exc_info=True)
            logger.info(f"Seeding desde config.py completado. {seeded_count} nuevas estrategias añadidas a la base de datos.")
        # else: # Descomentar si quieres un log cuando la BD ya tiene datos
        #     logger.debug("La base de datos de configuraciones de estrategia ya tiene datos. No se requiere seeding.")


    def _load_configs_from_db(self) -> Dict[str, StrategyConfig]:
        """Carga todas las configs de la BD y las convierte a Pydantic models."""
        db_configs = self.repo.get_all(limit=1000) # Obtener un límite alto
        # Convertir modelos SQLAlchemy a schemas Pydantic
        return {config.id: StrategyConfig.model_validate(config) for config in db_configs}

    def list_strategies(self) -> List[StrategyConfig]:
        """Devuelve una lista de todas las configs de estrategia desde la BD."""
        db_configs = self.repo.get_all(limit=1000)
        return [StrategyConfig.model_validate(config) for config in db_configs]

    def get_strategy_config(self, strategy_id: str) -> Optional[StrategyConfig]:
        """Devuelve la config para un ID específico desde la BD."""
        db_config = self.repo.get_by_id(strategy_id)
        if db_config:
            return StrategyConfig.model_validate(db_config)
        return None

    def get_active_strategy_configs(self) -> List[StrategyConfig]:
        """Devuelve una lista de todas las configs de estrategia ACTIVAS desde la BD."""
        db_configs = self.repo.get_all_active()
        return [StrategyConfig.model_validate(config) for config in db_configs]

    # --- NUEVOS MÉTODOS CRUD ---
    def create_strategy_config(self, config_in: StrategyConfigCreate) -> Optional[StrategyConfig]:
        """Crea una nueva configuración de estrategia en la BD."""
        # Validar que el ID no exista ya (el repo lo hace, pero podemos chequear aquí)
        if self.repo.get_by_id(config_in.id):
             logger.warning(f"Intento de crear estrategia con ID existente: {config_in.id}")
             return None # O lanzar HTTPException desde el endpoint

        db_config = self.repo.create(config_in)
        if db_config:
            return StrategyConfig.model_validate(db_config)
        return None

    def update_strategy_config(self, strategy_id: str, config_in: StrategyConfigUpdate) -> Optional[StrategyConfig]:
        """Actualiza una configuración de estrategia existente en la BD."""
        db_config = self.repo.update(strategy_id, config_in)
        if db_config:
            return StrategyConfig.model_validate(db_config)
        return None

    def delete_strategy_config(self, strategy_id: str) -> bool:
        """Elimina una configuración de estrategia de la BD."""
        return self.repo.delete(strategy_id)

# --- Dependencia para FastAPI (Modificada para inyectar db) ---
def get_strategy_service(db: Session = Depends(get_db)) -> StrategyService:
    # Crea y devuelve la instancia del servicio, pasándole la sesión de BD
    return StrategyService(db=db)
# Ya no hay instancia singleton a nivel de módulo, se crea por petición con su sesión de BD