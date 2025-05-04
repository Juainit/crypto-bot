# signals.py
import logging
import time  # Importación faltante en el código original
from typing import Dict, Optional

class SignalProcessor:
    """
    Procesador profesional de señales con:
    - Validación avanzada
    - Normalización de símbolos
    - Manejo de errores estructurado
    - Inicialización explícita
    """
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._configure_validations()
        self.initialized = False  # Nuevo estado de inicialización

    def initialize(self):
        """Inicialización explícita para el sistema de componentes"""
        if not self.initialized:
            self.logger.info("Inicializando procesador de señales")
            # Lógica de inicialización adicional si fuera necesaria
            self.initialized = True

    def _configure_validations(self):
        """Configuración centralizada de reglas de validación"""
        self.validation_rules = {
            'required_fields': ['action', 'symbol', 'trailing_stop'],
            'action_values': ['buy', 'sell'],
            'trailing_stop_range': (0.001, 0.2)  # 0.1% a 20%
        }

    def process_signal(self, raw_signal: Dict) -> Optional[Dict]:
        """Procesamiento profesional de señales"""
        try:
            if not self._validate_signal(raw_signal):
                return None
            return self._normalize_signal(raw_signal)
            
        except Exception as e:
            self.logger.error(f"Error procesando señal: {str(e)}", exc_info=True)
            return None

    def _validate_signal(self, signal: Dict) -> bool:
        """Validación de nivel empresarial"""
        # Validar campos requeridos
        if not all(field in signal for field in self.validation_rules['required_fields']):
            self.logger.warning(f"Señal incompleta: {signal}")
            return False

        # Validar acción permitida
        if signal['action'].lower() not in self.validation_rules['action_values']:
            self.logger.error(f"Acción inválida: {signal['action']}")
            return False

        # Validar rango del trailing stop
        trailing = float(signal.get('trailing_stop', 0))
        min_t, max_t = self.validation_rules['trailing_stop_range']
        if not min_t <= trailing <= max_t:
            self.logger.error(f"Trailing stop fuera de rango: {trailing}")
            return False

        return True

    def _normalize_signal(self, raw_signal: Dict) -> Dict:
        """Normalización profesional de formatos"""
        normalized = {
            'action': raw_signal['action'].lower(),
            'symbol': self._normalize_symbol(raw_signal['symbol']),
            'trailing_stop': round(float(raw_signal['trailing_stop']), 4),
            'timestamp': time.time()
        }

        # Campo opcional: take_profit
        if 'take_profit' in raw_signal:
            normalized['take_profit'] = round(float(raw_signal['take_profit']), 4)

        return normalized

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """Normalización de símbolos según estándares Kraken"""
        symbol = symbol.upper().replace('-', '/')
        if 'EUR' in symbol and '/' not in symbol:
            return symbol.upper().replace('-', '').replace('/', '')
        return symbol

# Instancia preconfigurada para uso global
signal_processor = SignalProcessor()