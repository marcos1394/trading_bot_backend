# schemas/portfolio.py
from pydantic import BaseModel
from typing import Dict, Optional

class PortfolioSummary(BaseModel):
    # Usamos 'balances' como clave principal para los datos devueltos
    balances: Optional[Dict[str, float]] = None # Asset -> Amount (solo los > 0)
    # Mensaje de error opcional si algo falla al obtener los datos
    error: Optional[str] = None

    # Ejemplo de cómo se vería una respuesta exitosa:
    # { "balances": { "USDT": 1000.50, "BTC": 0.05, "ETH": 1.2 } }
    # Ejemplo de respuesta si hubo error en el servicio:
    # { "balances": null, "error": "No se pudo obtener el balance del exchange..." }