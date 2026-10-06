# Aceptación local · revisión vigente del 6 de octubre de 2026

## Voz, interrupciones y confirmaciones naturales

La [reparación de voz](voice-confirmation-repair.md) permite confirmar dentro de una oración y recuperar variaciones fonéticas en respuestas de voz. La captura no se reinicia al interrumpir; la interrupción corta la salida. Whisper conserva PCM original, con contexto de idioma/vocabulario y ganancia acotada. La ganancia automática del navegador queda desactivada por defecto para evitar distorsión. Los fallos de reproducción no se presentan como fallos del micrófono.

| Verificación | Resultado | Evidencia |
|---|---|---|
| Lógica y contratos | 619 aprobadas, 21,37 s | `artifacts/gianna-voice-repair-unit-final.log` |
| Interpretación de aprobación con DeepSeek | 40 casos aprobados, 24,86 s; 38 llamadas reales y dos límites de datos literales | `artifacts/gianna-review-meaning-live-final.log` |
| Voz nativa + interfaz/API | Tres recorridos aprobados, 202,87 s | `artifacts/gianna-voice-repair-final-e2e.log` |
| Consola | 21 pruebas aprobadas; lint y build aprobados | `artifacts/gianna-voice-ui-test-final.log` |
| Código cargado y configuración efectiva | Hashes de fuente/consola verificados, micrófono recibiendo, AGC desactivada, cero errores de audio | `artifacts/testing-ready.json` y eventos locales |

El recorrido de interrupción creó exactamente un ticket y verificó su contenido en la API. Cada intervención se dijo una sola vez: negar durante la revisión, retomar y aprobar con «Sí, Gianna, confirmado, podés guardar la operación que acabás de revisar». El corte de salida RTC se midió en 163 y 244 ms desde la detección acústica, con silencio sostenido después. Se comprobaron ocho respuestas cortas a volumen normal y al 18 %, con su transcripción real y significado de aprobación/negación.

La regresión de impresoras exige que el borrador y el ticket correspondan a hojas de papel, además de Secretaría General y la categoría Impresoras. Un intento anterior que produjo «gomas (ocas)» pese a superar las aserciones antiguas se conserva como rechazado por contenido. El recorrido de interfaz verifica creación, cambio a En curso y resolución con motivo, versiones e historial remoto. Las pruebas escriben sólo en el stack aislado de API 5400; las seis operaciones confirmadas de la instancia del usuario permanecen conservadas.

La voz de estas pruebas es Daniela sintética. No se afirma precisión universal para micrófonos, acentos o ruido humano. Se conservaron los intentos rechazados y se realizó respaldo SQLite consistente antes del reinicio. El registro de audio del usuario sigue desactivado.

## Reparación de la conversación reportada

Los resultados históricos de este documento no acreditaban la conversación de las capturas ni comprensión general. El [diagnóstico y la reparación](conversation-repair.md) explican las contradicciones de preparación, pérdida de contexto y comprobante anterior que encontraron las nuevas pruebas. Este apartado es la evidencia vigente para esa reparación; lo que sigue conserva el historial de desarrollo.

Validación final sobre el código que quedó cargado:

| Verificación | Resultado | Evidencia local |
|---|---|---|
| Lógica y contratos | 595 aprobadas, 21,12 s | `artifacts/gianna-repair-unit-final.log` |
| DeepSeek real: conversaciones y categorías | 22 aprobadas, 61,86 s | `artifacts/gianna-harness-repair-cloud-final.log` |
| Interfaz/API y voz nativa | 2 recorridos completos aprobados, 181,05 s | `artifacts/gianna-repair-e2e-final.log` |
| Ruff y esquemas exportados | Aprobados | Comandos de validación del repositorio |

El recorrido desde la interfaz reprodujo los mensajes de las capturas sin sustituir el modelo ni la API. El ticket de prueba `IDL-TI-000033` quedó realmente en `resolved`, con origen Sociales, tipo Impresoras y el detalle de las dos impresoras y el plazo. Hubo exactamente tres operaciones confirmadas: crear, pasar a En curso y resolver. Repetir la confirmación de creación no generó otro ticket. El motivo de resolución indicado en la orden quedó en el historial. Se leyeron todos estos hechos en la API del proyecto aislado, no sólo en una respuesta conversacional.

