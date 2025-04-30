from .web_server import run_server
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

if __name__ == '__main__':
    print("""\n🚀 Iniciando Crypto Trading Bot:
    - Capital inicial: 40.00€
    - Servidor web en puerto 3000
    - Control de riesgo activado\n""")
    
    run_server()