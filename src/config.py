import os

# Capital inicial para el bot
INITIAL_CAPITAL  = float(os.getenv("INITIAL_CAPITAL", 40.0))
# Puerto en el que arranca Flask/Waitress
WEB_SERVER_PORT  = int(os.getenv("WEB_SERVER_PORT", 3000))
# Intervalo (en segundos) para el watcher
WATCH_INTERVAL   = float(os.getenv("WATCH_INTERVAL", 30.0))

# Kraken API credentials
KRAKEN_API_KEY = os.getenv("KRAKEN_API_KEY")
KRAKEN_SECRET = os.getenv("KRAKEN_SECRET")

# Database connection URL
DATABASE_URL = os.getenv("DATABASE_URL")