El otro recorrido usó Daniela sintética por el micrófono nativo de Chromium, WebRTC y Whisper. Verificó preparación, preguntas sobre catálogos, correcciones y un único ticket confirmado contra la API. Su evidencia está en `artifacts/gianna-harness-voice.json/.png`. No prueba eco físico ni precisión para todos los hablantes humanos.

Las 22 conversaciones con DeepSeek usan catálogos y lecturas de tickets de fixture declarados. Cubren el relato exacto, aclaraciones de turnos anteriores, paráfrasis de Sociales, origen/destino, correcciones, consultas, oficinas desconocidas, Internet, hardware y acceso a sistemas. Se evalúa conservación de hechos y resultado de la tarea, aceptando redacciones equivalentes; no se exige un orden literal de palabras. Un área desconocida puede aclararse antes de crear el objeto de borrador, pero el relato debe sobrevivir y completar la revisión al elegir un área válida.

La instancia del usuario se reinició mediante cierre normal, sin operaciones pendientes. Se conservó su conversación y una copia SQLite consistente en su directorio privado de respaldos. `artifacts/testing-ready.json` confirma administrador autenticado, micrófono conectado/recibiendo audio y hashes de agente, política, herramientas nativas, supervisor y revisión iguales a los archivos actuales. Los tickets de la demo del usuario no se usaron para las pruebas de escritura.

Reproducción desde `agent/`:

```powershell
.venv\Scripts\python.exe -m pytest tests/unit tests/contracts -q
$env:GIANNA_CLOUD_HARNESS='1'
.venv\Scripts\python.exe -m pytest tests/integration/test_cloud_harness.py -q -s
$env:GIANNA_REAL_E2E='1'
.venv\Scripts\python.exe -m pytest tests/e2e/test_conversation_repair.py tests/e2e/test_harness_voice.py -q -s
.venv\Scripts\ruff.exe check src tests scripts
.venv\Scripts\python.exe scripts/export_schemas.py --check
```

Los E2E necesitan el proyecto `idl-tickets-design-check` y las credenciales privadas preparadas como indica [pruebas](testing.md). Una prueba omitida no cuenta como aprobación. Las suites son evidencia sobre estos recorridos, no una garantía de entender cualquier conversación futura.

## Historial de aceptación inicial · 4 de octubre de 2026

Implementación y pruebas reales en Windows 11 build 26200, Python 3.12.14, AMD Ryzen 5 5500, 16 GB de RAM, RTX 3050 de 8 GB, driver 591.86, Node 22.15.1 y Ollama 0.35.1. Modelo Tev Q8_0 digest `8d11b3146b7f3f4f4d5e9a64665ab2bdaf8b46e4ec42a5880b60a716ae50e3fb`. Datos de pruebas en compose/DB aislados; la demo del usuario conserva sus volúmenes.

## Resultados

Validación inicial de la etapa: backend MariaDB, 56 pruebas aprobadas; agente unitarios/contratos, 76; consola, 2; frontend tickets, 13; visualizer, 10. Lint/typecheck/build y regeneración de OpenAPI/TS completados. Doctor con inferencias reales: ready. Suite inicial completa de servicios/modelos/audio: **5 aprobadas en 459,07 s**, con motores reales y sin sustitución de STT. Arranque residente listo para login en 15,84 s; la demo de tickets y Gianna devuelven HTTP 200 en sus comprobaciones de salud. Evidencia local ignorada en artifacts/; el archivo separado de credenciales de fixtures es secreto y no forma parte de los informes.

| Escenario solicitado | Evidencia / estado |
|---|---|
| 1 Login normal/2FA y delegación | Browser + SMTP + API/MariaDB reales |
| 2 Activación por audio | Whisper/Tev reales; no endpoint de texto |
| 3 Dictado, corrección y revisión | Tránsito/impresora, descripción corregida por voz |
| 4 Sí y un solo ticket/recibo leído | Una operación/ticket y audit voice_agent |
| 5 Pantalla recibe el ticket | DOM display-ticket del visualizer, sesión viewer |
| 6 Leer/mostrar/buscar | Navegación, heading/ID y filtro observados |
| 7 Ocultar e historia | Voz real; comprobante mínimo aun con GET404; historia en integración |
| 8 Interrumpir/resultado incierto | Barge-in en WebRTC; races unitarias; pérdida posterior al commit real y recuperación sin otro POST |
| 9 120 segundos/reactivar | Espera real, despedida única, nueva voz con transporte conectado |
| 10 Control manual | Preview readonly; formulario nuevo; transferencia durable; sin API+UI duplicados |
| 11 Fallos de componentes | Piper propio detenido/reiniciado; endpoints Tev/API inaccesibles y reconectados; cierre del navegador propio detectado. No se apagó el daemon Ollama del usuario ni se midieron fallos de hardware externo |
| 12 Flujo sin nube | Circuito local sin clave; bloqueo HTTP/HTTPS en harness final |

