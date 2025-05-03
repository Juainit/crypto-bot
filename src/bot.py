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
from config import config
from exchange import exchange_client

# =============================================
# CONFIGURACIÓN GLOBAL
# =============================================
app = Flask(__name__)
getcontext().prec = 8  # Precisión decimal para operaciones financieras

# Configuración de logging profesional
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)-18s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('TradingBot')

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
            return jsonify({"error": "Content-Type debe ser application/json"}), 400
            
        data = request.get_json()
        required = {'action', 'symbol'}
        missing = required - set(data.keys())
        
        if missing:
            return jsonify({"error": f"Campos faltantes: {', '.join(missing)}"}), 400
            
        if data['action'].lower() == 'buy' and 'trailing_stop' not in data:
            return jsonify({"error": "Se requiere trailing_stop para compras"}), 400
            
        return f(*args, **kwargs)
    return wrapper

# =============================================
# CORE DEL TRADING BOT (VERSIÓN PRODUCCIÓN)
# =============================================
class TradingBot:
    def __init__(self):
        self._lock = Lock()
        self._shutdown_event = Event()
        self._reset_trading_state()
        
        # Estado inicial validado
        self.current_capital = Decimal(str(config.INITIAL_CAPITAL))
        logger.info(f"Bot inicializado con capital: {self.current_capital}€")

    def _reset_trading_state(self):
        """Reinicia el estado de trading de forma segura"""
        with self._lock:
            self.active_position = False
            self.current_symbol = None
            self.entry_price = Decimal('0')
            self.stop_price = Decimal('0')
            self.position_size = Decimal('0')
            self.take_profit = None
            self.last_order_id = None
            self.last_update = None

    @synchronized('_lock')
    def execute_buy(self, symbol: str, trailing_percent: float) -> Tuple[bool, str]:
        """Ejecuta orden de compra con validación profesional"""
        try:
            # Validación de símbolo y posición
            if not exchange_client.markets.get(symbol):
                return False, f"Símbolo {symbol} no válido"
                
            if self.active_position:
                return False, "Posición activa existente"

            # Cálculos precisos con Decimal
            ticker = exchange_client.client.fetch_ticker(symbol)
            current_price = Decimal(str(ticker['ask']))
            amount = (self.current_capital / current_price).quantize(Decimal('1.00000000'))
            
            # Validación de tamaño mínimo
            market = exchange_client.markets[symbol]
            min_amount = Decimal(str(market['limits']['amount']['min']))
            if amount < min_amount:
                return False, f"Monto mínimo no alcanzado: {min_amount}"

            # Ejecución con gestión de nonce incorporada
            order = exchange_client.create_order({
                'symbol': symbol,
                'type': 'limit',
                'side': 'buy',
                'amount': float(amount),
                'price': float(current_price),
                'params': {
                    'timeout': 30000,
                    'trailingStop': float(trailing_percent)
                }
            })
            
            # Actualización de estado atómica
            with self._lock:
                self.active_position = True
                self.current_symbol = symbol
                self.entry_price = current_price
                self.stop_price = current_price * (1 - Decimal(str(trailing_percent)))
                self.position_size = amount
                self.last_order_id = order['id']
                self.last_update = time.time()

            logger.info(
                f"COMPRA EXITOSA | {symbol} | "
                f"Precio: {current_price:.4f}€ | "
                f"Monto: {amount:.6f} | "
                f"Stop: {self.stop_price:.4f}€"
            )
            
            return True, order['id']

        except ccxt.InvalidNonce as e:
            logger.error("Error de nonce, reintentando...")
            return self.execute_buy(symbol, trailing_percent)  # Reintento automático
            
        except Exception as e:
            logger.error(f"Error en compra: {str(e)}", exc_info=True)
            return False, str(e)

    @synchronized('_lock')
    def execute_sell(self) -> Tuple[bool, str]:
        """Ejecuta venta con sistema de fallback profesional"""
        try:
            if not self.active_position:
                return False, "Sin posición activa"

            # Obtener balance actualizado
            balance = exchange_client.get_balance()
            currency = self.current_symbol.split('/')[0]
            amount = Decimal(str(balance['free'][currency])).quantize(Decimal('1.00000000'))

            # Intentar orden limit primero
            try:
                order = exchange_client.create_order({
                    'symbol': self.current_symbol,
                    'type': 'limit',
                    'side': 'sell',
                    'amount': float(amount),
                    'price': float(self.stop_price)
                })
                logger.info(f"VENTA LIMITE | {order['id']}")
            except ccxt.InvalidOrder:
                # Fallback a market order
                order = exchange_client.create_order({
                    'symbol': self.current_symbol,
                    'type': 'market',
                    'side': 'sell',
                    'amount': float(amount)
                })
                logger.warning(f"VENTA DE MERCADO | {order['id']}")

            # Actualizar capital
            ticker = exchange_client.client.fetch_ticker(self.current_symbol)
            current_price = Decimal(str(ticker['bid']))
            profit = (current_price - self.entry_price) * self.position_size
            self.current_capital += profit
            
            logger.info(
                f"RESULTADO OPERACIÓN | "
                f"Ganancia: {profit:.2f}€ | "
                f"Capital Actual: {self.current_capital:.2f}€"
            )

            self._reset_trading_state()
            return True, order['id']

        except Exception as e:
            logger.critical(f"Error en venta: {str(e)}", exc_info=True)
            return False, str(e)

    def manage_orders(self):
        """Sistema profesional de gestión de órdenes en segundo plano"""
        logger.info("Iniciando gestor de órdenes")
        while not self._shutdown_event.is_set():
            try:
                with self._lock:
                    if not self.active_position:
                        time.sleep(10)
                        continue

                    # Timeout de seguridad
                    if time.time() - self.last_update > 1800:  # 30 minutos
                        logger.warning("Timeout de posición, liquidando...")
                        self.execute_sell()
                        continue

                    # Actualizar precios
                    ticker = exchange_client.client.fetch_ticker(self.current_symbol)
                    current_price = Decimal(str(ticker['bid']))

                    # Check stop loss
                    if current_price <= self.stop_price:
                        logger.info("Stop loss activado")
                        self.execute_sell()
                        continue

                    # Check take profit
                    if self.take_profit and current_price >= self.take_profit:
                        logger.info("Take profit alcanzado")
                        self.execute_sell()
                        continue

                    # Ajuste dinámico de trailing stop
                    new_stop = current_price * (1 - Decimal('0.02'))  # 2% trailing
                    if new_stop > self.stop_price:
                        self.stop_price = new_stop
                        self.last_update = time.time()
                        logger.debug(f"Nuevo stop: {self.stop_price:.4f}€")

                time.sleep(60)

            except Exception as e:
                logger.error(f"Error en gestor: {str(e)}")
                time.sleep(300)

    def shutdown(self):
        """Protocolo de apagado seguro"""
        logger.info("Iniciando apagado controlado...")
        self._shutdown_event.set()
        
        if self.active_position:
            success, msg = self.execute_sell()
            if not success:
                logger.error(f"Error liquidando posición: {msg}")
        
        logger.info("Bot apagado correctamente")

