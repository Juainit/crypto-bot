# trading_bot.py
import os
import time
import logging
import threading
from decimal import Decimal, getcontext
from typing import Dict, Optional, Tuple, Any
import ccxt
from flask import Flask, request, jsonify
from threading import Thread, Lock, Event
from functools import wraps

# =============================================
# CONFIGURACIÓN INICIAL
# =============================================
app = Flask(__name__)
getcontext().prec = 8  # Precisión decimal para operaciones

# Constantes configurables
CONFIG = {
    'INITIAL_CAPITAL': Decimal('40'),  # 40€ por operación
    'MIN_ORDER_SIZE': Decimal('10'),    # Mínimo 10€ por orden
    'FEE_RATE': Decimal('0.0026'),      # 0.26% fee en Kraken
    'DEFAULT_TRAILING': Decimal('0.02'), # 2% trailing stop
    'API_TIMEOUT': 30000,               # 30 segundos timeout
    'MAX_RETRIES': 3,                   # Reintentos para llamadas a API
}

# =============================================
# CLASE EXCHANGE CLIENT (INTEGRADA)
# =============================================
class ExchangeClient:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
            
        self._initialized = True
        self.logger = logging.getLogger('Exchange')
        self.client = self._init_client()
        self.markets = self._load_markets()

    def _init_client(self):
        """Inicialización segura del cliente de exchange"""
        try:
            kraken = ccxt.kraken({
                'apiKey': os.getenv('KRAKEN_API_KEY'),
                'secret': os.getenv('KRAKEN_SECRET'),
                'enableRateLimit': True,
                'timeout': CONFIG['API_TIMEOUT'],
                'options': {
                    'adjustForTimeDifference': True,
                    'recvWindow': 10000
                }
            })
            
            # Configuración crítica para producción
            kraken.nonce = lambda: int(time.time() * 1000)
            self._sync_exchange_time(kraken)
            return kraken
            
        except Exception as e:
            self.logger.critical(f"Init failed: {str(e)}")
            raise

    def _sync_exchange_time(self, client):
        """Sincronización horaria con el exchange"""
        try:
            server_time = client.fetch_time()
            local_time = int(time.time() * 1000)
            delta = server_time - local_time
            if abs(delta) > 1000:  # 1 segundo de diferencia
                self.logger.warning(f"Time delta detected: {delta}ms")
        except Exception as e:
            self.logger.error(f"Time sync failed: {str(e)}")

    def _load_markets(self):
        """Carga de mercados con reintentos"""
        for attempt in range(CONFIG['MAX_RETRIES']):
            try:
                markets = self.client.load_markets()
                self.logger.info(f"Loaded {len(markets)} trading pairs")
                return markets
            except Exception as e:
                if attempt == CONFIG['MAX_RETRIES'] - 1:
                    raise
                time.sleep(2 ** attempt)
                self.logger.warning(f"Retrying market load ({attempt + 1}/{CONFIG['MAX_RETRIES']})")

    def get_ticker(self, symbol: str) -> Dict:
        """Obtiene ticker con validación de símbolo"""
        try:
            if symbol not in self.markets:
                raise ValueError(f"Invalid symbol: {symbol}")
            return self.client.fetch_ticker(symbol)
        except Exception as e:
            self.logger.error(f"Ticker error: {str(e)}")
            raise

    def create_order(self, order_params: Dict) -> Dict:
        """Crea orden con validación de tamaño mínimo"""
        try:
            # Validación de tamaño mínimo
            if 'amount' in order_params and 'price' in order_params:
                order_value = Decimal(order_params['amount']) * Decimal(order_params['price'])
                if order_value < CONFIG['MIN_ORDER_SIZE']:
                    raise ValueError(f"Order size below minimum {CONFIG['MIN_ORDER_SIZE']}")

            return self.client.create_order(**order_params)
        except Exception as e:
            self.logger.error(f"Order failed: {str(e)}")
            raise

    def fetch_balance(self) -> Dict:
        """Obtiene balance con manejo de errores"""
        try:
            return self.client.fetch_balance()
        except Exception as e:
            self.logger.error(f"Balance error: {str(e)}")
            raise

