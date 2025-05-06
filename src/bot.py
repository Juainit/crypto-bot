# bot.py (Versión Profesional Corregida)
import os
import time
import atexit
import logging
from decimal import Decimal, getcontext, ROUND_UP
from typing import Dict, Optional, Tuple
from threading import Thread, Lock, Event
from functools import wraps
import ccxt
from flask import Flask, request, jsonify
from src.config import config
from src.exchange import exchange_client
from src.database import db_manager
from src.signals import signal_processor

# =============================================
# CONFIGURACIÓN GLOBAL
# =============================================
app = Flask(__name__)
getcontext().prec = 12  # Precisión para cálculos financieros

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
# DECORADORES MEJORADOS
# =============================================
def synchronized(lock_name: str):
    """Decorador thread-safe con timeout y registro"""
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            lock = getattr(self, lock_name)
            try:
                if not lock.acquire(timeout=15):
                    logger.error("Timeout adquiriendo lock")
                    raise TimeoutError("No se pudo adquirir el recurso")
                return func(self, *args, **kwargs)
            finally:
                lock.release()
        return wrapper
    return decorator

def validate_webhook(f):
    """Validador profesional de webhooks con auditoría"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        client_ip = request.remote_addr
        
        try:
            if not request.is_json:
                logger.warning(f"Intento de webhook no JSON desde {client_ip}")
                return jsonify({"error": "Se requiere application/json"}), 400
                
            data = request.get_json()
            logger.info(f"Webhook recibido desde {client_ip}: {data}")
            
            # Validación de campos esenciales
            required = {'action', 'symbol'}
            if missing := required - set(data.keys()):
                logger.warning(f"Campos faltantes desde {client_ip}: {', '.join(missing)}")
                return jsonify({"error": f"Campos requeridos: {', '.join(missing)}"}), 400
                
            # Procesamiento de señal
            processed_signal = signal_processor.process_signal(data)
            if not processed_signal:
                return jsonify({"error": "Señal inválida"}), 400
                
            return f(*args, **kwargs)
        finally:
            logger.info(f"Webhook procesado en {time.time() - start_time:.2f}s")
    return wrapper

# =============================================
# NÚCLEO DEL TRADING ENGINE (CORREGIDO)
# =============================================
class TradingBot:
    def __init__(self):
        self._lock = Lock()
        self._shutdown_event = Event()
        self._state = self._load_initial_state()
        self._setup_logging()
        logger.info("Motor de trading inicializado")

    def _setup_logging(self):
        """Configuración avanzada de logs de trading"""
        self._trade_logger = logging.getLogger('TradeAudit')
        handler = logging.FileHandler('trades.log')
        handler.setFormatter(logging.Formatter('%(asctime)s | %(message)s'))
        self._trade_logger.addHandler(handler)
        self._trade_logger.propagate = False

    def _load_initial_state(self) -> Dict:
        """Carga estado inicial desde DB con manejo de errores"""
        try:
            result = db_manager.execute_query(
                "SELECT * FROM positions WHERE closed = FALSE ORDER BY created_at DESC LIMIT 1"
            )
            if result:
                position = result[0]
                return {
                    'active': True,
                    'symbol': position['symbol'],
                    'entry_price': Decimal(str(position['entry_price'])),
                    'size': Decimal(str(position['size'])),
                    'trailing_stop': Decimal(str(position['trailing_stop'])),
                    'capital': Decimal(str(position['remaining_capital']))
                }
        except Exception as e:
            logger.error(f"Error cargando estado: {str(e)}")
        
        return {
            'active': False,
            'symbol': None,
            'entry_price': Decimal('0'),
            'size': Decimal('0'),
            'trailing_stop': Decimal('0.02'),
            'capital': Decimal(str(config.INITIAL_CAPITAL))
        }
    @synchronized('_lock')
    def execute_sell(self) -> Tuple[bool, str]:
        """Ejecución de venta con reinversión de capital"""
        try:
            if not self._state['active']:
                return False, "Sin posición activa"
            
            # Obtención de precio de mercado
            ticker = exchange_client.fetch_ticker(self._state['symbol'])
            price = Decimal(str(ticker['bid'])).quantize(Decimal('0.00000001'))
            
            # Intentar orden limitada primero
            try:
                order = exchange_client.create_limit_order(
                    symbol=self._state['symbol'],
                    side='sell',
                    amount=float(self._state['size']),
                    price=float(price)
                )
            except ccxt.InvalidOrder as e:
                logger.warning(f"Orden limitada rechazada: {str(e)}. Intentando market order...")
                order = exchange_client.create_market_order(
                    symbol=self._state['symbol'],
                    side='sell',
                    amount=float(self._state['size'])
                )
            
            # Cálculo preciso de ganancias
            sale_proceeds = self._state['size'] * price
            new_capital = self._state['capital'] + sale_proceeds
            profit = new_capital - config.INITIAL_CAPITAL
            
            # Actualización de estado
            self._state.update({
                'active': False,
                'capital': new_capital.quantize(Decimal('0.01')),
                'symbol': None,
                'size': Decimal('0')
            })
            
            # Actualización transaccional en DB
            db_manager.transactional([
                ("UPDATE positions SET exit_price = %s, closed = TRUE WHERE closed = FALSE",
                (float(price),)),
                ("UPDATE capital SET balance = %s", (float(new_capital),))
            ])
            
            self._trade_logger.info(
                f"VENTA | {self._state['symbol']} | "
                f"Precio: {price:.8f} | Beneficio: {profit:.2f}€ | "
                f"Nuevo capital: {new_capital:.2f}€"
            )
            
            return True, order['id']
            
        except Exception as e:
            logger.critical(f"Error en venta: {str(e)}", exc_info=True)
            return False, str(e)

    @synchronized('_lock')
    def execute_buy(self, symbol: str, trailing: Decimal) -> Tuple[bool, str]:
        """Ejecución de compra con configuración de trailing stop"""
        try:
            ticker = exchange_client.fetch_ticker(symbol)
            price = Decimal(str(ticker['ask'])).quantize(Decimal('0.00000001'))
            amount = (self._state['capital'] / price).quantize(Decimal('0.00000001'), rounding=ROUND_UP)
            order = exchange_client.create_market_order(
                symbol=symbol,
                side='buy',
                amount=float(amount)
            )
            self._state['order_id'] = order['id']
            self._state.update({
                'active': True,
                'symbol': symbol,
                'entry_price': price,
                'size': amount,
                'trailing_stop': trailing
            })
            initial_stop = price * (Decimal('1') - trailing)
            self._state['current_stop'] = initial_stop
            self._state['capital'] -= price * amount
            db_manager.transactional([
                ("INSERT INTO positions (symbol, entry_price, size, trailing_stop) VALUES (%s, %s, %s, %s)",
                 (symbol, float(price), float(amount), float(trailing)))
            ])
            self._trade_logger.info(
                f"COMPRA | {symbol} | Precio: {price:.8f} | Tamaño: {amount} | Trailing: {trailing}"
            )
            return True, order['id']
        except Exception as e:
            logger.critical(f"Error en compra: {str(e)}", exc_info=True)
            return False, str(e)

    def manage_orders(self):
        """Gestión activa de órdenes con trailing stop"""
        logger.info("Iniciando monitorización de posiciones")
        while not self._shutdown_event.is_set():
            try:
                if not self._state['active']:
                    time.sleep(15)
                    continue
                
                # Lógica de trailing stop actualizada
                ticker = exchange_client.fetch_ticker(self._state['symbol'])
                current_price = Decimal(str(ticker['last']))
                new_stop = current_price * (1 - self._state['trailing_stop'])
                
                # Actualización dinámica del stop
                if new_stop > self._state.get('current_stop', Decimal('0')):
                    exchange_client.update_order(
                        order_id=self._state['order_id'],
                        new_stop=float(new_stop))
                    self._state['current_stop'] = new_stop
                    logger.info(f"Trailing actualizado: {new_stop:.8f}")
                
                time.sleep(30)
                
            except Exception as e:
                logger.error(f"Error en monitorización: {str(e)}")
                time.sleep(60)

    def shutdown(self):
        """Protoculo de apagado seguro"""
        logger.info("Iniciando secuencia de apagado...")
        self._shutdown_event.set()
        
        try:
            if self._state['active']:
                logger.warning("Liquidando posición activa...")
                self.execute_sell()
        except Exception as e:
            logger.error(f"Error durante el apagado: {str(e)}")
        
        db_manager.close()
        logger.info("Sistema apagado correctamente")

# =============================================
# ENDPOINTS API PROFESIONALES
# =============================================
@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint de salud completo"""
    try:
        db_status = "OK" if db_manager.execute_query("SELECT 1") else "Error"
        exchange_status = "OK" if exchange_client.check_connection() else "Error"
        return jsonify({
            "status": "Operacional",
            "database": db_status,
            "exchange": exchange_status,
            "capital": float(bot._state['capital']),
            "posición_activa": bot._state['active']
        }), 200
    except Exception as e:
        logger.error(f"Health check fallido: {str(e)}")
        return jsonify({"status": "Error"}), 500

