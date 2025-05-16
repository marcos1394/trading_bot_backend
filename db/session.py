from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator
import logging

from core.config import settings

if not settings.SQLALCHEMY_DATABASE_URI:
    logging.critical("SQLALCHEMY_DATABASE_URI no está configurada. Revisa tu archivo .env y la configuración.")
    # Podrías salir aquí o manejarlo de otra forma, pero sin URI no se puede continuar.
    # exit(1) # Descomentar si quieres que falle aquí
    # Alternativa: Usar una URI dummy o SQLite para pruebas locales si no hay BD
    SQLALCHEMY_DATABASE_URI_FALLBACK = "sqlite:///./temp_db.db" # Ejemplo fallback
    logging.warning(f"Usando URI de fallback: {SQLALCHEMY_DATABASE_URI_FALLBACK}")
    engine = create_engine(SQLALCHEMY_DATABASE_URI_FALLBACK, connect_args={"check_same_thread": False}) # SQLite necesita check_same_thread
else:
     engine = create_engine(settings.SQLALCHEMY_DATABASE_URI, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Función de dependencia para inyectar la sesión de BD en las rutas API
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def check_db_connection():
    """Intenta conectar a la BD para verificar la configuración."""
    try:
        conn = engine.connect()
        conn.close()
        logging.info("Verificación de conexión a BD exitosa.")
        return True
    except Exception as e:
        logging.error(f"Fallo en la verificación de conexión a BD: {e}")
        return False