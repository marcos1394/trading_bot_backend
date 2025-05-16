# api/api_v1/endpoints/data.py
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
import logging
from typing import Optional

from db.session import get_db
# --- CAMBIO: Importar la CLASE del repositorio ---
from db.ohlcv_repository import OHLCVRepository
# -------------------------------------------------
from schemas.data import HistoricalDataResponse, OHLCVDataPoint # Importar schemas

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get(
    "/historical/{exchange}/{pair}/{timeframe}",
    response_model=HistoricalDataResponse,
    summary="Obtener Datos Históricos OHLCV",
    description="Recupera datos OHLCV desde la base de datos para un par y timeframe."
                " Por defecto devuelve las últimas 100 velas si no se especifican fechas."
)
async def read_historical_data(
    exchange: str,
    pair: str,
    timeframe: str,
    start_date: Optional[datetime] = Query(None, description="Fecha inicio (ISO 8601 UTC, ej: 2023-01-01T00:00:00Z)"),
    end_date: Optional[datetime] = Query(None, description="Fecha fin (ISO 8601 UTC, ej: 2023-01-02T00:00:00Z)"),
    limit: Optional[int] = Query(100, description="Número máximo de velas a devolver si no se usan fechas.", ge=1, le=2000), # Aumentado límite máximo posible
    db: Session = Depends(get_db) # Inyectar sesión de BD
):
    # Validar y normalizar el par (ej: btc/usdt -> BTC/USDT)
    normalized_pair = pair.upper().replace('-', '/')
    logger.info(f"Endpoint /historical llamado para {exchange}/{normalized_pair}/{timeframe}")

    # Lógica para fechas por defecto si no se proporcionan
    effective_limit = None
    if start_date is None and end_date is None:
        effective_limit = limit # Usar limit solo si no hay fechas
    elif end_date is None:
         end_date = datetime.now(timezone.utc) # Si hay start pero no end, usar hasta ahora

    # Asegurar que las fechas tengan timezone UTC si se proporcionan
    start_dt_utc = None
    end_dt_utc = None
    if start_date:
        if start_date.tzinfo is None: start_dt_utc = start_date.replace(tzinfo=timezone.utc)
        elif start_date.tzinfo != timezone.utc: start_dt_utc = start_date.astimezone(timezone.utc)
        else: start_dt_utc = start_date
    if end_date:
        if end_date.tzinfo is None: end_dt_utc = end_date.replace(tzinfo=timezone.utc)
        elif end_date.tzinfo != timezone.utc: end_dt_utc = end_date.astimezone(timezone.utc)
        else: end_dt_utc = end_date


    try:
        # --- CAMBIO: Crear instancia del repositorio y llamar al MÉTODO ---
        repo = OHLCVRepository(db=db)
        df_data = repo.get_ohlcv_data(
            exchange=exchange,
            pair=normalized_pair,
            timeframe=timeframe,
            start_dt=start_dt_utc, # Usar fechas con UTC
            end_dt=end_dt_utc,   # Usar fechas con UTC
            limit=effective_limit # Pasa el límite calculado
        )
        # -----------------------------------------------------------------

        response = HistoricalDataResponse(
            exchange=exchange,
            pair=normalized_pair,
            timeframe=timeframe
        )

        if df_data is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No se encontraron datos o ocurrió un error al leer para {exchange}/{normalized_pair} {timeframe}"
            )

        # Convertir DataFrame a lista de Pydantic models
        # reset_index() convierte el índice 'timestamp' en una columna normal
        df_data_reset = df_data.reset_index()
        # Usar .itertuples() suele ser más rápido que .iterrows()
        response.data = [
            OHLCVDataPoint.model_validate(row._asdict()) # Usar model_validate para Pydantic V2
            for row in df_data_reset.itertuples(index=False)
        ]
        # Alternativa si .itertuples no funciona como esperado con tipos:
        # response.data = [OHLCVDataPoint(**row) for row in df_data_reset.to_dict(orient='records')]


        logger.info(f"Devolviendo {len(response.data)} velas para {exchange}/{normalized_pair}/{timeframe}")
        return response

    except HTTPException as http_exc:
         raise http_exc # Re-lanzar excepciones HTTP generadas
    except Exception as e:
        logger.exception(f"Error inesperado en endpoint /historical")
        raise HTTPException(
             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
             detail="Error interno del servidor al obtener datos históricos."
        )