Los e2e no sustituyen reconocimiento por texto. Usan Daniela sintética en micrófono fixture de Chromium/WebAudio; no prueban eco físico ni calidad para hablantes reales. No se declara «cero errores del modelo». Las invariantes ejecutadas exigen cero duplicados/escrituras sin confirmación requerida/éxitos sin recibo dentro de su suite.

## Actualización de conversación cotidiana

La pregunta «Gianna, ¿estás ahí?» confirma disponibilidad y ofrece ayuda sin crear un borrador. La política separa conversación y dictado: saludar, pedir opciones, agradecer, disculparse, repetir, hablar más despacio, explicar el siguiente paso o resultado, pausar, reanudar y despedirse conservan los datos del pedido. «Finalizá eso» pide aclaración; resolver/cancelar un ticket identificado prepara motivo y revisión antes de confirmar. Las transiciones válidas se consultan en el catálogo, y el recibo se comprueba para el borrador y operación actuales.

Unitarios/contratos actualizados: **256 aprobadas en 14,23 s** (180 más que la etapa inicial). Activación: **10 regresiones aprobadas en 1,84 s**, con filtro de invocación y Tev local real en las candidatas. Ruff y comprobación de esquemas aprobados. Evidencias: `artifacts/gianna-conversation-unit.log` y `gianna-conversation-activation.log`.

También se repitieron y aprobaron individualmente los recorridos de creación por voz (`test_full_voice_ticket_and_safe_preview`) y consulta/ocultamiento/control manual (`test_live_audio_commands.py`), con motores y API reales. La creación conserva la espera real de 120 segundos, la corrección, comprobante y aparición en el visualizador. Los logs `gianna-conversation-final.log` y `gianna-conversation-regression.log` contienen además fallos intermedios de otras pruebas; no se presentan como suites completas aprobadas.

El recorrido nuevo de conversación y finalización por voz aprobó completo: **1 prueba en 211,58 s**, con 15 intervenciones conversacionales más confirmación real. Presencia/ayuda no crearon un pedido; preguntas, agradecimiento, repetición, pausa y despedida conservaron exactamente el borrador. «Finalizá el ticket número 7» preparó Resuelto, pidió motivo y revisión; la confirmación produjo una única operación de cierre, comprobada en API/MariaDB: `IDL-TI-000007`, versión 6 → 7, estado `resolved`, evento 51. Después de la respuesta y reactivación por voz, «Podemos seguir, por favor» recuperó el mismo ID, revisión y payload del borrador anterior y volvió a pedir el origen.

Evidencia del recorrido aprobado: `artifacts/gianna-conversation-complete.log`, `gianna-conversation.json`, `gianna-conversation-events.json` y `gianna-conversation.png`. La prueba mantuvo Whisper/Tev/Piper y WebRTC reales. Dos frases cortas de una ejecución anterior se transcribieron como «Hola Gianna, chao, olví» y «Polación, nos continuamos»: el filtro pidió aclaración/ignoró y no cambió datos ni ejecutó operaciones. Se conservan en `gianna-conversation-resume-rejected.json/.log`; el recorrido final sigue la aclaración hablada con una invocación explícita de ayuda y luego continuar. No se bajó el umbral ni se forzó la transcripción. El resultado acredita ese recorrido con voz sintética, no comprensión perfecta del habla humana.

La demo local tiene la política actual cargada: cuenta Administrador de pruebas, login y delegación normales, consola con micrófono conectado y tickets/visualizador autenticados. `artifacts/testing-ready.json` registra los hashes de la política de conversación y supervisor para verificar qué código se arrancó. El antiguo borrador compuesto únicamente por «¿estás ahí?» se conservó en una copia privada y se retiró de la recuperación automática; no se borraron tickets del servidor.

## Actualización de interpretación por contexto

