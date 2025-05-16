# schemas/live_position.py
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Dict, Any # Asegurar Dict, Any

# Reusar Enum de models si es posible, o redefinir aquí
# from models.live_position_model import PositionSide
# Si no, redefinir para Pydantic:
from enum import Enum
class PositionSideSchema(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"

class LivePositionBase(BaseModel):
    side: PositionSideSchema
    entry_price: float = Field(..., gt=0)
    size: float = Field(..., gt=0)
    entry_timestamp: datetime
    initial_sl_price: Optional[float] = Field(None, gt=0)
    initial_tp_price: Optional[float] = Field(None, gt=0)
    current_sl_price: Optional[float] = Field(None, gt=0)
    # parameters_at_entry: Optional[Dict[str, Any]] = None # Podríamos guardar params de la señal

class LivePositionCreate(LivePositionBase):
    strategy_id: str
    pair: str # ej. BTC/USDT

class LivePositionUpdate(BaseModel): # Solo campos actualizables
    current_sl_price: Optional[float] = Field(None, gt=0)
    # Podríamos añadir otros campos si el estado de la posición evoluciona

class LivePosition(LivePositionBase): # Para leer desde la BD
    strategy_id: str
    pair: str

    class Config:
        from_attributes = True # Para crear desde el modelo SQLAlchemy