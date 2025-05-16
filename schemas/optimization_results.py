# schemas/optimization_results.py
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from datetime import datetime
# Importar métricas para usarlas en los resultados
from .backtest_results import BacktestMetrics 

class OptimizationRequest(BaseModel):
    """Define el cuerpo de la petición para iniciar una optimización."""
    start_date: datetime = Field(..., description="Fecha de inicio (ISO 8601 UTC)")
    end_date: datetime = Field(..., description="Fecha de fin (ISO 8601 UTC)")
    # Espacio de parámetros: Clave=nombre del parámetro, Valor=Lista de valores a probar
    parameter_space: Dict[str, List[Any]] = Field(
        ...,
        description="Diccionario con los parámetros a optimizar y sus rangos/listas de valores.",
        example={'ema_short': [9, 12, 15], 'ema_long': [21, 26, 30, 50], 'atr_multiplier': [1.0, 1.5, 2.0]}
    )
    optimize_metric: str = Field(
        default="sharpe_ratio", # Métrica a maximizar/minimizar por defecto
        description="Nombre de la métrica a optimizar (de BacktestMetrics, ej. 'total_return_pct', 'profit_factor', 'sharpe_ratio' - si se implementa)",
        pattern="^(total_return_pct|max_drawdown_pct|win_rate_pct|profit_factor|total_trades|sharpe_ratio)$"
    )
    # Podríamos añadir: maximize=True/False, top_n_results=10, etc.

class OptimizationRunResult(BaseModel):
    """Resultado de una única ejecución de backtest dentro de la optimización."""
    parameters: Dict[str, Any]
    metrics: BacktestMetrics
    error: Optional[str] = None # Si esta ejecución específica falló

class OptimizationSummary(BaseModel):
    """Resumen de los resultados de la optimización."""
    strategy_id: str
    start_date: datetime
    end_date: datetime
    total_combinations_run: int
    optimize_metric: str
    best_run: Optional[OptimizationRunResult] = None # El mejor resultado encontrado
    top_n_runs: List[OptimizationRunResult] = Field(default_factory=list) # Opcional: devolver los N mejores
    errors_count: int = 0
    optimization_error: Optional[str] = None # Error general de la optimización