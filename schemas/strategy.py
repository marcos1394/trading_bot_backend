# schemas/strategy.py
from pydantic import BaseModel, Field, validator
from typing import Dict, Any, List, Optional

class StrategyConfigBase(BaseModel):
    """Schema base con campos comunes para creación y actualización."""
    name: Optional[str] = Field(None, description="Nombre descriptivo de la estrategia", min_length=3, max_length=100)
    strategy_type: Optional[str] = Field(None, description="Tipo/Clase de la estrategia (ej. 'ema_crossover')", min_length=3, max_length=50)
    exchange: Optional[str] = Field(default="binance", description="Exchange donde opera", min_length=3, max_length=50)
    pair: Optional[str] = Field(None, description="Par de trading (ej. 'BTC/USDT')", pattern=r"^[A-Z0-9-]{2,10}/[A-Z0-9]{2,10}$") # Pattern simple
    timeframe: Optional[str] = Field(None, description="Timeframe de las velas (ej. '5m', '1h')", min_length=2, max_length=10)
    parameters: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Parámetros específicos (ej. {'ema_short': 12})")
    is_active: Optional[bool] = Field(default=False, description="Indica si la estrategia debe ejecutarse")

    @validator('pair', pre=True, always=True)
    def pair_to_uppercase(cls, v):
        if v is not None:
            return v.upper()
        return v

class StrategyConfigCreate(StrategyConfigBase):
    """Schema para crear una nueva configuración de estrategia."""
    # ID es obligatorio y debe ser único, el usuario lo provee o lo generamos
    id: str = Field(..., description="Identificador único (alfanumérico, guiones bajos)", min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_]{3,50}$")
    name: str # Hacer obligatorio en Create
    strategy_type: str
    pair: str
    timeframe: str
    # parameters y is_active pueden tomar sus defaults de StrategyConfigBase

class StrategyConfigUpdate(StrategyConfigBase):
    """Schema para actualizar una configuración de estrategia. Todos los campos son opcionales."""
    # No se puede actualizar el ID
    pass # Hereda todos los campos como opcionales de StrategyConfigBase

class StrategyConfig(StrategyConfigBase): # Este es el schema principal para respuestas
    """Schema para leer/devolver una configuración de estrategia (incluyendo ID)."""
    id: str # ID es obligatorio al leer
    name: str
    strategy_type: str
    pair: str
    timeframe: str
    is_active: bool # Hacerlo no opcional para la respuesta

    class Config:
        from_attributes = True # Para crear desde el modelo SQLAlchemy
        json_schema_extra = { # Ejemplo OpenAPI
            "example": {
                "id": "BTCUSDT_EMA_CROSS_1H",
                "name": "EMA Crossover 1h BTC/USDT",
                "strategy_type": "ema_crossover",
                "exchange": "binance",
                "pair": "BTC/USDT",
                "timeframe": "1h",
                "parameters": {"ema_short": 12, "ema_long": 26, "risk_per_trade": 0.01},
                "is_active": True,
            }
        }

class StrategyListResponse(BaseModel):
    strategies: List[StrategyConfig]