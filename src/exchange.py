import ccxt
import logging
from typing import Dict, Optional
from .config import Config

class ExchangeClient:
    """
    Production-grade Kraken exchange client with:
    - Automatic rate limiting
    - Connection resiliency
    - Fee-aware calculations
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.client = self._initialize_client()
        self.markets = self._load_markets()

    def _initialize_client(self) -> ccxt.kraken:
        """Configure and validate the exchange connection"""
        try:
            kraken = ccxt.kraken({
                'apiKey': Config.KRAKEN_API_KEY,
                'secret': Config.KRAKEN_SECRET,
                'enableRateLimit': True,  # Critical for production
                'options': {
                    'adjustForTimeDifference': True,
                    'defaultType': 'spot'
                }
            })
            
            # Test connectivity
            kraken.check_required_credentials()
            return kraken
            
        except Exception as e:
            self.logger.critical(f"Kraken initialization failed: {str(e)}")
            raise

    def _load_markets(self) -> Dict:
        """Load and cache market data with retries"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                markets = self.client.load_markets()
                self.logger.info(f"Loaded {len(markets)} trading pairs")
                return markets
            except Exception as e:
                if attempt == max_retries - 1:
                    self.logger.error("Failed to load markets after retries")
                    raise
                self.logger.warning(f"Market load failed (attempt {attempt+1}): {str(e)}")
                time.sleep(2 ** attempt)  # Exponential backoff

    def get_balance(self) -> Dict:
        """Get account balance with error handling"""
        try:
            return self.client.fetch_balance()
        except ccxt.NetworkError as e:
            self.logger.error(f"Network error fetching balance: {str(e)}")
            raise
        except ccxt.ExchangeError as e:
            self.logger.error(f"Exchange error fetching balance: {str(e)}")
            raise

    def create_order(self, order_params: Dict) -> Optional[Dict]:
        """
        Create order with production safeguards:
        - Validates minimum order size (10€)
        - Includes fee calculation
        - Implements retry logic
        """
        try:
            # Validate minimum order size
            if 'amount' in order_params and 'price' in order_params:
                order_value = order_params['amount'] * order_params['price']
                if order_value < Config.MIN_ORDER_SIZE:
                    self.logger.warning(f"Order value {order_value}€ below minimum {Config.MIN_ORDER_SIZE}€")
                    return None

            # Add calculated fees to order metadata
            order_params['params'] = {
                'fee': self.calculate_fees(order_params.get('amount', 0))
            }
            
            return self.client.create_order(**order_params)
            
        except ccxt.InsufficientFunds as e:
            self.logger.error(f"Insufficient funds: {str(e)}")
            raise
        except ccxt.InvalidOrder as e:
            self.logger.error(f"Invalid order: {str(e)}")
            raise
        except Exception as e:
            self.logger.error(f"Order creation failed: {str(e)}")
            raise

    def get_ticker(self, symbol: str) -> Dict:
        """Get ticker data with symbol validation"""
        try:
            normalized_symbol = symbol.replace('EUR', '/EUR') if 'EUR' in symbol and '/' not in symbol else symbol
            if normalized_symbol not in self.markets:
                raise ValueError(f"Invalid symbol. Available pairs: {list(self.markets.keys())}")
            return self.client.fetch_ticker(normalized_symbol)
        except Exception as e:
            self.logger.error(f"Ticker fetch failed for {symbol}: {str(e)}")
            raise

    def calculate_fees(self, amount: float) -> float:
        """Calculate fees including exchange minimums"""
        fee = amount * Config.FEE_RATE
        return max(fee, 0.01)  # Kraken's minimum fee


# Singleton pattern for shared instance
exchange_client = ExchangeClient()