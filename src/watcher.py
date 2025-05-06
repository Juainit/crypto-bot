import time
import threading
import logging
from src.config import WATCH_INTERVAL
from src.database import DatabaseManager
from src.exchange import KrakenClient
from src.trading_engine import TradingEngine

class Watcher:
    def __init__(
        self,
        engine: TradingEngine,
        db: DatabaseManager,
        exchange: KrakenClient,
        interval: float = WATCH_INTERVAL
    ):
        self.engine = engine
        self.db = db
        self.exchange = exchange
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        logging.info("Starting Watcher thread")
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self):
        logging.info("Stopping Watcher thread")
        self._stop_event.set()
        if self._thread:
            self._thread.join()

    def _run(self):
        logging.info("Watcher loop started, polling every %s seconds", self.interval)
        while not self._stop_event.is_set():
            try:
                positions = self.db.get_open_positions()
                for pos in positions:
                    ticker = self.exchange.fetch_ticker(pos.symbol)['last']
                    # update highest and stop prices
                    pos.highest_price = max(pos.highest_price or ticker, ticker)
                    pos.stop_price = pos.highest_price * (1 - pos.trailing_pct)
                    self.db.update_position(pos)
                    # trigger trailing-stop sell if price has dropped
                    if ticker <= pos.stop_price:
                        logging.info(
                            "Trigger trailing-stop sell for %s at %s",
                            pos.symbol, pos.stop_price
                        )
                        self.engine.execute_limit_order(
                            symbol=pos.symbol,
                            side='sell',
                            amount=pos.amount,
                            price=pos.stop_price
                        )
                        pos.status = 'closed'
                        self.db.update_position(pos)
            except Exception:
                logging.exception("Error in Watcher loop")
            time.sleep(self.interval)