La interpretación ya no depende de una lista de respuestas completas para confirmar. `dialogue/interpretation.py` compone consentimiento, acción, vocativos y cortesía, consume el enunciado completo y aplica el significado a la revisión vigente. «Eso es todo, Gianna, registra» y «Confirmo Gianna» se reproducen en regresiones de operaciones; una corrección imperativa o declarativa tiene prioridad, una condición o calificación no comprendida conserva los datos, y una corrección sin datos pide completarla. La instrucción de crear se separa del dictado y los nombres dentro de los datos no se eliminan.

Validación actual: **433 unitarios/contratos aprobados**; Ruff y esquemas aprobados. **4 regresiones de clasificación con Tev real aprobadas en 1,30 s**, incluyendo las cinco categorías de la semilla: síntomas de impresión con «inpesora/impesora», red y falta de información. La decisión usa categorías reales y alias, mantiene el umbral .70 y preserva el texto; no reemplaza un tipo ya seleccionado sin una referencia explícita. La invocación mantiene su filtro y umbral .45.

El recorrido nuevo de voz aprobó en **138,60 s**: crear con prefijo, descripción limpia, «Sí, pero el origen es Informática», «No, todavía no», reanudar y aprobación compuesta. Se verificó un único commit real en API/MariaDB: `IDL-TI-000021`, versión 2, evento 54, actor operador. El audio de confirmación llegó primero como «Eso ahora es todo Gianna Registra» y requirió otra solicitud hablada («Eso es todo, registra el pedido»); no se descartaron palabras para autorizar ni se forzó la transcripción.

También aprobó individualmente la regresión de creación/preview/visualizador/120 segundos/reactivación en `gianna-interpretation-voice-final.log`. Ese log contiene un fallo intermedio del otro recorrido por una categoría ausente después de «inpesora», por lo que no se presenta como una suite agregada aprobada. El recorrido terminado y los eventos están en `gianna-interpretation-voice-complete.log`, `gianna-interpretation.json`, `gianna-interpretation-events.json` y `gianna-interpretation.png`; unitarios en `gianna-interpretation-unit-final.log`, clasificación en `gianna-interpretation-classification.log`. Son regresiones de texto y audio sintético con motores reales, no una medición de precisión para hablantes humanos.

La demo se arranca con cuenta de administrador y micrófono conectado. `testing-ready.json` incorpora hashes de conversación, interpretación, slots y supervisor; el cierre del proceso propio se hace estando inactivo y sin operaciones pendientes, conservando una copia privada de SQLite y los tickets del servidor.

## Cambio de flujo · 5 de octubre de 2026

Se eliminó la salida automática de texto desconocido a dictado. Qwen3 4B local identifica primero la intención sin dejar que una pregunta pendiente convierta una intervención social en datos. Sólo las respuestas breves de catálogo ambiguas se vuelven a interpretar en contexto de campo. Tev queda opcional para categorías; no decide activación, conversación o autorización. Contar un incidente ofrece abrir un ticket; aceptar la oferta inicia el borrador y después requiere la revisión y confirmación de envío. La consola muestra el campo pendiente y permite iniciar/descartar con controles explícitos.

Regresiones actuales: 69 casos con el intérprete real aprobados en 32,78 s; consola, 4 pruebas y build/lint aprobados. Se conservan los intentos anteriores con Phi y la primera configuración de Qwen en sus logs: no se contabilizan como aprobados. El banco actual es de regresión y fue usado para corregir la política; no mide precisión en un corpus humano independiente.

El recorrido original de creación, preview bloqueado, visualizador y 120 segundos/reactivación volvió a aprobar. El log agregado `gianna-flow-voice-discard-rejected.log` contiene un fallo del recorrido nuevo: «Descartar borrador» se transcribió como «Descartado al gradador», se rechazó por calidad y pidió repetir sin modificar el pedido. Se conserva en `gianna-flow-discard-rejected-events.json`. Esa ejecución también verificó por voz la frase exacta de la captura: se interpretó como presencia, respondió «Sí, estoy acá y te escucho» y no abrió un borrador.

