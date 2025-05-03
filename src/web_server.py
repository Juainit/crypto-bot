import os
import time
import atexit
import logging
from decimal import Decimal, getcontext
from threading import Thread, Lock, Event
from functools import wraps
from typing import Dict, Optional, Tuple

from flask import Flask, request, jsonify
import ccxt
from src.config import config
from exchange import exchange_client  # Cliente de exchange corregido

# =============================================
# CONFIGURACIÓN GLOBAL
# =============================================
app = Flask(__name__)
getcontext().prec = 8  # Precisión decimal para operaciones financieras

# Configuración profesional de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('trading.log')
    ]
)
logger = logging.getLogger('TradingServer')

# =============================================
# DECORADORES Y HELPERS
# =============================================
def synchronized(lock_name: str):
    """Decorador thread-safe para operaciones críticas"""
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            lock = getattr(self, lock_name)
            with lock:
                return func(self, *args, **kwargs)
        return wrapper
    return decorator

def validate_webhook(f):
    """Validador profesional de webhooks"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not request.is_json:
            return jsonify({"error": "Encabezado Content-Type debe ser application/json"}), 415
            
        data = request.get_json()
        required_fields = {'action', 'symbol'}
        missing = required_fields - set(data.keys())
        
        if missing:
            return jsonify({"error": f"Campos requeridos faltantes: {', '.join(missing)}"}), 400
            
        if data['action'].lower() == 'buy' and 'trailing_stop' not in data:
            return jsonify({"error": "Parámetro trailing_stop requerido para compras"}), 400
            
        return f(*args, **kwargs)
    return wrapper

# =============================================
# CORE DEL TRADING BOT (VERSIÓN PRODUCCIÓN)
# =============================================
class TradingEngine:
    def __init__(self):
        self._lock = Lock()
        self._shutdown_event = Event()
        self._position_lock = Lock()
        self._reset_state()
        
        # Estado inicial validado
        self.current_capital = Decimal(str(config.INITIAL_CAPITAL))
        logger.info(f"Motor inicializado con capital: {self.current_capital}€")

    def _reset_state(self):
        """Reinicio seguro del estado de trading"""
        with self._position_lock:
            self.active_position = False
            self.current_symbol = None
            self.entry_price = Decimal('0')
            self.stop_price = Decimal('0')
            self.position_size = Decimal('0')
            self.take_profit = None
            self.last_order_id = None
            self.last_update = time.time()

    @synchronized('_lock')
    def execute_order(self, order_type: str, params: Dict) -> Tuple[bool, str]:
        """Ejecuta órdenes con gestión profesional de errores"""
        try:
            # Sincronización temporal antes de cada operación
            exchange_client._sync_exchange_time(exchange_client.client)
            
            # Generación de nonce integrada en el cliente de exchange
            order = exchange_client.create_order(params)
            
            logger.info(
                f"ORDEN EJECUTADA | {order['id']} | "
                f"{params['symbol']} | "
                f"Tipo: {order_type.upper()} | "
                f"Monto: {params['amount']:.6f}"
            )
            
            return True, order['id']
            
        except ccxt.InvalidNonce as e:
            logger.warning("Nonce inválido detectado, reintentando...")
            return self.execute_order(order_type, params)  # Reintento automático
            
        except ccxt.NetworkError as e:
            logger.error(f"Error de red: {str(e)}")
            return False, str(e)
            
        except Exception as e:
            logger.critical(f"Error crítico: {str(e)}", exc_info=True)
            return False, str(e)

    @synchronized('_lock')
    def execute_buy(self, symbol: str, trailing: float) -> Tuple[bool, str]:
        """Lógica profesional de compra"""
        try:
            # Validación de mercado
            market = exchange_client.markets.get(symbol)
            if not market:
                return False, f"Par {symbol} no disponible"
                
            # Cálculo preciso del monto
            ticker = exchange_client.client.fetch_ticker(symbol)
            price = Decimal(str(ticker['ask']))
            amount = (self.current_capital / price).quantize(Decimal('0.00000000'))
            
            # Validación de límites del exchange
            if amount < Decimal(str(market['limits']['amount']['min'])):
                return False, f"Monto mínimo no alcanzado: {market['limits']['amount']['min']}"
            
            # Parámetros de la orden
            order_params = {
                'symbol': symbol,
                'type': 'limit',
                'side': 'buy',
                'amount': float(amount),
                'price': float(price),
                'params': {
                    'timeInForce': 'GTC',
                    'trailingStop': float(trailing)
                }
            }
            
            success, order_id = self.execute_order('buy', order_params)
            
            if success:
                with self._position_lock:
                    self.active_position = True
                    self.current_symbol = symbol
                    self.entry_price = price
                    self.stop_price = price * (1 - Decimal(str(trailing)))
                    self.position_size = amount
                    self.last_order_id = order_id
                    self.last_update = time.time()
                
                Thread(target=self._manage_position, daemon=True).start()
            
            return success, order_id
            
        except Exception as e:
            logger.error(f"Error en compra: {str(e)}", exc_info=True)
            return False, str(e)

    def _manage_position(self):
        """Gestión profesional de posiciones abiertas"""
        logger.info("Iniciando monitor de posición")
        while self.active_position and not self._shutdown_event.is_set():
            try:
                # Timeout de seguridad de 30 minutos
                if time.time() - self.last_update > 1800:
                    logger.warning("Timeout de posición, liquidando...")
                    self.execute_sell()
                    break
                
                # Actualización de precios
                ticker = exchange_client.client.fetch_ticker(self.current_symbol)
                current_price = Decimal(str(ticker['bid']))
                
                # Check stop loss
                if current_price <= self.stop_price:
                    logger.info("Stop loss activado")
                    self.execute_sell()
                    break
                
                # Ajuste dinámico del trailing stop
                new_stop = current_price * (1 - Decimal('0.02'))  # 2% trailing
                if new_stop > self.stop_price:
                    with self._position_lock:
                        self.stop_price = new_stop
                        self.last_update = time.time()
                    logger.debug(f"Actualizado stop loss: {new_stop:.4f}")
                
                time.sleep(60)
                
            except Exception as e:
                logger.error(f"Error en monitor: {str(e)}")
                time.sleep(30)

    @synchronized('_lock')
    def execute_sell(self) -> Tuple[bool, str]:
        """Lógica profesional de venta"""
        try:
            if not self.active_position:
                return False, "Sin posición activa"
            
            # Obtener balance actualizado
            balance = exchange_client.get_balance()
            currency = self.current_symbol.split('/')[0]
            amount = Decimal(str(balance['free'][currency])).quantize(Decimal('0.00000000'))
            
            # Intentar orden limit primero
            try:
                order_params = {
                    'symbol': self.current_symbol,
                    'type': 'limit',
                    'side': 'sell',
                    'amount': float(amount),
                    'price': float(self.stop_price)
                }
                success, order_id = self.execute_order('sell', order_params)
            except ccxt.InvalidOrder:
                # Fallback a market order
                order_params = {
                    'symbol': self.current_symbol,
                    'type': 'market',
                    'side': 'sell',
                    'amount': float(amount)
                }
                success, order_id = self.execute_order('sell', order_params)
            
            # Actualizar capital
            if success:
                ticker = exchange_client.client.fetch_ticker(self.current_symbol)
                current_price = Decimal(str(ticker['bid']))
                profit = (current_price - self.entry_price) * self.position_size
                self.current_capital += profit
                logger.info(f"Resultado operación: {profit:.2f}€ | Capital: {self.current_capital:.2f}€")
                self._reset_state()
            
            return success, order_id
            
        except Exception as e:
            logger.critical(f"Error en venta: {str(e)}", exc_info=True)
            return False, str(e)

    def shutdown(self):
        """Protocolo profesional de apagado"""
        logger.info("Iniciando secuencia de apagado...")
        self._shutdown_event.set()
        
        if self.active_position:
            success, msg = self.execute_sell()
            if not success:
                logger.error(f"Error liquidando posición: {msg}")
        
        logger.info("Motor detenido correctamente")

# =============================================
# ENDPOINTS API (PRODUCCIÓN GRADE)
# =============================================
@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint de salud profesional"""
    return jsonify({
        "status": "operacional",
        "timestamp": time.time(),
        "position_active": trading_engine.active_position,
        "current_capital": float(trading_engine.current_capital),
        "environment": os.getenv("ENV", "production")
    }), 200