# =============================================
# CLASE TRADING BOT (COMPLETA)
# =============================================
class TradingBot:
    def __init__(self):
        self.logger = logging.getLogger('TradingBot')
        self.exchange = ExchangeClient()  # Usa el singleton
        self._lock = Lock()
        self._shutdown_event = Event()
        self._reset_state()

    def _reset_state(self):
        """Reinicia el estado interno"""
        with self._lock:
            self.active_position = False
            self.current_symbol = None
            self.entry_price = Decimal('0')
            self.stop_price = Decimal('0')
            self.position_size = Decimal('0')
            self.take_profit = None

    def execute_buy(self, symbol: str, trailing_percent: Decimal) -> Tuple[bool, str]:
        """Ejecuta orden de compra con validaciones"""
        with self._lock:
            if self.active_position:
                return False, "Position already active"

            try:
                ticker = self.exchange.get_ticker(symbol)
                current_price = Decimal(str(ticker['ask']))
                amount = (CONFIG['INITIAL_CAPITAL'] / current_price).quantize(Decimal('0.00000001'))

                order = self.exchange.create_order({
                    'symbol': symbol,
                    'type': 'limit',
                    'side': 'buy',
                    'amount': float(amount),
                    'price': float(current_price)
                })

                # Actualizar estado
                self.active_position = True
                self.current_symbol = symbol
                self.entry_price = current_price
                self.stop_price = current_price * (1 - trailing_percent)
                self.position_size = amount

                # Iniciar gestión de órdenes
                Thread(
                    target=self._manage_position,
                    daemon=True,
                    name=f"PositionManager-{symbol}"
                ).start()

                return True, f"Buy order executed: {order['id']}"

            except Exception as e:
                self.logger.error(f"Buy failed: {str(e)}")
                return False, str(e)

    def _manage_position(self):
        """Gestiona la posición activa (trailing stop)"""
        while not self._shutdown_event.is_set() and self.active_position:
            try:
                with self._lock:
                    ticker = self.exchange.get_ticker(self.current_symbol)
                    current_price = Decimal(str(ticker['bid']))

                    # Actualizar trailing stop
                    new_stop = current_price * (1 - CONFIG['DEFAULT_TRAILING'])
                    if new_stop > self.stop_price:
                        self.stop_price = new_stop

                    # Verificar stop loss
                    if current_price <= self.stop_price:
                        self._execute_sell()
                        break

                time.sleep(60)  # Revisar cada minuto

            except Exception as e:
                self.logger.error(f"Position error: {str(e)}")
                time.sleep(120)

    def _execute_sell(self) -> Tuple[bool, str]:
        """Ejecuta orden de venta"""
        try:
            with self._lock:
                if not self.active_position:
                    return False, "No active position"

                balance = self.exchange.fetch_balance()
                currency = self.current_symbol.split('/')[0]
                amount = Decimal(str(balance['free'].get(currency, 0))).quantize(Decimal('0.00000001'))

                # Intentar orden limit primero
                try:
                    order = self.exchange.create_order({
                        'symbol': self.current_symbol,
                        'type': 'limit',
                        'side': 'sell',
                        'amount': float(amount),
                        'price': float(self.stop_price)
                    })
                except Exception:
                    # Fallback a market order
                    order = self.exchange.create_order({
                        'symbol': self.current_symbol,
                        'type': 'market',
                        'side': 'sell',
                        'amount': float(amount)
                    })

                self._reset_state()
                return True, f"Sell order executed: {order['id']}"

        except Exception as e:
            self.logger.error(f"Sell failed: {str(e)}")
            return False, str(e)

    def shutdown(self):
        """Apagado seguro del bot"""
        self._shutdown_event.set()
        if self.active_position:
            self._execute_sell()

# =============================================
# ENDPOINTS API WEB
# =============================================
def validate_webhook(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
            
        if 'action' not in data or 'symbol' not in data:
            return jsonify({"error": "Missing required fields"}), 400
            
        if data['action'].lower() == 'buy' and 'trailing_stop' not in data:
            return jsonify({"error": "Missing trailing_stop for buy"}), 400
            
        return f(*args, **kwargs)
    return wrapper

@app.route('/webhook', methods=['POST'])
@validate_webhook
def handle_webhook():
    try:
        data = request.get_json()
        symbol = data['symbol'].upper().replace('-', '/')
        
        if data['action'].lower() == 'buy':
            trailing = Decimal(data.get('trailing_stop', CONFIG['DEFAULT_TRAILING']))
            success, msg = bot.execute_buy(symbol, trailing)
            
            if success:
                return jsonify({"status": "success", "message": msg}), 200
            return jsonify({"error": msg}), 400
            
        return jsonify({"error": "Unsupported action"}), 400
        
    except Exception as e:
        app.logger.error(f"Webhook error: {str(e)}")
        return jsonify({"error": "Internal error"}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "running",
        "position_active": bot.active_position,
        "symbol": bot.current_symbol
    }), 200

# =============================================
# INICIALIZACIÓN
# =============================================
def setup_logging():
    """Configuración centralizada de logging"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('trading.log')
        ]
    )

def run_server():
    from waitress import serve
    port = int(os.getenv("PORT", 3000))
    serve(
        app,
        host="0.0.0.0",
        port=port,
        threads=4
    )

if __name__ == '__main__':
    setup_logging()
    bot = TradingBot()
    atexit.register(bot.shutdown)
    
    print("""
    ====================================
    🚀 TRADING BOT - PRODUCTION READY
    ====================================
    Exchange: Kraken
    Webhook: POST /webhook
    Health Check: GET /health
    ====================================
    """)
    
    run_server()