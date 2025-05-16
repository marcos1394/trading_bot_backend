# trading/strategies/base_strategy.py
from abc import ABC, abstractmethod
import pandas as pd
from typing import Dict, Any # Asegúrate que Dict y Any están importados

class BaseStrategy(ABC):
    """Clase base abstracta para estrategias de trading."""

    # --- ESTE MÉTODO ES CLAVE ---
    def __init__(self, config: Dict[str, Any]):
        """
        Constructor base que recibe la configuración específica de la instancia.

        Args:
            config: Un diccionario derivado de StrategyConfig con los detalles
                    (id, name, strategy_type, exchange, pair, timeframe, parameters).
        """
        if not isinstance(config, dict):
             # Añadir una validación básica
             raise ValueError("La configuración pasada a BaseStrategy debe ser un diccionario.")
        self.config = config # Guardar la configuración completa
        # Usar el ID de la config para el nombre base si está disponible
        self._name = f"Strategy_{config.get('id','UnknownID')}"
    # ---------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Nombre único de la instancia de la estrategia."""
        # Las clases hijas pueden sobreescribir esto si quieren un formato diferente
        # pero deben implementar la property.
        # Por ahora, hacemos que las hijas lo implementen obligatoriamente.
        pass
        # Alternativa: Podríamos devolver self._name aquí y que las hijas
        # simplemente definan cómo se genera self._name en su propio __init__
        # return self._name

    @abstractmethod
    def calculate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula indicadores y genera señales de trading.

        Args:
            df: DataFrame de Pandas con columnas OHLCV ('open','high','low','close','volume')
                y timestamp como índice.

        Returns:
            DataFrame de Pandas original con columnas adicionales:
            - Columnas de indicadores (ej. 'EMA_12', 'RSI_14').
            - 'signal': 1=Entrada Long, -1=Entrada Short, 0=Mantener,
                        2=Salida Long (por señal), -2=Salida Short (por señal).
            - 'sl_price': Precio de Stop Loss inicial (solo en velas de entrada).
            - 'tp_price': Precio de Take Profit inicial (solo en velas de entrada).
        """
        pass