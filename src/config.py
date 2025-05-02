import os
from dotenv import load_dotenv
from typing import Optional
import logging

class Config:
    """
    Production configuration with:
    - Environment validation
    - Type hints
    - Sensitive data protection
    - Runtime checks
    """
    
    def __init__(self):
        self._load_environment()
        self._validate()

    def _load_environment(self):
        """Load .env file with production safeguards"""
        try:
            if not load_dotenv():
                logging.warning("No .env file found - using system environment")
        except Exception as e:
            logging.critical(f"Environment loading failed: {str(e)}")
            raise

    def _validate(self):
        """Validate critical configuration"""
        if not all([self.KRAKEN_API_KEY, self.KRAKEN_SECRET]):
            logging.critical("Missing Kraken API credentials")
            raise EnvironmentError("Kraken API keys not configured")

    @property
    def KRAKEN_API_KEY(self) -> str:
        """Securely access API key with validation"""
        key = os.getenv("KRAKEN_API_KEY")
        if not key or len(key) != 56:  # Kraken key length
            raise ValueError("Invalid Kraken API key format")
        return key

    @property
    def KRAKEN_SECRET(self) -> str:
        """Securely access API secret"""
        secret = os.getenv("KRAKEN_SECRET")
        if not secret or len(secret) != 84:  # Kraken secret length
            raise ValueError("Invalid Kraken secret format")
        return secret

    @property
    def WEB_SERVER_PORT(self) -> int:
        """Get port with fallback"""
        return int(os.getenv("PORT", "3000"))

    @property
    def INITIAL_CAPITAL(self) -> float:
        """Validated trading capital"""
        capital = float(os.getenv("INITIAL_CAPITAL", "40.0"))
        if capital < 10:  # Minimum order size
            raise ValueError("Capital must be ≥10€")
        return capital

    @property
    def FEE_RATE(self) -> float:
        """Validated fee rate"""
        rate = float(os.getenv("FEE_RATE", "0.0026"))  # 0.26%
        if not 0 < rate < 0.01:  # Sanity check
            raise ValueError("Invalid fee rate")
        return rate

    @property
    def MIN_ORDER_SIZE(self) -> float:
        """Exchange minimum order threshold"""
        return 10.0  # Kraken's minimum in EUR


# Singleton instance for shared configuration
config = Config()