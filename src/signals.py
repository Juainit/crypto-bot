import logging
from typing import Dict, Optional, Union

class SignalProcessor:
    """
    Enhanced signal processor with:
    - Strict validation
    - Symbol normalization
    - Error handling
    - Logging
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """Convert FXSEUR → FXS/EUR if needed"""
        if isinstance(symbol, str):
            if 'EUR' in symbol and '/' not in symbol:
                return symbol.replace('EUR', '/EUR')
        return symbol

    def validate_signal(self, signal: Dict) -> bool:
        """Improved validation matching your bot's requirements"""
        required_fields = {
            'action': ['buy'],  # Supported actions
            'symbol': str,
            'trailing_stop': (float, int)  # Accepts both number types
        }
        
        try:
            # Check all required fields exist
            if not all(field in signal for field in required_fields):
                self.logger.warning(f"Missing fields in signal: {signal}")
                return False
                
            # Validate action type
            if signal['action'].lower() not in required_fields['action']:
                self.logger.warning(f"Invalid action: {signal['action']}")
                return False
                
            # Validate trailing stop value
            trailing_stop = float(signal['trailing_stop'])
            if not 0.001 <= trailing_stop <= 0.2:  # 0.1% to 20% range
                self.logger.warning(f"Trailing stop {trailing_stop} out of bounds")
                return False
                
            return True
            
        except (ValueError, TypeError) as e:
            self.logger.error(f"Validation error: {str(e)}")
            return False

    def process_signal(self, signal: Dict) -> Optional[Dict]:
        """Process and standardize signals for your bot"""
        if not self.validate_signal(signal):
            return None
            
        try:
            return {
                'action': signal['action'].lower(),
                'symbol': self._normalize_symbol(signal['symbol']),
                'trailing_stop': float(signal['trailing_stop'])
                # price is intentionally omitted as your bot calculates it
            }
        except Exception as e:
            self.logger.error(f"Processing failed: {str(e)}")
            return None


# Initialize for immediate use (matches your current structure)
processor = SignalProcessor()

# Maintain backwards compatibility with your existing methods
validate_signal = SignalProcessor.validate_signal
process_signal = SignalProcessor.process_signal