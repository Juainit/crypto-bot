from flask import Flask, request, jsonify
from threading import Thread, Lock
from decimal import Decimal, getcontext
import logging
import os
import time
import atexit
from typing import Tuple, Optional, Dict
from ccxt import kraken
from functools import wraps

app = Flask(__name__)

class TradingBot:
    def __init__(self):
        """Inicialización con configuración mejorada"""
        self.lock = Lock()
        self.active_position = False
        self.current_symbol = None
        self.stop_price = None
        self.entry_price = None
        self.position_size = Decimal('0')
        
        # Configuración mejorada del exchange
        self.exchange = kraken({
            'apiKey': os.getenv('KRAKEN_API_KEY'),
            'secret': os.getenv('KRAKEN_SECRET'),
            'enableRateLimit': True,
            'timeout': 30000,  # 30 segundos timeout
            'rateLimit': 3000   # Límite de llamadas
        })
        
        self.logger = self._setup_logger()
        getcontext().prec = 8  # Precisión decimal de 8 dígitos

    def _setup_logger(self):
        """Configuración avanzada de logging"""
        logger = logging.getLogger('TradingBot')
        logger.setLevel(logging.INFO)
        
        # Formato profesional
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
        )
        
        # Handler para consola
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        
        # Handler para archivo
        fh = logging.FileHandler('trading_bot.log')
        fh.setFormatter(formatter)
        
        logger.addHandler(ch)
        logger.addHandler(fh)
        return logger

    def synchronized(lock):
        """Decorador para sincronización de métodos"""
        def wrapper(f):
            @wraps(f)
            def inner_wrapper(*args, **kw):
                with lock:
                    return f(*args, **kw)
            return inner_wrapper
        return wrapper

    @synchronized(lock)
    def execute_buy(self, symbol: str, trailing_percent: float) -> Tuple[bool, str]:
        """Ejecuta orden de compra con validación mejorada"""
        try:
            if self.active_position:
                self.logger.warning(f"Posición activa en {self.current_symbol}")
                return False, "Posición ya abierta"

            # Validación de símbolo
            if not self._validate_symbol(symbol):
                return False, "Símbolo inválido"

            # Obtener ticker con manejo de errores
            ticker = self._safe_get_ticker(symbol)
            if not ticker:
                return False, "Error obteniendo precio"

            current_price = Decimal(str(ticker['ask']))
            amount = (Decimal('40') / current_price).quantize(Decimal('0.00000001'))
            
            # Validación de cantidad mínima
            min_amount = self._get_min_order_size(symbol)
            if amount < min_amount:
                return False, f"Cantidad menor al mínimo ({min_amount})"

            # Ejecutar orden con doble verificación
            order = self.exchange.create_order(
                symbol=symbol,
                type='limit',
                side='buy',
                amount=float(amount),
                price=float(current_price),
                params={
                    'timeout': 30000,
                    'validate': True  # Validación en el exchange
                }
            )

            # Actualizar estado
            self.active_position = True
            self.current_symbol = symbol
            self.entry_price = current_price
            self.stop_price = current_price * (1 - Decimal(str(trailing_percent)))
            self.position_size = amount
            
            self.logger.info(
                f"Compra ejecutada | {symbol} | "
                f"Precio: {current_price:.8f} | "
                f"Cantidad: {amount:.8f}"
            )
            
            return True, order['id']

        except Exception as e:
            self.logger.error(f"Error en execute_buy: {str(e)}", exc_info=True)
            return False, f"Error interno: {str(e)}"

    def _safe_get_ticker(self, symbol: str) -> Optional[Dict]:
        """Obtiene ticker con manejo robusto de errores"""
        try:
            return self.exchange.fetch_ticker(symbol)
        except Exception as e:
            self.logger.error(f"Error obteniendo ticker: {str(e)}")
            return None

    def _validate_symbol(self, symbol: str) -> bool:
        """Valida formato del símbolo"""
        return isinstance(symbol, str) and ('/' in symbol) and (len(symbol.split('/')) == 2)

    def _get_min_order_size(self, symbol: str) -> Decimal:
        """Obtiene el tamaño mínimo de orden para el par"""
        try:
            markets = self.exchange.load_markets()
            return Decimal(str(markets[symbol]['limits']['amount']['min']))
        except:
            return Decimal('0.00000001')  # Valor por defecto

# ... (Resto de métodos de la clase con las mismas mejoras)

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
            return jsonify({"status": "error", "message": "Invalid trailing stop"}), 400
            
        return f(*args, **kwargs)
    return wrapper

@app.route('/webhook', methods=['POST'])
@validate_webhook
def handle_webhook():
    """Endpoint mejorado para señales de trading"""
    try:
        data = request.get_json()
        symbol = data['symbol'].upper().replace('-', '/')
        
        if data['action'].lower() == 'buy':
            success, msg = bot.execute_buy(symbol, float(data['trailing_stop']))
            
            if success:
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
        app.logger.error(f"Error en webhook: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": "Internal server error"}), 500

def run_server():
    """Inicia servidor de producción optimizado"""
    from waitress import serve
    port = int(os.getenv("PORT", 3000))
    
    # Configuración profesional para producción
    serve(
        app,
        host="0.0.0.0",
        port=port,
        threads=8,  # Pool de threads optimizado
        channel_timeout=60  # Timeout de conexiones
    )

if __name__ == '__main__':
    bot = TradingBot()
    
    print("""
    ====================================
    🚀 CRYPTO TRADING BOT - PRODUCTION
    ====================================
    Versión: 2.1.0
    Exchange: Kraken
    Capital inicial: 40€
    Timeout operaciones: 30s
    Endpoint: POST /webhook
    ====================================
    """)
    
    run_server()