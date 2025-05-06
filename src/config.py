import os

# Kraken API credentials
KRAKEN_API_KEY = os.getenv("KRAKEN_API_KEY")
KRAKEN_SECRET = os.getenv("KRAKEN_SECRET")

# Database connection URL
DATABASE_URL = os.getenv("DATABASE_URL")

# Interval (in seconds) between watcher checks
WATCH_INTERVAL = float(os.getenv("WATCH_INTERVAL", "5"))