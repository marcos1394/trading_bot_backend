# core/config.py
import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv
from typing import Optional, List, Dict, Any # <<< Importaciones necesarias

# Cargar explícitamente .env si existe
load_dotenv()

# --- Definición de la Clase de Configuración ---
class Settings(BaseSettings):
    """
    Configuraciones de la aplicación cargadas desde variables de entorno
    y/o el archivo .env.
    """
    PROJECT_NAME: str = "Trading Bot Backend"
    API_V1_STR: str = "/api/v1"
    EXECUTE_LIVE_ORDERS: bool = bool(os.getenv("EXECUTE_LIVE_ORDERS", "False").lower() in ('true', '1', 't'))


    # --- Database settings ---
    # (Indentado al mismo nivel que PROJECT_NAME)
    DB_HOST: Optional[str] = os.getenv("DB_HOST", "localhost")
    DB_PORT: Optional[int] = int(os.getenv("DB_PORT", "5432")) if os.getenv("DB_PORT") else 5432
    DB_NAME: Optional[str] = os.getenv("DB_NAME", "crypto_trading_data")
    DB_USER: Optional[str] = os.getenv("DB_USER", "crypto_data_user")
    DB_PASSWORD: Optional[str] = os.getenv("DB_PASSWORD")
    SQLALCHEMY_DATABASE_URI: Optional[str] = None

    # --- Binance API settings ---
    # (Indentado al mismo nivel que PROJECT_NAME)
    BINANCE_API_KEY: Optional[str] = os.getenv("BINANCE_API_KEY")
    BINANCE_SECRET_KEY: Optional[str] = os.getenv("BINANCE_SECRET_KEY")

    # --- JWT Settings ---
    # (Indentado al mismo nivel que PROJECT_NAME)
    SECRET_KEY: str = os.getenv("SECRET_KEY", "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30))

    # --- Configuraciones de Estrategias ---
    # (Indentado al mismo nivel que PROJECT_NAME - ¡IMPORTANTE!)
    
        
       
    
    # ---------------------------------------

    # --- Configuración interna de Pydantic ---
    # (Indentado al mismo nivel que PROJECT_NAME)
    class Config:
        case_sensitive = True
        env_file = ".env"
        env_file_encoding = 'utf-8'

# --- Creación de la instancia global (Fuera de la clase Settings) ---
settings = Settings()

# --- Verificación de URI de BD (Fuera de la clase Settings) ---
# Generar URI de SQLAlchemy después de inicializar settings
if settings.DB_USER and settings.DB_PASSWORD and settings.DB_HOST and settings.DB_NAME and settings.DB_PORT:
     settings.SQLALCHEMY_DATABASE_URI = f"postgresql+psycopg2://{settings.DB_USER}:{settings.DB_PASSWORD}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"
else:
     print("-" * 60)
     print("ADVERTENCIA:")
     print("  SQLALCHEMY_DATABASE_URI no se pudo construir.")
     print("  Asegúrate de que las variables DB_USER, DB_PASSWORD, DB_HOST, DB_NAME, DB_PORT estén definidas en tu archivo .env")
     print("-" * 60)