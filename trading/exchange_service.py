# trading/exchange_service.py
import ccxt.async_support as ccxt
import logging
from core.config import settings # Necesitamos settings para las claves y el flag
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

class ExchangeService:
    def __init__(self):
        self.client: Optional[ccxt.Exchange] = None
        # La inicialización ahora se hace explícitamente con initialize()
        logger.debug("ExchangeService __init__: Instancia creada, cliente NO inicializado.")

    async def initialize(self):
        """
        Inicializa el cliente CCXT explícitamente y carga mercados.
        Activa el modo Sandbox si settings.EXECUTE_LIVE_ORDERS es True.
        """
        if self.client is not None and self.client.markets:
            logger.info("Cliente CCXT ya inicializado y con mercados cargados. Omitiendo.")
            return

        logger.info("ExchangeService.initialize(): Iniciando inicialización explícita...")

        # Configuración base
        exchange_config = {
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'}
        }

        # Añadir claves API si están disponibles
        if settings.BINANCE_API_KEY and settings.BINANCE_SECRET_KEY:
            logger.info("Utilizando claves API de Binance desde .env.")
            exchange_config['apiKey'] = settings.BINANCE_API_KEY
            exchange_config['secret'] = settings.BINANCE_SECRET_KEY
        else:
            logger.warning("Claves API de Binance no configuradas en .env. Funcionalidad limitada a datos públicos.")

        logger.debug(f"Configuración CCXT a usar: {exchange_config}")

        try:
            self.client = ccxt.binance(exchange_config)
            logger.debug(f"Instancia CCXT creada: {type(self.client)}")

            if self.client:
                logger.info(f"Cliente CCXT para '{self.client.id}' instanciado. API Key presente: {bool(self.client.apiKey)}")

                # --- ACTIVAR MODO SANDBOX/TESTNET ---
                if settings.EXECUTE_LIVE_ORDERS:
                    try:
                        logger.warning("EXECUTE_LIVE_ORDERS=True. Habilitando Modo Sandbox/Testnet en CCXT...")
                        self.client.set_sandbox_mode(True) # <<< ¡LÍNEA CLAVE!
                        logger.info("Modo Sandbox/Testnet HABILITADO en CCXT.")
                    except Exception as e_sandbox:
                         # Loguear si set_sandbox_mode falla, pero intentar continuar
                         logger.error(f"Error al intentar habilitar modo sandbox: {e_sandbox}", exc_info=True)
                         # Podrías decidir si abortar aquí o no
                else:
                    logger.info("Modo Sandbox/Testnet NO habilitado en CCXT (EXECUTE_LIVE_ORDERS=False).")
                # ------------------------------------

                # Cargar mercados (después de set_sandbox_mode si aplica)
                await self.load_markets_safe(reload=True)

            else:
                logger.error("Fallo crítico al instanciar cliente CCXT: ccxt.binance() devolvió None.")
                self.client = None
        except Exception as e:
            logger.error(f"Error FATAL durante ExchangeService.initialize(): {e}", exc_info=True)
            self.client = None # Asegurar que sea None en caso de error

        if self.client is None:
             logger.critical("¡FALLO! ExchangeService.initialize() no pudo configurar el cliente CCXT.")
        else:
             logger.info("ExchangeService.initialize() completado.")


    async def close_client(self):
        if self.client and hasattr(self.client, 'close') and callable(self.client.close):
             try: await self.client.close(); logger.info(f"Cliente CCXT {self.client.id} cerrado.")
             except Exception as e: logger.error(f"Error cerrando cliente CCXT: {e}", exc_info=True)

    def get_client(self) -> Optional[ccxt.Exchange]:
        if self.client is None: logger.warning("get_client() llamado pero self.client es None.")
        return self.client

    async def load_markets_safe(self, reload: bool = False):
        client = self.get_client()
        if not client: logger.error("load_markets_safe: cliente CCXT es None."); return
        if reload or not client.markets or not len(client.markets):
            try:
                logger.info(f"Cargando mercados para {client.id} (Sandbox: {client.sandbox if hasattr(client,'sandbox') else 'N/A'}, reload={reload})...")
                await client.load_markets(reload)
                market_count = len(client.markets) if client.markets else 0
                logger.info(f"Mercados para {client.id} cargados: {market_count}.")
                if market_count == 0: logger.warning(f"load_markets para {client.id} no devolvió mercados.")
            except Exception as e: logger.error(f"No se pudieron cargar mercados: {e}", exc_info=True)
        else: logger.debug(f"Mercados para {client.id} ya cargados y reload=False.")

    async def get_balance(self) -> Optional[Dict[str, Any]]:
        client = self.get_client()
        if not client or not client.apiKey: logger.warning("get_balance: Cliente no listo o sin API Key."); return None
        try: await self.load_markets_safe(); balance = await client.fetch_balance(); return balance.get('total', {})
        except Exception as e: logger.error(f"Error obteniendo balance: {e}", exc_info=True); return None

    async def create_market_order(self, symbol: str, side: str, amount: float, params: Optional[Dict] = None) -> Optional[Dict]:
        client = self.get_client();
        if not client or not client.apiKey: logger.error(f"create_market_order: Cliente no listo o sin API Key para {symbol}."); return None
        # if not client.has['createMarketOrder']: logger.error(f"Exchange {client.id} no soporta createMarketOrder."); return None # 'has' puede ser poco fiable
        await self.load_markets_safe(); final_params = params or {}
        # Ajustar precisión de cantidad según el mercado
        try:
            market = client.market(symbol)
            amount_precise = client.amount_to_precision(symbol, amount)
            if float(amount_precise) <= 0 or (market.get('limits',{}).get('amount',{}).get('min') and float(amount_precise) < market['limits']['amount']['min']):
                 logger.error(f"Cantidad inválida o por debajo del mínimo para {symbol}: Solicitado={amount:.8f}, Preciso={amount_precise}, Mínimo={market.get('limits',{}).get('amount',{}).get('min')}")
                 raise ccxt.InvalidOrder(f"Cantidad {amount_precise} menor al mínimo para {symbol}")
            logger.info(f"Intentando crear orden MERCADO: {side.upper()} {amount_precise} {symbol} con params {final_params}")
            if side.lower() == 'buy': order = await client.create_market_buy_order(symbol, float(amount_precise), final_params)
            elif side.lower() == 'sell': order = await client.create_market_sell_order(symbol, float(amount_precise), final_params)
            else: logger.error(f"Lado de orden inválido: '{side}'."); return None
            logger.info(f"Orden MERCADO creada para {symbol}: ID {order.get('id')}, Status {order.get('status')}")
            return order
        except ccxt.InsufficientFunds as e: logger.error(f"Fondos insuficientes: {e}"); raise
        except ccxt.InvalidOrder as e: logger.error(f"Orden inválida: {e}"); raise
        except ccxt.ExchangeError as e: logger.error(f"Error Exchange (orden): {e}"); raise
        except Exception as e: logger.error(f"Error inesperado (orden): {e}", exc_info=True); raise

    async def fetch_order_status(self, order_id: str, symbol: str) -> Optional[Dict]:
        client = self.get_client()
        if not client or not client.apiKey: logger.error("fetch_order_status: Cliente no listo o sin API Key."); return None
        # if not client.has['fetchOrder']: logger.error(f"Exchange {client.id} no soporta fetchOrder."); return None
        try: order = await client.fetch_order(order_id, symbol); logger.debug(f"Estado orden {order_id}: {order.get('status')}"); return order
        except ccxt.OrderNotFound as e: logger.warning(f"Orden {order_id} no encontrada: {e}"); return None
        except Exception as e: logger.error(f"Error consultando orden {order_id}: {e}", exc_info=True); return None

# --- Instancia Singleton Global ---
exchange_service_instance = ExchangeService()

# --- Dependencia para FastAPI ---
def get_exchange_service() -> ExchangeService:
    return exchange_service_instance

# --- Funciones de Ciclo de Vida para FastAPI ---
async def startup_exchange_service():
    """Función a llamar desde el lifespan startup de FastAPI."""
    logger.info("Llamando a ExchangeService.initialize() desde startup...")
    await exchange_service_instance.initialize()
    if exchange_service_instance.get_client() is None:
        logger.critical("¡FALLO CRÍTICO! El cliente CCXT no se pudo inicializar durante el startup.")
    else:
        logger.info("ExchangeService.initialize() completado en startup.")

async def shutdown_exchange_service():
    logger.info("Iniciando cierre del ExchangeService (shutdown FastAPI)...")
    await exchange_service_instance.close_client()
    logger.info("Cierre del ExchangeService finalizado.")