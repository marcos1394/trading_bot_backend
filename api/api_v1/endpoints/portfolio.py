# api/api_v1/endpoints/portfolio.py
from fastapi import APIRouter, Depends, HTTPException, status as http_status
import logging

from schemas.portfolio import PortfolioSummary
from services.portfolio_service import PortfolioService
# Importar la dependencia que obtiene la INSTANCIA del ExchangeService
from trading.exchange_service import ExchangeService, get_exchange_service

router = APIRouter()
logger = logging.getLogger(__name__)

# Inyección de dependencias:
# Esta función ayuda a FastAPI a crear PortfolioService
# pasándole la instancia única de ExchangeService.
def get_portfolio_service(
    exchange_service: ExchangeService = Depends(get_exchange_service)
) -> PortfolioService:
     return PortfolioService(exchange_service=exchange_service)

@router.get(
    "/summary",
    response_model=PortfolioSummary,
    summary="Obtener Resumen de Balances",
    description="Obtiene un resumen de los balances totales por cada activo en la cuenta del exchange. Requiere claves API válidas.",
)
async def read_portfolio_summary(
    # FastAPI ejecutará get_portfolio_service para obtener la instancia
    portfolio_service: PortfolioService = Depends(get_portfolio_service)
):
    logger.info("Endpoint /portfolio/summary llamado.")
    try:
        summary_data = await portfolio_service.get_portfolio_summary()

        # Si el servicio devuelve None, indica un fallo al obtener el balance
        if summary_data is None:
             # Usamos 503 Service Unavailable, ya que el problema puede ser externo (exchange) o de config
             raise HTTPException(
                  status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                  detail="No se pudo obtener el balance del exchange. Verifique la configuración API o el estado del servicio del exchange."
             )

        # Devolvemos los datos dentro del esquema Pydantic
        return PortfolioSummary(balances=summary_data)

    except HTTPException as http_exc:
         # Re-lanzar excepciones HTTP que ya generamos (como la 503)
         raise http_exc
    except Exception as e:
         # Capturar cualquier otro error inesperado
         logger.exception("Error inesperado en endpoint /portfolio/summary") # Log con traceback
         raise HTTPException(
              status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
              detail=f"Error interno del servidor al obtener el portfolio." # No exponer detalles del error al cliente
         )