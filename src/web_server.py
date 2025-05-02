from flask import Flask, request, jsonify
from threading import Thread, Lock, Event
from decimal import Decimal, getcontext
import logging
import os
import time
import atexit
from typing import Tuple, Optional, Dict, Any
from ccxt import kraken
from functools import wraps

# =============================================
# CONFIGURACIÓN INICIAL
# =============================================
app = Flask(__name__)
getcontext().prec = 8  # Precisión decimal para operaciones financieras

# =============================================
# DECORADOR SYNCHRONIZED (VERSIÓN FINAL CORREGIDA)
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

# =============================================
# CLASE PRINCIPAL DEL TRADING BOT (COMPLETA)
# =============================================
class TradingBot:
    def __init__(self):
        """Inicialización completa del bot"""
        # 1. Sistema de bloqueo y eventos
        self._lock = Lock()
        self._shutdown_event = Event()

        # 2. Estado del trading
        self.active_position = False
        self.current_symbol = None
        self.entry_price = None
        self.stop_price = None
        self.position_size = Decimal('0')
        self.take_profit = None

        # 3. Conexión con el exchange
        self.exchange = kraken({
            'apiKey': os.getenv('KRAKEN_API_KEY'),
            'secret': os.getenv('KRAKEN_SECRET'),
            'enableRateLimit': True,
            'timeout': 30000,
            'rateLimit': 3000
        })

        # 4. Configuración de logging
        self.logger = self._setup_logger()

        # 5. Carga inicial de mercados
        self._load_markets()
        self.logger.info("Trading Bot inicializado correctamente")

    def _setup_logger(self):
        """Configuración profesional del logger"""
        logger = logging.getLogger('TradingBot')
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
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
        """Carga los mercados disponibles con manejo de errores"""
        try:
            self.exchange.load_markets()
            self.logger.info("Mercados cargados correctamente")
        except Exception as e:
            self.logger.error(f"Error cargando mercados: {str(e)}")
            raise

    def _validate_symbol(self, symbol: str) -> bool:
        """Valida el formato del símbolo"""
        return (isinstance(symbol, str) and '/' in symbol and len(symbol.split('/')) == 2)

    def _safe_get_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Obtiene ticker con manejo de errores"""
        try:
            return self.exchange.fetch_ticker(symbol)
        except Exception as e:
            self.logger.error(f"Error obteniendo ticker: {str(e)}")
            return None

    def _get_min_order_size(self, symbol: str) -> Decimal:
        """Obtiene tamaño mínimo de orden"""
        try:
            market = self.exchange.market(symbol)
            return Decimal(str(market['limits']['amount']['min']))
        except Exception as e:
            self.logger.warning(f"Usando mínimo por defecto: {str(e)}")
            return Decimal('0.00000001')

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
            amount = (Decimal('40') / current_price).quantize(Decimal('0.00000001'))

            # Validar tamaño mínimo
            min_amount = self._get_min_order_size(symbol)
            if amount < min_amount:
                return False, f"Cantidad menor al mínimo ({min_amount})"

            # Ejecutar orden
            order = self.exchange.create_order(
                symbol=symbol,
                type='limit',
                side='buy',
                amount=float(amount),
                price=float(current_price),
                params={'timeout': 30000}
            )

            # Actualizar estado
            self.active_position = True
            self.current_symbol = symbol
            self.entry_price = current_price
            self.stop_price = current_price * (1 - Decimal(str(trailing_percent)))
            self.position_size = amount
            if take_profit:
                self.take_profit = current_price * (1 + Decimal(str(take_profit)))

            self.logger.info(
                f"COMPRA | {symbol} | "
                f"Precio: {current_price:.8f} | "
                f"Size: {amount:.8f} | "
                f"Stop: {self.stop_price:.8f}" +
                (f" | TP: {self.take_profit:.8f}" if take_profit else "")
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
                self.logger.warning("No hay posición activa")
                return False

            # Obtener balance
            balance = self.exchange.fetch_balance()
            currency = self.current_symbol.split('/')[0]
            amount = Decimal(str(balance['free'][currency])).quantize(Decimal('0.00000001'))

            # Intentar orden limit primero
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
            except Exception:
                # Fallback a market order
                order = self.exchange.create_order(
                    symbol=self.current_symbol,
                    type='market',
                    side='sell',
                    amount=float(amount),
                    params={'timeout': 30000}
                )
                self.logger.warning(f"VENTA MERCADO | {order['id']}")

            # Resetear estado
            self.active_position = False
            self.current_symbol = None
            self.entry_price = None
            self.stop_price = None
            self.position_size = Decimal('0')
            self.take_profit = None
            return True
        except Exception as e:
            self.logger.critical(f"Error en venta: {str(e)}", exc_info=True)
            return False

    def manage_orders(self):
        """Gestiona stops y toma de ganancias"""
        while not self._shutdown_event.is_set():
            try:
                with self._lock:
                    if not self.active_position:
                        time.sleep(10)
                        continue

                    ticker = self.exchange.fetch_ticker(self.current_symbol)
                    current_price = Decimal(str(ticker['bid']))

                    # Verificar stop loss
                    if current_price <= self.stop_price:
                        self.logger.info("Stop loss activado")
                        self.execute_sell()
                        continue

                    # Verificar take profit
                    if self.take_profit and current_price >= self.take_profit:
                        self.logger.info("Take profit activado")
                        self.execute_sell()
                        continue

                    # Ajustar trailing stop
                    new_stop = current_price * Decimal('0.98')  # 2% trailing
                    if new_stop > self.stop_price:
                        self.stop_price = new_stop
                        self.logger.debug(f"Nuevo stop: {self.stop_price:.8f}")

                time.sleep(60)  # Verificar cada minuto
            except Exception as e:
                self.logger.error(f"Error en gestión de órdenes: {str(e)}")
                time.sleep(300)

    def shutdown(self):
        """Apagado seguro del bot"""
        self._shutdown_event.set()
        if self.active_position:
            self.execute_sell()
        self.logger.info("Bot detenido correctamente")

# =============================================
# ENDPOINTS API WEB
# =============================================
def validate_webhook(f):
    """Middleware de validación para webhooks"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        data = request.get_json()
        if not data:
            return jsonify({"error": "No se proporcionaron datos"}), 400

        required = ['action', 'symbol']
        if not all(k in data for k in required):
            return jsonify({"error": "Faltan campos requeridos"}), 400

        if data['action'].lower() == 'buy' and 'trailing_stop' not in data:
            return jsonify({"error": "Falta trailing_stop para compra"}), 400

        return f(*args, **kwargs)
    return wrapper

@app.route('/webhook', methods=['POST'])
@validate_webhook
def handle_webhook():
    """Endpoint principal para trading"""
    try:
        data = request.get_json()
        symbol = data['symbol'].upper().replace('-', '/')

        if data['action'].lower() == 'buy':
            trailing = float(data.get('trailing_stop', 0.02))
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
                    "take_profit": take_profit
                }), 200

            return jsonify({"error": response}), 400

        return jsonify({"error": "Acción no soportada"}), 400
    except Exception as e:
        app.logger.error(f"Error en webhook: {str(e)}", exc_info=True)
        return jsonify({"error": "Error interno del servidor"}), 500

# =============================================
# INICIALIZACIÓN Y EJECUCIÓN
# =============================================
def run_server():
    """Inicia el servidor de producción"""
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
atexit.register(bot.shutdown)

if __name__ == '__main__':
    print("""
    ====================================
    🚀 TRADING BOT - MODO PRODUCCIÓN
    ====================================
    Exchange: Kraken
    Webhook: POST /webhook
    ====================================
    """)
    run_server()