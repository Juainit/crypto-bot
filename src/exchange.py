import ccxt
import logging
import time
from typing import Dict, Optional
from decimal import Decimal
from src.config import config  # Importamos la configuración centralizada

class ExchangeClient:
    """
    Cliente de intercambio robusto para Kraken con:
    - Manejo avanzado de nonce
    - Sincronización horaria
    - Reintentos automáticos
    """
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.client = self._initialize_client()
        self.markets = self._load_markets()
        
    def _initialize_client(self) -> ccxt.kraken:
        """Configuración segura del cliente de intercambio"""
        exchange = ccxt.kraken({
            'apiKey': config.KRAKEN_API_KEY,
            'secret': config.KRAKEN_SECRET,
            'enableRateLimit': True,
            'options': {
                'adjustForTimeDifference': True,
                'recvWindow': 10000
            },
            'nonce': self._create_nonce_generator()  # Generador robusto
        })
        
        self._sync_exchange_time(exchange)  # Sincronización inicial
        return exchange

    def _create_nonce_generator(self):
        """Generador de nonce inmune a desincronización temporal"""
        last_nonce = int(time.time() * 1000)
        
        def generator():
            nonlocal last_nonce
            current = int(time.time() * 1000)
            last_nonce = current if current > last_nonce else last_nonce + 1
            return last_nonce
            
        return generator

    def _sync_exchange_time(self, client: ccxt.kraken):
        """Sincronización horaria con el servidor de Kraken"""
        try:
            server_time = client.fetch_time()
            local_time = int(time.time() * 1000)
            delta = server_time - local_time
            if abs(delta) > 1000:  # 1 segundo de diferencia
                self.logger.warning(f"Desincronía temporal detectada: {delta}ms")
        except Exception as e:
            self.logger.error(f"Error sincronizando tiempo: {str(e)}")
            raise

    def _load_markets(self):
        """Carga los mercados disponibles con reintentos"""
        for attempt in range(3):
            try:
                markets = self.client.load_markets()
                self.logger.info(f"Mercados cargados ({len(markets)} pares)")
                return markets
            except ccxt.NetworkError as e:
                if attempt == 2:
                    raise
                time.sleep(1.5 ** attempt)

    def get_balance(self) -> Dict:
        """Obtiene balance con manejo profesional de errores"""
        try:
            balance = self.client.fetch_balance()
            return {
                'free': balance['free'],
                'used': balance['used'],
                'total': balance['total']
            }
        except ccxt.NetworkError as e:
            self.logger.error(f"Error de red: {str(e)}")
            raise
        except ccxt.ExchangeError as e:
            self.logger.error(f"Error del exchange: {str(e)}")
            raise

    def create_order(self, order_params: Dict) -> Optional[Dict]:
        """
        Crea órdenes con validación de tamaño mínimo y gestión de tarifas
        """
        try:
            # Validación avanzada del tamaño de orden
            market = self.client.market(order_params['symbol'])
            min_amount = Decimal(str(market['limits']['amount']['min']))
            
            if Decimal(str(order_params['amount'])) < min_amount:
                self.logger.warning(
                    f"Orden muy pequeña: {order_params['amount']} < {min_amount}"
                )
                return None

            # Sincronización previa a la operación
            self._sync_exchange_time(self.client)
            
            return self.client.create_order(**order_params)
            
        except ccxt.InvalidNonce as e:
            self.logger.critical(f"Error de nonce: {str(e)}")
            raise
        except ccxt.NetworkError as e:
            self.logger.error(f"Error de red: {str(e)}")
            return None
        except Exception as e:
            self.logger.error(f"Error inesperado: {str(e)}", exc_info=True)
            raise

# Instancia preconfigurada para uso global
exchange_client = ExchangeClient()