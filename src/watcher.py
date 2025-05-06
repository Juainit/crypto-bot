import threading
import time
import logging

from .database import DatabaseManager
from .exchange import exchange_client
from . import config

logger = logging.getLogger(__name__)

db_manager = DatabaseManager()

class Watcher:
    def __init__(self, interval: float = config.WATCH_INTERVAL):
        self.interval = interval
        self._thread = None
        self._stop = threading.Event()

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            logger.info("Position watcher thread started")

    def _run(self):
        logger.info("Watcher loop started, polling every %s seconds", self.interval)
        while not self._stop.is_set():
            try:
                open_positions = db_manager.get_open_positions()
                for pos in open_positions:
                    ticker_data = exchange_client.fetch_ticker(pos.symbol)
                    last_price = ticker_data['last']
                    if last_price > pos.highest_price:
                        pos.highest_price = last_price
                    pos.stop_price = pos.highest_price * (1 - pos.trailing_pct)
                    db_manager.update_position(pos)

                    if last_price <= pos.stop_price:
                        logger.info(
                            "Trailing stop hit for %s: last=%.8f stop=%.8f",
                            pos.symbol, last_price, pos.stop_price
                        )
                        exchange_client.create_limit_order(
                            symbol=pos.symbol,
                            side='sell',
                            amount=pos.amount,
                            price=pos.stop_price
                        )
                        pos.status = 'closed'
                        db_manager.update_position(pos)
                time.sleep(self.interval)
            except Exception:
                logger.exception("Error in watcher loop, retrying after interval")
                time.sleep(self.interval)

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join()