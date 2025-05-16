# api/api_v1/api.py
from fastapi import APIRouter
from api.api_v1.endpoints import status
from api.api_v1.endpoints import portfolio
from api.api_v1.endpoints import strategies
from api.api_v1.endpoints import backtest
from api.api_v1.endpoints import data
from api.api_v1.endpoints import optimize
from api.api_v1.endpoints import validate
from api.api_v1.endpoints import tasks # <<< IMPORTAR NUEVO ROUTER

api_router = APIRouter()

# Incluir los routers
api_router.include_router(status.router, prefix="/status", tags=["Status"])
api_router.include_router(portfolio.router, prefix="/portfolio", tags=["Portfolio"])
api_router.include_router(strategies.router, prefix="/strategies", tags=["Strategies"])
api_router.include_router(backtest.router, prefix="/backtest", tags=["Backtesting"])
api_router.include_router(data.router, prefix="/data", tags=["Market Data"])
api_router.include_router(optimize.router, prefix="/optimize", tags=["Optimization"])
api_router.include_router(validate.router, prefix="/validate", tags=["Validation"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["Async Tasks"]) # <<< AÑADIR ROUTER DE TAREAS