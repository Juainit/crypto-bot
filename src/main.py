#!/usr/bin/env python3
import os
import logging
from src.web_server import run_server
from src.signals import SignalProcessor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')
    ]
)

logger = logging.getLogger(__name__)

def print_banner():
    """Display startup information"""
    banner = f"""
    ==============================
    🚀 Crypto Trading Bot (Production)
    - Version: 1.0.0
    - Endpoint: /webhook
    - Capital: 40.00€
    - Risk Control: Active
    - Trailing Stop Range: 0.5%-20%
    ==============================
    """
    print(banner)
    logger.info("Application starting")

def check_environment():
    """Verify required environment variables"""
    required_vars = ['KRAKEN_API_KEY', 'KRAKEN_SECRET', 'DATABASE_URL']
    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        logger.critical(f"Missing environment variables: {missing}")
        raise EnvironmentError(f"Required env vars missing: {missing}")

def main():
    try:
        check_environment()
        print_banner()
        
        # Initialize components
        SignalProcessor()  # Warm up signal processor
        
        # Start web server
        run_server()
        
    except Exception as e:
        logger.critical(f"Fatal startup error: {str(e)}", exc_info=True)
        raise

if __name__ == '__main__':
    main()