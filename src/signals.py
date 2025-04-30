class SignalProcessor:
    @staticmethod
    def validate_signal(signal):
        required_fields = ['action', 'symbol', 'price', 'trailing_stop']
        return all(field in signal for field in required_fields)
    
    @staticmethod
    def process_signal(signal):
        if signal['action'] == 'buy':
            return {
                'symbol': signal['symbol'],
                'price': float(signal['price']),
                'trailing_stop': float(signal['trailing_stop'])
            }
        return None