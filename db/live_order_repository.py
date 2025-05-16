# db/live_order_repository.py
import logging
from typing import List, Optional
from sqlalchemy.orm import Session

from models.live_order_model import LiveOrderModel, OrderStatus
from schemas.live_order import LiveOrderCreate, LiveOrderUpdate

logger = logging.getLogger(__name__)

class LiveOrderRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, order_id: str) -> Optional[LiveOrderModel]:
        return self.db.query(LiveOrderModel).filter(LiveOrderModel.order_id == order_id).first()

    def get_pending_orders_by_strategy(self, strategy_id: str, pair: str) -> List[LiveOrderModel]:
        """Obtiene órdenes abiertas o pendientes para una estrategia/par."""
        return self.db.query(LiveOrderModel).filter(
            LiveOrderModel.strategy_id == strategy_id,
            LiveOrderModel.pair == pair,
            LiveOrderModel.status.in_([OrderStatus.OPEN, OrderStatus.PENDING])
        ).all()

    def get_all_pending_orders(self) -> List[LiveOrderModel]:
        """Obtiene todas las órdenes abiertas o pendientes del sistema."""
        return self.db.query(LiveOrderModel).filter(
            LiveOrderModel.status.in_([OrderStatus.OPEN, OrderStatus.PENDING])
        ).all()

    def create(self, order_in: LiveOrderCreate) -> LiveOrderModel:
        # OJO: Aquí asumimos que la orden se colocó bien en el exchange
        # y solo guardamos el registro. El estado inicial es PENDING/OPEN.
        db_order = LiveOrderModel(**order_in.model_dump())
        try:
            self.db.add(db_order)
            self.db.commit()
            self.db.refresh(db_order)
            logger.info(f"Orden CREADA en BD: ID={db_order.order_id}, Strat={db_order.strategy_id}, Pair={db_order.pair}, Status={db_order.status}")
            return db_order
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error creando orden en BD {order_in.order_id}: {e}", exc_info=True)
            raise # Relanzar para que el llamador sepa que falló

    def update_status(self, order_id: str, status: OrderStatus, filled: float = 0.0, avg_price: Optional[float] = None) -> Optional[LiveOrderModel]:
        """Actualiza el estado, llenado y precio promedio de una orden."""
        db_order = self.get_by_id(order_id)
        if not db_order:
            logger.warning(f"Intento de actualizar estado de orden inexistente en BD: {order_id}")
            return None

        db_order.status = status
        db_order.filled_amount = filled
        if avg_price is not None:
            db_order.average_price = avg_price
        # updated_at se actualiza automáticamente por el trigger/default de la BD

        try:
            self.db.add(db_order)
            self.db.commit()
            self.db.refresh(db_order)
            logger.info(f"Orden ACTUALIZADA en BD: ID={db_order.order_id}, Status={db_order.status}, Filled={db_order.filled_amount}")
            return db_order
        except Exception as e:
             self.db.rollback()
             logger.error(f"Error actualizando orden en BD {order_id}: {e}", exc_info=True)
             return None


    def delete(self, order_id: str) -> bool:
        """Elimina una orden de la tabla (generalmente cuando ya no se necesita seguir)."""
        db_order = self.get_by_id(order_id)
        if db_order:
            try:
                self.db.delete(db_order)
                self.db.commit()
                logger.info(f"Orden ELIMINADA de BD: {order_id}")
                return True
            except Exception as e:
                 self.db.rollback()
                 logger.error(f"Error eliminando orden de BD {order_id}: {e}", exc_info=True)
                 return False
        return False # No existía