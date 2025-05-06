

import time
import threading
import logging

from database import DatabaseManager
from exchange import KrakenClient
from trading_engine import TradingEngine
import config

logger = logging.getLogger(__name__)

class Watcher:
    def __init__(self):
        self.db = DatabaseManager()
        self.exchange = KrakenClient(api_key=config.KRAKEN_API_KEY, secret=config.KRAKEN_SECRET)
        self.engine = TradingEngine(self.exchange, self.db)
        self.interval = config.WATCH_INTERVAL

    def _run(self):
        logger.info("Watcher loop started, polling every %s seconds", self.interval)
        while True:
            try:
                open_positions = self.db.get_open_positions()
                for pos in open_positions:
                    ticker_data = self.exchange.fetch_ticker(pos.symbol)
                    last_price = ticker_data['last']
                    if last_price > pos.highest_price:
                        pos.highest_price = last_price
                    pos.stop_price = pos.highest_price * (1 - pos.trailing_pct)
                    self.db.update_position(pos)

                    if last_price <= pos.stop_price:
                        logger.info(
                            "Trailing stop hit for %s: last=%.8f stop=%.8f",
                            pos.symbol, last_price, pos.stop_price
                        )
                        self.engine.execute_limit_order(
                            symbol=pos.symbol,
                            side='sell',
                            amount=pos.amount,
                            price=pos.stop_price
                        )
                        pos.status = 'closed'
                        self.db.update_position(pos)
                time.sleep(self.interval)
            except Exception:
                logger.exception("Error in watcher loop, retrying after interval")
                time.sleep(self.interval)

    def start(self):
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()
        logger.info("Position watcher thread started")