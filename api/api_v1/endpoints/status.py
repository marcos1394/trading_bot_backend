from fastapi import APIRouter, Depends
from datetime import datetime, timezone
from sqlalchemy.orm import Session
import logging

from schemas.status import StatusResponse
from db.session import get_db, check_db_connection # Importa get_db aunque no se use directamente aquí

router = APIRouter()

@router.get("", response_model=StatusResponse)
def get_status(): # No necesita db: Session = Depends(get_db) para solo chequear
    """
    Endpoint para verificar el estado básico del backend y la conexión a BD.
    """
    # Intenta verificar la conexión a BD (no bloquea si falla)
    db_ok = check_db_connection()

    logging.info(f"Status endpoint called. DB Connection OK: {db_ok}")

    return StatusResponse(
        status="ok",
        timestamp=datetime.now(timezone.utc),
        db_connection_ok=db_ok
    )