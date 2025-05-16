# schemas/backtest_results.py
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any # Asegurar Any
from datetime import datetime
from .trade import Trade
# Importar config para incluirla en los resultados
from .strategy import StrategyConfig

class BacktestMetrics(BaseModel):
    """Métricas calculadas al final del backtest (a nivel de portfolio)."""
    initial_portfolio_value: float
    final_portfolio_value: float
    total_return_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None # Drawdown del portfolio
    win_rate_pct: Optional[float] = None # Calculado sobre todos los trades
    profit_factor: Optional[float] = None # Calculado sobre todos los trades
    total_trades: int = 0
    total_commission_paid: Optional[float] = None
    sharpe_ratio: Optional[float] = None # <<< AÑADIR

    # Podríamos añadir más métricas aquí: Sharpe, Sortino, etc.
    # Y opcionalmente, métricas por estrategia

class PortfolioBacktestResult(BaseModel): # <<< Cambiado nombre para claridad
    """Resultados completos de una ejecución de backtest de portfolio."""
    # IDs de las estrategias incluidas
    strategy_ids: List[str]
    # Configuraciones completas usadas
    strategy_configs: List[StrategyConfig]
    # Rango de fechas del backtest
    start_date: datetime
    end_date: datetime
    # Métricas globales del portfolio
    metrics: BacktestMetrics
    # Lista de todos los trades ejecutados por cualquier estrategia
    trades: List[Trade] = Field(default_factory=list)
    # Curva de equity del portfolio (opcional, puede ser grande)
    # equity_curve: Optional[List[float]] = None
    # Indica si el backtest fue detenido por la regla de drawdown
    stopped_by_drawdown_rule: bool = False
    # Mensaje de error general si el backtest falló
    error: Optional[str] = None