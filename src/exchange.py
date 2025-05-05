import os
import time
import logging
import ccxt
from decimal import Decimal, ROUND_UP, ROUND_DOWN
from typing import Dict, Optional, Tuple, Any

logger = logging.getLogger("KrakenBot")  
logger.setLevel(logging.INFO)

# Configura un handler básico si no existe
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
    logger.addHandler(handler)

class ExchangeClient:
    """Cliente profesional para Kraken con manejo robusto de errores"""
    
    def __init__(self):
        self.client = self._initialize_client()
        self._last_market_load = 0
        self.time_delta = 0
        
    def _initialize_client(self) -> ccxt.kraken:
        """Configuración segura del cliente con validación de credenciales"""
        try:
            exchange = ccxt.kraken({
                'apiKey': os.getenv("KRAKEN_API_KEY", "").strip(),
                'secret': os.getenv("KRAKEN_SECRET", "").strip(),
                'enableRateLimit': True,
                'options': {
                    'adjustForTimeDifference': True,
                    'recvWindow': 15000,
                    'rateLimit': 3000,
                    'fetchMarkets': 'spot'  # Nueva opción crítica [4]
                }
            })
            exchange.load_markets()  # Precarga los mercados
            self._force_time_sync(exchange)
            logger.info("Cliente Kraken inicializado | Server: %s", exchange.urls['api']['public'])
            return exchange
            
        except ccxt.AuthenticationError as e:
            logger.critical("Error de autenticación: Verifica las API keys")
            raise SystemExit(1) from e
        except Exception as e:
            logger.critical("Error inicializando cliente: %s", str(e))
            raise

    def _nonce_generator(self):
        """Generador compatible con Kraken"""
        last_nonce = int(time.time() + self.time_delta) * 1000
        while True:
            yield last_nonce + 1

    def _force_time_sync(self, client: ccxt.kraken):
        """Sincronización horaria robusta con manejo de errores"""
        try:
            # 1. Obtener respuesta de la API
            response = client.fetch_time()
            
            # 2. Debug: Registrar respuesta completa
            logger.debug(f"Respuesta de Kraken: {response}")
            
            # 3. Validar estructura de respuesta
            if not isinstance(response, dict):
                raise ValueError("La respuesta no es un diccionario")
                
            if 'error' in response and response['error']:
                raise ValueError(f"Error de Kraken: {response['error']}")
                
            if 'result' not in response or 'unixtime' not in response['result']:
                raise ValueError("Estructura de respuesta inválida")
            
            # 4. Extraer timestamp
            server_time = response['result']['unixtime']
            local_time = int(time.time())
            
            # 5. Calcular diferencia
            self.time_delta = server_time - local_time
            logger.info(f"Sincronización exitosa. Diferencia: {self.time_delta}s")
            
        except Exception as e:
            logger.error(f"Fallo en sincronización: {str(e)}")
            # Modo fallback: continuar sin sincronización
            self.time_delta = 0
            logger.warning("Usando diferencia horaria = 0 (modo fallback)")

    def validate_connection(self) -> bool:
        """Verifica la conexión con Kraken"""
        try:
            self.client.fetch_time()
            logger.info("Conexión con Kraken verificada")
            return True
        except ccxt.NetworkError as e:
            logger.error("Error de red: %s", str(e))
            return False
            
    def validate_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Versión definitiva validada con Kraken [4][6]"""
        try:
            # 1. Forzar recarga de mercados si hay error
            if not self.client.markets or symbol not in self.client.markets:
                self.client.load_markets(reload=True)
            
            # 2. Usar ID exacto del mercado
            market = self.client.market(symbol)
            
            # 3. Log de diagnóstico crítico
            logger.debug("Mercados cargados: %s", list(self.client.markets.keys())[:20])
            
            return {
                'id': market['id'],
                'symbol': market['symbol'],  # ← Usar símbolo oficial de Kraken
                'limits': market['limits'],
                'precision': market['precision'],
                'active': market['active']
            }
            
        except ccxt.BadSymbol:
            logger.error("PAR NO ENCONTRADO. Requiere: 'XREPZEUR' | Disponibles: %s", 
                    [k for k in self.client.markets.keys() if 'XREP' in k])
            return None

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        """Obtiene datos de mercado para un símbolo (ACTUALIZADO) [4]"""
        try:
            normalized_symbol = self._normalize_symbol(symbol)
            return self.client.fetch_ticker(normalized_symbol)
        except ccxt.NetworkError as e:
            logger.error("Error obteniendo ticker: %s", str(e))
            raise
        except ccxt.BadSymbol as e:
            self.client.load_markets(reload=True)  # Recarga mercados
            return self.client.fetch_ticker(normalized_symbol)
        except Exception as e:
            logger.error("Error inesperado en fetch_ticker: %s", str(e))
            raise

    def create_limit_order(self, symbol: str, side: str, amount: float, price: float) -> Dict[str, Any]:
        """Crea una orden limitada con validación mejorada"""
        try:
            normalized_symbol = self._normalize_symbol(symbol)
            return self.client.create_limit_order(
                symbol=normalized_symbol,
                side=side.lower(),
                amount=self._format_amount(amount, normalized_symbol),
                price=self._format_price(price, normalized_symbol)
            )
        except ccxt.InvalidOrder as e:
            logger.error("Orden inválida: %s", str(e))
            raise
        except Exception as e:
            logger.error("Error inesperado en create_limit_order: %s", str(e))
            raise

    def create_market_order(self, symbol: str, side: str, amount: float) -> Dict[str, Any]:
        """Crea una orden de mercado con validación mejorada"""
        try:
            normalized_symbol = self._normalize_symbol(symbol)
            return self.client.create_market_order(
                symbol=normalized_symbol,
                side=side.lower(),
                amount=self._format_amount(amount, normalized_symbol)
            )
        except ccxt.InsufficientFunds as e:
            logger.error("Fondos insuficientes: %s", str(e))
            raise
        except Exception as e:
            logger.error("Error inesperado en create_market_order: %s", str(e))
            raise

    def _normalize_symbol(self, symbol: str) -> str:
        """Normalización profesional para pares de Kraken [4][6]"""
        # Mapeo directo de símbolos complejos
        kraken_symbols = {
            'REP/EUR': 'XREPZEUR',
            'XREPZEUR': 'XREPZEUR',  # ← ¡Clave añadida!
            'BTC/EUR': 'XXBTZEUR',
            'ETH/EUR': 'XETHZEUR'
        }
    
        symbol = symbol.upper().replace(' ', '').replace('-', '')
    
        # Forzar recarga de mercados si no se encuentra
        if symbol not in self.client.markets:
            self.client.load_markets(reload=True)
    
        return kraken_symbols.get(symbol, symbol)

    def _format_amount(self, amount: float, symbol: str) -> float:
        try:
            market = self.client.market(symbol)
            
            # Obtener precisión correctamente
            precision = market['precision']['amount']
            if isinstance(precision, (list, tuple)):
                precision = precision[1]  # Índice 1 para precisión de cantidad
            
            # Convertir a Decimal y redondear
            amount_dec = Decimal(str(amount)).quantize(
                Decimal(10) ** -int(precision),
                rounding=ROUND_DOWN
            )
            
            return float(amount_dec)
            
        except Exception as e:
            logger.error(f"Error formateando cantidad: {str(e)}")
            raise

    def _format_price(self, price: float, symbol: str) -> float:
        """Ajuste profesional de precisión"""
        market = self.client.market(symbol)
        precision = int(market['precision']['price'])  # ← Conversión crítica
        return float(round(Decimal(str(price)), precision))

# Instancia global para uso en otros módulos
exchange_client = ExchangeClient()