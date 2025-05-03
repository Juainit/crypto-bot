import os
import time
import atexit
import logging
from decimal import Decimal, getcontext
from typing import Dict, Optional, Tuple
from threading import Thread, Lock, Event
from functools import wraps
import ccxt
from flask import Flask, request, jsonify
from src.config import config
from src.exchange import exchange_client
from src.database import db_manager  # Nueva importación

# =============================================
# CONFIGURACIÓN GLOBAL MEJORADA
# =============================================
app = Flask(__name__)
getcontext().prec = 10  # Mayor precisión para cálculos financieros

# Configuración profesional de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('trading.log')
    ]
)
logger = logging.getLogger('TradingEngine')

# =============================================
# MEJORAS EN DECORADORES Y HELPERS
# =============================================
def synchronized(lock_name: str):
    """Decorador thread-safe mejorado con timeout"""
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            lock = getattr(self, lock_name)
            if not lock.acquire(timeout=10):  # Timeout de 10 segundos
                raise TimeoutError("No se pudo adquirir el lock")
            try:
                return func(self, *args, **kwargs)
            finally:
                lock.release()
        return wrapper
    return decorator

def validate_webhook(f):
    """Validador mejorado de webhooks con registro de auditoría"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        client_ip = request.remote_addr
        
        try:
            # Validación básica
            if not request.is_json:
                logger.warning(f"Intento de webhook no JSON desde {client_ip}")
                return jsonify({"error": "Content-Type debe ser application/json"}), 400
                
            data = request.get_json()
            logger.debug(f"Webhook recibido desde {client_ip}: {data}")
            
            # Validación de campos
            required = {'action', 'symbol'}
            missing = required - set(data.keys())
            if missing:
                logger.warning(f"Campos faltantes desde {client_ip}: {', '.join(missing)}")
                return jsonify({"error": f"Campos faltantes: {', '.join(missing)}"}), 400
                
            # Validación específica para compras
            if data['action'].lower() == 'buy':
                if 'trailing_stop' not in data:
                    logger.warning(f"Falta trailing_stop desde {client_ip}")
                    return jsonify({"error": "Se requiere trailing_stop para compras"}), 400
                
                # Validación de rango de trailing stop [7]
                trailing = float(data['trailing_stop'])
                if not (0.001 <= trailing <= 0.2):
                    logger.warning(f"Trailing stop inválido desde {client_ip}: {trailing}")
                    return jsonify({"error": "Trailing stop debe estar entre 0.1% y 20%"}), 400
            
            return f(*args, **kwargs)
        finally:
            logger.info(f"Webhook procesado en {time.time() - start_time:.2f}s")
            
    return wrapper

# =============================================
# NÚCLEO DEL TRADING BOT (VERSIÓN PRODUCCIÓN)
# =============================================
class TradingBot:
    def __init__(self):
        self._lock = Lock()
        self._shutdown_event = Event()
        self._state = self._load_initial_state()  # Carga estado desde DB [6]
        self._setup_logging()
        
        logger.info("Inicialización completa del motor de trading")

    def _setup_logging(self):
        """Configuración profesional de logs"""
        self._trade_logger = logging.getLogger('TradeLogger')
        self._trade_logger.propagate = False
        self._trade_logger.addHandler(logging.FileHandler('trades.log'))

    def _load_initial_state(self) -> Dict:
        """Carga estado inicial desde PostgreSQL [6]"""
        try:
            result = db_manager.execute_query(
                "SELECT * FROM positions WHERE closed = FALSE ORDER BY created_at DESC LIMIT 1"
            )
            if result:
                position = result[0]
                logger.info(f"Estado recuperado de DB: {position['symbol']}")
                return {
                    'active': True,
                    'symbol': position['symbol'],
                    'entry_price': Decimal(str(position['entry_price'])),
                    'size': Decimal(str(position['size'])),
                    'trailing_stop': Decimal(str(position['trailing_stop'])),
                    'capital': Decimal(str(position['remaining_capital']))
                }
        except Exception as e:
            logger.error(f"Error cargando estado inicial: {str(e)}")
        
        return {
            'active': False,
            'symbol': None,
            'entry_price': Decimal('0'),
            'size': Decimal('0'),
            'trailing_stop': Decimal('0.02'),
            'capital': Decimal(str(config.INITIAL_CAPITAL))
        }

    @synchronized('_lock')
    def execute_buy(self, symbol: str, trailing_percent: float) -> Tuple[bool, str]:
        """Ejecución mejorada de compra con persistencia en DB"""
        try:
            # Validación de mercado
            market = exchange_client.validate_symbol(symbol)
            if not market:
                return False, f"Par {symbol} no disponible"
            
            # Cálculos precisos
            ticker = exchange_client.fetch_ticker(symbol)
            price = Decimal(str(ticker['ask']))
            amount = (self._state['capital'] / price).quantize(Decimal('0.00000001'))
            
            # Verificación de límites
            if amount < market['min_amount']:
                return False, f"Monto mínimo no alcanzado: {market['min_amount']}"
            
            # Ejecución de orden
            order = exchange_client.create_limit_order(
                symbol=symbol,
                side='buy',
                amount=amount,
                price=price,
                trailing_stop=trailing_percent
            )
            
            # Actualización de estado
            self._state.update({
                'active': True,
                'symbol': symbol,
                'entry_price': price,
                'size': amount,
                'trailing_stop': Decimal(str(trailing_percent)),
                'capital': Decimal('0')
            })
            
            # Persistencia en DB [6]
            db_manager.transactional([
                ("INSERT INTO positions (symbol, entry_price, size, trailing_stop, remaining_capital) VALUES (%s, %s, %s, %s, %s)",
                 (symbol, float(price), float(amount), float(trailing_percent), 0.0)),
                ("UPDATE capital SET balance = %s", (0.0,))
            ])
            
            self._trade_logger.info(
                f"COMPRA | {symbol} | "
                f"Precio: {price:.8f} | "
                f"Tamaño: {amount:.8f} | "
                f"Trailing: {trailing_percent*100:.2f}%"
            )
            
            return True, order['id']
            
        except ccxt.InsufficientFunds as e:
            logger.critical("Fondos insuficientes en el exchange")
            return False, str(e)
        except Exception as e:
            logger.error(f"Error en compra: {str(e)}", exc_info=True)
            return False, str(e)

    @synchronized('_lock')
    def execute_sell(self) -> Tuple[bool, str]:
        """Ejecución mejorada de venta con gestión de fallos"""
        try:
            if not self._state['active']:
                return False, "Sin posición activa"
            
            # Obtener datos de mercado
            ticker = exchange_client.fetch_ticker(self._state['symbol'])
            price = Decimal(str(ticker['bid']))
            
            # Ejecutar venta
            try:
                order = exchange_client.create_limit_order(
                    symbol=self._state['symbol'],
                    side='sell',
                    amount=self._state['size'],
                    price=price
                )
            except ccxt.InvalidOrder:
                order = exchange_client.create_market_order(
                    symbol=self._state['symbol'],
                    side='sell',
                    amount=self._state['size']
                )
            
            # Actualizar capital
            new_capital = self._state['size'] * price
            profit = new_capital - self._state['capital']
            
            # Actualizar estado y DB
            self._state.update({
                'active': False,
                'capital': new_capital,
                'symbol': None,
                'size': Decimal('0')
            })
            
            db_manager.transactional([
                ("UPDATE positions SET exit_price = %s, closed = TRUE WHERE closed = FALSE",
                 (float(price),)),
                ("UPDATE capital SET balance = %s", (float(new_capital),))
            ])
            
            self._trade_logger.info(
                f"VENTA | {self._state['symbol']} | "
                f"Precio: {price:.8f} | "
                f"Beneficio: {profit:.2f}€"
            )
            
            return True, order['id']
            
        except Exception as e:
            logger.critical(f"Error crítico en venta: {str(e)}", exc_info=True)
            return False, str(e)

    def manage_orders(self):
        """Gestión profesional de órdenes con trailing stop [3]"""
        logger.info("Iniciando monitorización de posiciones")
        while not self._shutdown_event.is_set():
            try:
                if not self._state['active']:
                    time.sleep(15)
                    continue
                
                # Verificar timeout de posición
                if time.time() - self._state['last_update'] > 1800:
                    logger.warning("Timeout de posición, liquidando...")
                    self.execute_sell()
                    continue
                
                # Actualizar precio y trailing stop
                ticker = exchange_client.fetch_ticker(self._state['symbol'])
                current_price = Decimal(str(ticker['last']))
                
                # Calcular nuevo stop
                new_stop = current_price * (1 - self._state['trailing_stop'])
                if new_stop > self._state['stop_price']:
                    exchange_client.update_order(
                        order_id=self._state['order_id'],
                        new_stop=new_stop
                    )
                    self._state.update({
                        'stop_price': new_stop,
                        'last_update': time.time()
                    })
                    logger.debug(f"Trailing actualizado: {new_stop:.8f}")
                
                time.sleep(30)
                
            except Exception as e:
                logger.error(f"Error en monitorización: {str(e)}")
                time.sleep(60)

    def shutdown(self):
        """Protocolo de apagado mejorado"""
        logger.info("Iniciando secuencia de apagado...")
        self._shutdown_event.set()
        
        try:
            if self._state['active']:
                logger.warning("Liquidando posición activa...")
                success, _ = self.execute_sell()
                if not success:
                    logger.error("No se pudo liquidar posición")
        except Exception as e:
            logger.error(f"Error en apagado: {str(e)}")
        
        db_manager.close()
        logger.info("Sistema apagado correctamente")

# =============================================
# ENDPOINTS API OPTIMIZADOS
# =============================================
@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint de salud mejorado con verificación de DB"""
    try:
        db_status = "ok" if db_manager.test_connection() else "error"
    except Exception as e:
        db_status = f"error: {str(e)}"
    
    return jsonify({
        "status": "operacional",
        "db_status": db_status,
        "capital": float(bot._state['capital']),
        "posicion_activa": bot._state['active']
    }), 200

