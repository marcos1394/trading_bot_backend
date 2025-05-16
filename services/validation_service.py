# services/validation_service.py
import logging
import pandas as pd
import numpy as np # Necesario si se usa en métricas o estrategias
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from dateutil.relativedelta import relativedelta
from requests import Session

# --- Importaciones para Celery y dependencias de tarea ---
from core.celery_app import celery_app
from db.session import SessionLocal # Para crear sesión de BD en la tarea
from services.strategy_service import StrategyService
from services.optimization_service import OptimizationService # Para instanciar dentro de la tarea
from services.backtesting_service import BacktestingService, INITIAL_CAPITAL
from schemas.strategy import StrategyConfig # Necesario para crear oos_config
from schemas.validation_results import WalkForwardRequest, WalkForwardFoldResult, WalkForwardSummary
from schemas.backtest_results import BacktestMetrics # Para el tipo de métrica
from schemas.trade import Trade

logger = logging.getLogger(__name__)

# Helper para convertir string de periodo (ej. '6M', '1Y') a relativedelta
def parse_period_string(period_str: str) -> relativedelta:
    period_str = period_str.upper()
    if period_str.endswith('M'): return relativedelta(months=int(period_str[:-1]))
    elif period_str.endswith('Y'): return relativedelta(years=int(period_str[:-1]))
    elif period_str.endswith('D'): return relativedelta(days=int(period_str[:-1]))
    else: raise ValueError(f"Formato de periodo no soportado: {period_str}. Usar ej: '3M', '1Y', '90D'.")

