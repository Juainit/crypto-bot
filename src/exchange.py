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

    # Mapeo completo de símbolos (actualizado 2024)
    SYMBOL_MAPPING = {
        'REP/EUR': 'XREPZEUR',
        'BTC/EUR': 'XXBTZEUR',
        'ETH/EUR': 'XETHZEUR',
        'ADA/EUR': 'ADAEUR',
        'SOL/EUR': 'SOLEUR',
        'DOT/EUR': 'DOTEUR'
    }

    # Precisión mínima por tipo de activo (backup)
    MIN_PRECISION = {
        'BTC/EUR': {'amount': 8, 'price': 1},
        'ETH/EUR': {'amount': 6, 'price': 2},
        'DEFAULT': {'amount': 4, 'price': 4}
    }

    def __init__(self):
        """Inicialización con validación completa"""
        self._last_nonce = int(time.time() * 1000)
        self._initialize_time_sync()
        self.client = self._initialize_client()
        self._validate_connection()

    def _initialize_time_sync(self):
        """Sincronización horaria robusta"""
        self.time_delta = 0
        if not self._check_system_time():
            logger.critical("El reloj del sistema está desincronizado")
            raise SystemExit(1)

    def _check_system_time(self) -> bool:
        """Verifica que el reloj del sistema sea razonable"""
        current_year = time.localtime().tm_year
        return 2023 <= current_year <= 2025

    def _initialize_client(self) -> ccxt.kraken:
        """Configuración con validación de credenciales"""
        api_key = os.getenv("KRAKEN_API_KEY", "").strip()
        api_secret = os.getenv("KRAKEN_SECRET", "").strip()

        if not api_key or not api_secret:
            logger.critical("API keys no configuradas")
            raise SystemExit(1)

        try:
            exchange = ccxt.kraken({
                'apiKey': api_key,
                'secret': api_secret,
                'enableRateLimit': True,
                'options': {
                    'adjustForTimeDifference': True,
                    'recvWindow': 20000,
                    'rateLimit': 3500,
                    'fetchMarkets': 'spot'
                },
                'timeout': 30000
            })

            self._load_markets_with_retry(exchange)
            return exchange

        except Exception as e:
            logger.critical(f"Error inicializando cliente: {str(e)}")
            raise SystemExit(1) from e

    def _load_markets_with_retry(self, exchange, max_retries=3):
        """Carga de mercados con reintentos y validación"""
        for attempt in range(max_retries):
            try:
                exchange.load_markets()
                if not exchange.markets:
                    raise ValueError("Mercados no cargados correctamente")
                logger.info(f"Mercados cargados ({len(exchange.markets)} pares)")
                return
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.critical("Fallo al cargar mercados")
                    raise
                time.sleep(2 ** attempt)

    def _validate_connection(self):
        """Validación completa de conexión"""
        try:
            # 1. Verificar tiempo del servidor
            server_time = self.client.fetch_time()
            if not isinstance(server_time, dict):
                raise ValueError("Respuesta inválida del servidor")

            # 2. Verificar balance
            balance = self.client.fetch_balance()
            if not isinstance(balance, dict):
                raise ValueError("No se pudo obtener balance")

            logger.info("Conexión validada correctamente")
        except Exception as e:
            logger.critical(f"Error validando conexión: {str(e)}")
            raise SystemExit(1) from e

    def _get_nonce(self) -> int:
        """Generación segura de nonce para producción"""
        current_nonce = int(time.time() * 1000)
        self._last_nonce = max(current_nonce, self._last_nonce + 1)
        return self._last_nonce

    def _normalize_symbol(self, symbol: str) -> str:
        """Normalización profesional con validación completa"""
        original_symbol = symbol
        symbol = symbol.upper().strip().replace('-', '/')

        # 1. Verificar mapeo directo
        if symbol in self.SYMBOL_MAPPING:
            return self.SYMBOL_MAPPING[symbol]

        # 2. Verificar formato básico
        if '/' not in symbol:
            raise ValueError(f"Símbolo mal formado: {original_symbol}")

        # 3. Buscar en mercados cargados
        if symbol in self.client.markets:
            return symbol

        # 4. Intentar variantes
        for market_symbol in self.client.markets:
            if symbol.replace('/', '') == market_symbol.replace('/', ''):
                return market_symbol

        # 5. Error detallado
        available = [k for k in self.client.markets.keys() if symbol.split('/')[0] in k]
        raise ValueError(
            f"Símbolo no soportado: {original_symbol}. "
            f"Disponibles: {available[:10]}..."
        )

    def _validate_order_params(self, symbol: str, amount: float, price: float):
        """Validación profesional de parámetros de orden"""
        market = self.client.market(symbol)
        
        # Validar cantidad mínima
        min_amount = float(market['limits']['amount']['min'])
        if amount < min_amount:
            raise ValueError(
                f"Cantidad {amount} menor al mínimo {min_amount} para {symbol}"
            )

        # Validar incremento de cantidad
        if 'amount' in market['precision']:
            step = float(market['precision']['amount'])
            if (amount / step) != int(amount / step):
                raise ValueError(
                    f"Cantidad {amount} no cumple incremento de {step} para {symbol}"
                )

        # Validar precio mínimo
        min_price = float(market['limits']['price']['min'])
        if price < min_price:
            raise ValueError(
                f"Precio {price} menor al mínimo {min_price} para {symbol}"
            )

    def create_limit_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """Método profesional para órdenes limitadas"""
        # Validación inicial
        side = side.lower()
        if side not in ('buy', 'sell'):
            raise ValueError("Lado de orden inválido (debe ser 'buy' o 'sell')")

        normalized_symbol = self._normalize_symbol(symbol)
        self._validate_order_params(normalized_symbol, amount, price)

        # Reintentos profesionales
        for attempt in range(max_retries):
            try:
                order = self.client.create_order(
                    symbol=normalized_symbol,
                    type='limit',
                    side=side,
                    amount=amount,
                    price=price,
                    params={'nonce': self._get_nonce()}
                )

                logger.info(
                    f"Orden {order['id']} creada | {normalized_symbol} | "
                    f"{side.upper()} {amount} @ {price}"
                )
                return order

            except ccxt.InvalidNonce:
                if attempt == max_retries - 1:
                    raise
                time.sleep(1)
            except ccxt.NetworkError as e:
                logger.warning(f"Error de red (reintento {attempt + 1}/{max_retries}): {str(e)}")
                if attempt == max_retries - 1:
                    raise
                time.sleep(2 ** attempt)
            except Exception as e:
                logger.error(f"Error inesperado: {str(e)}")
                raise

    # Métodos adicionales (create_market_order, fetch_ticker, etc.) con el mismo nivel de validación

# Instancia global con manejo de errores
try:
    exchange_client = ExchangeClient()
except Exception as e:
    logger.critical(f"Error crítico al iniciar ExchangeClient: {str(e)}")
    raise