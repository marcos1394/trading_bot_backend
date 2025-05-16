# schemas/live_order.py
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Any, Dict
import enum

# Reutilizar Enums o redefinir
class PositionSideSchema(str, enum.Enum):
    LONG = "LONG"
    SHORT = "SHORT"

class OrderStatusSchema(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    PENDING = "pending" # Estado inicial nuestro

class OrderTypeSchema(str, enum.Enum):
    MARKET = "market"
    LIMIT = "limit"

class LiveOrderBase(BaseModel):
    strategy_id: str
    pair: str
    side: PositionSideSchema
    order_type: OrderTypeSchema = OrderTypeSchema.MARKET
    amount: float = Field(..., gt=0)
    price: Optional[float] = Field(None, gt=0) # Solo para órdenes límite
    status: OrderStatusSchema = OrderStatusSchema.PENDING
    filled_amount: float = 0.0
    average_price: Optional[float] = None

class LiveOrderCreate(LiveOrderBase):
    order_id: str # ID del exchange es obligatorio al crear en nuestra BD

class LiveOrderUpdate(BaseModel): # Campos que actualizamos desde fetch_order_status
    status: Optional[OrderStatusSchema] = None
    filled_amount: Optional[float] = None
    average_price: Optional[float] = None
    # updated_at se maneja por DB

class LiveOrder(LiveOrderBase): # Schema para leer/devolver desde la API/DB
    order_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True