@app.route('/webhook', methods=['POST'])
@validate_webhook
def handle_signal():
    """Manejador profesional de señales de trading"""
    data = request.get_json()
    action = data['action'].lower()
    symbol = data['symbol'].upper().replace('-', '/')
    
    try:
        if action == 'buy':
            trailing = float(data.get('trailing_stop', 0.02))
            success, order_id = trading_engine.execute_buy(symbol, trailing)
            status_code = 200 if success else 400
            return jsonify({
                "status": "success" if success else "error",
                "order_id": order_id,
                "details": {
                    "symbol": symbol,
                    "trailing_stop": trailing,
                    "capital": float(trading_engine.current_capital)
                }
            }), status_code
            
        elif action == 'sell':
            success, order_id = trading_engine.execute_sell()
            return jsonify({
                "status": "success" if success else "error",
                "order_id": order_id
            }), 200 if success else 400
            
        return jsonify({"error": "Acción no soportada"}), 400
        
    except Exception as e:
        logger.error(f"Error en webhook: {str(e)}", exc_info=True)
        return jsonify({
            "error": "Error interno del servidor",
            "details": str(e)
        }), 500

# =============================================
# INICIALIZACIÓN Y SERVICIO WEB
# =============================================
def run_production_server():
    """Servidor web profesional para producción"""
    from waitress import serve
    
    logger.info(f"Iniciando servidor en puerto {config.WEB_SERVER_PORT}")
    serve(
        app,
        host="0.0.0.0",
        port=config.WEB_SERVER_PORT,
        threads=os.cpu_count() or 4,
        channel_timeout=120
    )

# Instancia global con seguridad
try:
    trading_engine = TradingEngine()
    atexit.register(trading_engine.shutdown)
except Exception as e:
    logger.critical(f"Error de inicialización: {str(e)}")
    raise SystemExit(1)

if __name__ == '__main__':
    print("\n" + "="*50)
    print("🚀 SERVICIO DE TRADING AUTOMATIZADO - PRODUCCIÓN")
    print(f"• Endpoint: http://0.0.0.0:{config.WEB_SERVER_PORT}")
    print(f"• Entorno: {os.getenv('ENV', 'production')}")
    print("="*50 + "\n")
    
    run_production_server()