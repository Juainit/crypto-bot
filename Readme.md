
Consideraciones del asistente, obligaciones:

1. Los conocimientos de programación son muy limitados de la persona a la que se dirige el asistente. El asistente debe mostrar los pasos 1 por 1, nunca mas de una secuencia de más de dos pasos.
3. El asistente nunca debe mostrar las modificaciones de codigo aisladas, en otras palabras, el asistente siempre debe mostrar el codigo listo y entero para que la persona lo copie entero y lo pegue entero. Siempre se debe proporcionar el bloque de código entero para copiar, no solo una línea. Si es solo una línea, crear todo el bloque. 
4. Se dispone de Terminal, Visual Studio Code, Github, Railway, Tradingview. Docker Desktop, se valora Github desktop.


Objetivos del bot:
1. comprar barato y vender caro, obteniendo así beneficios.
Dos fases:
Fase1: 
El bot recibe señales de compra, alertas de tradingview, de un algoritmo realizado en pinescript. 
La plataforma exchange es Kraken.
El bot compra a precio límite, y se asegura de comprar de verdad a límite. El bot vende a límite también, y se asegura de vender a límite. 
Cuando ha comprado, aplica el trailing stop que le ha venido definido por el mensaje de tradingview. 
El algoritmo de tradingview genera múltiples alarmas, así que si el bot ha comprado una moneda, y recibe más alertas de compra de esa moneda, debe ignorarlas porque ya la ha comprado. Solo debe aceptar la primera alarma después de haber vendido.
Entiendo que el bot necesita una base de datos donde registrar las acciones para calcular las reacciones, por ejemplo, saber a qué precio se ha comprado para saber a qué precio se va a vender. A partir de aquí, todo lo que el asistente crea oportno para mejorar la toma de decisiones para obtener mayores beneficios será bienvenido. entiendo que para ello, también es importante conocer el fee de cada operación. 
El bot inicia una compra de 40€ de ese activo, después reinvierte siempre en base a los beneficios o perdidas anteriores. Si en la primera operación ha ganado 10€, pues en la segunda empieza con 50€. Si en la siguiente ha perdido 5, pues cuando vuelva a arrancar, arrancará con 45€.
El manejo de logs, erroes e información es vital. 

Fase2
Convertimos los scripts de pinescript a python, y los hacemos correr en una máquina local que genera las alarmas.
Esta máquina local se conecta al exchange, evalúa de todas las monedas cuáles presentan una mayor volatilidad (%), y en base a las lógicas diseñadas, valida que el resultado del algoritmo (antes pinescrip después python) se ajuste a momento de compra o venta para todas las monedas que se ajusten a los parámetros. (Los parámetros tienen métricas de 3D, 1D y 3H) y realiza los calculos necesarios para no solamente generar señales de compra, sino también para decidir cuando vender, o trailing o lo que sea. Trabajar en local directamente con el exchange será un logro. No se dispone todavia de una máquina local.

Fase3
Definir una interficie gràfica.

Github del proyecto https://github.com/Juainit/crypto-bot
Debo crear un nuevo servicio en Railway cuando tenga hecho el repositorio hecho en github.


