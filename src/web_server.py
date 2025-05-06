import os
import time
import atexit
import json
import logging
from decimal import Decimal, getcontext
from threading import Thread, Lock, Event
from functools import wraps
from typing import Dict, Optional, Tuple
from flask import Flask, request, jsonify
import ccxt
from src.config import config
from src.exchange import exchange_client
from src.database import db_manager  # Nueva importación

# =============================================
# CONFIGURACIÓN GLOBAL MEJORADA
# =============================================
app = Flask(__name__)
getcontext().prec = 10  # Mayor precisión decimal

# Configuración profesional de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('trading_server.log')
    ]
)
logger = logging.getLogger('TradingEngine')

# =============================================
# DECORADORES MEJORADOS
# =============================================
def synchronized(lock_name: str):
    """Decorador thread-safe con timeout"""
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            lock = getattr(self, lock_name)
            if not lock.acquire(timeout=15):  # Timeout de 15 segundos
                raise TimeoutError(f"No se pudo obtener lock {lock_name}")
            try:
                return func(self, *args, **kwargs)
            finally:
                lock.release()
        return wrapper
    return decorator

def validate_webhook(f):
    """Validador mejorado de webhooks con auditoría"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        client_ip = request.remote_addr
        
        try:
            if not request.is_json:
                logger.warning(f"Intento de webhook no JSON desde {client_ip}")
                return jsonify({"error": "Content-Type debe ser application/json"}), 415
                
            data = request.get_json()
            logger.info(f"Webhook recibido desde {client_ip}: {json.dumps(data)}")
            
            # Validación extendida
            required_fields = {'action', 'symbol'}
            missing = required_fields - set(data.keys())
            if missing:
                logger.warning(f"Campos faltantes desde {client_ip}: {', '.join(missing)}")
                return jsonify({"error": f"Campos requeridos faltantes: {', '.join(missing)}"}), 400
                
            if data['action'].lower() == 'buy':
                if 'trailing_stop' not in data:
                    logger.warning(f"Falta trailing_stop desde {client_ip}")
                    return jsonify({"error": "Parámetro trailing_stop requerido para compras"}), 400
                
                if not 0.001 <= float(data['trailing_stop']) <= 0.2:  # Validación de rango [7]
                    logger.warning(f"Trailing stop inválido desde {client_ip}: {data['trailing_stop']}")
                    return jsonify({"error": "Trailing stop debe estar entre 0.1% y 20%"}), 400
            
            return f(*args, **kwargs)
        finally:
            logger.info(f"Webhook procesado en {time.time() - start_time:.2f}s")
    return wrapper

# =============================================
# NÚCLEO DEL MOTOR DE TRADING (PRODUCCIÓN) - VERSIÓN CORREGIDA
# =============================================
class TradingEngine:
    def __init__(self):
        self._lock = Lock()
        self._shutdown_event = Event()
        self._position_lock = Lock()
        self._operation_lock = Lock()
        self._state = self._load_initial_state()
        
        logger.info("Motor inicializado | Capital: €%.2f", self.current_capital)

    def _load_initial_state(self) -> Dict:
        """Carga estado inicial desde PostgreSQL"""
        try:
            result = db_manager.execute_query(
                "SELECT * FROM positions WHERE closed = FALSE ORDER BY created_at DESC LIMIT 1"
            )
            if result:
                position = result[0]
                logger.info("Estado recuperado de DB: %s", position['symbol'])
                return {
                    'active': True,
                    'symbol': position['symbol'],
                    'entry_price': Decimal(str(position['entry_price'])),
                    'size': Decimal(str(position['size'])),
                    'trailing_stop': Decimal(str(position['trailing_stop'])),
                    'capital': Decimal(str(position['remaining_capital']))
                }
        except Exception as e:
            logger.error("Error cargando estado inicial: %s", str(e))
        
        return {
            'active': False,
            'symbol': None,
            'entry_price': Decimal('0'),
            'size': Decimal('0'),
            'trailing_stop': Decimal('0.02'),
            'capital': Decimal(str(config.INITIAL_CAPITAL))
        }

    @property
    def current_capital(self) -> Decimal:
        return self._state['capital']

    @synchronized('_lock')
    def execute_buy(self, symbol: str, trailing_stop: float) -> Tuple[bool, str]:
        """Lógica de compra mejorada con validación completa"""
        normalized = exchange_client._normalize_symbol(symbol)
        market = exchange_client.client.market(normalized)
        if not market:
            return False, f"Par {symbol} no disponible"

        try:
            with self._operation_lock:
                # Obtener precio actual
                ticker = exchange_client.fetch_ticker(symbol)
                price = Decimal(str(ticker['ask']))
                
                # Calcular cantidad con precisión
                amount = (self.current_capital / price).quantize(Decimal('0.00000001'))
                
                # Validar límites del mercado
                if amount < Decimal(str(market['limits']['amount']['min'])):
                    return False, f"Monto mínimo no alcanzado: {market['limits']['amount']['min']}"
                
                # Ejecutar orden
                payload = request.get_json() if request else {}
                logger.info(f"Orden {('MARKET' if payload.get('market') else 'LIMIT')} -> {symbol} | amount={amount} | price={price}")
                if payload.get("market", False):
                    order = exchange_client.create_market_order(
                        symbol=symbol,
                        side="buy",
                        amount=float(amount)
                    )
                else:
                    order = exchange_client.create_limit_order(
                        symbol=symbol,
                        side="buy",
                        amount=float(amount),
                        price=float(price)
                    )
                
                # Actualizar estado
                self._state.update({
                    'active': True,
                    'symbol': symbol,
                    'entry_price': price,
                    'size': amount,
                    'trailing_stop': Decimal(str(trailing_stop)),
                    'capital': Decimal('0'),
                    'last_update': time.time(),
                    'max_price': price,  # Inicializar max_price con entry price
                })
                
                # Persistir en DB
                db_manager.transactional([
                    ("INSERT INTO positions (symbol, entry_price, size, trailing_stop, remaining_capital) VALUES (%s, %s, %s, %s, %s)",
                     (symbol, float(price), float(amount), float(trailing_stop), 0.0)),
                    ("UPDATE capital SET balance = %s", (0.0,))
                ])
                
                # Iniciar monitorización
                Thread(
                    target=self._manage_position,
                    daemon=True,
                    name=f"PositionManager-{symbol}"
                ).start()
                
                return True, order['id']
                
        except ccxt.InsufficientFunds as e:
            logger.critical("Fondos insuficientes en exchange: %s", str(e))
            return False, str(e)
        except Exception as e:
            logger.error("Error en compra: %s", str(e), exc_info=True)
            db_manager.log_error("buy_error", str(e))
            return False, str(e)

    def _manage_position(self):
        """Monitorización activa de la posición con trailing stop basado en max_price"""
        logger.info("Iniciando monitorización de posición para %s", self._state['symbol'])
        while self._state['active'] and not self._shutdown_event.is_set():
            try:
                # Timeout de posición (30 minutos)
                if time.time() - self._state['last_update'] > 1800:
                    logger.warning("Timeout de posición, liquidando...")
                    self.execute_sell()
                    break

                # Update maximum price seen since entry
                current_price = Decimal(str(exchange_client.fetch_ticker(self._state['symbol'])['last']))
                with self._position_lock:
                    if current_price > self._state.get('max_price', Decimal('0')):
                        self._state['max_price'] = current_price

                # Compute trailing stop price based on max_price
                stop_price = self._state['max_price'] * (Decimal('1') - self._state['trailing_stop'])

                # Check if stop hit
                if current_price <= stop_price:
                    logger.info("Trailing stop activado a %.4f", stop_price)
                    self.execute_sell()
                    break

                time.sleep(30)

            except Exception as e:
                logger.error("Error en monitorización: %s", str(e))
                db_manager.log_error("position_manager_error", str(e))
                time.sleep(60)

    @synchronized('_lock')
    def execute_sell(self) -> Tuple[bool, str]:
        """Lógica de venta con manejo de errores"""
        if not self._state['active']:
            return False, "Sin posición activa"

        try:
            # Obtener datos de mercado
            ticker = exchange_client.fetch_ticker(self._state['symbol'])
            price = Decimal(str(ticker['bid']))
            
            # Intentar venta limitada primero, luego market
            try:
                order = exchange_client.create_limit_order(
                    symbol=self._state['symbol'],
                    side='sell',
                    amount=float(self._state['size']),
                    price=float(price)
                )
            except ccxt.InvalidOrder:
                order = exchange_client.create_market_order(
                    symbol=self._state['symbol'],
                    side='sell',
                    amount=float(self._state['size'])
                )
            
            # Calcular nuevo capital
            new_capital = self._state['size'] * price
            
            # Actualizar estado
            self._state.update({
                'active': False,
                'capital': new_capital,
                'symbol': None,
                'size': Decimal('0')
            })
            
            # Persistir en DB
            db_manager.transactional([
                ("UPDATE positions SET exit_price = %s, closed = TRUE, profit = %s WHERE closed = FALSE",
                 (float(price), float(new_capital - config.INITIAL_CAPITAL))),
                ("UPDATE capital SET balance = %s", (float(new_capital),))
            ])
            
            logger.info("Venta ejecutada correctamente. Beneficio: €%.2f", new_capital - config.INITIAL_CAPITAL)
            return True, order['id']
            
        except Exception as e:
            logger.critical("Error en venta: %s", str(e), exc_info=True)
            db_manager.log_error("sell_error", str(e))
            return False, str(e)

    def shutdown(self):
        """Protocolo de apagado seguro"""
        logger.info("Iniciando secuencia de apagado...")
        self._shutdown_event.set()
        
        try:
            if self._state['active']:
                logger.warning("Liquidando posición activa...")
                success, _ = self.execute_sell()
                if not success:
                    logger.error("Error liquidando posición")
        except Exception as e:
            logger.error("Error en apagado: %s", str(e))
        
        db_manager.close()
        logger.info("Motor detenido correctamente")

# =============================================
# ENDPOINTS API OPTIMIZADOS
# =============================================
@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint de salud mejorado"""
    try:
        db_status = "ok" if db_manager.test_connection() else "error"
    except Exception as e:
        db_status = f"error: {str(e)}"
    
    return jsonify({
        "status": "operacional",
        "timestamp": time.time(),
        "position_active": trading_engine._state['active'],
        "current_capital": float(trading_engine.current_capital),
        "database_status": db_status,
        "environment": os.getenv("ENV", "production")
    }), 200

