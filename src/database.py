# src/database.py
import os
import logging
import json
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
        self._initialize_positions_table()

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

    def initialize(self):
        """Inicialización pública para el sistema de componentes"""
        if not self.pool:  # Solo inicializar si no existe el pool
            self._initialize_pool()
        self._test_connection()
        logger.info("DatabaseManager inicializado")

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

    def log_webhook(self, request_data: dict, response_data: dict, status_code: int) -> None:
        try:
            self.execute_query(
                """INSERT INTO webhook_logs 
                (request_data, response_data, status_code) 
                VALUES (%s, %s, %s)""",
                (json.dumps(request_data), json.dumps(response_data), status_code)  # Requiere importación
            )
        except Exception as e:
            logger.error(f"Error registrando webhook: {str(e)}")

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

    def _initialize_positions_table(self) -> None:
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS positions (
            id SERIAL PRIMARY KEY,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            amount NUMERIC NOT NULL,
            entry_price NUMERIC NOT NULL,
            trailing_pct NUMERIC NOT NULL,
            highest_price NUMERIC NOT NULL,
            stop_price NUMERIC NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        )
        """
        self.execute_query(create_table_sql)

    def add_position(self, symbol: str, side: str, amount: float, entry_price: float, trailing_pct: float, highest_price: float, stop_price: float) -> int:
        insert_sql = """
        INSERT INTO positions (symbol, side, amount, entry_price, trailing_pct, highest_price, stop_price)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """
        result = self.execute_query(insert_sql, (symbol, side, amount, entry_price, trailing_pct, highest_price, stop_price))
        return result[0][0] if result else None

    def get_open_positions(self) -> List[Tuple]:
        select_sql = "SELECT * FROM positions WHERE status = 'open'"
        return self.execute_query(select_sql)

    def update_position(self, position_id: int, highest_price: float, stop_price: float, status: Optional[str] = None) -> None:
        if status is not None:
            update_sql = """
            UPDATE positions
            SET highest_price = %s, stop_price = %s, status = %s
            WHERE id = %s
            """
            params = (highest_price, stop_price, status, position_id)
        else:
            update_sql = """
            UPDATE positions
            SET highest_price = %s, stop_price = %s
            WHERE id = %s
            """
            params = (highest_price, stop_price, position_id)
        self.execute_query(update_sql, params)

# Instancia global para uso en otros módulos
db_manager = DatabaseManager()