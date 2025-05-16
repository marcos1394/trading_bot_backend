# models/live_order_model.py
from datetime import datetime
from typing import Optional
from sqlalchemy import Column, String, Float, DateTime, Enum as SAEnum
from sqlalchemy.sql import func
import sqlalchemy # Para DateTime
import enum

# Reutilizar Base de otros modelos
try:
    from .strategy_config_model import Base
except ImportError:
    from models.strategy_config_model import Base

# Usar el mismo Enum para side que en live_position_model si es consistente
# O importar si está en un archivo común
class PositionSide(str, enum.Enum):
    LONG = "LONG"
    SHORT = "SHORT"

class OrderStatus(str, enum.Enum):
    OPEN = "open"       # Orden enviada, esperando llenado
    CLOSED = "closed"   # Orden llenada completamente
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    PENDING = "pending" # Estado inicial antes de confirmar recepción por exchange

class OrderType(str, enum.Enum):
    MARKET = "market"
    LIMIT = "limit"
    # Añadir otros tipos si se usan (STOP_LOSS_LIMIT, etc.)

class LiveOrderModel(Base):
    __tablename__ = "live_orders"

    order_id: str = Column(String, primary_key=True, index=True) # ID devuelto por el exchange
    strategy_id: str = Column(String, index=True, nullable=False)
    pair: str = Column(String, index=True, nullable=False)

    side: PositionSide = Column(SAEnum(PositionSide), nullable=False) # 'LONG' o 'SHORT' (representa la POSICIÓN deseada)
    order_type: OrderType = Column(SAEnum(OrderType), nullable=False, default=OrderType.MARKET)
    amount: float = Column(Float, nullable=False) # Cantidad solicitada
    price: Optional[float] = Column(Float, nullable=True) # Precio límite (si aplica)

    # Campos de estado de CCXT (o mapeo a nuestro Enum)
    status: OrderStatus = Column(SAEnum(OrderStatus), nullable=False, default=OrderStatus.PENDING, index=True)
    filled_amount: float = Column(Float, default=0.0)
    average_price: Optional[float] = Column(Float, nullable=True) # Precio promedio de llenado

    created_at: datetime = Column(sqlalchemy.DateTime(timezone=True), server_default=func.now())
    updated_at: datetime = Column(sqlalchemy.DateTime(timezone=True), default=func.now(), onupdate=func.now())
    # Podríamos añadir: related_position_id, client_order_id, etc.

    def __repr__(self):
        return f"<LiveOrder(id='{self.order_id}', strat='{self.strategy_id}', pair='{self.pair}', side='{self.side.value}', status='{self.status.value}')>"