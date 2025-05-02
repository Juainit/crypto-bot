#!/usr/bin/env python3
import os
import logging
from time import sleep
from typing import Dict, Any
from src.web_server import run_server
from src.signals import SignalProcessor
from src.config import config  # Using our Config class

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

class StartupValidator:
    """Handles pre-launch checks and debug output"""
    
    @staticmethod
    def print_banner() -> None:
        """Display secure startup information"""
        banner = f"""
        ==============================
        🚀 Crypto Trading Bot (Production)
        - Version: {os.getenv('APP_VERSION', '1.0.0')}
        - Environment: {os.getenv('ENV', 'development')}
        - Debug Mode: {config._debug_mode}
        - Capital: {config.INITIAL_CAPITAL}€
        ==============================
        """
        print(banner)
        logger.info("Application starting in %s mode", os.getenv('ENV', 'development'))

    @staticmethod
    def debug_environment() -> None:
        """Secure debug output for environment verification"""
        env_vars = {
            'KRAKEN_API_KEY': config._redact_key(config.KRAKEN_API_KEY),
            'KRAKEN_SECRET': '*****' if config.KRAKEN_SECRET else None,
            'DATABASE_URL': config._mask_url(config.DATABASE_URL),
            'SERVER_PORT': config.WEB_SERVER_PORT,
            'TRADING_CAPITAL': config.INITIAL_CAPITAL
        }
        
        logger.debug("=== ENVIRONMENT VERIFICATION ===")
        for var, value in env_vars.items():
            logger.debug("%-18s: %s", var, value)
        
        # System health check
        logger.debug("System Checks:")
        logger.debug("- Python: %s", os.sys.version.split()[0])
        logger.debug("- PID: %s", os.getpid())
        logger.debug("===============================")

    @staticmethod
    def warmup_components() -> None:
        """Initialize critical components with timeout"""
        from concurrent.futures import ThreadPoolExecutor, TimeoutError
        
        with ThreadPoolExecutor() as executor:
            try:
                future = executor.submit(SignalProcessor)
                future.result(timeout=5)  # 5-second timeout
                logger.info("Signal processor initialized")
            except TimeoutError:
                logger.error("Signal processor warmup timed out")
                raise RuntimeError("Component initialization failed")

def main() -> None:
    try:
        # Phase 1: Pre-initialization
        StartupValidator.print_banner()
        
        if config._debug_mode:
            StartupValidator.debug_environment()
            sleep(1)  # Ensure debug output is visible
        
        # Phase 2: System Verification
        if not all([config.KRAKEN_API_KEY, config.KRAKEN_SECRET]):
            logger.critical("Missing required API credentials")
            raise EnvironmentError("API keys not configured")
        
        # Phase 3: Component Initialization
        StartupValidator.warmup_components()
        
        # Phase 4: Service Launch
        logger.info("Starting web server on port %s", config.WEB_SERVER_PORT)
        run_server()
        
    except Exception as e:
        logger.critical("Startup failed: %s", str(e), exc_info=True)
        raise SystemExit(1) from e

if __name__ == '__main__':
    main()