@app.route('/webhook', methods=['POST'])
@validate_webhook
def handle_webhook():
    """Manejador mejorado de webhooks con registro en DB"""
    data = request.get_json()
    action = data['action'].lower()
    symbol = data['symbol'].replace('-', '/').upper()
    
    try:
        if action == 'buy':
            trailing = float(data['trailing_stop'])
            success, order_id = bot.execute_buy(symbol, trailing)
            
            if success:
                # Iniciar monitorización en hilo seguro
                Thread(
                    target=bot.manage_orders,
                    daemon=True,
                    name=f"OrderManager-{symbol}"
                ).start()
                
                return jsonify({
                    "status": "success",
                    "order_id": order_id
                }), 200
                
            return jsonify({"error": order_id}), 400
            
        elif action == 'sell':
            success, order_id = bot.execute_sell()
            return jsonify({
                "status": "success" if success else "error",
                "order_id": order_id
            }), 200 if success else 400
            
        return jsonify({"error": "Acción no válida"}), 400
        
    except Exception as e:
        logger.error(f"Error en webhook: {str(e)}", exc_info=True)
        db_manager.log_error("webhook_error", str(e))
        return jsonify({"error": "Error interno"}), 500

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
        channel_timeout=600,  # Timeout aumentado
        connection_limit=100
    )

try:
    bot = TradingBot()
    atexit.register(bot.shutdown)
    logger.info("Servicio inicializado correctamente")
except Exception as e:
    logger.critical(f"Error de inicialización: {str(e)}")
    raise SystemExit(1)

if __name__ == '__main__':
    print("\n" + "="*50)
    print("🚀 CRYPTO TRADING BOT - EDICIÓN PRODUCCIÓN")
    print(f"🔗 Puerto: {config.WEB_SERVER_PORT}")
    print(f"💰 Capital inicial: {config.INITIAL_CAPITAL}€")
    print("="*50 + "\n")
    
    run_server()