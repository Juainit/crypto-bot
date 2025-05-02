import os
import time
import threading
import json
import logging
import psutil
import atexit
from threading import Thread, Lock, Event
from typing import Dict, Optional, Tuple, Any, List
from decimal import Decimal, getcontext
import psycopg2
import ccxt
from ccxt import kraken
from flask import jsonify
from .config import config
from .exchange import ExchangeClient

# Configuración de precisión decimal
getcontext().prec = 8

class TradingBot:
    """ 
    Trading Bot profesional con gestión avanzada de:
    - Posiciones y órdenes
    - Risk management
    - Performance tracking
    - Sistema de auto-recuperación
    """

    def __init__(self):
        # Configuración inicial
        self.logger = self._setup_logging()
        self.exchange = ExchangeClient()
        self._shutdown_event = Event()
        self.lock = Lock()  # Para operaciones de trading
        self.db_lock = Lock()  # Para operaciones DB
        self.trailing_percent = Decimal('0.02')  # 2% trailing stop

        # Estado inicial
        self._init_db()
        self._reset_state()
        self._start_background_services()

    # === CORE TRADING METHODS ===
    def execute_buy(self, symbol: str, amount: Decimal, price: Decimal) -> Tuple[bool, str]:
        """Ejecuta compra con gestión avanzada de errores"""
        with self.lock:
            try:
                # Validaciones iniciales
                if self.active_position:
                    return False, "Posición ya abierta"
                
                if not self._check_exchange_connectivity():
                    return False, "Exchange no disponible"

                # Ejecución de orden
                order = self.exchange.create_order({
                    'symbol': symbol,
                    'type': 'limit',
                    'side': 'buy',
                    'amount': float(amount.quantize(Decimal('0.00000001'))),
                    'price': float(price.quantize(Decimal('0.00000001')))
                
                # Actualizar estado
                self._update_position(
                    symbol=symbol,
                    entry_price=price,
                    stop_price=price * (Decimal('1') - self.trailing_percent),
                    is_open=True
                )
                
                # Iniciar trailing stop
                Thread(
                    target=self._manage_trailing_stop,
                    daemon=True,
                    name=f"TrailingStop-{symbol}"
                ).start()

                return True, f"Orden ejecutada: {order['id']}"

            except ccxt.NetworkError as e:
                self.logger.error(f"Network error: {str(e)}")
                return False, "Error de conexión"
            except ccxt.ExchangeError as e:
                self.logger.error(f"Exchange error: {str(e)}")
                return False, "Error en el exchange"
            except Exception as e:
                self.logger.critical(f"Critical error: {str(e)}", exc_info=True)
                self._emergency_shutdown()
                return False, "Error crítico"

    def _execute_sell(self) -> None:
        """Venta con sistema de fallback robusto"""
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

                # Actualizar estado
                self._update_position(None, None, None, False)
                self._reset_state()

            except Exception as e:
                self.logger.critical(f"Fallo en venta: {str(e)}")
                self._emergency_shutdown()
                raise

    # === RISK MANAGEMENT ===
    def _manage_trailing_stop(self) -> None:
        """Trailing stop dinámico con backoff exponencial"""
        retry_delay = 5  # Segundos iniciales
        
        while not self._shutdown_event.is_set():
            try:
                with self.lock:
                    if not self.active_position:
                        break

                    ticker = self.exchange.get_ticker(self.current_symbol)
                    current_price = Decimal(str(ticker['bid']))
                    
                    # Actualizar stop
                    new_stop = current_price * (Decimal('1') - self.trailing_percent)
                    if new_stop > self.stop_price:
                        self.stop_price = new_stop
                        self._update_stop_price()
                    
                    # Verificar stop
                    if current_price <= self.stop_price:
                        self._execute_sell()
                        break

                retry_delay = 5  # Reset on success
                time.sleep(retry_delay)

            except Exception as e:
                retry_delay = min(retry_delay * 2, 300)  # Max 5 min
                self.logger.error(f"Trailing stop error (retry in {retry_delay}s): {str(e)}")
                time.sleep(retry_delay)

    # === DATABASE METHODS ===
    def _init_db(self) -> None:
        """Inicialización segura de conexión a DB"""
        try:
            self.conn = psycopg2.connect(
                config.DATABASE_URL,
                connect_timeout=5,
                keepalives=1,
                keepalives_idle=30
            )
            self._create_tables()
        except Exception as e:
            self.logger.critical(f"DB connection failed: {str(e)}")
            raise

    def _update_position(self, symbol: Optional[str], 
                        entry_price: Optional[Decimal],
                        stop_price: Optional[Decimal],
                        is_open: bool) -> None:
        """Actualización atómica de posición"""
        with self.db_lock:
            try:
                with self.conn.cursor() as cursor:
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
                        """, (float(pnl), self.position_id))
                    self.conn.commit()
            except Exception as e:
                self.conn.rollback()
                raise

    # === UTILITIES ===
    def _calculate_pnl(self) -> Decimal:
        """Cálculo preciso de PnL"""
        with self.lock:
            if not self.active_position:
                return Decimal('0')
                
            ticker = self.exchange.get_ticker(self.current_symbol)
            current_price = Decimal(str(ticker['bid']))
            return (current_price - self.entry_price) * self.position_size

    def _get_position_amount(self) -> Decimal:
        """Cantidad disponible con precisión decimal"""
        with self.lock:
            balance = self.exchange.fetch_balance()
            currency = self.current_symbol.split('/')[0]
            return Decimal(str(balance['free'].get(currency, 0))).quantize(Decimal('0.00000001'))

    # === SYSTEM MANAGEMENT ===
    def shutdown(self) -> None:
        """Apagado seguro del bot"""
        self._shutdown_event.set()
        self._save_state()
        self.conn.close()
        self.logger.info("Bot apagado correctamente")

    def _emergency_shutdown(self) -> None:
        """Protocolo de emergencia"""
        self.logger.critical("INICIANDO APAGADO DE EMERGENCIA")
        try:
            if self.active_position:
                self._execute_sell()
        except Exception:
            pass
        finally:
            self.shutdown()

# Instancia global con manejo seguro
bot_instance = TradingBot()
atexit.register(bot_instance.shutdown)