Validación final del cambio: **464 unitarios/contratos aprobados**, 69 regresiones con el modelo real y 4 pruebas de consola. El recorrido completo nuevo aprobó en **197,53 s**, con WAV/WebRTC/Whisper/Qwen/Piper y un único comprobante real en API/MariaDB. Incluye la frase de la captura, presencia con descripción pendiente, oferta sin envío, descarte hablado, creación explícita, corrección, negación, reanudar y confirmación. Una confirmación mal transcrita ya no puede reiniciar el borrador por una hipótesis del modelo: conserva la revisión y pide aclaración. El recorrido anterior de creación/preview/TV/120 segundos también aprobó individualmente. No se declara una suite agregada de todos los modelos aprobada; el log agregado anterior incluye el intento rechazado.

Evidencia actual: `gianna-flow-unit-final.log`, `gianna-flow-semantic-qwen.log`, `gianna-flow-ui-*.log`, `gianna-flow-voice-final.log`, `gianna-interpretation.json/.png` y eventos. Los intentos con «Nuevo ticket» reconocido como «No ticket», y la confirmación corrupta que reveló el reinicio de borrador, se conservan en `gianna-flow-voice-new-ticket-rejected.log` y `gianna-flow-voice-review-restart-rejected.log` con sus eventos. Se añadieron regresiones que impiden a hipótesis del modelo cambiar la revisión vigente o iniciar otro pedido. El primer caso requirió una solicitud hablada más completa; no se reemplazó su transcripción ni se redujo el umbral de audio.

## Apertura y conexión de consola · 5 de octubre de 2026

La consola ya no depende de la cookie privada que el launcher insertaba en su Chromium. Una navegación local válida la vincula con cookie HttpOnly/SameSite Strict; un fetch JSON del mismo origen puede renovar ese vínculo después de reiniciar. Host/Origin, Fetch Metadata y bloqueo de iframes mantienen la frontera local. El estado de conexión se distingue del arranque de motores; los fallos recuperan estado/eventos con espera progresiva y sin repetir comandos. Abrir una segunda consola no interrumpe la reproducción ni el micrófono; conectar explícitamente su micrófono transfiere el único canal.

Validación: **514 unitarios/contratos**, **11 pruebas de UI**, lint/build aprobados. El e2e de consola con modelos/WebRTC reales aprobó en **26,20 s**: apertura sin cookie, pérdida de red, renovación desde la UI cargada sin recargar, y conexión/transferencia de audio entre dos contextos de navegador. No escribe tickets ni sustituye STT. El primer intento mostró que emular una pérdida de red no cerraba por sí solo el SSE existente; se añadió detección de eventos offline/online y se conserva ese intento en `gianna-console-connection-offline-rejected.log`. Evidencia final: `gianna-console-connection-unit.log`, `gianna-console-connection-ui.log` y `gianna-console-connection-e2e.log`. El informe `testing-ready.json` incluye hashes de autenticación local, conexión de UI y build abierto.

## Mediciones de la validación inicial

| Componente / perfil | p50 | p95 | Muestras |
|---|---:|---:|---:|
| STT GPU benchmark warm | 373,13 ms | 642,53 ms | 10 |
| STT CPU int8 benchmark warm | 18 498,66 ms | 20 391,17 ms | 10 |
| Tev benchmark GPU | 34,00 ms | 63,27 ms | 10 |
| Tev benchmark CPU | 35,12 ms | 75,35 ms | 10 |
| STT, creación WebRTC | 687,17 ms | 717,05 ms | 5 |
| API tickets, creación | 8,78 ms | 266,01 ms | 9 |
| Silencio reportado por VAD | 600,00 ms | 600,00 ms | 5 |
| Inferencia SmartTurn CPU | 76,60 ms | 80,63 ms | 5 |
| Evento VAD de fin → turno despachado | 724,77 ms | 1 501,66 ms | 5 |
| Síntesis → primer audio de servidor Piper | 1 175,96 ms | 2 205,02 ms | 7 |
| Evento VAD de fin → primer audio de respuesta | 2 540,67 ms | 2 925,09 ms | 5 |
| Fin de habla estimado → primer audio de respuesta | 3 140,67 ms | 3 525,09 ms | 5 |
| Event-loop lag, últimas muestras | 0,00 ms | 0,25 ms | 512 |
| Fin de habla estimado → respuesta, consultas/archivo | 2 910,61 ms | 3 763,15 ms | 11 |

Warmup residente del benchmark: GPU 9,54 s y CPU 29,05 s. Son procesos con modelos ya descargados; no una prueba de cache de disco completamente frío. SmartTurn informa el tiempo de inferencia desde su implementación real; el silencio VAD es el valor reportado por el detector. La estimación del fin de habla resta ese silencio del evento VAD. El primer audio es del servidor, no el primer sonido físico.

