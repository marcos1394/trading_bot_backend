from pydantic import BaseModel
from datetime import datetime

class StatusResponse(BaseModel):
    status: str
    timestamp: datetime
    db_connection_ok: bool