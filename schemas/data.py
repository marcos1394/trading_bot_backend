# schemas/data.py
from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional

class OHLCVDataPoint(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

class HistoricalDataResponse(BaseModel):
    exchange: str
    pair: str
    timeframe: str
    data: List[OHLCVDataPoint] = []
    error: Optional[str] = None