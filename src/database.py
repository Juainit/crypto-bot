# database.py
import psycopg2
import logging
import time
from typing import Optional, Dict, Any
from urllib.parse import urlparse
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor
from src.config import config  # Importar configuración centralizada

logger = logging.getLogger("Database")

class DatabaseManager:
    """Gestor profesional de conexiones PostgreSQL con:
    - Pool de conexiones seguro
    - Reconexión automática
    - Timeouts configurados
    - Soporte SSL para producción
    """
    
    def __init__(self):
        self.pool = None
        self._initialize_pool()
        self._test_connection()

    def _initialize_pool(self) -> None:
        """Configuración profesional del connection pool"""
        try:
            parsed = urlparse(config.DATABASE_URL)
            
            # Parámetros esenciales
            db_params = {
                'host': parsed.hostname,
                'port': parsed.port or 5432,
                'user': parsed.username,
                'password': parsed.password,
                'database': parsed.path[1:],
                'sslmode': 'require' if config.IS_PRODUCTION else 'prefer',
                'connect_timeout': 15,  # 15 segundos máximo para conectar
                'options': f"-c statement_timeout={30000}"  # 30 segundos por query
            }

            self.pool = ThreadedConnectionPool(
                minconn=5,
                maxconn=20,
                **db_params
            )
            
            logger.info(
                f"Pool PostgreSQL inicializado | "
                f"Host: {parsed.hostname}:{parsed.port} | "
                f"SSL: {db_params['sslmode'].upper()}"
            )
            
        except Exception as e:
            logger.critical(f"Error inicializando pool: {str(e)}")
            raise

    def _test_connection(self) -> None:  # Línea 59
        """Verificación profesional de conexión inicial"""
        retries = 3  # ← Ahora SÍ está indentado
        for attempt in range(retries):
            try:
                conn = self.get_connection()
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT 1 AS test")
                    result = cur.fetchone()
                    if result['test'] != 1:
                        raise ValueError("Test query fallida")
                logger.info("Conexión a PostgreSQL verificada")
                self.release_connection(conn)
                return
            except Exception as e:
                if attempt == retries - 1:
                    logger.error(f"Fallo conexión BD después de {retries} intentos")
                    raise
                logger.warning(f"Reintentando conexión ({attempt + 1}/{retries})...")
                time.sleep(2 ** attempt)

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

    def log_error(self, error_type: str, message: str) -> None:
        """Registro profesional de errores en DB"""
        query = """
            INSERT INTO errors (type, message, timestamp)
            VALUES (%s, %s, NOW())
        """
        self.execute_query(query, (error_type, message))

    def _reconnect(self) -> None:
        """Reconexión profesional tras fallos"""
        logger.info("Intentando reconexión a PostgreSQL...")
        try:
            self.pool.closeall()
            self._initialize_pool()
        except Exception as e:
            logger.critical(f"Reconexión fallida: {str(e)}")
            raise

    def execute_query(self, query: str, params: tuple = None) -> Optional[Dict]:
        """Ejecuta consultas con seguridad profesional"""
        conn = self.get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                if cur.rowcount > 0 and cur.description:
                    return cur.fetchall()
                return None
        except psycopg2.Error as e:
            logger.error(f"Error en query: {str(e)}")
            conn.rollback()
            raise
        finally:
            self.release_connection(conn)

    def transactional(self, queries: list) -> bool:
        """Ejecuta transacciones ACID profesionales"""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                for query, params in queries:
                    cur.execute(query, params)
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Rollback transacción: {str(e)}")
            conn.rollback()
            return False
        finally:
            self.release_connection(conn)

# Instancia global preconfigurada
db_manager = DatabaseManager()