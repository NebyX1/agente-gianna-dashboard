# Tickets fáciles de escuchar

Gianna usa el número completo del ticket, sin las letras ni los ceros que se agregan al código para mostrarlo ordenado. El mismo número identifica siempre el mismo ticket, aunque haya sido creado otro día.

| Código guardado | Lo que dice Gianna | Lo que podés decir |
| --- | --- | --- |
| IDL-TI-000001 | Ticket número 1 | «Leeme el ticket uno» |
| IDL-TI-000025 | Ticket número 25 | «¿Qué pasó con el ticket terminación veinticinco?» |
| IDL-TI-000123 | Ticket número 123 | «Poné el ticket ciento veintitrés en curso» |

«Terminación 25» significa el número **25**, no cualquier código que termine en esas dos cifras: no selecciona el 125 ni el 1025. Si se nombran varios tickets al pedir un cambio, Gianna necesita aclarar cuál. Una confirmación que nombra otro número no autoriza el cambio revisado.

El código completo, el ID interno, la historia y los comprobantes se conservan. El número hablado no se reinicia por día. No hay que migrar ni reiniciar la base de datos para usar esta mejora. Aunque normalmente el número coincide con el ID interno, Gianna busca el ticket y usa el ID obtenido de la API: nunca supone esa coincidencia.

## Preguntas que podés hacer

- «¿Cuántos tickets de Tránsito tengo activos?»
- «¿Y de la dirección de Sociales?»
- «¿Cuáles son los de Tránsito? Decime diez como máximo»
- «Seguí con los siguientes diez de esa lista»
- «¿Qué problema tiene el ticket terminación 25?»

Por defecto, «de Tránsito» identifica el **área que pide ayuda**, aunque Informática atienda el pedido. Si preguntás por los tickets que recibe o atiende Informática, se consulta el **equipo responsable**.

Activos incluye Nuevo, En curso y En espera. No incluye Resuelto, Cancelado ni tickets ocultos. La cantidad se obtiene del total de la API, no del número de tarjetas ni del tamaño de una página. Gianna cuenta con una consulta breve y, al enumerar, puede avanzar en páginas de hasta diez sin perder resultados entre páginas.

## Cómo se comprueba

Los tests de `tests/unit/test_ticket_references.py` comprueban números hablados, referencias ambiguas, conservación de IDs y comprobantes, cantidades y paginación. `test_review_meaning.py` impide que una referencia a otro ticket llegue al modelo de consentimiento.

`tests/integration/test_ticket_accessibility_live.py` usa DeepSeek real y la API con MariaDB del stack aislado 5400. Crea datos de prueba en varios estados, comprueba cantidades mayores a una página, preguntas consecutivas por área, continuación de listas y lectura por número corto. Exige que la conversación sólo haga lecturas y sintetiza la respuesta real con Piper. Nunca utiliza la base de datos de la demo del usuario.

`test_short_reference_audio.py` comprueba 1, 25 y 123 con voz sintética de Daniela y Whisper real. `test_review_meaning_live.py` agrega confirmaciones por número corto y rechazos cuando se nombra otro ticket o su ID interno. Estas pruebas no representan una medición de reconocimiento con un micrófono humano.

Desde `agent/`, con el stack aislado y los modelos preparados:

```powershell
$env:GIANNA_REAL_E2E = '1'
$env:GIANNA_CLOUD_HARNESS = '1'
.\.venv\Scripts\python.exe -m pytest tests/integration/test_ticket_accessibility_live.py tests/integration/test_short_reference_audio.py tests/integration/test_review_meaning_live.py -q
```
