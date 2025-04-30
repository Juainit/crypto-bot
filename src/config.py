import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    KRAKEN_API_KEY = os.getenv("KRAKEN_API_KEY")
    KRAKEN_SECRET = os.getenv("KRAKEN_SECRET")
    WEB_SERVER_PORT = int(os.getenv("PORT", 3000))
    INITIAL_CAPITAL = 40.0  # EUR
    FEE_RATE = 0.0026
    MIN_ORDER_SIZE = 10  # EUR