@app.route('/webhook', methods=['POST'])
@validate_webhook
def handle_signal():
    """Manejador profesional de señales"""
    data = request.get_json()
    action = data['action'].lower()
    symbol = data['symbol'].upper().replace('-', '/')
    
    try:
        if action == 'buy':
            trailing = float(data['trailing_stop'])
            success, order_id = trading_engine.execute_buy(symbol, trailing)
            
            response = {
                "status": "success" if success else "error",
                "order_id": order_id,
                "symbol": symbol,
                "trailing_stop": trailing
            }
            
            status_code = 200 if success else 400
            db_manager.log_webhook(data, response, status_code)
            return jsonify(response), status_code
            
        elif action == 'sell':
            success, order_id = trading_engine.execute_sell()
            response = {
                "status": "success" if success else "error",
                "order_id": order_id
            }
            status_code = 200 if success else 400
            db_manager.log_webhook(data, response, status_code)
            return jsonify(response), status_code
            
        return jsonify({"error": "Acción no válida"}), 400
        
    except Exception as e:
        logger.error("Error en webhook: %s", str(e), exc_info=True)
        db_manager.log_error("webhook_error", str(e))
        return jsonify({"error": "Error interno del servidor"}), 500

# =============================================
# INICIALIZACIÓN ROBUSTA
# =============================================
def run_server():
    """Lanzador profesional mejorado"""
    from waitress import serve
    serve(
        app,
        host="0.0.0.0",
        port=config.WEB_SERVER_PORT,
        threads=4,  # Número fijo para producción
        channel_timeout=600,
        connection_limit=50
    )

try:
    trading_engine = TradingEngine()
    atexit.register(trading_engine.shutdown)
    logger.info("Servicio inicializado correctamente")
except Exception as e:
    logger.critical("Error de inicialización: %s", str(e))
    raise SystemExit(1)

if __name__ == '__main__':
    print("\n" + "="*50)
    print("🚀 SERVICIO DE TRADING AUTOMATIZADO - PRODUCCIÓN")
    print(f"• Endpoint: http://0.0.0.0:{config.WEB_SERVER_PORT}")
    print(f"• Entorno: {os.getenv('ENV', 'production')}")
    print(f"• Capital inicial: {config.INITIAL_CAPITAL}€")
    print("="*50 + "\n")
    
    run_server()