import os
import time
import json
import logging
import threading
import psutil
import psycopg2
from threading import Thread, Lock, Event
from typing import Dict, Optional, Tuple, Any
from decimal import Decimal, getcontext
from ccxt import ExchangeError, NetworkError
from flask import jsonify
from .config import config
from .exchange import ExchangeClient

# Configuración de precisión decimal
getcontext().prec = 8

class TradingBot:
    """
    Trading Bot profesional con:
    - Gestión de posiciones atómica
    - Mecanismos de emergencia
    - Monitoreo de rendimiento mejorado
    - Sistema completo de health checks
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.exchange = ExchangeClient()
        self._shutdown_event = Event()
        
        # Locks para concurrencia
        self.lock = Lock()  # Para estado principal
        self.db_lock = Lock()  # Para operaciones DB
        
        # Estado inicial
        self._reset_state()
        self._init_db()
        
        # Sistemas de monitoreo
        self._start_health_monitor()
        self._start_performance_tracker()

    def _reset_state(self) -> None:
        """Inicialización segura del estado"""
        with self.lock:
            self.active_position = False
            self.current_symbol = None
            self.position_id = None
            self.entry_price = Decimal('0')
            self.stop_price = Decimal('0')
            self.position_size = Decimal('0')
            self.last_update = time.time()

    def _init_db(self, max_retries: int = 5) -> None:
        """Conexión robusta a PostgreSQL con reintentos"""
        for attempt in range(max_retries):
            try:
                with self.db_lock:
                    self.conn = psycopg2.connect(
                        config.DATABASE_URL,
                        connect_timeout=5,
                        keepalives=1,
                        keepalives_idle=30
                    )
                    self._create_tables()
                    self.logger.info("Conexión a DB establecida")
                    return
            except Exception as e:
                if attempt == max_retries - 1:
                    self.logger.critical("Fallo en conexión a DB")
                    raise
                backoff = min(2 ** attempt, 30)
                time.sleep(backoff)
                self.logger.warning(f"Reintento DB {attempt + 1}/{max_retries}")

    def _create_tables(self) -> None:
        """Inicialización segura de tablas"""
        with self.db_lock, self.conn.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(10) NOT NULL,
                    entry_price DECIMAL(16,8) NOT NULL,
                    stop_price DECIMAL(16,8) NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    closed_at TIMESTAMPTZ,
                    pnl DECIMAL(16,8)
                );
                CREATE TABLE IF NOT EXISTS performance_metrics (
                    timestamp TIMESTAMPTZ PRIMARY KEY,
                    data JSONB NOT NULL
                );
            """)
            self.conn.commit()

    # ======================
    # OPERACIONES DE TRADING
    # ======================
    
    def execute_buy(self, symbol: str, trailing_percent: float) -> Tuple[bool, str]:
        """
        Ejecuta compra con validación completa
        """
        with self.lock:
            if self.active_position:
                msg = f"Posición activa en {self.current_symbol}"
                self.logger.warning(msg)
                return False, msg
                
            try:
                # Validación de mercado
                ticker = self.exchange.get_ticker(symbol)
                if not ticker or 'ask' not in ticker:
                    return False, "Datos de mercado inválidos"
                
                # Cálculos precisos
                limit_price = Decimal(str(ticker['ask'])) * Decimal('1.01')
                amount = Decimal(config.INITIAL_CAPITAL) / limit_price
                
                # Ejecución orden
                order = self.exchange.create_order({
                    'symbol': symbol,
                    'type': 'limit',
                    'side': 'buy',
                    'amount': float(amount.quantize(Decimal('0.00000001'))),
                    'price': float(limit_price.quantize(Decimal('0.01')))
                })
                
                # Actualización de estado
                stop_price = limit_price * (1 - Decimal(str(trailing_percent)))
                self._update_position(symbol, limit_price, stop_price, True)
                
                # Inicio de trailing stop
                Thread(
                    target=self._manage_trailing_stop,
                    daemon=True,
                    name=f"TrailingStop-{symbol}"
                ).start()
                
                msg = f"Compra: {amount:.8f} {symbol} @ {limit_price:.2f}€"
                self.logger.info(msg)
                return True, msg
                
            except NetworkError as e:
                self.logger.error(f"Error de red: {str(e)}")
                return False, "Error de conexión"
            except ExchangeError as e:
                self.logger.error(f"Error exchange: {str(e)}")
                return False, "Error en operación"
            except Exception as e:
                self.logger.error(f"Error inesperado: {str(e)}", exc_info=True)
                self._reset_state()
                return False, f"Error: {str(e)}"

    def _manage_trailing_stop(self) -> None:
        """Gestión activa del trailing stop"""
        retry_delay = 60  # Segundos iniciales
        
        while not self._shutdown_event.is_set():
            try:
                with self.lock:
                    if not self.active_position:
                        break
                        
                    ticker = self.exchange.get_ticker(self.current_symbol)
                    current_price = Decimal(str(ticker['bid']))
                    
                    # Actualización dinámica
                    new_stop = current_price * (1 - self.trailing_percent)
                    if new_stop > self.stop_price:
                        self.stop_price = new_stop
                        self._update_stop_price()
                    
                    # Verificación de activación
                    if current_price <= self.stop_price:
                        self._execute_sell()
                        break
                
                retry_delay = 60  # Resetear delay
                time.sleep(retry_delay)
                
            except Exception as e:
                self.logger.error(f"Error trailing stop: {str(e)}")
                retry_delay = min(retry_delay * 2, 300)  # Backoff exponencial
                time.sleep(retry_delay)

    def _execute_sell(self) -> None:
        """Ejecuta venta con fallback a mercado"""
        with self.lock:
            try:
                amount = self._get_position_amount()
                if amount <= Decimal('0'):
                    raise ValueError("Cantidad inválida")
                
                # 1. Intento con orden limitada
                try:
                    order = self.exchange.create_order({
                        'symbol': self.current_symbol,
                        'type': 'limit',
                        'side': 'sell',
                        'amount': float(amount.quantize(Decimal('0.00000001'))),
                        'price': float(self.stop_price.quantize(Decimal('0.00000001')))
                    })
                except Exception:
                    # 2. Fallback a mercado
                    order = self.exchange.create_order({
                        'symbol': self.current_symbol,
                        'type': 'market',
                        'side': 'sell',
                        'amount': float(amount.quantize(Decimal('0.00000001')))
                    })
                
                # 3. Actualización consistente
                pnl = self._calculate_pnl()
                self._update_position(None, None, None, False)
                self.logger.info(f"Venta ejecutada. PnL: {pnl:.2f}€")
                
            except Exception as e:
                self.logger.critical(f"Error crítico en venta: {str(e)}")
                raise
            finally:
                self._reset_state()

    # ======================
    # MÉTODOS DE MONITOREO
    # ======================
    
    def _start_health_monitor(self) -> None:
        """Inicia hilo de monitoreo de salud"""
        def monitor():
            while not self._shutdown_event.is_set():
                try:
                    self._check_system_health()
                    time.sleep(300)  # 5 minutos
                except Exception as e:
                    self.logger.error(f"Monitor falló: {str(e)}")
                    time.sleep(600)
        
        Thread(target=monitor, daemon=True, name="HealthMonitor").start()

    def _start_performance_tracker(self) -> None:
        """Inicia hilo de métricas de rendimiento"""
        def tracker():
            while not self._shutdown_event.is_set():
                try:
                    self._log_performance_metrics()
                    time.sleep(300)  # 5 minutos
                except Exception as e:
                    self.logger.error(f"Tracker falló: {str(e)}")
                    time.sleep(600)
        
        Thread(target=tracker, daemon=True, name="PerformanceTracker").start()

    def _check_system_health(self) -> Dict[str, bool]:
        """Verificación completa del sistema"""
        return {
            'database': not self.conn.closed,
            'exchange': self._check_exchange_connectivity(),
            'position': self._verify_position_state(),
            'memory': psutil.virtual_memory().percent < 90,
            'cpu': psutil.cpu_percent(interval=1) < 80
        }

    def _log_performance_metrics(self) -> None:
        """Registro de métricas clave"""
        metrics = {
            'timestamp': time.time(),
            'positions': self._count_open_positions(),
            'performance': float(self._calculate_pnl()),
            'exchange_latency': self._measure_latency(),
            'system': {
                'memory': psutil.virtual_memory().percent,
                'cpu': psutil.cpu_percent(interval=1)
            }
        }
        self.logger.info(f"Métricas: {metrics}")
        
        # Persistencia en DB
        with self.db_lock, self.conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO performance_metrics (timestamp, data)
                VALUES (to_timestamp(%s), %s)
                ON CONFLICT (timestamp) DO UPDATE
                SET data = EXCLUDED.data
            """, (metrics['timestamp'], json.dumps(metrics)))
            self.conn.commit()

    # ======================
    # MÉTODOS AUXILIARES
    # ======================
    
    def _get_position_amount(self) -> Decimal:
        """Obtiene cantidad disponible del activo"""
        with self.lock:
            if not self.active_position:
                return Decimal('0')
            balance = self.exchange.fetch_balance()
            currency = self.current_symbol.split('/')[0]
            return Decimal(str(balance['free'].get(currency, 0)))

    def _calculate_pnl(self) -> Decimal:
        """Calcula ganancias/pérdidas actuales"""
        with self.lock:
            if not self.active_position:
                return Decimal('0')
            ticker = self.exchange.get_ticker(self.current_symbol)
            current_price = Decimal(str(ticker['bid']))
            return (current_price - self.entry_price) * (Decimal(config.INITIAL_CAPITAL) / self.entry_price)

    def _measure_latency(self) -> float:
        """Mide latencia del exchange"""
        start = time.time()
        try:
            self.exchange.fetch_time()
            return (time.time() - start) * 1000  # ms
        except Exception:
            return -1

    def _update_position(self, symbol: Optional[str], 
                        entry_price: Optional[Decimal], 
                        stop_price: Optional[Decimal], 
                        is_open: bool) -> None:
        """Actualización atómica de posición"""
        with self.db_lock:
            cursor = self.conn.cursor()
            try:
                if is_open:
                    cursor.execute("""
                        INSERT INTO positions
                        (symbol, entry_price, stop_price)
                        VALUES (%s, %s, %s)
                        RETURNING id
                    """, (
                        symbol,
                        float(entry_price) if entry_price else None,
                        float(stop_price) if stop_price else None
                    ))
                    self.position_id = cursor.fetchone()[0]
                else:
                    pnl = self._calculate_pnl()
                    cursor.execute("""
                        UPDATE positions
                        SET closed_at = NOW(),
                            pnl = %s
                        WHERE id = %s
                    """, (
                        float(pnl) if pnl else None,
                        self.position_id
                    ))
                self.conn.commit()
            except Exception as e:
                self.conn.rollback()
                raise

    def _update_stop_price(self) -> None:
        """Actualiza stop price en DB"""
        with self.db_lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                UPDATE positions
                SET stop_price = %s
                WHERE id = %s
            """, (float(self.stop_price), self.position_id))
            self.conn.commit()

    def _verify_position_state(self) -> bool:
        """Verifica consistencia estado-DB"""
        with self.db_lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM positions
                WHERE closed_at IS NULL
            """)
            return cursor.fetchone()[0] == (1 if self.active_position else 0)

    def _count_open_positions(self) -> int:
        """Cuenta posiciones abiertas"""
        with self.db_lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM positions
                WHERE closed_at IS NULL
            """)
            return cursor.fetchone()[0]

    def shutdown(self) -> None:
        """Apagado controlado"""
        self._shutdown_event.set()
        with self.lock:
            if self.active_position:
                self._execute_sell()
        with self.db_lock:
            if hasattr(self, 'conn') and not self.conn.closed:
                self.conn.close()

# Instancia global con manejo de shutdown
bot_instance = TradingBot()
import atexit
atexit.register(bot_instance.shutdown)