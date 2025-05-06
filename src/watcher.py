from src.watcher import Watcher
from src.database import db_manager
from src.exchange import exchange_client

watcher = Watcher(db=db_manager, exchange=exchange_client)
watcher.start()