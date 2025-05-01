import logging
from threading import Thread
from .exchange import ExchangeClient
from .config import Config

logger = logging.getLogger(__name__)

class TradingBot:
    def __init__(self):
        self.exchange = ExchangeClient()
        self.current_capital = Config.INITIAL_CAPITAL
        self.active_position = False
        self.current_stop_loss = None
        self.trailing_percent = None
        self.current_symbol = None
        self.current_order = None

    def execute_buy(self, symbol, price):
        try:
            if self.active_position or self.current_capital < Config.MIN_ORDER_SIZE:
                logger.warning("No se puede comprar - posición existente o capital insuficiente")
                return False
                
            max_invest = self.current_capital / (1 + Config.FEE_RATE)
            quantity = max_invest / price
            
            order = self.exchange.create_order({
                'symbol': symbol,
                'type': 'limit',
                'side': 'buy',
                'amount': quantity,
                'price': price
            })
            
            self._update_balance_after_buy(order)
            logger.info(f"Orden de compra ejecutada: {order}")
            return True
            
        except Exception as e:
            logger.error(f"Error en compra: {str(e)}")
            return False

    def _update_balance_after_buy(self, order):
        cost = float(order['amount']) * float(order['price'])
        fee = self.exchange.calculate_fees(cost)
        self.current_capital -= (cost + fee)
        self.active_position = True
        self.current_order = order

    def manage_trailing_stop(self):
        try:
            while self.active_position:
                ticker = self.exchange.get_ticker(self.current_symbol)
                current_price = ticker['last']
                
                new_stop_loss = current_price * (1 - self.trailing_percent)
                
                if self.current_stop_loss is None or new_stop_loss > self.current_stop_loss:
                    self.current_stop_loss = new_stop_loss
                    logger.info(f"Actualizado stop loss: {self.current_stop_loss:.4f}")

                if current_price <= self.current_stop_loss:
                    logger.info("Activando stop loss...")
                    self.execute_sell()
                    break

                time.sleep(10)
        except Exception as e:
            logger.error(f"Error en trailing stop: {str(e)}")

    def execute_sell(self):
        try:
            balance = self.exchange.get_balance()
            base_currency = self.current_symbol.split('/')[0]
            quantity = balance[base_currency]['free']
            
            if quantity > 0:
                order = self.exchange.create_order({
                    'symbol': self.current_symbol,
                    'type': 'market',
                    'side': 'sell',
                    'amount': quantity
                })
                
                sell_value = float(order['amount']) * float(order['price'])
                fee = self.exchange.calculate_fees(sell_value)
                self.current_capital += (sell_value - fee)
                
                self.active_position = False
                self.current_stop_loss = None
                logger.info(f"Venta exitosa: {order}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error en venta: {str(e)}")
            return False