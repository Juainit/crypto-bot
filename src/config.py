# config.py
import os
import logging
from typing import Optional

logger = logging.getLogger("Config")

class Config:
    """
    Configuración profesional para entornos de producción con:
    - Validación estricta de variables
    - Enmascaramiento de datos sensibles
    - Soporte para PostgreSQL y Kraken
    """
    
    def __init__(self):
        self._validate_core()
        self._log_config_state()
    
    def _validate_core(self) -> None:
        """Valida variables críticas para producción"""
        missing = []
        if not self.KRAKEN_API_KEY:
            missing.append("KRAKEN_API_KEY")
        if not self.KRAKEN_SECRET:
            missing.append("KRAKEN_SECRET")
        if not self.DATABASE_URL:
            missing.append("DATABASE_URL")
        
        if missing:
            logger.critical("Variables faltantes: %s", ", ".join(missing))
            raise EnvironmentError("Configuración incompleta")
    
    @property
    def KRAKEN_API_KEY(self) -> str:
        """API Key de Kraken (requerida)"""
        return os.getenv("KRAKEN_API_KEY", "").strip()
    
    @property
    def KRAKEN_SECRET(self) -> str:
        """API Secret de Kraken (requerida)"""
        return os.getenv("KRAKEN_SECRET", "").strip()
    
    @property
    def DATABASE_URL(self) -> str:
        """URL de PostgreSQL (usa DATABASE_URL en producción)"""
        if self.IS_PRODUCTION:
            return os.getenv("DATABASE_URL", "")  # Corregido para Railway [4]
        return os.getenv("PUBLIC_DATABASE_URL", "")
    
    @property
    def WEB_SERVER_PORT(self) -> int:
        """Puerto HTTP (usa variable PORT en producción)"""
        if self.IS_PRODUCTION:
            return int(os.getenv("PORT", "3000"))
        return int(os.getenv("WEB_SERVER_PORT", "3000"))
    
    @property
    def INITIAL_CAPITAL(self) -> float:
        """Capital inicial en EUR (valor seguro por defecto)"""
        try:
            return float(os.getenv("INITIAL_CAPITAL", "40.0"))
        except ValueError:
            logger.warning("INITIAL_CAPITAL inválido, usando 40.0")
            return 40.0
    
    @property
    def IS_PRODUCTION(self) -> bool:
        """Detecta entorno de producción (Railway)"""
        return bool(os.getenv("RAILWAY_ENVIRONMENT"))
    
    @property
    def ENVIRONMENT(self) -> str:
        """Entorno actual (production/staging)"""
        return os.getenv("ENVIRONMENT", "production")
    
    @property
    def SSL_DATABASE(self) -> bool:
        """Habilita SSL para PostgreSQL en producción"""
        return self.IS_PRODUCTION
    
    def _redact_key(self, key: str) -> Optional[str]:
        """Enmascara datos sensibles para logging"""
        if not key:
            return None
        return f"{key[:2]}***{key[-2:]}" if len(key) > 4 else "****"
    
    def _log_config_state(self) -> None:
        """Log seguro de configuración inicial"""
        debug_info = {
            'KRAKEN_API_KEY': self._redact_key(self.KRAKEN_API_KEY),
            'KRAKEN_SECRET': '*****' if self.KRAKEN_SECRET else None,
            'DATABASE_HOST': self.DATABASE_URL.split('@')[-1].split('/')[0] if self.DATABASE_URL else None,
            'WEB_PORT': self.WEB_SERVER_PORT,
            'INITIAL_CAPITAL': self.INITIAL_CAPITAL,
            'MODO': "PRODUCCIÓN" if self.IS_PRODUCTION else "DESARROLLO"
        }
        logger.info("Configuración activa: %s", debug_info)

# Inicialización segura
try:
    config = Config()
except Exception as e:
    logger.critical("Error fatal en configuración: %s", str(e))
    raise
    @property
    def WATCH_INTERVAL(self) -> int:
        """Intervalo de vigilancia del precio en segundos"""
        return int(os.getenv("WATCH_INTERVAL", "30"))