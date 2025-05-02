from flask import Flask, request, jsonify
from threading import Thread, Lock
from decimal import Decimal, getcontext
import logging
import os
import time
import atexit
from typing import Tuple, Optional, Dict, Any
from ccxt import kraken
from functools import wraps

app = Flask(__name__)

# ======================
# DECORADOR SYNCHRONIZED
# ======================
def synchronized(lock_name: str):
    """Decorador thread-safe que obtiene el lock por nombre"""
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            lock = getattr(self, lock_name)
            with lock:
                return func(self, *args, **kwargs)
        return wrapper
    return decorator

# ===================
# CLASE TRADING BOT
# ===================
class TradingBot:
    def __init__(self):
        """Inicialización completa del bot"""
        # 1. Primero inicializamos el Lock
        self._lock = Lock()  # Atributo interno con underscore
        
        # 2. Estado del trading
        self.active_position = False
        self.current_symbol = None
        self.stop_price = None
        self.entry_price = None
        self.position_size = Decimal('0')
        self._shutdown_event = Event()
        
        # 3. Configuración del exchange Kraken
        self.exchange = kraken({
            'apiKey': os.getenv('KRAKEN_API_KEY'),
            'secret': os.getenv('KRAKEN_SECRET'),
            'enableRateLimit': True,
            'timeout': 30000,  # 30 segundos
            'rateLimit': 3000   # Límite de llamadas
        })
        
        # 4. Precisión decimal
        getcontext().prec = 8
        
        # 5. Configuración de logging
        self.logger = self._setup_logger()
        
        # 6. Cargar mercados al iniciar
        self._load_markets()

    def _setup_logger(self):
        """Configura logging profesional"""
        logger = logging.getLogger('TradingBot')
        logger.setLevel(logging.INFO)
        
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
        )
        
        # Handler para consola
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        
        # Handler para archivo
        fh = logging.FileHandler('trading.log')
        fh.setFormatter(formatter)
        
        logger.addHandler(ch)
        logger.addHandler(fh)
        return logger

    def _load_markets(self):
        """Carga los mercados disponibles"""
        try:
            self.exchange.load_markets()
            self.logger.info("Mercados cargados correctamente")
        except Exception as e:
            self.logger.error(f"Error cargando mercados: {str(e)}")
            raise

    @synchronized('_lock')
    def execute_buy(self, symbol: str, trailing_percent: float) -> Tuple[bool, str]:
        """Ejecuta orden de compra con validación mejorada"""
        try:
            # Validación de posición existente
            if self.active_position:
                msg = f"Posición activa en {self.current_symbol}"
                self.logger.warning(msg)
                return False, msg

            # Validación de símbolo
            if not self._validate_symbol(symbol):
                return False, "Formato de símbolo inválido (ej: BTC/EUR)"

            # Obtener ticker
            ticker = self._safe_get_ticker(symbol)
            if not ticker:
                return False, "Error obteniendo datos del mercado"

            current_price = Decimal(str(ticker['ask']))
            amount = (Decimal('40') / current_price).quantize(Decimal('0.00000001'))
            
            # Validar cantidad mínima
            min_amount = self._get_min_order_size(symbol)
            if amount < min_amount:
                msg = f"Cantidad {amount} menor al mínimo {min_amount}"
                return False, msg

            # Ejecutar orden
            order = self.exchange.create_order(
                symbol=symbol,
                type='limit',
                side='buy',
                amount=float(amount),
                price=float(current_price),
                params={
                    'timeout': 30000,
                    'validate': True
                }
            )

            # Actualizar estado
            self.active_position = True
            self.current_symbol = symbol
            self.entry_price = current_price
            self.stop_price = current_price * (1 - Decimal(str(trailing_percent)))
            self.position_size = amount
            
            self.logger.info(
                f"COMPRA | {symbol} | "
                f"Precio: {current_price:.8f} | "
                f"Cantidad: {amount:.8f} | "
                f"Stop: {self.stop_price:.8f}"
            )
            
            return True, order['id']

        except Exception as e:
            self.logger.error(f"Error en compra: {str(e)}", exc_info=True)
            return False, f"Error interno: {str(e)}"

    @synchronized('_lock')
    def execute_sell(self) -> bool:
        """Ejecuta venta con fallback a mercado"""
        try:
            if not self.active_position:
                self.logger.warning("No hay posición activa para vender")
                return False

            # Obtener balance
            balance = self.exchange.fetch_balance()
            currency = self.current_symbol.split('/')[0]
            amount = Decimal(str(balance['free'][currency])).quantize(Decimal('0.00000001'))
            
            # 1. Intento con orden limit
            try:
                order = self.exchange.create_order(
                    symbol=self.current_symbol,
                    type='limit',
                    side='sell',
                    amount=float(amount),
                    price=float(self.stop_price),
                    params={'timeout': 30000}
                )
                self.logger.info(f"VENTA LIMITE | {order['id']}")
            except Exception as e:
                # 2. Fallback a market order
                order = self.exchange.create_order(
                    symbol=self.current_symbol,
                    type='market',
                    side='sell',
                    amount=float(amount),
                    params={'timeout': 30000}
                )
                self.logger.warning(f"VENTA MERCADO | {order['id']}")

            # Actualizar estado
            self.active_position = False
            self.current_symbol = None
            return True

        except Exception as e:
            self.logger.critical(f"Error en venta: {str(e)}", exc_info=True)
            return False

    def manage_trailing_stop(self):
        """Gestión activa del trailing stop"""
        while not self._shutdown_event.is_set() and self.active_position:
            try:
                # Usamos bloque with para el lock
                with self._lock:
                    if not self.active_position:
                        break

                    ticker = self.exchange.fetch_ticker(self.current_symbol)
                    current_price = Decimal(str(ticker['bid']))
                    
                    # Actualizar stop
                    new_stop = current_price * (1 - Decimal('0.02'))  # 2% trailing
                    if new_stop > self.stop_price:
                        self.stop_price = new_stop
                        self.logger.debug(f"Stop actualizado: {self.stop_price:.8f}")
                    
                    # Verificar activación
                    if current_price <= self.stop_price:
                        self.execute_sell()
                        break

                time.sleep(60)  # Verificar cada minuto

            except Exception as e:
                self.logger.error(f"Error en trailing stop: {str(e)}")
                time.sleep(300)  # Esperar 5 minutos ante errores

    def shutdown(self):
        """Apagado seguro del bot"""
        self._shutdown_event.set()
        self.logger.info("Bot apagado correctamente")

    def _validate_symbol(self, symbol: str) -> bool:
        """Valida formato del símbolo"""
        return (isinstance(symbol, str) and 
                '/' in symbol and 
                len(symbol.split('/')) == 2)

    def _safe_get_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Obtiene ticker con manejo de errores"""
        try:
            return self.exchange.fetch_ticker(symbol)
        except Exception as e:
            self.logger.error(f"Error obteniendo ticker: {str(e)}")
            return None

    def _get_min_order_size(self, symbol: str) -> Decimal:
        """Obtiene tamaño mínimo de orden para el par"""
        try:
            market = self.exchange.market(symbol)
            return Decimal(str(market['limits']['amount']['min']))
        except Exception as e:
            self.logger.warning(f"Usando mínimo por defecto: {str(e)}")
            return Decimal('0.00000001')  # Valor por defecto seguro

# ======================
# CONFIGURACIÓN WEBHOOK
# ======================
def validate_webhook(f):
    """Decorador para validación de webhooks"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        data = request.get_json()
        
        if not data:
            return jsonify({"status": "error", "message": "No data provided"}), 400
            
        required = ['action', 'symbol', 'trailing_stop']
        if not all(k in data for k in required):
            return jsonify({"status": "error", "message": "Missing required fields"}), 400
            
        try:
            trailing = float(data['trailing_stop'])
            if not (0 < trailing < 1):
                raise ValueError
        except:
            return jsonify({"status": "error", "message": "Invalid trailing stop (0-1)"}), 400
            
        return f(*args, **kwargs)
    return wrapper

