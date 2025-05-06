#!/usr/bin/env python3
import os
import logging
from time import sleep
from typing import Dict, Any
from src.web_server import run_server
from src.config import config
from src.database import db_manager  # Nueva importación

# Configuración profesional de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('production.log')
    ]
)
logger = logging.getLogger('Main')

class StartupValidator:
    """Verificación profesional de entorno y componentes"""
    
    @staticmethod
    def print_production_banner() -> None:
        """Banner seguro para producción"""
        banner = f"""
        ==============================
        🚀 Crypto Trading Bot (Production)
        - Version: {os.getenv('APP_VERSION', '1.1.0')}
        - Environment: {config.ENVIRONMENT}
        - Port: {config.WEB_SERVER_PORT}
        - Capital: {config.INITIAL_CAPITAL}€
        ==============================
        """
        print(banner)
        logger.info("Iniciando servicio en modo: %s", config.ENVIRONMENT)

    @staticmethod
    def verify_environment() -> None:
        """Verificación profesional de entorno"""
        required_vars = {
            'KRAKEN_API_KEY': config.KRAKEN_API_KEY,
            'KRAKEN_SECRET': config.KRAKEN_SECRET,
            'DATABASE_URL': config.DATABASE_URL
        }
        
        logger.info("=== VERIFICACIÓN DE ENTORNO ===")
        for var, value in required_vars.items():
            logger.info("%-15s: %s", var, "Configurado" if value else "Faltante")
        
        if not all(required_vars.values()):
            logger.critical("Faltan variables críticas de entorno")
            raise EnvironmentError("Configuración incompleta")

    @staticmethod
    def perform_system_checks() -> None:
        """Chequeos profesionales del sistema"""
        logger.info("=== CHEQUEO DE SISTEMA ===")
        
        # 1. Verificar conexión a PostgreSQL
        try:
            db_status = "OK" if db_manager.test_connection() else "Error"
            logger.info("PostgreSQL: %s", db_status)
        except Exception as e:
            logger.error("Error conexión PostgreSQL: %s", str(e))
            raise

        # 2. Verificar conexión a Kraken
        try:
            from src.exchange import exchange_client
            exchange_client.validate_connection()
            logger.info("Kraken API: Conectado")
        except Exception as e:
            logger.error("Error conexión Kraken: %s", str(e))
            raise

        logger.info("Todos los sistemas operativos")

    @staticmethod
    def initialize_components() -> None:
        """Inicialización profesional de componentes"""
        from concurrent.futures import ThreadPoolExecutor, TimeoutError
        from src.signals import SignalProcessor
        
        components = [
            (db_manager, "Database Manager"),
            (SignalProcessor(), "Signal Processor")
        ]
        
        with ThreadPoolExecutor(max_workers=2) as executor:
            for component, name in components:
                try:
                    future = executor.submit(component.initialize)
                    future.result(timeout=10)
                    logger.info("%s inicializado", name)
                except TimeoutError:
                    logger.error("%s: Timeout de inicialización", name)
                    raise
                except Exception as e:
                    logger.error("%s: Error de inicialización - %s", name, str(e))
                    raise

def main() -> None:
    try:
        # Fase 1: Pre-inicialización
        StartupValidator.print_production_banner()
        
        # Fase 2: Verificación de entorno
        StartupValidator.verify_environment()
        
        # Fase 3: Chequeos del sistema
        StartupValidator.perform_system_checks()
        
        # Fase 4: Inicialización de componentes
        StartupValidator.initialize_components()

        from src.watcher import Watcher
        watcher = Watcher()
        watcher.start()

        import atexit
        atexit.register(watcher.stop)
        
        # Fase 5: Lanzamiento del servicio
        logger.info("Iniciando servidor web en puerto %d", config.WEB_SERVER_PORT)
        run_server()

    except Exception as e:
        logger.critical("Error crítico durante el inicio: %s", str(e), exc_info=True)
        db_manager.log_error("startup_failure", str(e))  # Registro en DB
        raise SystemExit(1) from e

if __name__ == '__main__':
    main()