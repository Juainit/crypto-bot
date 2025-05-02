import os
import time
import psycopg2
import logging
from threading import Thread, Lock
from typing import Dict, Optional
from ccxt import kraken
from flask import jsonify
from .config import config
from .exchange import ExchangeClient

class TradingBot:
    """
    Production-grade trading bot with:
    - Thread-safe position management
    - Automatic trailing stops
    - Database persistence
    - Comprehensive error handling
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.exchange = ExchangeClient()
        self._init_db()
        self._reset_state()
        self.lock = Lock()  # Thread safety for shared state

    def _reset_state(self):
        """Initialize all runtime tracking variables"""
        with self.lock:
            self.active_position = False
            self.current_symbol = None
            self.position_id = None
            self.entry_price = 0.0
            self.trailing_percent = 0.0
            self.stop_price = 0.0

    def _init_db(self):
        """Initialize PostgreSQL connection"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.conn = psycopg2.connect(os.getenv("DATABASE_URL"))
                self._create_tables()
                return
            except Exception as e:
                if attempt == max_retries - 1:
                    self.logger.critical(f"DB connection failed after {max_retries} attempts")
                    raise
                time.sleep(2 ** attempt)
                self.logger.warning(f"DB connection retry {attempt + 1}: {str(e)}")

    def _create_tables(self):
        """Ensure required tables exist"""
        with self.conn.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(10) NOT NULL,
                    entry_price DECIMAL(16,8) NOT NULL,
                    stop_price DECIMAL(16,8) NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            self.conn.commit()

    def execute_buy(self, symbol: str, trailing_percent: float) -> bool:
        """Execute buy order with production safeguards"""
        with self.lock:
            if self.active_position:
                self.logger.warning(f"Ignoring buy - position already open for {self.current_symbol}")
                return False

            try:
                # Calculate order parameters
                ticker = self.exchange.get_ticker(symbol)
                limit_price = round(ticker['ask'] * 1.01, 2)  # Price +1%
                amount = round(config.INITIAL_CAPITAL / limit_price, 8)

                # Place order
                order = self.exchange.create_order({
                    'symbol': symbol,
                    'type': 'limit',
                    'side': 'buy',
                    'amount': amount,
                    'price': limit_price
                })

                # Update state
                self.active_position = True
                self.current_symbol = symbol
                self.entry_price = limit_price
                self.trailing_percent = trailing_percent
                self.stop_price = limit_price * (1 - trailing_percent)

                # Persist position
                with self.conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO positions (symbol, entry_price, stop_price)
                        VALUES (%s, %s, %s)
                        RETURNING id
                    """, (symbol, limit_price, self.stop_price))
                    self.position_id = cursor.fetchone()[0]
                    self.conn.commit()

                self.logger.info(f"Bought {amount} {symbol} @ {limit_price}€")
                return True

            except Exception as e:
                self.logger.error(f"Buy failed: {str(e)}")
                self._reset_state()
                return False

    def manage_trailing_stop(self):
        """Active trailing stop management thread"""
        self.logger.info(f"Starting trailing stop for {self.current_symbol}")
        
        while self.active_position:
            try:
                with self.lock:
                    ticker = self.exchange.get_ticker(self.current_symbol)
                    current_price = ticker['bid']
                    
                    # Update stop price if gaining
                    new_stop = current_price * (1 - self.trailing_percent)
                    if new_stop > self.stop_price:
                        self.stop_price = new_stop
                        self._update_stop_price()
                    
                    # Check if stop triggered
                    if current_price <= self.stop_price:
                        self._execute_sell()
                        break
                    
                time.sleep(60)  # Check every minute
                
            except Exception as e:
                self.logger.error(f"Trailing stop error: {str(e)}")
                time.sleep(300)  # Wait 5 minutes on errors

    def _execute_sell(self):
        """Execute sell order and clean up position"""
        with self.lock:
            try:
                ticker = self.exchange.get_ticker(self.current_symbol)
                sell_price = round(ticker['bid'] * 0.99, 2)  # Price -1%
                
                order = self.exchange.create_order({
                    'symbol': self.current_symbol,
                    'type': 'limit',
                    'side': 'sell',
                    'amount': self._get_position_amount(),
                    'price': sell_price
                })
                
                self.logger.info(f"Sold {self.current_symbol} @ {sell_price}€")
                self._close_position()
                
            except Exception as e:
                self.logger.critical(f"Sell failed: {str(e)}")
                # Emergency market sell attempt
                try:
                    self.exchange.create_order({
                        'symbol': self.current_symbol,
                        'type': 'market',
                        'side': 'sell',
                        'amount': self._get_position_amount()
                    })
                except Exception as emergency_error:
                    self.logger.error(f"Emergency sell failed: {str(emergency_error)}")
                finally:
                    self._close_position()

    def _get_position_amount(self) -> float:
        """Calculate current position amount"""
        balance = self.exchange.get_balance()
        return balance['free'].get(self.current_symbol.split('/')[0], 0)

    def _update_stop_price(self):
        """Persist updated stop price"""
        with self.conn.cursor() as cursor:
            cursor.execute("""
                UPDATE positions SET stop_price = %s
                WHERE id = %s
            """, (self.stop_price, self.position_id))
            self.conn.commit()

    def _close_position(self):
        """Clean up after position closure"""
        with self.conn.cursor() as cursor:
            cursor.execute("""
                UPDATE positions SET closed_at = NOW()
                WHERE id = %s
            """, (self.position_id,))
            self.conn.commit()
        self._reset_state()


# Singleton instance for shared bot
bot_instance = TradingBot()