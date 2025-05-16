# test_ccxt_websocket.py

# --- PASO 1: winloop.install() ANTES DE TODO LO ASYNCIO ---
import asyncio # Importar asyncio DESPUÉS de winloop.install si es posible
try:
    import winloop
    winloop.install()
    print("INFO: Política de bucle de eventos de Winloop instalada.")
except ImportError:
    print("ADVERTENCIA: winloop no encontrado.")
except Exception as e_winloop:
    print(f"ERROR al instalar winloop: {e_winloop}")
# -----------------------------------------------------------

import ccxt.async_support as ccxt # Importar CCXT después
import logging
import os
# from dotenv import load_dotenv # No la necesitamos si no usamos claves API

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s') # DEBUG para más detalle
logger = logging.getLogger("CCXT_WS_MINIMAL_TEST")

async def run_test():
    logger.info("Iniciando prueba mínima de CCXT watchOHLCV para Binance...")

    exchange_config = {
        'enableRateLimit': True, # Siempre bueno tenerlo
        'options': {
            'defaultType': 'spot', # Para REST API y como fallback
            # --- Intento de ser más explícito para WebSockets ---
            # Algunas versiones/implementaciones de CCXT podrían usar esto
            # para determinar el endpoint correcto del stream.
            'watchOHLCV': {'type': 'spot'}, # Indica que queremos klines de spot
            # También podríamos probar con 'market_type': 'spot' directamente en options
            # o incluso 'marketType': 'spot'
        },
        # 'timeout': 30000, # Aumentar timeout si hay problemas de red lentos
        # No usar claves API para esta prueba de stream público
    }
    logger.info(f"Configuración CCXT: {exchange_config}")

    # Forzar la creación de un nuevo bucle de eventos si es necesario
    # loop = asyncio.new_event_loop()
    # asyncio.set_event_loop(loop)

    exchange = ccxt.binance(exchange_config)
    logger.info(f"Cliente CCXT Binance instanciado: {type(exchange)}")

    # --- Forzar el tipo de mercado en la instancia si es posible (diagnóstico) ---
    # A veces, establecerlo explícitamente en la instancia puede ayudar
    # exchange.options['defaultType'] = 'spot' # Ya está en config
    # exchange.options['type'] = 'spot' # Otra forma de intentarlo
    # logger.info(f"Opciones del cliente después de instanciar: {exchange.options}")
    # -----------------------------------------------------------------------


    symbol_to_watch = 'BTC/USDT'
    timeframe_to_watch = '1m'

    try:
        logger.info(f"Intentando cargar mercados para {exchange.id} (reload=True)...")
        await exchange.load_markets(reload=True)
        market_count = len(exchange.markets) if exchange.markets else 0
        logger.info(f"Mercados cargados: {market_count}")
        if market_count == 0:
            logger.error("No se cargaron mercados. Terminando prueba.")
            await exchange.close()
            return

        # Loguear capacidades después de cargar mercados
        supports_watch_ohlcv = exchange.has.get('watchOHLCV')
        logger.info(f"Capacidad 'watchOHLCV' reportada por client.has: {supports_watch_ohlcv}")
        # logger.debug(f"Diccionario 'has' completo: {exchange.has}") # Puede ser muy largo

        # Loguear URLs de WebSocket
        ws_urls_api = exchange.urls.get('api', {}).get('ws', {})
        if ws_urls_api:
            logger.info(f"URLs WS configuradas en exchange.urls['api']['ws']: {ws_urls_api}")
        else:
            logger.warning("exchange.urls['api']['ws'] no encontrada o vacía.")


        if not supports_watch_ohlcv:
             logger.warning("CCXT reporta que watchOHLCV no está soportado (según 'has' dict). Intentando la llamada directa...")
        else:
             logger.info("CCXT reporta que watchOHLCV SÍ está soportado (según 'has' dict).")


        logger.info(f"Intentando suscribirse a watchOHLCV para {symbol_to_watch} @ {timeframe_to_watch}...")
        
        counter = 0
        while counter < 3: # Escuchar por 3 velas
            # Añadir un timeout a la llamada de watch_ohlcv para que no se quede colgado indefinidamente
            candles = await asyncio.wait_for(exchange.watch_ohlcv(symbol_to_watch, timeframe_to_watch), timeout=60.0)
            if candles:
                logger.info(f"Vela(s) recibida(s) para {symbol_to_watch} (vela más reciente): {candles[-1]}")
                counter += 1
            else:
                logger.info(f"watchOHLCV devolvió lista vacía para {symbol_to_watch}.")
            # No es necesario un sleep aquí si watch_ohlcv bloquea hasta la siguiente vela
            
    except asyncio.TimeoutError:
        logger.error(f"Timeout esperando velas de {symbol_to_watch}. ¿Está el stream funcionando o hay conexión?")
    except ccxt.NotSupported as e_ns:
        logger.error(f"ERROR ccxt.NotSupported: {e_ns}", exc_info=True)
    except ccxt.NetworkError as e_net: # Errores de red, timeouts, etc.
        logger.error(f"ERROR de Red CCXT: {e_net}", exc_info=True)
    except ccxt.ExchangeError as e_exc: # Errores específicos del exchange
        logger.error(f"ERROR de Exchange CCXT: {e_exc}", exc_info=True)
    except Exception as e: # Cualquier otra excepción
        logger.error(f"ERROR Inesperado: {e}", exc_info=True)
    finally:
        logger.info("Intentando cerrar conexión del exchange...")
        if hasattr(exchange, 'close') and callable(exchange.close):
            await exchange.close()
            logger.info("Conexión del exchange cerrada.")
        else:
            logger.warning("Instancia exchange no tiene método close asíncrono.")

if __name__ == '__main__':
    try:
        # loop = asyncio.ProactorEventLoop() # Solo en Windows, si winloop no funciona
        # asyncio.set_event_loop(loop)
        asyncio.run(run_test())
    except KeyboardInterrupt:
        logger.info("Prueba interrumpida por el usuario.")
    except Exception as e_run:
        logger.error(f"Error al ejecutar asyncio.run: {e_run}", exc_info=True)