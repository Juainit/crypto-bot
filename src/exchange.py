import os
import time
import logging
import ccxt
from decimal import Decimal, ROUND_UP, ROUND_DOWN
from typing import Dict, Optional, Tuple, Any, List

logger = logging.getLogger("KrakenClient")
logger.setLevel(logging.INFO)

# Configuración profesional de logging
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s'
    ))
    logger.addHandler(handler)

class ExchangeClient:
    """Cliente profesional para Kraken con validaciones completas y listo para producción"""

    MIN_PRECISION = {
        'BTC/EUR': {'amount': 8, 'price': 1},
        'ETH/EUR': {'amount': 6, 'price': 2},
        'DEFAULT': {'amount': 4, 'price': 4}
    }

    def __init__(self):
        self._last_nonce = int(time.time() * 1000)
        self._connection_retries = 0
        self.MAX_RETRIES = 3
        self.client = self._initialize_client()
        self._load_markets_with_retry(self.client)
        self.SYMBOL_MAPPING = {
            f"{v['base']}/{v['quote']}": k
            for k, v in self.client.markets.items()
        }
        self.validate_connection()

    def _initialize_time_sync(self):
        self.time_delta = 0
        if not self._check_system_time():
            logger.critical("El reloj del sistema está desincronizado")
            raise SystemExit(1)

    def _check_system_time(self) -> bool:
        current_year = time.localtime().tm_year
        return 2020 <= current_year <= 2100

    def _initialize_client(self) -> ccxt.kraken:
        api_key = os.getenv("KRAKEN_API_KEY", "").strip()
        api_secret = os.getenv("KRAKEN_SECRET", "").strip()

        if not api_key or not api_secret:
            logger.critical("❌ Faltan las variables de entorno KRAKEN_API_KEY o KRAKEN_SECRET")
        else:
            logger.info("✅ Claves de API Kraken cargadas")

        return ccxt.kraken({
            'apiKey': api_key,
            'secret': api_secret,
            'timeout': 30000,  # 30 segundos
            'enableRateLimit': True,
            'options': {
                'adjustForTimeDifference': True,
                'recvWindow': 20000,
                'rateLimit': 3500,
                'numRetries': 3
            }
        })

    def _load_markets_with_retry(self, exchange, max_retries=3):
        for attempt in range(max_retries):
            try:
                exchange.load_markets()
                if not exchange.markets:
                    raise ValueError("Mercados no cargados correctamente")
                logger.info(f"✅ Mercados cargados ({len(exchange.markets)} pares)")
                return
            except Exception as e:
                logger.warning(f"Error al cargar mercados (intento {attempt+1}): {str(e)}")
                if attempt == max_retries - 1:
                    logger.critical(f"Fallo al cargar mercados tras {max_retries} intentos")
                    raise
                time.sleep(2 ** attempt)

    def validate_connection(self):
        try:
            if not self._light_check():
                logger.error("❌ La prueba liviana falló: no se pudo obtener el ticker BTC/EUR")
                raise ConnectionError("Fallo en prueba inicial: ticker no disponible")

            server_time = self.client.fetch_time()
            if not isinstance(server_time, (int, float)):
                raise ValueError(f"Tiempo del servidor inválido: {server_time}")
            logger.info(f"🕒 Tiempo del servidor Kraken: {server_time}")

            logger.info("✅ Conexión con Kraken validada exitosamente")

        except Exception as e:
            self._connection_retries += 1
            logger.error(f"Detalles del error de conexión: {str(e)}")
            if self._connection_retries >= self.MAX_RETRIES:
                logger.critical("Fallo persistente en conexión. Terminando.")
                raise SystemExit(1)

            wait_time = 2 ** self._connection_retries
            logger.warning(f"Reintento {self._connection_retries} en {wait_time}s...")
            time.sleep(wait_time)
            self.validate_connection()

    def _light_check(self) -> bool:
        try:
            ticker = self.client.fetch_ticker('BTC/EUR')
            return isinstance(ticker, dict)
        except Exception as e:
            logger.debug(f"Excepción en _light_check: {str(e)}")
            return False

    def _get_nonce(self) -> int:
        current_nonce = int(time.time() * 1000)
        self._last_nonce = max(current_nonce, self._last_nonce + 1)
        return self._last_nonce

    def _normalize_symbol(self, symbol: str) -> str:
        original_symbol = symbol
        symbol = symbol.upper().strip().replace('-', '/')

        if symbol in self.SYMBOL_MAPPING:
            return self.SYMBOL_MAPPING[symbol]

        if '/' not in symbol:
            raise ValueError(f"Símbolo mal formado: {original_symbol}")

        if symbol in self.client.markets:
            return symbol

        for market_symbol in self.client.markets:
            if symbol.replace('/', '') == market_symbol.replace('/', ''):
                return market_symbol

        available = [k for k in self.client.markets.keys() if symbol.split('/')[0] in k]
        raise ValueError(
            f"Símbolo no soportado: {original_symbol}. Disponibles: {available[:10]}..."
        )

    def _validate_order_params(self, symbol: str, amount: float, price: float):
        market = self.client.market(symbol)

        min_amount = float(market['limits']['amount']['min'])
        if amount < min_amount:
            raise ValueError(f"Cantidad {amount} menor al mínimo {min_amount} para {symbol}")

        if 'amount' in market['precision']:
            step = float(market['precision']['amount'])
            if (amount / step) != int(amount / step):
                raise ValueError(f"Cantidad {amount} no cumple incremento de {step} para {symbol}")

        min_price = float(market['limits']['price']['min'])
        if price < min_price:
            raise ValueError(f"Precio {price} menor al mínimo {min_price} para {symbol}")

    def _adjust_amount_to_step(self, amount: float, symbol: str) -> float:
        market = self.client.market(symbol)
        precision = market['precision'].get('amount', None)

        if not isinstance(precision, int):
            logger.warning(f"Precision inválida para {symbol}: {precision}. Se usará 8 por defecto.")
            precision = 8  # Valor seguro por defecto

        try:
            try:
                step = Decimal('1') / (Decimal('10') ** int(precision))
            except Exception:
                logger.warning(f"Precision inválida para {symbol}: {precision}. Se usará 8 por defecto.")
                precision = 8
                step = Decimal('1') / (Decimal('10') ** 8)
            amt = Decimal(str(amount)).quantize(step, rounding=ROUND_DOWN)
            logger.debug(f"Cantidad ajustada para {symbol}: {amt}")
            return float(amt)
        except Exception as e:
            logger.error(f"Error al ajustar amount para {symbol}: {e}")
            raise

    def create_limit_order(self, symbol: str, side: str, amount: float, price: float):
        """
        Ejecuta una orden limitada.
        """
        symbol_norm = self._normalize_symbol(symbol)
        order = self.client.create_order(symbol_norm, 'limit', side, amount, price)
        return order

    def create_market_order(self, symbol: str, side: str, amount: float, trailing_stop: float = None):
        """
        Ejecuta una orden de mercado; el parámetro trailing_stop se ignora (gestión interna del bot).
        """
        symbol_norm = self._normalize_symbol(symbol)
        return self.client.create_order(symbol_norm, 'market', side, amount)

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        normalized_symbol = self._normalize_symbol(symbol)
        return self.client.fetch_ticker(normalized_symbol)

# Instancia global con manejo de errores
try:
    exchange_client = ExchangeClient()
except Exception as e:
    logger.critical(f"Error crítico al iniciar ExchangeClient: {str(e)}")
    raise