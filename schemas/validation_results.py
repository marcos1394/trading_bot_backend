# schemas/validation_results.py
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from datetime import datetime
# Importar otros schemas necesarios
from .backtest_results import BacktestMetrics, Trade
from .optimization_results import OptimizationRunResult

class WalkForwardRequest(BaseModel):
    """Define el cuerpo de la petición para iniciar una validación Walk-Forward."""
    strategy_id: str = Field(..., description="ID de la estrategia a validar.")
    full_start_date: datetime = Field(..., description="Fecha inicio TODO el periodo histórico (ISO 8601 UTC)")
    full_end_date: datetime = Field(..., description="Fecha fin TODO el periodo histórico (ISO 8601 UTC)")
    in_sample_period: str = Field(..., description="Duración del periodo In-Sample (ej. '6M', '1Y')", example="6M")
    out_of_sample_period: str = Field(..., description="Duración del periodo Out-Of-Sample (ej. '3M')", example="3M")
    parameter_space: Dict[str, List[Any]] = Field(..., description="Espacio de parámetros para optimizar en cada IS.")
    optimize_metric: str = Field(default="sharpe_ratio", description="Métrica a optimizar en IS.")
    # Podríamos añadir 'step_period' si el deslizamiento no es igual al OOS period

class WalkForwardFoldResult(BaseModel):
    """Resultados de un único pliegue (fold) de Walk-Forward."""
    fold_number: int
    in_sample_start: datetime
    in_sample_end: datetime
    out_of_sample_start: datetime
    out_of_sample_end: datetime
    optimization_best_run: Optional[OptimizationRunResult] = None # Mejor resultado de la optimización IS
    out_of_sample_metrics: Optional[BacktestMetrics] = None # Métricas del OOS backtest
    out_of_sample_trades: List[Trade] = Field(default_factory=list) # Trades del OOS backtest
    error: Optional[str] = None # Error específico de este fold

class WalkForwardSummary(BaseModel):
    """Resultados agregados de toda la validación Walk-Forward."""
    strategy_id: str
    full_start_date: datetime
    full_end_date: datetime
    in_sample_period: str
    out_of_sample_period: str
    optimize_metric: str
    number_of_folds: int
    # Métricas agregadas de TODOS los periodos OOS
    aggregated_oos_metrics: Optional[BacktestMetrics] = None
    # Lista detallada de cada fold (opcional, puede ser grande)
    fold_results: List[WalkForwardFoldResult] = Field(default_factory=list)
    # Lista de todos los trades OOS (opcional, puede ser grande)
    # all_oos_trades: List[Trade] = Field(default_factory=list)
    total_errors: int = 0
    overall_error: Optional[str] = None # Error general del proceso WFO