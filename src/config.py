import os
import logging
from typing import Optional

class Config:
    """
    Clase de configuración robusta para producción con:
    - Validación de variables obligatorias
    - Manejo seguro de secrets
    - Tipado estático
    """
    
    def __init__(self, debug_mode: bool = False):
        self._logger = logging.getLogger(self.__class__.__name__)
        self._debug_mode = debug_mode
        
        # Cargar variables inmediatamente
        self._validate_core()
        
        if debug_mode:
            self._log_config_state()

    def _validate_core(self) -> None:
        """Valida variables obligatorias"""
        if not all([self.KRAKEN_API_KEY, self.KRAKEN_SECRET]):
            self._logger.critical("Faltan credenciales de Kraken")
            raise EnvironmentError("Configuración incompleta")

    @property
    def KRAKEN_API_KEY(self) -> str:
        """API Key de Kraken (requerida)"""
        key = os.getenv("KRAKEN_API_KEY")
        if not key:
            raise ValueError("KRAKEN_API_KEY no configurada")
        return key

    @property
    def KRAKEN_SECRET(self) -> str:
        """API Secret de Kraken (requerida)"""
        secret = os.getenv("KRAKEN_SECRET")
        if not secret:
            raise ValueError("KRAKEN_SECRET no configurada")
        return secret

    @property
    def WEB_SERVER_PORT(self) -> int:
        """Puerto del servidor web (opcional)"""
        try:
            return int(os.getenv("PORT", "3000"))
        except ValueError:
            self._logger.warning("PORT inválido, usando 3000")
            return 3000

    @property
    def INITIAL_CAPITAL(self) -> float:
        """Capital inicial en EUR (opcional)"""
        try:
            return float(os.getenv("INITIAL_CAPITAL", "40.0"))
        except ValueError:
            self._logger.warning("INITIAL_CAPITAL inválido, usando 40.0")
            return 40.0

    @property
    def DEBUG_MODE(self) -> bool:
        """Modo desarrollo (no usar en producción)"""
        return self._debug_mode

    def _log_config_state(self) -> None:
        """Log seguro con información sensible enmascarada"""
        debug_info = {
            'KRAKEN_API_KEY': self._redact_key(self.KRAKEN_API_KEY),
            'KRAKEN_SECRET': '*****' if self.KRAKEN_SECRET else None,
            'WEB_SERVER_PORT': self.WEB_SERVER_PORT,
            'INITIAL_CAPITAL': self.INITIAL_CAPITAL,
            'DEBUG_MODE': self.DEBUG_MODE
        }
        self._logger.debug("Configuración activa: %s", debug_info)

    @staticmethod
    def _redact_key(key: str) -> Optional[str]:
        """Enmascara parcialmente API keys"""
        if not key:
            return None
        return f"{key[:4]}...{key[-2:]}" if len(key) > 6 else "****"

# Inicialización segura para producción
try:
    config = Config(debug_mode=os.getenv("DEBUG_MODE", "false").lower() == "true")
except Exception as e:
    logging.critical(f"Error fatal en configuración: {str(e)}")
    raise