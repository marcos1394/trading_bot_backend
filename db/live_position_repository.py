# db/live_position_repository.py
import logging
from typing import Optional, List
from sqlalchemy.orm import Session

from models.live_position_model import LivePositionModel, PositionSide
from schemas.live_position import LivePositionCreate, LivePositionUpdate # Usaremos para crear/actualizar

logger = logging.getLogger(__name__)

class LivePositionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_strategy_and_pair(self, strategy_id: str, pair: str) -> Optional[LivePositionModel]:
        return self.db.query(LivePositionModel).filter_by(strategy_id=strategy_id, pair=pair).first()

    def get_all_open(self) -> List[LivePositionModel]:
        # Por ahora, todas las que están en la tabla se consideran abiertas
        return self.db.query(LivePositionModel).all()

    def create(self, position_in: LivePositionCreate) -> LivePositionModel:
        db_position = LivePositionModel(
            strategy_id=position_in.strategy_id,
            pair=position_in.pair,
            side=position_in.side,
            entry_price=position_in.entry_price,
            size=position_in.size,
            entry_timestamp=position_in.entry_timestamp,
            initial_sl_price=position_in.initial_sl_price,
            initial_tp_price=position_in.initial_tp_price,
            current_sl_price=position_in.initial_sl_price # Inicialmente SL actual = SL inicial
        )
        self.db.add(db_position)
        self.db.commit()
        self.db.refresh(db_position)
        logger.info(f"Posición CREADA en BD: {strategy_id}/{pair} {position_in.side}") # type: ignore
        return db_position

    def update(self, strategy_id: str, pair: str, position_update: LivePositionUpdate) -> Optional[LivePositionModel]:
        db_position = self.get_by_strategy_and_pair(strategy_id, pair)
        if not db_position:
            return None
        update_data = position_update.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_position, key, value)
        self.db.commit()
        self.db.refresh(db_position)
        logger.info(f"Posición ACTUALIZADA en BD: {strategy_id}/{pair} - Datos: {update_data}")
        return db_position

    def delete(self, strategy_id: str, pair: str) -> bool:
        db_position = self.get_by_strategy_and_pair(strategy_id, pair)
        if db_position:
            self.db.delete(db_position)
            self.db.commit()
            logger.info(f"Posición ELIMINADA de BD: {strategy_id}/{pair}")
            return True
        return False