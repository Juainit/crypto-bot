from flask import Flask, request, jsonify
from threading import Thread, Lock, Event
from decimal import Decimal, getcontext
import logging
import os
import time
import atexit
from typing import Tuple, Optional, Dict, Any
import ccxt
from functools import wraps
from datetime import datetime, timedelta

# =============================================
# CONFIGURACIÓN INICIAL
# =============================================
app = Flask(__name__)
getcontext().prec = 8  # Precisión decimal para operaciones financieras

# Constantes
MAX_RETRIES = 3
RETRY_DELAY = 1
ORDER_TIMEOUT = 30000  # 30 segundos
DEFAULT_TRAILING = 0.02  # 2%
INITIAL_CAPITAL = Decimal('40')  # Capital inicial en EUR

# Configuración básica de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('TradingBot')

# =============================================
# DECORADORES
# =============================================
def synchronized(lock_name: str):
    """Decorador para sincronización thread-safe"""
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            lock = getattr(self, lock_name)
            with lock:
                return func(self, *args, **kwargs)
        return wrapper
    return decorator

def validate_webhook(f):
    """Middleware de validación para webhooks"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        data = request.get_json()
        if not data:
            return jsonify({"error": "No se proporcionaron datos"}), 400
        
        required = ['action', 'symbol']
        if not all(k in data for k in required):
            return jsonify({"error": f"Faltan campos requeridos: {required}"}), 400
        
        if data['action'].lower() == 'buy' and 'trailing_stop' not in data:
            return jsonify({"error": "Falta trailing_stop para compra"}), 400
            
        return f(*args, **kwargs)
    return wrapper

# =============================================
# CLASE PRINCIPAL DEL TRADING BOT
# =============================================
class TradingBot:
    def __init__(self):
        """Inicialización completa del bot con manejo robusto de errores"""
        # 1. Sistema de bloqueo y eventos
        self._lock = Lock()
        self._shutdown_event = Event()
        
        # 2. Estado del trading
        self._reset_trading_state()
        
        # 3. Conexión con el exchange
        self.exchange = self._init_exchange()
        
        # 4. Carga inicial de mercados
        self._load_markets()
        
        logger.info("Trading Bot inicializado correctamente")

    def _init_exchange(self):
        """Configuración robusta de la conexión con Kraken"""
        api_key = os.getenv('KRAKEN_API_KEY')
        secret = os.getenv('KRAKEN_SECRET')
        
        if not api_key or not secret:
            raise ValueError("Las credenciales de Kraken no están configuradas")
        
        exchange = ccxt.kraken({
            'apiKey': api_key,
            'secret': secret,
            'enableRateLimit': True,
            'timeout': ORDER_TIMEOUT,
            'rateLimit': 3000,
            'options': {
                'adjustForTimeDifference': True,
                'recvWindow': 10000
            }
        })
        
        # Solución definitiva para nonce
        exchange.nonce = self._create_nonce_generator()
        return exchange

    def _create_nonce_generator(self):
        """Generador de nonce robusto para Kraken"""
        last_nonce = int(time.time() * 1000)
        
        def generator():
            nonlocal last_nonce
            current = int(time.time() * 1000)
            last_nonce = current if current > last_nonce else last_nonce + 1
            return last_nonce
            
        return generator

    def _reset_trading_state(self):
        """Reinicia el estado de trading"""
        self.active_position = False
        self.current_symbol = None
        self.entry_price = None
        self.stop_price = None
        self.position_size = Decimal('0')
        self.take_profit = None
        self.last_order_id = None
        self.last_update = None
        self.current_capital = INITIAL_CAPITAL

    def _load_markets(self):
        """Carga los mercados disponibles con manejo de errores"""
        try:
            self.exchange.load_markets()
            logger.info("Mercados cargados correctamente")
        except Exception as e:
            logger.error(f"Error cargando mercados: {str(e)}")
            raise

    def _validate_symbol(self, symbol: str) -> bool:
        """Valida el formato del símbolo"""
        return (isinstance(symbol, str) and
                '/' in symbol and
                len(symbol.split('/')) == 2 and
                symbol in self.exchange.markets)

    def _safe_get_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Obtiene ticker con manejo de errores"""
        for attempt in range(MAX_RETRIES):
            try:
                return self.exchange.fetch_ticker(symbol)
            except ccxt.NetworkError as e:
                if attempt == MAX_RETRIES - 1:
                    raise
                time.sleep(RETRY_DELAY * (attempt + 1))
            except Exception as e:
                logger.error(f"Error obteniendo ticker: {str(e)}")
                return None

    def _get_min_order_size(self, symbol: str) -> Decimal:
        """Obtiene tamaño mínimo de orden"""
        try:
            market = self.exchange.market(symbol)
            return Decimal(str(market['limits']['amount']['min']))
        except Exception as e:
            logger.warning(f"Usando mínimo por defecto: {str(e)}")
            return Decimal('0.00000001')

    def _execute_with_retry(self, func, *args, **kwargs):
        """Ejecuta una función con reintentos para errores de API"""
        last_exception = None
        
        for attempt in range(MAX_RETRIES):
            try:
                # Regenerar nonce en cada intento
                self.exchange.nonce = self._create_nonce_generator()
                return func(*args, **kwargs)
            except ccxt.InvalidNonce as e:
                last_exception = e
                if attempt == MAX_RETRIES - 1:
                    break
                time.sleep(RETRY_DELAY * (attempt + 1))
            except ccxt.NetworkError as e:
                last_exception = e
                if attempt == MAX_RETRIES - 1:
                    break
                time.sleep(RETRY_DELAY * (attempt + 1))
            except Exception as e:
                last_exception = e
                break
                
        raise last_exception if last_exception else Exception("Error desconocido")

    @synchronized('_lock')
    def execute_buy(self, symbol: str, trailing_percent: float, take_profit: float = None) -> Tuple[bool, str]:
        """Ejecuta orden de compra con validaciones completas"""
        try:
            # Validaciones iniciales
            if not self._validate_symbol(symbol):
                return False, "Formato de símbolo inválido"
                
            if self.active_position:
                return False, "Ya existe una posición activa"
            
            # Obtener datos del mercado
            ticker = self._safe_get_ticker(symbol)
            if not ticker:
                return False, "Error obteniendo datos del mercado"
                
            current_price = Decimal(str(ticker['ask']))
            amount = (self.current_capital / current_price).quantize(Decimal('0.00000001'))
            
            # Validar tamaño mínimo
            min_amount = self._get_min_order_size(symbol)
            if amount < min_amount:
                return False, f"Cantidad menor al mínimo ({min_amount})"
            
            # Ejecutar orden con reintentos
            order = self._execute_with_retry(
                self.exchange.create_order,
                symbol=symbol,
                type='limit',
                side='buy',
                amount=float(amount),
                price=float(current_price),
                params={'timeout': ORDER_TIMEOUT}
            )
            
            # Actualizar estado
            self.active_position = True
            self.current_symbol = symbol
            self.entry_price = current_price
            self.stop_price = current_price * (1 - Decimal(str(trailing_percent)))
            self.position_size = amount
            self.take_profit = current_price * (1 + Decimal(str(take_profit))) if take_profit else None
            self.last_order_id = order['id']
            self.last_update = datetime.now()
            
            logger.info(
                f"COMPRA | {symbol} | "
                f"Precio: {current_price:.8f} | "
                f"Size: {amount:.8f} | "
                f"Stop: {self.stop_price:.8f}" +
                (f" | TP: {self.take_profit:.8f}" if take_profit else "")
            )
            
            return True, order['id']
        except Exception as e:
            logger.error(f"Error en compra: {str(e)}", exc_info=True)
            return False, f"Error interno: {str(e)}"

    @synchronized('_lock')
    def execute_sell(self) -> Tuple[bool, str]:
        """Ejecuta venta con fallback a mercado"""
        try:
            if not self.active_position:
                logger.warning("No hay posición activa")
                return False, "No hay posición activa"
            
            # Obtener balance
            balance = self._execute_with_retry(self.exchange.fetch_balance)
            currency = self.current_symbol.split('/')[0]
            amount = Decimal(str(balance['free'][currency])).quantize(Decimal('0.00000001'))
            
            # Intentar orden limit primero
            try:
                order = self._execute_with_retry(
                    self.exchange.create_order,
                    symbol=self.current_symbol,
                    type='limit',
                    side='sell',
                    amount=float(amount),
                    price=float(self.stop_price),
                    params={'timeout': ORDER_TIMEOUT}
                )
                logger.info(f"VENTA LIMITE | {order['id']}")
            except Exception:
                # Fallback a market order
                order = self._execute_with_retry(
                    self.exchange.create_order,
                    symbol=self.current_symbol,
                    type='market',
                    side='sell',
                    amount=float(amount),
                    params={'timeout': ORDER_TIMEOUT}
                )
                logger.warning(f"VENTA MERCADO | {order['id']}")
            
            # Calcular ganancias/pérdidas y actualizar capital
            ticker = self._safe_get_ticker(self.current_symbol)
            if ticker:
                current_price = Decimal(str(ticker['bid']))
                profit = (current_price - self.entry_price) * self.position_size
                self.current_capital += profit
                logger.info(f"Resultado operación: {profit:.2f} EUR | Capital actual: {self.current_capital:.2f} EUR")
            
            # Resetear estado
            self._reset_trading_state()
            return True, order['id']
        except Exception as e:
            logger.critical(f"Error en venta: {str(e)}", exc_info=True)
            return False, f"Error en venta: {str(e)}"

    def manage_orders(self):
        """Gestiona stops y toma de ganancias"""
        logger.info("Iniciando gestión de órdenes")
        
        while not self._shutdown_event.is_set():
            try:
                with self._lock:
                    if not self.active_position:
                        time.sleep(10)
                        continue
                    
                    # Verificar timeout de orden
                    if self.last_update and (datetime.now() - self.last_update) > timedelta(minutes=30):
                        logger.warning("Timeout de posición, cerrando...")
                        self.execute_sell()
                        continue
                    
                    ticker = self._safe_get_ticker(self.current_symbol)
                    if not ticker:
                        time.sleep(60)
                        continue
                        
                    current_price = Decimal(str(ticker['bid']))
                    
                    # Verificar stop loss
                    if current_price <= self.stop_price:
                        logger.info("Stop loss activado")
                        self.execute_sell()
                        continue
                    
                    # Verificar take profit
                    if self.take_profit and current_price >= self.take_profit:
                        logger.info("Take profit activado")
                        self.execute_sell()
                        continue
                    
                    # Ajustar trailing stop (solo si el precio sube)
                    new_stop = current_price * (1 - Decimal(str(DEFAULT_TRAILING)))
                    if new_stop > self.stop_price:
                        self.stop_price = new_stop
                        self.last_update = datetime.now()
                        logger.debug(f"Nuevo stop: {self.stop_price:.8f}")
                
                time.sleep(60)  # Verificar cada minuto
            except Exception as e:
                logger.error(f"Error en gestión de órdenes: {str(e)}")
                time.sleep(300)

    def shutdown(self):
        """Apagado seguro del bot"""
        logger.info("Iniciando apagado...")
        self._shutdown_event.set()
        
        if self.active_position:
            success, msg = self.execute_sell()
            if not success:
                logger.error(f"No se pudo cerrar posición: {msg}")
        
        logger.info("Bot detenido correctamente")