# =============================================
# ENDPOINTS API (PRODUCCIÓN READY)
# =============================================
@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint profesional de monitoreo"""
    return jsonify({
        "status": "operacional",
        "capital_actual": float(bot.current_capital),
        "posicion_activa": bot.active_position,
        "ultima_actualizacion": bot.last_update
    }), 200

@app.route('/webhook', methods=['POST'])
@validate_webhook
def handle_webhook():
    """Manejador profesional de señales"""
    data = request.get_json()
    symbol = data['symbol'].replace('-', '/').upper()
    
    try:
        if data['action'].lower() == 'buy':
            trailing = float(data.get('trailing_stop', 0.02))
            success, order_id = bot.execute_buy(symbol, trailing)
            
            if success:
                Thread(target=bot.manage_orders, daemon=True).start()
                return jsonify({
                    "status": "success",
                    "order_id": order_id,
                    "capital": float(bot.current_capital)
                }), 200
                
            return jsonify({"error": order_id}), 400
            
        elif data['action'].lower() == 'sell':
            success, order_id = bot.execute_sell()
            return jsonify({
                "status": "success" if success else "error",
                "order_id": order_id
            }), 200 if success else 400
            
        return jsonify({"error": "Acción no soportada"}), 400
        
    except Exception as e:
        logger.error(f"Error en webhook: {str(e)}", exc_info=True)
        return jsonify({"error": "Error interno del servidor"}), 500

# =============================================
# INICIALIZACIÓN Y EJECUCIÓN
# =============================================
def run_server():
    """Lanzador profesional para producción"""
    from waitress import serve
    
    serve(
        app,
        host="0.0.0.0",
        port=config.WEB_SERVER_PORT,
        threads=os.cpu_count() or 4,
        channel_timeout=120
    )

# Instancia global con seguridad
try:
    bot = TradingBot()
    atexit.register(bot.shutdown)
except Exception as e:
    logger.critical(f"Error de inicialización: {str(e)}")
    raise SystemExit(1)

if __name__ == '__main__':
    print("\n" + "="*40)
    print("🚀 BOT DE TRADING EN PRODUCCIÓN")
    print(f"🔗 Webhook: http://0.0.0.0:{config.WEB_SERVER_PORT}/webhook")
    print("="*40 + "\n")
    
    run_server()