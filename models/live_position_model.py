# models/live_position_model.py
from sqlalchemy import Column, String, Float, DateTime, Boolean, Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB # Si planeas usar parámetros como JSONB
import enum
from datetime import datetime
from sqlalchemy.sql import func # Para server_default=func.now()
import sqlalchemy # Para el tipo DateTime en created_at/updated_at

# --- NUEVA LÍNEA DE IMPORTACIÓN ---
from typing import Optional, Dict, Any
# ---------------------------------

# Si tienes db/base_class.py con "Base = declarative_base()", impórtala:
# from db.base_class import Base
# Si no, y la Base está en strategy_config_model.py y es la misma:
try:
    from .strategy_config_model import Base # Intenta importación relativa
except ImportError:
    from models.strategy_config_model import Base # Fallback si se corre de forma diferente

class PositionSide(str, enum.Enum):
    LONG = "LONG"
    SHORT = "SHORT"

class LivePositionModel(Base):
    __tablename__ = "live_positions"

    strategy_id: str = Column(String, primary_key=True, index=True)
    pair: str = Column(String, primary_key=True, index=True)

    side: PositionSide = Column(SAEnum(PositionSide), nullable=False)
    entry_price: float = Column(Float, nullable=False)
    size: float = Column(Float, nullable=False)
    entry_timestamp: datetime = Column(DateTime(timezone=True), nullable=False)

    initial_sl_price: Optional[float] = Column(Float, nullable=True)
    initial_tp_price: Optional[float] = Column(Float, nullable=True)
    current_sl_price: Optional[float] = Column(Float, nullable=True)

    # Opcional: Timestamps de auditoría
    created_at: datetime = Column(sqlalchemy.DateTime(timezone=True), server_default=func.now())
    updated_at: datetime = Column(sqlalchemy.DateTime(timezone=True), default=func.now(), onupdate=func.now())


    def __repr__(self):
        return f"<LivePosition(strategy='{self.strategy_id}', pair='{self.pair}', side='{self.side.value}', size='{self.size}')>"