# =============================================
# ENDPOINTS API WEB
# =============================================
@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint de verificación de salud"""
    return jsonify({
        "status": "running",
        "timestamp": datetime.now().isoformat(),
        "position_active": bot.active_position,
        "symbol": bot.current_symbol,
        "current_capital": float(bot.current_capital)
    }), 200

@app.route('/webhook', methods=['POST'])
@validate_webhook
def handle_webhook():
    """Endpoint principal para trading"""
    try:
        data = request.get_json()
        symbol = data['symbol'].upper().replace('-', '/')
        
        if data['action'].lower() == 'buy':
            trailing = float(data.get('trailing_stop', DEFAULT_TRAILING))
            take_profit = float(data.get('take_profit')) if 'take_profit' in data else None
            
            success, response = bot.execute_buy(
                symbol,
                trailing_percent=trailing,
                take_profit=take_profit
            )
            
            if success:
                Thread(
                    target=bot.manage_orders,
                    daemon=True,
                    name=f"OrderManager-{symbol}"
                ).start()
                
                return jsonify({
                    "status": "success",
                    "order_id": response,
                    "symbol": symbol,
                    "trailing_stop": trailing,
                    "take_profit": take_profit,
                    "current_capital": float(bot.current_capital)
                }), 200
                
            return jsonify({"error": response}), 400
            
        elif data['action'].lower() == 'sell':
            success, response = bot.execute_sell()
            return jsonify({
                "status": "success" if success else "error",
                "message": response,
                "current_capital": float(bot.current_capital)
            }), 200 if success else 400
            
        return jsonify({"error": "Acción no soportada"}), 400
    except Exception as e:
        logger.error(f"Error en webhook: {str(e)}", exc_info=True)
        return jsonify({"error": "Error interno del servidor"}), 500

# =============================================
# INICIALIZACIÓN Y EJECUCIÓN
# =============================================
def run_server():
    """Inicia el servidor de producción"""
    from waitress import serve
    
    port = int(os.getenv("PORT", 3000))
    workers = int(os.getenv("WORKERS", 4))
    
    logger.info(f"Iniciando servidor en puerto {port} con {workers} workers")
    
    serve(
        app,
        host="0.0.0.0",
        port=port,
        threads=workers,
        channel_timeout=60
    )

# Instancia global del bot
bot = TradingBot()
atexit.register(bot.shutdown)

if __name__ == '__main__':
    print("""
    ====================================
    🚀 TRADING BOT - MODO PRODUCCIÓN
    ====================================
    Exchange: Kraken
    Webhook: POST /webhook
    Health Check: GET /health
    ====================================
    """)
    
    run_server()