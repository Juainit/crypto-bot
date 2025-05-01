# src/bot.py
import os
import time
import psycopg2
import logging
from threading import Thread
from flask import Flask, request, jsonify
from ccxt import kraken

# Configuración
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
app = Flask(__name__)

class TradingBot:
    def __init__(self):
        self.exchange = kraken({
            'apiKey': os.getenv("KRAKEN_API_KEY"),
            'secret': os.getenv("KRAKEN_SECRET"),
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'}
        })
        self.current_capital = float(os.getenv("INITIAL_CAPITAL", 40.0))
        self._init_db()
        self.exchange.load_markets()  # Carga todos los mercados disponibles

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
                        sell_price FLOAT,
                        sell_type VARCHAR(10),
                        status VARCHAR(10) DEFAULT 'open',
                        created_at TIMESTAMP DEFAULT NOW(),
                        updated_at TIMESTAMP DEFAULT NOW()
                    );
                """)
                conn.commit()

    def _validate_symbol(self, symbol):
        """Convierte 'BTCEUR' a formato Kraken (XBT/EUR) y valida"""
        # Pares base de Kraken (ej: XBT para Bitcoin)
        kraken_symbol = symbol.replace("BTC", "XBT").replace("EUR", "EUR")
        if "/" not in kraken_symbol:
            kraken_symbol = f"{kraken_symbol[:3]}/{kraken_symbol[3:]}"
        
        if kraken_symbol not in self.exchange.markets:
            raise ValueError(f"Par no válido: {symbol}")
        return kraken_symbol

    def execute_buy(self, symbol, trailing_percent):
        try:
            # Validar y convertir símbolo (ej: BTCEUR → XBT/EUR)
            kraken_symbol = self._validate_symbol(symbol)
            
            # Obtener precio y calcular límite (+1%)
            ticker = self.exchange.fetch_ticker(kraken_symbol)
            limit_price = round(ticker['ask'] * 1.01, 2)
            max_invest = self.current_capital / 1.0026  # Ajuste por fee 0.26%
            quantity = round(max_invest / limit_price, 6)

            # Registrar en DB
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO positions 
                        (symbol, buy_price, quantity, trailing_percent, fee_paid, status)
                        VALUES (%s, %s, %s, %s, %s, 'pending')
                        RETURNING id;
                    """, (kraken_symbol, limit_price, quantity, trailing_percent, max_invest * 0.0026))
                    position_id = cur.fetchone()[0]
                    conn.commit()

            # Ejecutar orden
            order = self.exchange.create_order(
                symbol=kraken_symbol,
                type='limit',
                side='buy',
                amount=quantity,
                price=limit_price
            )

            # Actualizar DB
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE positions 
                        SET status = 'open'
                        WHERE id = %s;
                    """, (position_id,))
                    conn.commit()

            self.current_capital -= (quantity * limit_price + (max_invest * 0.0026))
            logging.info(f"Compra: {quantity} {kraken_symbol} @ {limit_price}€")
            return position_id

        except Exception as e:
            logging.error(f"Error en compra: {str(e)}")
            return None

    def manage_trailing_stop(self, position_id):
        try:
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT symbol, trailing_percent 
                        FROM positions 
                        WHERE id = %s AND status = 'open';
                    """, (position_id,))
                    symbol, trailing_percent = cur.fetchone()

            while True:
                ticker = self.exchange.fetch_ticker(symbol)
                current_price = ticker['bid']
                new_stop_loss = round(current_price * (1 - trailing_percent), 2)

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

                time.sleep(60)

        except Exception as e:
            logging.error(f"Error en trailing stop: {str(e)}")

    def execute_sell(self, position_id):
        try:
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT symbol, quantity, stop_loss 
                        FROM positions 
                        WHERE id = %s AND status = 'open';
                    """, (position_id,))
                    symbol, quantity, stop_loss = cur.fetchone()

                    # 1. Intento con límite (0.5% bajo stop_loss)
                    limit_price = round(stop_loss * 0.995, 2)
                    try:
                        order = self.exchange.create_order(
                            symbol=symbol,
                            type='limit',
                            side='sell',
                            amount=quantity,
                            price=limit_price
                        )
                        logging.info(f"Venta límite @ {limit_price}€")

                        time.sleep(120)
                        order_status = self.exchange.fetch_order(order['id'], symbol)

                        if order_status['filled'] == 0:
                            self.exchange.cancel_order(order['id'], symbol)
                            raise Exception("Orden límite no ejecutada")

                    except Exception as e:
                        # 2. Fallback a market order
                        logging.warning(f"Fallo límite. Usando market order...")
                        order = self.exchange.create_order(
                            symbol=symbol,
                            type='market',
                            side='sell',
                            amount=quantity
                        )

                    # Actualizar DB
                    cur.execute("""
                        UPDATE positions 
                        SET status = 'closed',
                            sell_price = %s,
                            sell_type = %s,
                            updated_at = NOW()
                        WHERE id = %s;
                    """, (order['price'], 'limit' if 'price' in order else 'market', position_id))
                    conn.commit()

            logging.info(f"Venta exitosa @ {order['price']}€")
            return True

        except Exception as e:
            logging.error(f"Error al vender: {str(e)}")
            return False

# Configuración de Flask
bot = TradingBot()

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    data = request.json
    if not data or 'action' not in data or 'symbol' not in data:
        return jsonify({"status": "error", "message": "Señal inválida"}), 400

    if data['action'].lower() == 'buy':
        try:
            trailing_percent = float(data.get('trailing_stop_percent', 0.02))
            position_id = bot.execute_buy(
                symbol=data['symbol'],  # Ej: "BTCEUR"
                trailing_percent=trailing_percent
            )
            
            if position_id:
                Thread(target=bot.manage_trailing_stop, args=(position_id,)).start()
                return jsonify({"status": "success", "position_id": position_id})
        
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400
    
    return jsonify({"status": "ignored"})

def run_server():
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", 3000)), use_reloader=False)

if __name__ == '__main__':
    print("""
    ==============================
    🚀 Bot activo (Kraken)
    - Formato de símbolo: BTCEUR
    - Endpoint: /webhook
    - Capital inicial: 40.00€
    ==============================
    """)
    run_server()