@app.route('/webhook', methods=['POST'])
@validate_webhook
def handle_webhook():
    """Manejador profesional de webhooks"""
    data = request.get_json()
    action = data['action'].lower()
    
    try:
        if action == 'buy':
            symbol = data['symbol']
            trailing_cfg = float(data.get("trailing_stop", 0.02))
            logger.info(f"🔔 Señal recibida para {symbol}")
            # Normalización y obtención del mercado
            # normalized = exchange_client._normalize_symbol(symbol)
            # market = exchange_client.client.market(normalized)
            if bot._state['active'] and bot._state['symbol'] == symbol:
                logger.info(f"❌ Ya hay posición abierta para {symbol}")
            else:
                logger.info(f"✅ No hay posición abierta, ejecutando compra")
            success, order_id = bot.execute_buy(symbol, trailing_cfg)
            if success:
                Thread(target=bot.manage_orders, daemon=True).start()
                return jsonify({
                    "status": "success",
                    "order_id": order_id,
                    "symbol": bot._state['symbol'],
                    "capital_restante": float(bot._state['capital'])
                }), 200
            return jsonify({"error": order_id}), 400
            
        elif action == 'sell':
            success, order_id = bot.execute_sell()
            return jsonify({
                "status": "success" if success else "error",
                "order_id": order_id,
                "nuevo_capital": float(bot._state['capital'])
            }), 200 if success else 400
            
        return jsonify({"error": "Acción no válida"}), 400
    except Exception as e:
        logger.error(f"Error en webhook: {str(e)}")
        db_manager.log_error("webhook_error", str(e))
        return jsonify({"error": "Error interno del servidor"}), 500

# =============================================
# INICIALIZACIÓN ROBUSTA
# =============================================
def run_server():
    """Lanzador profesional para producción"""
    from waitress import serve
    serve(
        app,
        host="0.0.0.0",
        port=config.WEB_SERVER_PORT,
        threads=8,
        channel_timeout=1200
    )

if __name__ == '__main__':
    try:
        bot = TradingBot()
        atexit.register(bot.shutdown)
        logger.info(f"""
        ==============================
        🚀 Crypto Trading Bot (v1.2.0)
        Port: {config.WEB_SERVER_PORT}
        Capital: {config.INITIAL_CAPITAL}€
        ==============================
        """)
        run_server()
    except Exception as e:
        logger.critical(f"Error de inicialización: {str(e)}")
        raise SystemExit(1)