# --- NUEVA FUNCIÓN DE TAREA CELERY PARA WALK-FORWARD ---
@celery_app.task(bind=True, name='tasks.run_walk_forward')
def run_walk_forward_task(self, # 'self' es la instancia de la tarea Celery
                          strategy_id: str,
                          full_start_date_iso: str,
                          full_end_date_iso: str,
                          in_sample_period_str: str,
                          out_of_sample_period_str: str,
                          parameter_space: Dict[str, List[Any]],
                          optimize_metric: str) -> Dict: # Devolver un Diccionario serializable
    """
    Tarea Celery para ejecutar Walk-Forward Optimization en segundo plano.
    """
    task_id = self.request.id
    logger.info(f"TASK[{task_id}]: Iniciando Walk-Forward para {strategy_id}")

    # Convertir fechas ISO string a datetime
    try:
        full_start_date = datetime.fromisoformat(full_start_date_iso.replace('Z', '+00:00'))
        full_end_date = datetime.fromisoformat(full_end_date_iso.replace('Z', '+00:00'))
        is_period = parse_period_string(in_sample_period_str)
        oos_period = parse_period_string(out_of_sample_period_str)
        step_period = oos_period # Deslizar por el tamaño del OOS
    except ValueError as e:
        logger.error(f"TASK[{task_id}]: Error parseando fechas/periodos: {e}")
        self.update_state(state='FAILURE', meta={'exc_type': type(e).__name__, 'exc_message': str(e)})
        return {"error": f"Error en formato de fechas/periodos: {e}"}

    # --- Crear instancias de servicios y sesión DB DENTRO de la tarea ---
    db: Optional[Session] = None # Inicializar a None
    try:
        db = SessionLocal() # ¡Nueva sesión para esta tarea!
        strategy_service = StrategyService() # No necesita BD en __init__
        backtesting_service = BacktestingService(db=db, strategy_service=strategy_service)
        # OptimizationService necesita StrategyService y BacktestingService
        optimization_service = OptimizationService(strategy_service=strategy_service, backtesting_service=backtesting_service)
    except Exception as service_err:
        logger.error(f"TASK[{task_id}]: Error inicializando servicios para WFO: {service_err}", exc_info=True)
        if db: db.close()
        self.update_state(state='FAILURE', meta={'exc_type': type(service_err).__name__, 'exc_message': str(service_err)})
        return {"error": f"Error inicializando servicios para WFO: {service_err}"}

    # --- Lógica principal de Walk-Forward (similar a la clase ValidationService anterior) ---
    try:
        # Obtener config base
        base_config = strategy_service.get_strategy_config(strategy_id)
        if not base_config:
            raise ValueError(f"Estrategia base ID '{strategy_id}' no encontrada.")

        # Validaciones de fechas y periodos (podrían estar en el endpoint también)
        if full_start_date + is_period + oos_period > full_end_date + timedelta(days=1):
            raise ValueError("Periodo IS + OOS es mayor que el rango de fechas total.")

        all_oos_trades: List[Trade] = []
        all_fold_results: List[WalkForwardFoldResult] = []
        fold_number = 0
        total_errors_folds = 0 # Errores específicos de folds
        current_is_start = full_start_date

        while True:
            fold_number += 1
            is_end = current_is_start + is_period - timedelta(microseconds=1)
            oos_start = is_end + timedelta(microseconds=1)
            oos_end = oos_start + oos_period - timedelta(microseconds=1)

            if oos_start > full_end_date:
                logger.info(f"TASK[{task_id}]: Fin de Walk-Forward. Inicio OOS ({oos_start}) excede fecha final ({full_end_date}).")
                fold_number -=1 # No se completó este fold
                break
            if oos_end > full_end_date:
                oos_end = full_end_date
                logger.info(f"TASK[{task_id}]: Ajustando fin del último periodo OOS a {oos_end}")

            # Actualizar estado de la tarea Celery
            self.update_state(state='PROGRESS', meta={
                'current_fold': fold_number,
                'is_period': f"{current_is_start.date()} -> {is_end.date()}",
                'oos_period': f"{oos_start.date()} -> {oos_end.date()}"
            })

            logger.info(f"TASK[{task_id}]: Fold #{fold_number}: IS {current_is_start.date()}-{is_end.date()}, OOS {oos_start.date()}-{oos_end.date()}")

            fold_result_data = WalkForwardFoldResult(
                fold_number=fold_number,
                in_sample_start=current_is_start, in_sample_end=is_end,
                out_of_sample_start=oos_start, out_of_sample_end=oos_end,
                out_of_sample_metrics=BacktestMetrics(initial_portfolio_value=INITIAL_CAPITAL, final_portfolio_value=INITIAL_CAPITAL) # Default
            )

            # 1. Optimizar en In-Sample
            best_params_is: Optional[Dict[str, Any]] = None
            try:
                logger.info(f"TASK[{task_id}]: Fold #{fold_number} - Iniciando Optimización IS...")
                opt_summary = optimization_service.run_grid_search(
                    strategy_id=strategy_id, param_space=parameter_space,
                    start_dt=current_is_start, end_dt=is_end,
                    optimize_metric=optimize_metric, top_n=1 # Solo necesitamos el mejor
                )
                if opt_summary.optimization_error or not opt_summary.best_run:
                    fold_result_data.error = opt_summary.optimization_error or "No se encontraron parámetros óptimos IS."
                    logger.error(f"TASK[{task_id}]: Fold #{fold_number} - Optimización IS falló: {fold_result_data.error}")
                    total_errors_folds += 1
                else:
                    best_params_is = opt_summary.best_run.parameters
                    fold_result_data.optimization_best_run = opt_summary.best_run
                    logger.info(f"TASK[{task_id}]: Fold #{fold_number} - Optimización IS completada. Params: {best_params_is}")
            except Exception as e_opt:
                logger.exception(f"TASK[{task_id}]: Fold #{fold_number} - Excepción en Optimización IS.")
                fold_result_data.error = f"Excepción Opt IS: {e_opt}"
                total_errors_folds += 1

            # 2. Backtest en Out-of-Sample
            if best_params_is and fold_result_data.error is None:
                logger.info(f"TASK[{task_id}]: Fold #{fold_number} - Iniciando Backtest OOS con params: {best_params_is}...")
                try:
                    temp_config_dict = base_config.model_dump()
                    temp_config_dict['parameters'].update(best_params_is)
                    oos_strategy_config = StrategyConfig(**temp_config_dict)

                    oos_result = backtesting_service.run_single_strategy_backtest(
                        config=oos_strategy_config, start_dt=oos_start, end_dt=oos_end
                    )
                    if oos_result.error:
                        fold_result_data.error = f"Backtest OOS: {oos_result.error}"
                        logger.error(f"TASK[{task_id}]: Fold #{fold_number} - Backtest OOS falló: {oos_result.error}")
                        total_errors_folds +=1
                    else:
                        fold_result_data.out_of_sample_metrics = oos_result.metrics
                        fold_result_data.out_of_sample_trades = oos_result.trades
                        all_oos_trades.extend(oos_result.trades)
                        logger.info(f"TASK[{task_id}]: Fold #{fold_number} - Backtest OOS completado. Retorno: {oos_result.metrics.total_return_pct:.2f}%")
                except Exception as e_bt:
                    logger.exception(f"TASK[{task_id}]: Fold #{fold_number} - Excepción en Backtest OOS.")
                    fold_result_data.error = f"Excepción BT OOS: {e_bt}"
                    total_errors_folds += 1

            all_fold_results.append(fold_result_data)
            current_is_start += step_period
            if oos_end >= full_end_date: break # Condición de salida final

        # --- Fin Bucle Walk-Forward ---
        logger.info(f"TASK[{task_id}]: Proceso WFO completado. Calculando métricas agregadas OOS...")

        # Calcular Métricas Agregadas OOS (lógica similar a antes)
        aggregated_metrics: Optional[BacktestMetrics] = None
        if all_oos_trades:
             try:
                  oos_equity = [INITIAL_CAPITAL]; oos_timestamps = [full_start_date - timedelta(seconds=1)]
                  current_equity = INITIAL_CAPITAL
                  for trade in sorted(all_oos_trades, key=lambda t: t.exit_timestamp if t.exit_timestamp else t.entry_timestamp):
                       net_pnl = (trade.pnl_abs or 0.0) - (trade.commission or 0.0)
                       current_equity += net_pnl
                       if trade.exit_timestamp: oos_timestamps.append(trade.exit_timestamp); oos_equity.append(current_equity)
                  oos_equity_df = pd.DataFrame({'equity': oos_equity}, index=pd.to_datetime(oos_timestamps, utc=True)).sort_index()
                  oos_equity_df = oos_equity_df[~oos_equity_df.index.duplicated(keep='last')]
                  oos_total_commission = sum(t.commission for t in all_oos_trades if t.commission is not None)
                  oos_final_equity = oos_equity_df['equity'].iloc[-1] if not oos_equity_df.empty else INITIAL_CAPITAL
                  # Usar el timeframe de la primera config activa para anualización
                  oos_timeframe = strategy_service.get_strategy_config(active_strategy_ids[0]).timeframe if active_strategy_ids else "1h" # type: ignore

                  aggregated_metrics = backtesting_service._calculate_metrics(
                       oos_equity_df, all_oos_trades, oos_total_commission, oos_final_equity, oos_timeframe, is_portfolio=True
                  )
             except Exception as agg_err: logger.exception("Error calculando métricas OOS"); aggregated_metrics = BacktestMetrics(initial_portfolio_value=INITIAL_CAPITAL, final_portfolio_value=INITIAL_CAPITAL, error=f"Error métricas OOS: {agg_err}")

        summary = WalkForwardSummary(
            strategy_id=strategy_id, full_start_date=full_start_date, full_end_date=full_end_date,
            in_sample_period=in_sample_period_str, out_of_sample_period=out_of_sample_period_str,
            optimize_metric=optimize_metric, number_of_folds=fold_number,
            aggregated_oos_metrics=aggregated_metrics, fold_results=all_fold_results, total_errors=total_errors_folds
        )
        logger.info(f"TASK[{task_id}]: Validación Walk-Forward finalizada.")
        return summary.model_dump(mode='json')

    except Exception as task_err:
        logger.exception(f"TASK[{task_id}]: Error fatal durante Walk-Forward")
        self.update_state(state='FAILURE', meta={'exc_type': type(task_err).__name__, 'exc_message': str(task_err)})
        return {"error": f"Error fatal en WFO: {task_err}"}
    finally:
        if db: db.close() # Asegurar cierre de sesión de BD de la tarea
        logger.debug(f"TASK[{task_id}]: Sesión de BD WFO cerrada.")


# --- Ya NO necesitamos la clase ValidationService ni get_validation_service ---
# --- si toda la lógica está en la tarea Celery ---