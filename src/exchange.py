# exchange.py
import os
import ccxt
import time
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger("ExchangeClient")

class ExchangeClient:
    """Cliente mejorado para Kraken con:
    - Sincronización temporal automática
    - Manejo robusto de errores
    - Logging detallado
    """
    
    def __init__(self):
        self.client = self._initialize_client()
        self._last_sync = 0
        
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
            logger.critical("Error de autenticación en Kraken. Verifica las API keys [4]")
            raise SystemExit(1) from e
    def validate_connection(self):
        """Verifica la conexión con Kraken"""
        try:
            self.client.fetch_time()  # Llamada básica de prueba
            logger.info("Conexión con Kraken verificada")
            return True
        except ccxt.NetworkError as e:
            logger.error("Error de red: %s", str(e))
            return False
            
    def validate_symbol(self, symbol: str) -> bool:
        try:
            markets = self.client.load_markets()
            return symbol in markets
        except Exception as e:
            logger.error(f"Error validando símbolo: {str(e)}")
            return False
            
    def _nonce_generator(self):
        """Generador de nonce a prueba de colisiones [5]"""
        last_nonce = int(time.time() * 1000)
        while True:
            current_time = int(time.time() * 1000)
            last_nonce = max(last_nonce + 1, current_time)
            yield last_nonce

    def _force_time_sync(self, client: ccxt.kraken):
        """Sincronización horaria estricta con Kraken [5]"""
        try:
            server_time = client.fetch_time()
            local_time = int(time.time() * 1000)
            self.time_delta = server_time - local_time
            logger.debug("Sincronización horaria | Diferencia: %dms", self.time_delta)
            
            if abs(self.time_delta) > 5000:  # 5 seg diferencia
                logger.warning("Gran desincronía temporal con Kraken")
                
        except ccxt.NetworkError as e:
            logger.error("Fallo sincronización: %s", str(e))
            raise

    def create_order(self, symbol: str, order_type: str, side: str, amount: float, price: float, params: Dict) -> Optional[Dict]:
        """Ejecuta órdenes con manejo profesional de errores"""
        try:
            # Resincronizar cada 5 min [5]
            if (time.time() - self._last_sync) > 300:
                self._force_time_sync(self.client)
                self._last_sync = time.time()
                
            logger.info("Enviando orden: %s %s %s @ %s", symbol, order_type.upper(), side.upper(), price)
            
            order = self.client.create_order(
                symbol=symbol,
                type=order_type,
                side=side,
                amount=amount,
                price=price,
                params=params
            )
            
            logger.debug("Respuesta Kraken: %s", order)
            self._validate_order_response(order)
            return order
            
        except ccxt.InsufficientFunds as e:
            logger.error("Fondos insuficientes: %s", str(e))
            raise
        except ccxt.NetworkError as e:
            logger.error("Error de red: %s", str(e))
            raise
        except Exception as e:
            logger.critical("Error inesperado: %s", str(e), exc_info=True)
            raise

    def _validate_order_response(self, response: Dict):
        """Validación profesional de respuestas [7]"""
        required_fields = ['id', 'status', 'filled']
        for field in required_fields:
            if field not in response:
                raise ValueError(f"Respuesta inválida de Kraken. Falta campo: {field}")
                
        if response['status'] not in ['closed', 'open']:
            raise ValueError(f"Estado de orden no reconocido: {response['status']}")

# Instancia global preconfigurada
exchange_client = ExchangeClient()