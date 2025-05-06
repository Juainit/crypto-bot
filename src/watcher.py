# src/watcher.py
from src.config   import WATCH_INTERVAL
from src.database import db_manager
from src.exchange import exchange_client
import time
import threading
import logging

logger = logging.getLogger("Watcher")

class Watcher:
    def __init__(self, interval: float = WATCH_INTERVAL):
        self.interval = interval
        self.db = db_manager
        self.exchange = exchange_client
        self.running = False
        self.thread = None

    def start(self):
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._run)
            self.thread.start()
            logger.info("Watcher started")

    def stop(self):
        if self.running:
            self.running = False
            self.thread.join()
            logger.info("Watcher stopped")

    def _run(self):
        while self.running:
            try:
                self.check_positions()
            except Exception as e:
                logger.error(f"Error in watcher loop: {e}")
            time.sleep(self.interval)

    def check_positions(self):
        positions = self.db.get_open_positions()
        for position in positions:
            symbol = position['symbol']
            current_price = self.exchange.get_price(symbol)
            trailing_stop = position.get('trailing_stop')

            if trailing_stop is None or current_price > trailing_stop:
                new_trailing_stop = current_price * 0.98  # example trailing stop at 2% below current price
                self.db.update_position_trailing_stop(position['id'], new_trailing_stop)
                logger.info(f"Updated trailing stop for {symbol} to {new_trailing_stop}")

            if current_price <= trailing_stop:
                self.exchange.close_position(position['id'])
                self.db.close_position(position['id'])
                logger.info(f"Closed position {position['id']} for {symbol} due to trailing stop hit")