La respuesta completa observada supera el objetivo inicial de 2 s. Se mantienen motores residentes, worker exclusivo, caché de frases públicas y HTTP asíncrono; las revisiones variables de Piper se sintetizan completas antes de transmitir. No se recorta la revisión para aparentar menor latencia. Enqueue de InterruptionFrame: p95 0,01 ms; eso **no demuestra** corte audible dentro de 250 ms. El tiempo hasta el parlante y la usabilidad acústica necesitan medición física.

Observación de creación: 225,40 s, 45 muestras de carga. Máximos muestreados: CPU del sistema 25 %, RAM del sistema 14,67 GiB, RSS del runtime 1 951,29 MiB y memoria GPU del sistema 6 631 MiB. En consulta/archivo: 39 muestras, CPU 33,1 %, RAM 13,60 GiB, RSS 920,42 MiB y GPU 5 740 MiB. CPU/RAM/GPU del sistema incluyen otras aplicaciones, Docker/Ollama y el runtime manual simultáneo; no se atribuyen íntegramente al agente ni se presentan como máximos instantáneos. Soak de 12 h opcional, no ejecutado.

Evidencia local: `artifacts/gianna-real-acceptance-final.log`, `gianna-unit-final.log`, `gianna-voice-e2e.json`, `gianna-live-commands.json`, `gianna-real-recovery.json`, `gianna-components.json`, `gianna-doctor-final.json`, `gianna-benchmark-cuda.json` y `gianna-benchmark-cpu.json`. Los archivos de audio/regresión y los eventos conservan errores reconocidos, incluso de ejecuciones previas que fallaron; sólo la suite final completa se cuenta como aprobada.

## Banco de 500 decisiones

Medición histórica de la etapa inicial, con el criterio de activación anterior. No se repitió el banco completo después de incluir presencia y saludos en ese criterio; sus porcentajes no acreditan la política de conversación actualizada.

| Categoría test | Casos | Exactitud cruda | Aclaraciones con gate | Aceptadas erróneas |
|---|---:|---:|---:|---:|
| Activación | 96 | 63,5% | 7 | 1 |
| Confirmación | 80 | 40,0% | 62 | 0 |
| Dictado/verbos | 32 | 0,0% | 31 | 1 |
| Intención | 96 | 74,0% | 44 | 2 |
| Origen | 48 | 100% | 8 | 0 |
| Tipo | 48 | 83,3% | 19 | 0 |

La política de activación aplicó primero filtro determinista de invocación; 40/40 invocaciones positivas pasaron, hubo 1 falsa activación textual en96 («Gianna? No sé…») y ninguna omisión en ese subconjunto. No se transforma eso en falsos despertares/hora: no existe duración acústica humana. Los gates del benchmark para otros grupos son experimentales; runtime usa .70 para desambiguación de catálogo y confirma/especifica recursos con reglas exactas. Nunca se usa Tev para ejecutar verbos de un dictado o aceptar un sí ambiguo. Ese contraste explica la protección del circuito aunque la clasificación libre tenga resultados modestos.

Fallas encontradas durante pruebas: Piper corto «Gianna…» a veces pierde el nombre en Whisper; «sí, eso es todo» llegó como «sí, eso restado» y «impresora» como «impesora», y un «confirmo» corto fue rechazado al llegar como «Unfeetable»; «contengan» sufrió variaciones STT. La confirmación dudosa conserva el payload y pide «confirmo», y un tipo ausente requiere contestar la pregunta de catálogo. El test responde por audio real a esas aclaraciones. Se conservan los errores, sin presentarlos como audios humanos ni cambiar los umbrales contra el banco final. También se corrigió la dependencia del gestor de medios predeterminado de un CDN; el transporte final usa captura nativa y funciona con HTTPS externo bloqueado.

En las mediciones iniciales quedaron pendientes la llamada cloud autenticada (sin clave entonces), Linux real, lector de pantalla con administrativo, micrófono/parlantes/auriculares y corpus humano independiente. Las rutas y procedimientos están implementados/documentados; esas mediciones no se declaran aprobadas.


## Captura continua y DeepSeek Cloud · 5 de octubre de 2026

