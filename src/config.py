# watcher.py

import threading
import time
import logging

from src.config import WATCH_INTERVAL
from src.database import DatabaseManager
from src.exchange import KrakenClient

logger = logging.getLogger("Watcher")

class Watcher:
    def __init__(self, interval: float = WATCH_INTERVAL):
        self.interval = interval
        self.db = DatabaseManager()
        self.client = KrakenClient()
        self._stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        logger.info("Starting watcher loop with interval %s seconds", self.interval)
        self.thread.start()

    def stop(self):
        logger.info("Stopping watcher loop")
        self._stop_event.set()
        self.thread.join()

    def _run(self):
        while not self._stop_event.is_set():
            try:
                self.check_positions()
            except Exception as e:
                logger.error("Error in watcher loop: %s", str(e))
            time.sleep(self.interval)

    def check_positions(self):
        positions = self.db.get_open_positions()
        for pos in positions:
            ticker = self.client.fetch_ticker(pos.symbol).get('last')
            if ticker is None:
                continue
            # update highest price and stop price
            pos.highest_price = max(pos.highest_price or ticker, ticker)
            pos.stop_price = pos.highest_price * (1.0 - pos.trailing_pct)
            self.db.update_position(pos)

            # if price falls below stop, execute limit sell
            if ticker <= pos.stop_price:
                logger.info(
                    "Triggering trailing stop for %s: sell %s @ %s",
                    pos.symbol, pos.amount, pos.stop_price
                )
                self.client.create_limit_order(
                    symbol=pos.symbol,
                    side='sell',
                    amount=pos.amount,
                    price=pos.stop_price
                )
                pos.status = 'closed'
                self.db.update_position(pos)