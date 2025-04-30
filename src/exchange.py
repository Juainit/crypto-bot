import ccxt
from .config import Config

class ExchangeClient:
    def __init__(self):
        self.client = ccxt.kraken({
            'apiKey': Config.KRAKEN_API_KEY,
            'secret': Config.KRAKEN_SECRET,
            'enableRateLimit': True
        })
    
    def get_balance(self):
        return self.client.fetch_balance()
    
    def create_order(self, order_params):
        return self.client.create_order(**order_params)
    
    def get_ticker(self, symbol):
        return self.client.fetch_ticker(symbol)
    
    def calculate_fees(self, amount):
        return amount * Config.FEE_RATE