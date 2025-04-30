from flask import Flask, request, jsonify
from .bot import TradingBot
from .config import Config
import logging

app = Flask(__name__)
bot = TradingBot()
logger = logging.getLogger(__name__)

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    try:
        data = request.json
        logger.info(f"Señal recibida: {data}")
        
        if not valid_signal(data):
            return jsonify({"status": "error", "message": "Señal inválida"}), 400
        
        if data['action'].lower() == 'buy' and not bot.active_position:
            success = bot.execute_buy(
                symbol=data['symbol'],
                price=data['price']
            )
            
            if success:
                bot.trailing_percent = data['trailing_stop_percent']
                bot.current_symbol = data['symbol']
                Thread(target=bot.manage_trailing_stop).start()
                return jsonify({"status": "success", "capital": f"{bot.current_capital:.2f}€"})
        
        return jsonify({"status": "ignored"})
    
    except Exception as e:
        logger.error(f"Error procesando webhook: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

def valid_signal(data):
    required = ['action', 'symbol', 'price', 'trailing_stop_percent']
    return all(key in data for key in required)

def run_server():
    app.run(
        host='0.0.0.0',
        port=Config.WEB_SERVER_PORT,
        debug=False,
        use_reloader=False
    )