@app.route('/webhook', methods=['POST'])
@validate_webhook
def handle_webhook():
    """Endpoint principal para señales de trading"""
    try:
        data = request.get_json()
        symbol = data['symbol'].upper().replace('-', '/')
        
        if data['action'].lower() == 'buy':
            success, msg = bot.execute_buy(symbol, float(data['trailing_stop']))
            
            if success:
                # Iniciar trailing stop en thread separado
                Thread(
                    target=bot.manage_trailing_stop,
                    daemon=True,
                    name=f"TrailingStop-{symbol}"
                ).start()
                
                return jsonify({
                    "status": "success",
                    "order_id": msg,
                    "symbol": symbol,
                    "trailing_stop": data['trailing_stop']
                }), 200
                
            return jsonify({"status": "error", "message": msg}), 400
            
        return jsonify({"status": "ignored", "message": "Invalid action"}), 400

    except Exception as e:
        app.logger.error(f"Webhook error: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": "Internal server error"}), 500

# ======================
# INICIALIZACIÓN
# ======================
def run_server():
    """Inicia servidor de producción"""
    from waitress import serve
    port = int(os.getenv("PORT", 3000))
    
    serve(
        app,
        host="0.0.0.0",
        port=port,
        threads=8,
        channel_timeout=60
    )

# Instancia global del bot
bot = TradingBot()

# Manejo de shutdown
atexit.register(bot.shutdown)

if __name__ == '__main__':
    print("""
    ====================================
    🚀 CRYPTO TRADING BOT - PRODUCTION
    ====================================
    Exchange: Kraken
    Timeout: 30 segundos
    Endpoint: POST /webhook
    ====================================
    """)
    
    run_server()