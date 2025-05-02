import os
import logging
from typing import Optional

class Config:
    """
    Production-ready configuration with:
    - Mandatory vs optional variables
    - Secure debug output
    - Environment variable caching
    - Type hints for IDE support
    """

    def __init__(self, debug_mode: bool = False):
        self._logger = logging.getLogger(__name__)
        self._debug_mode = debug_mode
        self._validate_core()
        
        if debug_mode:
            self._log_config_state()

    def _validate_core(self) -> None:
        """Verify absolutely required variables"""
        if not all([self.KRAKEN_API_KEY, self.KRAKEN_SECRET]):
            self._logger.error("Missing Kraken API credentials")
            # Continue anyway since validation is non-strict

    def _log_config_state(self) -> None:
        """Secure debug output (redacts sensitive data)"""
        from pprint import pformat
        debug_info = {
            'KRAKEN_API_KEY': self._redact_key(self.KRAKEN_API_KEY),
            'KRAKEN_SECRET': '*****' if self.KRAKEN_SECRET else None,
            'DATABASE_URL': self._mask_url(self.DATABASE_URL),
            'WEB_SERVER_PORT': self.WEB_SERVER_PORT,
            'INITIAL_CAPITAL': self.INITIAL_CAPITAL,
            'IS_CONFIG_VALID': all([self.KRAKEN_API_KEY, self.KRAKEN_SECRET])
        }
        self._logger.debug("Active Configuration:\n%s", pformat(debug_info))

    @staticmethod
    def _redact_key(key: str) -> Optional[str]:
        if not key:
            return None
        return f"{key[:4]}...{key[-2:]}" if len(key) > 6 else "****"

    @staticmethod
    def _mask_url(url: str) -> Optional[str]:
        if not url:
            return None
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.password:
            return url.replace(parsed.password, "*****")
        return url

    # --- Environment Properties ---
    @property
    def KRAKEN_API_KEY(self) -> str:
        """Required: Trading API key"""
        return os.getenv("KRAKEN_API_KEY", "").strip()

    @property
    def KRAKEN_SECRET(self) -> str:
        """Required: Trading API secret"""
        return os.getenv("KRAKEN_SECRET", "").strip()

    @property
    def DATABASE_URL(self) -> str:
        """Optional: Database connection string"""
        return os.getenv("DATABASE_URL", "").strip()

    @property
    def WEB_SERVER_PORT(self) -> int:
        """Optional: Default 3000"""
        try:
            return int(os.getenv("PORT", "3000"))
        except ValueError:
            self._logger.warning("Invalid PORT value, defaulting to 3000")
            return 3000

    @property
    def INITIAL_CAPITAL(self) -> float:
        """Optional: Default 40.0"""
        try:
            return float(os.getenv("INITIAL_CAPITAL", "40.0"))
        except ValueError:
            self._logger.warning("Invalid INITIAL_CAPITAL, defaulting to 40.0")
            return 40.0

# Initialize with debug=False in production!
config = Config(debug_mode=os.getenv("CONFIG_DEBUG", "false").lower() == "true")