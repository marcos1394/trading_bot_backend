# services/optimization_service.py
import logging
import itertools
import pandas as pd # Asegúrate de que pandas esté importado si lo usas
from datetime import datetime
from typing import Dict, Any, List, Optional

from requests import Session

from core.celery_app import celery_app
from db.session import SessionLocal, get_db # get_db no se usa aquí directamente, pero SessionLocal sí
# Dependencias de servicios y schemas
from services.strategy_service import StrategyService, get_strategy_service # Para ser inyectado en la clase
from services.backtesting_service import BacktestingService, INITIAL_CAPITAL, get_backtesting_service # Para ser inyectado en la clase
from schemas.strategy import StrategyConfig
from schemas.optimization_results import OptimizationRunResult, OptimizationSummary
from schemas.backtest_results import BacktestMetrics

logger = logging.getLogger(__name__)

class OptimizationService: # <<< REINTRODUCIR LA CLASE
    def __init__(self, strategy_service: StrategyService, backtesting_service: BacktestingService):
        self.strategy_service = strategy_service
        self.backtesting_service = backtesting_service

    def _generate_parameter_combinations(self, param_space: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
        """Genera todas las combinaciones posibles de parámetros (Grid Search)."""
        if not param_space: return [{}]
        keys = param_space.keys(); values = param_space.values()
        try:
            combinations = [dict(zip(keys, c)) for c in itertools.product(*values)]
            logger.info(f"Generadas {len(combinations)} combinaciones de parámetros.")
            return combinations
        except Exception as e:
            logger.error(f"Error generando combinaciones: {e}", exc_info=True); return []

    def run_grid_search(self,
                        strategy_id: str,
                        param_space: Dict[str, List[Any]],
                        start_dt: datetime,
                        end_dt: datetime,
                        optimize_metric: str = "sharpe_ratio",
                        top_n: int = 5) -> OptimizationSummary:
        """Ejecuta una optimización Grid Search para una estrategia."""
        logger.info(f"Lógica Grid Search para {strategy_id} optimizando por '{optimize_metric}'...")

        base_config = self.strategy_service.get_strategy_config(strategy_id)
        if not base_config:
            return OptimizationSummary(strategy_id=strategy_id, start_date=start_dt, end_date=end_dt,
                                       total_combinations_run=0, optimize_metric=optimize_metric,
                                       optimization_error=f"Estrategia base ID '{strategy_id}' no encontrada.")

        parameter_combinations = self._generate_parameter_combinations(param_space)
        total_runs = len(parameter_combinations)
        if total_runs == 0:
             return OptimizationSummary(strategy_id=strategy_id, start_date=start_dt, end_date=end_dt,
                                        total_combinations_run=0, optimize_metric=optimize_metric,
                                        optimization_error="No se generaron combinaciones de parámetros.")
        logger.info(f"Se ejecutarán {total_runs} backtests individuales...")
        all_run_results: List[OptimizationRunResult] = []
        errors_count = 0

        for i, params_to_test in enumerate(parameter_combinations):
            logger.info(f"--- Opt Run {i+1}/{total_runs} para {strategy_id} con params: {params_to_test} ---")
            run_error_msg = None
            run_metrics = BacktestMetrics(initial_portfolio_value=INITIAL_CAPITAL, final_portfolio_value=INITIAL_CAPITAL)
            try:
                 temp_config_dict = base_config.model_dump()
                 if 'parameters' not in temp_config_dict: temp_config_dict['parameters'] = {}
                 temp_config_dict['parameters'].update(params_to_test)
                 temp_config = StrategyConfig(**temp_config_dict)

                 backtest_result = self.backtesting_service.run_single_strategy_backtest(
                     config=temp_config, start_dt=start_dt, end_dt=end_dt
                 )
                 if backtest_result.error: run_error_msg = backtest_result.error; errors_count += 1
                 run_metrics = backtest_result.metrics or run_metrics
            except ValueError as val_err: run_error_msg = f"Config inválida: {val_err}"; errors_count += 1
            except Exception as run_err: logger.exception("Error crítico en backtest"); run_error_msg = f"Excepción: {run_err}"; errors_count += 1
            all_run_results.append(OptimizationRunResult(parameters=params_to_test, metrics=run_metrics, error=run_error_msg))

        logger.info("Análisis de resultados de optimización...")
        valid_results = [r for r in all_run_results if r.error is None]
        if not valid_results:
             logger.error("No se obtuvieron resultados válidos en la optimización.")
             return OptimizationSummary(strategy_id=strategy_id, start_date=start_dt, end_date=end_dt,
                                        total_combinations_run=total_runs, optimize_metric=optimize_metric,
                                        errors_count=errors_count, optimization_error="No hubo resultados válidos.")
        maximize = optimize_metric not in ["max_drawdown_pct"]
        def get_metric_value(run_result, metric_name, maximize_flag):
            metric_val = getattr(run_result.metrics, metric_name, None)
            if metric_val is None: return float('-inf') if maximize_flag else float('inf')
            return metric_val
        try:
             sorted_results = sorted(valid_results, key=lambda r: get_metric_value(r, optimize_metric, maximize), reverse=maximize)
        except Exception as sort_err:
             logger.error(f"Error al ordenar resultados: {sort_err}")
             return OptimizationSummary(strategy_id=strategy_id, start_date=start_dt, end_date=end_dt, total_combinations_run=total_runs, optimize_metric=optimize_metric, top_n_runs=valid_results[:top_n], errors_count=errors_count, optimization_error=f"Error al ordenar: {sort_err}")
        best_run = sorted_results[0] if sorted_results else None
        top_n_runs = sorted_results[:min(top_n, len(sorted_results))]
        if best_run: logger.info(f"Mejor resultado ({optimize_metric}): {getattr(best_run.metrics, optimize_metric, 'N/A')} con params: {best_run.parameters}")
        else: logger.error("No se encontró 'mejor' resultado válido.")
        return OptimizationSummary(strategy_id=strategy_id, start_date=start_dt, end_date=end_dt, total_combinations_run=total_runs, optimize_metric=optimize_metric, best_run=best_run, top_n_runs=top_n_runs, errors_count=errors_count)

# --- FUNCIÓN DE TAREA CELERY (Usa la clase OptimizationService) ---
@celery_app.task(bind=True, name='tasks.run_grid_search')
def run_grid_search_task(self, # 'self' es la instancia de la tarea Celery
                         strategy_id: str,
                         param_space: Dict[str, List[Any]],
                         start_dt_iso: str,
                         end_dt_iso: str,
                         optimize_metric: str = "sharpe_ratio",
                         top_n: int = 5) -> Dict: # Devolver un Diccionario
    """Tarea Celery para ejecutar Grid Search en segundo plano."""
    task_id = self.request.id
    logger.info(f"TASK[{task_id}]: Iniciando Grid Search para {strategy_id}")
    start_dt = datetime.fromisoformat(start_dt_iso.replace('Z', '+00:00'))
    end_dt = datetime.fromisoformat(end_dt_iso.replace('Z', '+00:00'))

    db: Optional[Session] = None
    try:
        db = SessionLocal() # Nueva sesión para esta tarea
        # Instanciar servicios con la nueva sesión de BD
        # Esto asume que __init__ de StrategyService espera 'db' o puede manejar 'None'
        # si no se pasa. Vamos a asumir que StrategyService ahora toma 'db' como __init__
        strategy_service = StrategyService(db=db) # StrategyService necesita db para el seeding/repo
        backtesting_service = BacktestingService(db=db, strategy_service=strategy_service)
        # Crear instancia de OptimizationService
        optimization_service = OptimizationService(
            strategy_service=strategy_service,
            backtesting_service=backtesting_service
        )

        # Usar el método de la clase para la lógica
        summary = optimization_service.run_grid_search(
            strategy_id=strategy_id,
            param_space=param_space,
            start_dt=start_dt,
            end_dt=end_dt,
            optimize_metric=optimize_metric,
            top_n=top_n
        )
        logger.info(f"TASK[{task_id}]: Optimización completada. Devolviendo summary.")
        return summary.model_dump(mode='json')

    except Exception as task_err:
         logger.exception(f"TASK[{task_id}]: Error fatal durante Grid Search")
         self.update_state(state='FAILURE', meta={'exc_type': type(task_err).__name__, 'exc_message': str(task_err)})
         return {"error": f"Error fatal en optimización: {task_err}"}
    finally:
         if db: db.close()
         logger.debug(f"TASK[{task_id}]: Sesión de BD optimización cerrada.")

# --- Dependencia para FastAPI (REINTRODUCIR si OptimizationService se usa directamente en algún endpoint) ---
# Si la clase OptimizationService solo se usa internamente por la tarea Celery
# y no hay endpoints API que la inyecten directamente, esta función get_optimization_service
# no es estrictamente necesaria para el endpoint /optimize/grid que llama a la tarea.
# PERO, es necesaria para que ValidationService pueda inyectarla.

from fastapi import Depends # Mover el Depends acá si no está
from db.session import get_db # Re-asegurar importación

def get_optimization_service(
    db: Session = Depends(get_db), # Necesita la sesión de BD
    strategy_service: StrategyService = Depends(get_strategy_service),
    backtesting_service: BacktestingService = Depends(get_backtesting_service)
) -> OptimizationService:
    return OptimizationService(
        strategy_service=strategy_service,
        backtesting_service=backtesting_service
    )