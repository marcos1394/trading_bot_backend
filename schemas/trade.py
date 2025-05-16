# schemas/trade.py
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class Trade(BaseModel):
    """Representa una operación simulada en el backtest."""
    strategy_id: str # <<< AÑADIDO: ID de la estrategia que generó el trade
    pair: str
    entry_timestamp: datetime
    exit_timestamp: Optional[datetime] = None
    entry_price: float
    exit_price: Optional[float] = None
    position_side: str = Field(..., pattern="^(LONG|SHORT)$")
    size: float
    pnl_abs: Optional[float] = None
    pnl_pct: Optional[float] = None
    entry_signal_type: int
    exit_reason: Optional[str] = None
    commission: Optional[float] = 0.0

    class Config:
         from_attributes = True # Útil si creas Trades desde otros objetos