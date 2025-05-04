# src/database.py
import os
import logging
import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from urllib.parse import urlparse
from typing import Optional, Union, List, Tuple

logger = logging.getLogger('Database')

class DatabaseManager:
    """
    Gestor profesional de conexiones PostgreSQL con:
    - Pool de conexiones seguro para threads
    - Reconexión automática
    - Logging detallado
    """
    
    def __init__(self):
        self.pool = None
        self._initialize_pool()
        self._test_connection()

    def _initialize_pool(self) -> None:
        """Configuración profesional del connection pool"""
        try:
            parsed = urlparse(os.getenv("DATABASE_URL"))
            db_params = {
                'host': parsed.hostname,
                'port': parsed.port or 5432,
                'user': parsed.username,
                'password': parsed.password,
                'database': parsed.path[1:],
                'sslmode': 'require',
                'connect_timeout': 15
            }
            
            self.pool = ThreadedConnectionPool(
                minconn=5,
                maxconn=20,
                **db_params
            )
            logger.info("Pool PostgreSQL inicializado")
            
        except Exception as e:
            logger.critical(f"Error inicializando pool: {str(e)}")
            raise

    def _test_connection(self) -> bool:
        """Verificación profesional de conexión inicial"""
        try:
            conn = self.get_connection()
            conn.cursor().execute("SELECT 1")
            self.release_connection(conn)
            return True
        except Exception as e:
            logger.error(f"Error probando conexión: {str(e)}")
            return False

    def test_connection(self) -> bool:
        """Versión pública del test de conexión"""
        return self._test_connection()

    def get_connection(self):
        """Obtiene conexión del pool con manejo de errores"""
        try:
            return self.pool.getconn()
        except psycopg2.OperationalError as e:
            logger.error(f"Error de conexión: {str(e)}")
            self._reconnect()
            return self.pool.getconn()

    def release_connection(self, conn) -> None:
        """Devuelve conexión al pool de forma segura"""
        try:
            if not conn.closed:
                self.pool.putconn(conn)
        except Exception as e:
            logger.error(f"Error liberando conexión: {str(e)}")

    def close(self) -> None:
        """Cierre profesional del pool"""
        if self.pool:
            self.pool.closeall()
            logger.info("Pool PostgreSQL cerrado")

    def execute_query(self, query: str, params: Tuple = None) -> Optional[List]:
        """Ejecuta consultas con manejo de errores"""
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(query, params or ())
            
            if query.strip().upper().startswith("SELECT"):
                return cursor.fetchall()
                
            conn.commit()
            return None
            
        except Exception as e:
            logger.error(f"Error en query: {str(e)}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                self.release_connection(conn)

    def log_error(self, error_type: str, message: str) -> None:
        """Registro profesional de errores en DB"""
        try:
            self.execute_query(
                "INSERT INTO errors (type, message) VALUES (%s, %s)",
                (error_type, message)
            )
        except Exception as e:
            logger.error(f"Error registrando fallo: {str(e)}")

# Instancia global para uso en otros módulos
db_manager = DatabaseManager()