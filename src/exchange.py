import os
import time
import logging
import ccxt
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

class ExchangeClient:
    """Cliente mejorado para Kraken con todos los métodos necesarios"""
    
    def __init__(self):
        self.client = self._initialize_client()
        self._last_sync = 0
        self.time_delta = 0
        
    def _initialize_client(self) -> ccxt.kraken:
        """Configuración segura del cliente con validación de credenciales"""
        try:
            exchange = ccxt.kraken({
                'apiKey': os.getenv("KRAKEN_API_KEY"),
                'secret': os.getenv("KRAKEN_SECRET"),
                'enableRateLimit': True,
                'options': {
                    'adjustForTimeDifference': True,
                    'recvWindow': 15000  # 15 seg timeout
                },
                'nonce': self._nonce_generator()
            })
            
            self._force_time_sync(exchange)
            logger.info("Cliente Kraken inicializado | Server: %s", exchange.urls['api']['public'])
            return exchange
            
        except ccxt.AuthenticationError as e:
            logger.critical("Error de autenticación en Kraken. Verifica las API keys")
            raise SystemExit(1) from e

    def _nonce_generator(self):
        """Generador de nonce a prueba de colisiones"""
        last_nonce = int(time.time() * 1000)
        while True:
            current_time = int(time.time() * 1000)
            last_nonce = max(last_nonce + 1, current_time)
            yield last_nonce

    def _force_time_sync(self, client: ccxt.kraken):
        """Sincronización horaria con Kraken"""
        try:
            server_time = client.fetch_time()
            local_time = int(time.time() * 1000)
            self.time_delta = server_time - local_time
            logger.debug("Diferencia horaria con Kraken: %dms", self.time_delta)
        except ccxt.NetworkError as e:
            logger.error("Fallo en sincronización horaria: %s", str(e))
            raise

    def validate_connection(self) -> bool:
        """Verifica la conexión con Kraken"""
        try:
            self.client.fetch_time()
            logger.info("Conexión con Kraken verificada")
            return True
        except ccxt.NetworkError as e:
            logger.error("Error de red: %s", str(e))
            return False
            
    def validate_symbol(self, symbol: str) -> bool:
        """Valida si un símbolo existe en Kraken"""
        try:
            markets = self.client.load_markets()
            return symbol.upper().replace('-', '/') in markets
        except Exception as e:
            logger.error("Error validando símbolo: %s", str(e))
            return False

    def fetch_ticker(self, symbol: str) -> Dict:
        """Obtiene datos de mercado para un símbolo"""
        try:
            return self.client.fetch_ticker(symbol.upper().replace('-', '/'))
        except ccxt.NetworkError as e:
            logger.error("Error obteniendo ticker: %s", str(e))
            raise

    def create_limit_order(self, symbol: str, side: str, amount: float, price: float) -> Dict:
        """Crea una orden limitada"""
        try:
            return self.client.create_limit_order(
                symbol=symbol.upper().replace('-', '/'),
                side=side.lower(),
                amount=amount,
                price=price
            )
        except ccxt.InvalidOrder as e:
            logger.error("Orden inválida: %s", str(e))
            raise

    def create_market_order(self, symbol: str, side: str, amount: float) -> Dict:
        """Crea una orden de mercado"""
        try:
            return self.client.create_market_order(
                symbol=symbol.upper().replace('-', '/'),
                side=side.lower(),
                amount=amount
            )
        except ccxt.InsufficientFunds as e:
            logger.error("Fondos insuficientes: %s", str(e))
            raise

exchange_client = ExchangeClient()  # ¡Nota el nombre en minúsculas!        