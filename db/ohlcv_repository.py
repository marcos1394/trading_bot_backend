# db/ohlcv_repository.py
import logging
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy.sql import text # Para ejecutar SQL parametrizado de forma segura
from datetime import datetime, timezone # Importar timezone
from typing import Optional

logger = logging.getLogger(__name__)

class OHLCVRepository:
    """
    Clase Repositorio para interactuar con las tablas de datos OHLCV
    en la base de datos TimescaleDB.
    """
    def __init__(self, db: Session):
        """
        Inicializa el repositorio con una sesión de base de datos SQLAlchemy.

        Args:
            db: La sesión de SQLAlchemy inyectada.
        """
        self.db = db

    def get_ohlcv_data(self, exchange: str, pair: str, timeframe: str,
                       start_dt: Optional[datetime] = None,
                       end_dt: Optional[datetime] = None) -> Optional[pd.DataFrame]:
        """
        Obtiene datos OHLCV de la tabla apropiada para un exchange, par, timeframe
        y rango de fechas opcional.

        Args:
            exchange: Nombre del exchange (ej. 'binance').
            pair: Par de trading (ej. 'BTC/USDT').
            timeframe: Timeframe de las velas (ej. '5m', '1h').
            start_dt: Fecha/hora de inicio opcional (timezone-aware UTC recomendado).
            end_dt: Fecha/hora de fin opcional (timezone-aware UTC recomendado).

        Returns:
            Un DataFrame de Pandas con los datos OHLCV y timestamp como índice,
            o None si no se encuentran datos o ocurre un error.
        """
        # Construir el nombre de la tabla dinámicamente (¡asegúrate que 'timeframe' sea seguro!)
        # La validación debería ocurrir antes de llamar a esta función, pero replace simple ayuda.
        safe_tf = timeframe.replace('-', '').replace('_', '') # Limpieza básica
        table_name = f"ohlcv_{safe_tf}"
        logger.debug(f"Consultando tabla '{table_name}' para {exchange}/{pair} ({timeframe})")

        # Construir la query SQL base usando parámetros seguros (:param)
        base_query = f"""
            SELECT timestamp, open, high, low, close, volume
            FROM {table_name} -- Interpolación segura aquí porque deriva de timeframe validado
            WHERE exchange = :exchange AND pair = :pair
        """
        params = {"exchange": exchange, "pair": pair}

        # Añadir filtros de fecha si se proporcionan, asegurando que sean timezone-aware (UTC)
        # ya que la columna de la BD es TIMESTAMPTZ
        if start_dt:
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            elif start_dt.tzinfo != timezone.utc:
                 start_dt = start_dt.astimezone(timezone.utc)
            base_query += " AND timestamp >= :start_dt"
            params["start_dt"] = start_dt
            logger.debug(f"  Filtro inicio: >= {start_dt}")

        if end_dt:
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            elif end_dt.tzinfo != timezone.utc:
                 end_dt = end_dt.astimezone(timezone.utc)
            base_query += " AND timestamp <= :end_dt"
            params["end_dt"] = end_dt
            logger.debug(f"  Filtro fin: <= {end_dt}")

        base_query += " ORDER BY timestamp ASC;" # Es crucial ordenar por tiempo

        try:
            logger.debug(f"Ejecutando SQL: {base_query} con params: {params}")
            # Crear objeto de sentencia SQL seguro
            stmt = text(base_query)

            # Usar la conexión de la sesión SQLAlchemy para ejecutar con Pandas
            # index_col='timestamp' le dice a Pandas que use esa columna como índice
            df = pd.read_sql(stmt, self.db.connection(), params=params, index_col='timestamp')

            if df.empty:
                logger.warning(f"No se encontraron datos en '{table_name}' para {exchange}/{pair}/{timeframe} "
                               f"en el rango [{start_dt}, {end_dt}].")
                return None # Devolver None explícitamente

            # Asegurar que el índice es DatetimeIndex y está en UTC
            # (read_sql debería manejar TIMESTAMPTZ bien, pero verificamos)
            if not isinstance(df.index, pd.DatetimeIndex):
                 df.index = pd.to_datetime(df.index, utc=True)
            elif df.index.tz is None:
                 df.index = df.index.tz_localize('UTC')
            elif df.index.tz != timezone.utc:
                 df.index = df.index.tz_convert('UTC')

            logger.info(f"Se obtuvieron {len(df)} filas de '{table_name}' para {exchange}/{pair}/{timeframe}")
            return df

        except Exception as e:
            # Manejar error específico si la tabla no existe
            error_str = str(e).lower()
            if ("relation" in error_str and "does not exist" in error_str) or \
               ("tabla" in error_str and "no existe" in error_str): # Añadir check en español
                 logger.warning(f"La tabla '{table_name}' no existe. ¿Se descargaron datos para timeframe '{timeframe}'?")
            else:
                 # Loguear otros errores inesperados de base de datos
                 logger.exception(f"Error al ejecutar consulta SQL en '{table_name}'")
            return None # Devolver None en caso de cualquier error