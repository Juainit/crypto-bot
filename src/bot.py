import logging
from threading import Thread
from .exchange import ExchangeClient
from .config import Config

class TradingBot:
    def __init__(self):
        self.exchange = ExchangeClient()
        self.current_capital = Config.INITIAL_CAPITAL
        self.active_position = False
        self.current_stop_loss = None
        self.trailing_percent = None
        self.current_symbol = None

    def execute_buy(self, symbol, price):
        if self.active_position or self.current_capital < Config.MIN_ORDER_SIZE:
            return False
            
        try:
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
            return True
            
        except Exception as e:
            logging.error(f"Buy error: {str(e)}")
            return False

    def _update_balance_after_buy(self, order):
        cost = float(order['amount']) * float(order['price'])
        fee = self.exchange.calculate_fees(cost)
        self.current_capital -= (cost + fee)
        self.active_position = True

    def manage_trailing_stop(self):
        # Implementación similar a versión anterior
        pass