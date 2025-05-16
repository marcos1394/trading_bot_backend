# models/strategy_config_model.py
from typing import Dict
from sqlalchemy import Column, String, Boolean, Integer # Integer no se usa aquí, pero es común
import sqlalchemy
from sqlalchemy.dialects.postgresql import JSONB # Específico para PostgreSQL JSON
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
from sqlalchemy.sql import func # Para default timestamps

# Usaremos una Base separada o la que ya tengas en db/base.py
# Si tienes db/base.py con "Base = declarative_base()", impórtala:
# from db.base_class import Base
# Si no, define Base aquí:
Base = declarative_base()

class StrategyConfigModel(Base):
    __tablename__ = "strategy_configs"

    id: str = Column(String, primary_key=True, index=True, unique=True, nullable=False)
    name: str = Column(String, nullable=False, index=True)
    strategy_type: str = Column(String, nullable=False, index=True)
    exchange: str = Column(String, nullable=False, default="binance")
    pair: str = Column(String, nullable=False, index=True)
    timeframe: str = Column(String, nullable=False)
    parameters: Dict = Column(JSONB, nullable=False, default=lambda: {}) # Guardar parámetros como JSON
    is_active: bool = Column(Boolean, default=False, nullable=False)

    # Opcional: Timestamps de auditoría
    created_at: datetime = Column(sqlalchemy.DateTime(timezone=True), server_default=func.now())
    updated_at: datetime = Column(sqlalchemy.DateTime(timezone=True), default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<StrategyConfigModel(id='{self.id}', name='{self.name}', type='{self.strategy_type}')>"