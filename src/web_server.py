from flask import Flask, request, jsonify
from threading import Thread
from .bot import TradingBot
import logging
import os

app = Flask(__name__)
bot = TradingBot()
logger = logging.getLogger(__name__)

def valid_signal(data):
    """Validate webhook payload structure"""
    required_fields = ['action', 'symbol', 'trailing_stop']
    return all(field in data for field in required_fields)

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    try:
        data = request.get_json()
        logger.info(f"Signal received: {data}")

        if not valid_signal(data):
            return jsonify({"status": "error", "message": "Invalid signal format"}), 400

        # Normalize symbol format (FXSEUR -> FXS/EUR)
        symbol = data['symbol']
        if 'EUR' in symbol and '/' not in symbol:
            symbol = symbol.replace('EUR', '/EUR')

        if data['action'].lower() == 'buy':
            if bot.active_position:
                logger.warning(f"Ignored duplicate signal for {symbol}")
                return jsonify({"status": "ignored", "reason": "Position already open"})

            success = bot.execute_buy(
                symbol=symbol,
                trailing_percent=float(data['trailing_stop'])
            )
            
            if success:
                bot.active_position = True
                bot.current_symbol = symbol
                Thread(target=bot.manage_trailing_stop).start()
                return jsonify({
                    "status": "success",
                    "symbol": symbol,
                    "trailing_stop": data['trailing_stop']
                })

        return jsonify({"status": "ignored"})

    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

def run_server():
    app.run(
        host='0.0.0.0',
        port=int(os.getenv("PORT", 3000)),
        debug=False,
        use_reloader=False
    )

if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    print("""
    ==============================
    🚀 Crypto Trading Bot Online
    - Endpoint: /webhook (POST)
    - Initial capital: 40.00€
    - Risk control: Active
    ==============================
    """)
    run_server()