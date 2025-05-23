# signals.py
import logging
import time
from typing import Dict, Optional, Any

logger = logging.getLogger("SignalProcessor")
logger.setLevel(logging.INFO)

class SignalProcessor:
    """
    Procesador profesional de señales de trading con:
    - Validación avanzada de campos
    - Normalización de símbolos compatible con Kraken
    - Manejo de errores estructurado
    - Registro de auditoría
    """
    
    def __init__(self):
        self._configure_validations()
        self.initialized = False
        self._last_processed = {}

    def initialize(self):
        """Inicialización explícita del componente"""
        if not self.initialized:
            logger.info("Inicializando procesador de señales")
            self.initialized = True

    def _configure_validations(self):
        """Configuración centralizada de reglas de validación"""
        self.validation_rules = {
            'required_fields': ['action', 'symbol', 'trailing_stop'],
            'action_values': ['buy', 'sell'],
            'trailing_stop_range': (0.001, 0.2),  # 0.1% a 20%
            'symbol_blacklist': ['TESTNET', 'FAKE']  # Pares problemáticos [4][6]
        }

    def process_signal(self, raw_signal: Dict) -> Optional[Dict]:
        """Procesamiento principal de señales"""
        try:
            logger.debug("Señal recibida: %s", raw_signal)
            
            if not self._validate_signal(raw_signal):
                return None
                
            normalized = self._normalize_signal(raw_signal)
            logger.info("Señal normalizada: %s", normalized)
            
            if self._is_duplicate(normalized):
                logger.warning("Señal duplicada ignorada")
                return None
                
            return normalized
            
        except Exception as e:
            logger.error(f"Error procesando señal: {str(e)}", exc_info=True)
            return None

    def _validate_signal(self, signal: Dict) -> bool:
        """Validación de nivel profesional"""
        # Validación de campos requeridos
        if not all(field in signal for field in self.validation_rules['required_fields']):
            logger.warning(f"Señal incompleta: {signal}")
            return False
            
        # Validación de acción permitida
        if signal['action'].lower() not in self.validation_rules['action_values']:
            logger.error(f"Acción inválida: {signal['action']}")
            return False
            
        # Validación de trailing stop
        trailing = float(signal.get('trailing_stop', 0))
        min_t, max_t = self.validation_rules['trailing_stop_range']
        if not (min_t <= trailing <= max_t):
            logger.error(f"Trailing stop fuera de rango: {trailing}")
            return False
            
        # Validación de símbolos bloqueados [4][6]
        symbol = self._normalize_symbol(signal['symbol'])
        if symbol in self.validation_rules['symbol_blacklist']:
            logger.error(f"Símbolo bloqueado: {symbol}")
            return False
            
        return True

    def _normalize_signal(self, raw_signal: Dict) -> Dict:
        """Normalización profesional de formatos"""
        return {
            'action': raw_signal['action'].lower(),
            'symbol': self._normalize_symbol(raw_signal['symbol']),
            'trailing_stop': round(float(raw_signal['trailing_stop']), 4),
            'timestamp': time.time(),
            'take_profit': round(float(raw_signal.get('take_profit', 0)), 4) if 'take_profit' in raw_signal else None
        }

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """Mapeo exacto requerido por Kraken [4][6]"""
        kraken_symbols = {
            'REP/EUR': 'XREPZEUR',
            'XREP/EUR': 'XREPZEUR',
            'REPZEUR': 'XREPZEUR',
            'XREPZEUR': 'XREPZEUR'  # ← Clave crítica añadida
        }
        return kraken_symbols.get(symbol.upper().replace(' ', ''), symbol.upper())
        
        # Separar base y quote
        parts = symbol.upper().replace('-', '/').split('/')
        if len(parts) != 2:
            return symbol.replace('/', '')
            
        base, quote = parts
        base = symbol_mappings.get(base, base)
        
        return f"{base}{quote}"

    def _is_duplicate(self, signal: Dict) -> bool:
        """Detección profesional de duplicados (MEJORADO) [6][8]"""
        key_fields = (signal['symbol'], signal['action'], signal['trailing_stop'])
        current_hash = hash(frozenset(key_fields))
        
        if current_hash == self._last_processed.get(signal['symbol']):
            return True
            
        self._last_processed[signal['symbol']] = current_hash
        return False

# Instancia preconfigurada para uso global
signal_processor = SignalProcessor()