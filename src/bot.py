# src/bot.py
import os
import psycopg2
import logging
from threading import Thread
from flask import Flask, request, jsonify
from ccxt import kraken

# Configuración inicial
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

class TradingBot:
    def __init__(self):
        self.exchange = kraken({
            'apiKey': os.getenv("KRAKEN_API_KEY"),
            'secret': os.getenv("KRAKEN_SECRET"),
            'enableRateLimit': True
        })
        self.current_capital = float(os.getenv("INITIAL_CAPITAL", 40.0))
        self._init_db()  # Crea la tabla si no existe

    def _get_db_connection(self):
        return psycopg2.connect(os.getenv("DATABASE_URL"))

    def _init_db(self):
        with self._get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS positions (
                        id SERIAL PRIMARY KEY,
                        symbol VARCHAR(10) NOT NULL,
                        buy_price FLOAT NOT NULL,
                        quantity FLOAT NOT NULL,
                        trailing_percent FLOAT NOT NULL,
                        stop_loss FLOAT,
                        fee_paid FLOAT NOT NULL,
                        status VARCHAR(10) DEFAULT 'open',
                        created_at TIMESTAMP DEFAULT NOW(),
                        updated_at TIMESTAMP DEFAULT NOW()
                    );
                """)
                conn.commit()

    def execute_buy(self, symbol, price, trailing_percent):
        try:
            # Cálculo de cantidad y fee
            max_invest = self.current_capital / (1 + 0.0026)  # Fee del 0.26%
            quantity = max_invest / price
            
            # Registra en la base de datos PRIMERO (patrón "store-first")
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO positions 
                        (symbol, buy_price, quantity, trailing_percent, fee_paid, status)
                        VALUES (%s, %s, %s, %s, %s, 'pending')
                        RETURNING id;
                    """, (symbol, price, quantity, trailing_percent, max_invest * 0.0026))
                    position_id = cur.fetchone()[0]
                    conn.commit()

            # Ejecuta la orden real
            order = self.exchange.create_order(
                symbol=symbol,
                type='limit',
                side='buy',
                amount=quantity,
                price=price
            )

            # Actualiza la base de datos
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE positions 
                        SET status = 'open'
                        WHERE id = %s;
                    """, (position_id,))
                    conn.commit()

            self.current_capital -= (quantity * price + (max_invest * 0.0026))
            logging.info(f"Compra registrada en DB. ID: {position_id}")
            return True

        except Exception as e:
            logging.error(f"Error en compra: {str(e)}")
            return False

    def manage_trailing_stop(self, position_id):
        try:
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT symbol, buy_price, trailing_percent 
                        FROM positions 
                        WHERE id = %s AND status = 'open';
                    """, (position_id,))
                    data = cur.fetchone()

            if not data:
                return

            symbol, buy_price, trailing_percent = data

            while True:
                ticker = self.exchange.fetch_ticker(symbol)
                current_price = ticker['last']
                new_stop_loss = current_price * (1 - trailing_percent)

                # Actualiza stop_loss en DB solo si sube
                with self._get_db_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            UPDATE positions 
                            SET stop_loss = GREATEST(%s, COALESCE(stop_loss, 0)),
                                updated_at = NOW()
                            WHERE id = %s
                            RETURNING stop_loss;
                        """, (new_stop_loss, position_id))
                        current_stop_loss = cur.fetchone()[0]
                        conn.commit()

                if current_price <= current_stop_loss:
                    self.execute_sell(position_id)
                    break

                time.sleep(60)  # Verificar cada minuto

        except Exception as e:
            logging.error(f"Error en trailing stop: {str(e)}")

    def execute_sell(self, position_id):
        try:
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT symbol, quantity 
                        FROM positions 
                        WHERE id = %s AND status = 'open';
                    """, (position_id,))
                    symbol, quantity = cur.fetchone()

            order = self.exchange.create_order(
                symbol=symbol,
                type='market',
                side='sell',
                amount=quantity
            )

            # Registra la venta
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE positions 
                        SET status = 'closed',
                            updated_at = NOW()
                        WHERE id = %s;
                    """, (position_id,))
                    conn.commit()

            logging.info(f"Venta ejecutada para posición {position_id}")
            return True

        except Exception as e:
            logging.error(f"Error en venta: {str(e)}")
            return False

# Configuración de Flask
bot = TradingBot()

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    data = request.json
    if not data or 'action' not in data:
        return jsonify({"status": "error", "message": "Invalid signal"}), 400

    if data['action'].lower() == 'buy':
        success = bot.execute_buy(
            symbol=data['symbol'],
            price=float(data['price']),
            trailing_percent=float(data.get('trailing_stop_percent', 0.02))
        
        if success:
            return jsonify({"status": "success"})
    
    return jsonify({"status": "ignored"})

def run_server():
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", 3000)), use_reloader=False)

if __name__ == '__main__':
    run_server()