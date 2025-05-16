# db/strategy_config_repository.py
import logging
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError # Para capturar error de ID duplicado

from models.strategy_config_model import StrategyConfigModel
from schemas.strategy import StrategyConfigCreate, StrategyConfigUpdate

logger = logging.getLogger(__name__)

class StrategyConfigRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, strategy_id: str) -> Optional[StrategyConfigModel]:
        return self.db.query(StrategyConfigModel).filter(StrategyConfigModel.id == strategy_id).first()

    def get_all(self, skip: int = 0, limit: int = 100) -> List[StrategyConfigModel]:
        return self.db.query(StrategyConfigModel).offset(skip).limit(limit).all()
    
    def get_all_active(self) -> List[StrategyConfigModel]:
        return self.db.query(StrategyConfigModel).filter(StrategyConfigModel.is_active == True).all()

    def create(self, config_in: StrategyConfigCreate) -> Optional[StrategyConfigModel]:
        # Crear instancia del modelo SQLAlchemy desde el schema Pydantic
        db_config = StrategyConfigModel(**config_in.model_dump())
        try:
            self.db.add(db_config)
            self.db.commit()
            self.db.refresh(db_config)
            logger.info(f"Configuración de estrategia creada: {db_config.id}")
            return db_config
        except IntegrityError: # Captura error de ID duplicado (PRIMARY KEY o UNIQUE)
            self.db.rollback()
            logger.error(f"Error de integridad: ID de estrategia '{config_in.id}' ya existe.")
            return None # O lanzar una excepción específica
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error creando configuración de estrategia: {e}", exc_info=True)
            return None


    def update(self, strategy_id: str, config_in: StrategyConfigUpdate) -> Optional[StrategyConfigModel]:
        db_config = self.get_by_id(strategy_id)
        if not db_config:
            return None
        
        update_data = config_in.model_dump(exclude_unset=True) # Solo campos que vienen en el request
        for field, value in update_data.items():
            setattr(db_config, field, value)
        
        try:
            self.db.add(db_config)
            self.db.commit()
            self.db.refresh(db_config)
            logger.info(f"Configuración de estrategia actualizada: {db_config.id}")
            return db_config
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error actualizando configuración de estrategia {strategy_id}: {e}", exc_info=True)
            return None

    def delete(self, strategy_id: str) -> bool:
        db_config = self.get_by_id(strategy_id)
        if not db_config:
            return False
        try:
            self.db.delete(db_config)
            self.db.commit()
            logger.info(f"Configuración de estrategia eliminada: {strategy_id}")
            return True
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error eliminando configuración de estrategia {strategy_id}: {e}", exc_info=True)
            return False