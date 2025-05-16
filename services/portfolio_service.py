# services/portfolio_service.py
import logging
from typing import Dict, Any, Optional
# Importa la CLASE ExchangeService, no la instancia
from trading.exchange_service import ExchangeService

logger = logging.getLogger(__name__)

class PortfolioService:
    # Inyecta la instancia del servicio de exchange vía constructor
    def __init__(self, exchange_service: ExchangeService):
        self.exchange_service = exchange_service

    async def get_portfolio_summary(self) -> Optional[Dict[str, float]]:
        """
        Calcula un resumen simple del portfolio (total por asset).
        Devuelve solo assets con balance > 0.
        """
        logger.info("Obteniendo resumen del portfolio...")
        balance_total = await self.exchange_service.get_balance()

        if balance_total is None:
            logger.warning("No se pudo obtener balance para el resumen del portfolio.")
            return None # El endpoint manejará esto como un error

        # Filtrar assets con balance numéricamente mayor a cero
        # (maneja posibles valores muy pequeños pero no cero)
        summary = {
            asset: float(amount)
            for asset, amount in balance_total.items()
            if isinstance(amount, (int, float)) and amount > 1e-12 # Umbral pequeño para evitar polvo
        }

        if not summary:
            logger.info("Resumen de portfolio vacío (todos los balances son cero o muy pequeños).")
        else:
             # Loguear con formato para mejor lectura si hay muchos assets
             log_summary = {k: f"{v:.8f}" for k, v in summary.items()} # Formatear a 8 decimales
             logger.info(f"Resumen de portfolio (balances > 0): {log_summary}")


        # --- Ampliaciones Futuras ---
        # Aquí iría la lógica para:
        # 1. Obtener precios actuales (ej. usando client.fetch_tickers())
        # 2. Calcular valor total en USDT.
        # 3. Obtener posiciones abiertas (client.fetch_positions() para futuros).
        # 4. Calcular P&L no realizado.
        # -----------------------------

        return summary