Por pedido del usuario, `agent/.env` configura `OLLAMA_API_KEY`, `OLLAMA_MODEL=deepseek-v4.1-flash:cloud` y backend Cloud. Se comprobó autenticación real y disponibilidad en Ollama Cloud. Intención y catálogo usan el endpoint HTTPS directo; no se invoca Qwen ni Tev ni hay fallback local. La clave permanece en el backend, se ignora en Git y no aparece en el build ni en los informes. Los motores de audio siguen en el puesto.

La captura entrega la pista nativa de getUserMedia directamente a WebRTC. Se eliminó el destino WebAudio susceptible de suspensión. El servidor comprueba PCM recibido, informa nivel únicamente al cliente conectado y la consola muestra reconexión si pasan cinco segundos sin paquetes. Se corrigió la espera de fin de turno que se reiniciaba con cada paquete de audio continuo. La reserva de transcripciones empieza con VAD y se ignoran eventos de habla duplicados hacia upstream. SmartTurn incompleto tiene cierre por silencio acotado, conservando la espera de transcripciones y la cancelación si vuelve a hablar.

Validación: **528 unitarios/contratos**, **14 pruebas de UI**, Ruff, esquemas, typecheck/lint/build aprobados. **69 regresiones semánticas con DeepSeek real en 45,19 s** y **4 de catálogo en 2,41 s**, sin modelo LLM local. El banco se usa para regresión, no como medida de precisión de habla humana independiente.

La prueba de captura nativa usa un WAV sintético en el dispositivo de Chromium, sin sustituir getUserMedia ni usar WebAudio para su entrada y sin override de autoplay. Dos frases fueron transcritas y contestadas por separado mientras continuaba entrando PCM. Verifica el medidor, dos primeros audios de respuesta del servidor, ausencia de escrituras y ninguna llamada al puerto LLM local. Junto con el recorrido de creación/corrección/negación/reanudar/confirmación hablada, **2 e2e aprobaron en 303,33 s**. El recorrido de negocio produjo una única operación y un comprobante API/MariaDB en la base aislada, nunca en la demo del usuario. La prueba de apertura/recuperación/transferencia real de consola también pasó en esta ejecución.

Evidencia: `artifacts/gianna-cloud-unit.log`, `gianna-deepseek-semantic.log`, `gianna-deepseek-catalogue.log`, `gianna-deepseek-voice-final.log`, `gianna-native-microphone.json/.png`, `gianna-native-events.json` y `gianna-interpretation.json`. El primer intento de captura produjo las dos respuestas correctas pero una expectativa del test requería presencia en el saludo inicial; esa expectativa se ajustó al contrato de activación y se conserva el intento en `gianna-native-microphone-first-expectation.log`. No se declara reconocimiento perfecto del micrófono físico ni medición del parlante con este WAV.

En los dos turnos de captura nativa, VAD-fin→despacho p50 1136 ms/p95 1244 ms; fin de habla estimado→primer audio de respuesta en servidor p50 3233 ms/p95 4035 ms. Son dos muestras sintéticas de regresión, no una distribución representativa de latencia humana.

Demo reiniciada con Administrador de pruebas y DeepSeek Cloud listo. El launcher verificó PCM recibido del micrófono real y los hashes del build/captura/cliente Cloud. El borrador anterior mantiene ID, revisión y payload tras el reinicio; se conserva una copia privada de SQLite. Una consola nueva sin cookies verificó admin, estado HTTP 200 y audio activo sin transferir el micrófono. Evidencia: `artifacts/gianna-deepseek-running.json`, `testing-ready.json`. La recepción PCM acredita transporte del dispositivo, no comprensión de habla humana.


## Corrección de contexto y borrar conversación — 05/10/2026

La oración completa sobre Secretaría General y reponer hojas a las impresoras ya no se reduce a una respuesta al campo Tipo. DeepSeek recibe el borrador y la pregunta real, distingue reclamos, reemplazos y agregados, y extrae menciones literales del origen y destino. Una oficina ausente del catálogo elimina la asociación vieja y pide una correspondencia registrada. El texto literal se conserva y todo cambio requiere una revisión y confirmación nuevas. Una interpretación fallida o tardía no reescribe la conversación nueva.

Whisper usa beam 5 y evita filtrar por VAD una segunda vez un segmento ya aceptado. La voz baja tiene ganancia acotada después del rechazo de silencio/ruido; la captura predeterminada usa AGC y AEC y deja RNNoise en el servidor. Esto se verificó con audio sintético de nivel bajo y constituye una regresión de la cadena, sin afirmar precisión universal para el micrófono humano.

**Borrar conversación** limpia el chat, texto pendiente, borradores locales sin transferir, revisión, propuestas y respuestas pendientes de la cuenta. Abre una conversación nueva y el botón reconecta su micrófono activo. Conserva autenticación, preferencias, formularios transferidos, operaciones e historial de tickets. Una operación pendiente impide el reset. Pruebas cubren aislamiento entre cuentas, migración del historial antiguo, cambio de cuenta durante el cierre de audio, cancelación de resultados tardíos y reingreso sin recuperar el contexto borrado.

Validación: **556 unitarios/contratos en 27,61 s**, más **7 pruebas de endpoints** tras contemplar el caso de audio aún no inicializado; **19 pruebas de UI**, Ruff y lint/typecheck/build aprobados. **79 casos con DeepSeek Cloud real en 49,00 s**. El recorrido de voz baja, corrección y borrado con reconexión aprobó en **50,75 s**, con una transcripción real y un nuevo canal PCM, sin escribir tickets. Los primeros intentos detectaron expectativas demasiado estrechas sobre la ganancia de AGC y la conservación literal de conectores; se ajustaron sin debilitar las comprobaciones de contenido, aislamiento o envío.

Evidencia: `artifacts/gianna-reset-unit.log`, `gianna-reset-ui.log`, `gianna-reset-cloud.log`, `gianna-quiet-reset.log`, `gianna-quiet-reset.json/.png`. La demo conserva el borrador de revisión 4 hasta que el usuario decida borrarlo con el botón.


## Harness conversacional con herramientas · 5 de octubre de 2026

Se revisaron semantic_router, conversation_memory, main/persona y el controlador de turnos de Gianna Turismo en el commit solicitado. El flujo activo reemplaza la clasificación de mensajes libres seguida de respuestas fijas por ConversationAgent: historial factual de actor/sesión, llamadas nativas DeepSeek Cloud, catálogos y consultas reales, y preparación local validada. Un pedido largo cambia descripción/origen juntos y genera una sola revisión; una elección de catálogo conserva el dictado. La confirmación y los recibos siguen bajo Supervisor/OperationManager. Secretaría General se agregó de forma idempotente al catálogo inicial y a las dos demos, sin modificar los tres tickets del usuario.

Resultados locales: **584 unitarios/contratos**, **57 pruebas de backend en MariaDB descartable**, **19 de consola** y **9 conversaciones/consultas con DeepSeek real** aprobadas. Las nueve usan catálogos de fixture explícitos para comprobar semántica y trayectorias, no se presentan como prueba de audio o DB. Ruff, esquemas, lint y typecheck aprobados.

Dos recorridos nativos aprobados individualmente: corrección con voz baja, borrar conversación y reconectar RTC (resultado en gianna-quiet-reset.json; primera prueba de gianna-harness-native-final.log); y incidente reportado, áreas reales, tipos, selección/corrección de origen y creación confirmada de un único ticket comprobado en la API/DB aislada (**102,47 s**, gianna-harness-voice-final.log y gianna-harness-voice.json/png). El segundo empieza con el botón público Activar Gianna antes de conectar el micrófono; todos los pedidos/consultas iniciales entran por captura WAV nativa, sin sustituir getUserMedia ni forzar autoplay. Los pasos posteriores de selección y confirmación usan la UI real.

La entrada es Daniela sintética. Una ejecución anterior transcribió Gianna como «Que anda» y el filtro dormido ignoró ese audio correctamente; gianna-harness-wake-stt-variation.json conserva el resultado como limitación del reconocimiento del nombre, no como aprobación de activación por voz. Con señal baja, Whisper también produjo «ponernos las hojas» en lugar de «poner nuevas hojas»; gianna-harness-low-voice-stt-variation.json/log conserva esa variación. Las pruebas verifican que se mantienen oficina, hojas, impresoras y el fragmento de la transcripción efectiva; no la sustituyen por la frase esperada. No se acredita precisión para el micrófono/hablante real con estos audios.

El launcher de testing abre una conversación ya activada tras el login normal/delegación y la conexión del micrófono. El launcher diario conserva la activación por nombre. testing-ready.json registra el diagnóstico de herramientas nativas y los hashes de ConversationAgent, AgentTools y Supervisor cargados.
