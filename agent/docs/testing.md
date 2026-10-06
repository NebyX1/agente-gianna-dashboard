# Pruebas reproducibles

Las [referencias accesibles de tickets](ticket-references.md) se comprueban con `test_ticket_references.py`, `test_ticket_accessibility_live.py`, `test_short_reference_audio.py` y las confirmaciones por número corto de `test_review_meaning_live.py`. Separan el número público del ID interno y verifican cantidades reales por área, paginación, voz sin ceros y rechazo de otra referencia durante la confirmación.

`tests/e2e/test_window_layout.py` comprueba el navegador visible administrado, sin emular el viewport: redimensiona su ventana nativa a 1280, 1920 y 1536 px mediante CDP, activa cada pestaña y exige que tickets, consola y estadísticas usen el ancho disponible. También comprueba el formulario amplio. Requiere `GIANNA_WINDOW_E2E=1`, el portal aislado 5473 y la consola local 7860; sólo inicia sesión de pruebas y lee las vistas, sin conectar otro micrófono ni enviar comandos de conversación o tickets. Conserva medidas y capturas en `artifacts/gianna-native-window-layout.json` y `gianna-native-width-*.png`.

La [reparación de voz y confirmación natural](voice-confirmation-repair.md) agrega `test_review_meaning_live.py` (40 respuestas, 38 con DeepSeek real y dos límites locales), `test_review_meaning.py`, `test_recognition_audio.py` y `test_audio_cancellation.py` (autoridad, audio original para reconocimiento, cancelación y recuperación), y `test_native_barge_in.py`. Esta última usa ocho respuestas cortas con STT/semántica reales a dos volúmenes y tres intervenciones por un micrófono WAV nativo de Chromium: niega durante voz, retoma y confirma dentro de una oración, sin repetir la intervención. Mide muestras reales de salida RTC y exige corte dentro de 500 ms desde el evento acústico; el indicador no es una medida de latencia de detección ni de un altavoz físico. Comprueba un solo ticket en API/MariaDB. Para ejecutarla: `GIANNA_REAL_E2E=1`, con el stack aislado disponible; las pruebas semánticas requieren `GIANNA_CLOUD_HARNESS=1`.

La reparación de las capturas del 5 de octubre se comprueba con `tests/integration/test_cloud_harness.py` (DeepSeek real, fixtures de catálogo/lectura explícitos) y `tests/e2e/test_conversation_repair.py` (mensajes originales desde la interfaz, API/MariaDB reales, creación y resolución con motivo en una misma frase). Se exige verificar el resultado remoto, no sólo detectar una respuesta. La confirmación repetida no puede duplicar el ticket. `test_harness_voice.py` añade voz sintética mediante captura nativa de Chromium/WebRTC/Whisper. [Diagnóstico](conversation-repair.md) y [resultados vigentes](acceptance-report.md) separan esas comprobaciones de los resultados históricos.

`test_local_auth.py` cubre apertura local sin cookie previa, renovación tras pérdida de emparejamiento, alias localhost y rechazo de sitios ajenos/formularios/iframes. `test_console_audio.py` comprueba que sólo una oferta nueva válida libera el canal anterior y que una renegociación o una oferta rechazada no lo desconectan. Los tests de UI cubren conexión inicial, vinculación automática, recuperación sin repetir comandos, conservación del borrador y ventanas que observan voz reproducida en otra consola. `test_console_connection.py` verifica el transporte real: elimina la cookie del launcher, recarga, provoca un corte de red, elimina otra vez la cookie y vuelve a conectar desde la UI sin recargar. Finalmente conecta el micrófono y transfiere el canal a un segundo contexto de navegador que parte sin cookies. Usa los modelos y WebRTC reales; no escribe tickets.

`test_intent_flow.py` comprueba que lo desconocido no crea borradores, que las intervenciones sociales preservan datos/revisión/pregunta, que aceptar abrir un pedido no autoriza su envío, y que la oferta queda acotada a actor, sesión, vencimiento y pregunta inmediata. También prueba descarte local, pausa durante interpretación y JSON inválido. `test_semantic_routing.py` ejecuta 69 regresiones con el intérprete configurado (DeepSeek Cloud por defecto): paráfrasis en tres contextos, respuestas concretas y llamadas/menciones. Son regresiones, no una garantía de precisión fuera de este banco. El fixture de los tests de datos simula una interpretación ya validada; la calidad semántica se verifica con el modelo real.

`test_interpretation.py` reproduce las órdenes reportadas y variantes compuestas: nombre al inicio/medio/final, consentimiento + verbo, solicitudes corteses, final de dictado según la operación, correcciones imperativas/declarativas, negaciones, condiciones, datos literales y órdenes incompletas. Verifica operaciones durables con el OperationManager, sin sustituir commit: una confirmación repetida durante HTTP conserva la generación y sólo hay un envío; actor/sesión/revisión/propiedad/vencimiento siguen siendo barreras. Las calificaciones no interpretadas conservan payload y confirmación.

`test_voice_interpretation.py` empieza por la aclaración «Te dije a ver si me habías escuchado», una oferta de creación aceptada sin envío, descarte local, y una pregunta de presencia durante la descripción. Luego reproduce por WAV/WebRTC/STT el pedido con prefijo «Necesito registrar un nuevo ticket», corrige el origen con «Sí, pero…», niega el envío, retoma y confirma mediante «Eso es todo, Gianna, registrá» o una repetición hablada explícita. Comprueba la descripción sin el prefijo, el origen corregido, un único comprobante y el registro real en API/MariaDB. Un verbo mal reconocido se conserva en los eventos y pide una aclaración; no se transforma a posteriori en autorización. Evidencia: `artifacts/gianna-interpretation*.json/.log/.png`.

`test_incident_classification.py` comprueba cuatro regresiones con Tev real: dos palabras de impresora mal transcritas y sus síntomas, navegación/red y ausencia de información. Usa nombres y alias del perfil; no es un banco estadístico de precisión ni una prueba de audio humano. Los unitarios verifican además que se conserva el dictado, se pregunta una clasificación incierta y se descarta el resultado tardío después de pausar.

`test_conversation.py` cubre presencia, saludos, orientación, agradecimientos, reconocimientos, correcciones, repetir, ritmo, siguiente paso, estado del trabajo, pausa/reanudar/despedida y finalizar o cancelar tickets. Prueba cada límite de estado, conserva payload/revisión/pregunta, rechaza confirmaciones ambiguas, respeta el control manual y evita atribuir un recibo viejo al pedido actual. Incluye respuestas durante un HTTP reservado, cierre con resultado tardío y cambio de actor durante reconciliación.

`test_voice_conversation.py` usa WAV reales de Daniela por WebAudio/WebRTC y los motores locales: pregunta de presencia, ayuda extensa, pregunta durante dictado, agradecimiento, siguiente paso, repetir, teléfono/pausa, reanudar, despedida, cambio explícito a En curso si hace falta, resolver con motivo/confirmación y recuperar el borrador anterior. Verifica estado y versión en API, comprobante y una única operación de cierre. El helper de confirmación identifica el borrador y la operación actuales; un recibo anterior no puede aprobar otro cambio. Los eventos y resultados quedan en `artifacts/gianna-conversation*.json`.

Un clip rechazado puede repetirse con otra solicitud hablada explícita. El harness comprueba que el borrador y las operaciones no cambiaron antes de repetir; no reintenta escrituras inciertas ni reemplaza una transcripción. Cada intento fallido queda en los resultados. `test_conversation_activation.py` conserva la regresión histórica de Tev con diez casos de presencia, ayuda, reanudar, pedido, mención, nombre ajeno e invocación ambigua con el filtro y Tev local; son regresiones textuales específicas, no una medida de falsos despertares por hora.

Ejecutar desde agent/ para resolver el paquete tests de fixture:

```powershell
.venv\Scripts\python.exe -m pytest tests/unit tests/contracts -q
.venv\Scripts\ruff.exe check src tests scripts
.venv\Scripts\python.exe scripts/export_schemas.py --check
$env:SWC_NATIVE_BINDING_CACHE = Join-Path $env:USERPROFILE '.codex\swc-native-cache'
npm --prefix ui run lint
npm --prefix ui run typecheck
npm --prefix ui test
npm --prefix ui run build
```

La suite de backend usa `python scripts/test-backend.py` desde la raíz y crea una MariaDB descartable única; no usa la DB de la demo. Los tests de voz usan el proyecto fijo `idl-tickets-design-check` (API 5400, web 5473, TV 5474, SMTP 8027), definido por `compose.yaml` y `agent/scripts/compose.integration.yaml`.

Desde agent/, ejecutar `.venv\Scripts\python.exe scripts/prepare-integration.py`. Construye e inicia sólo ese proyecto, migra y siembra catálogos de forma idempotente. Si falta el archivo secreto de usuarios, los crea una sola vez y copia `artifacts/design-check-users.json` con acceso restringido al usuario. No reinicializa usuarios existentes ni elimina volúmenes. Ante usuarios ya existentes sin ese archivo falla deliberadamente: recuperar las credenciales del entorno aislado. **No ejecutar scripts/start-e2e.py sobre la demo del usuario: ese script reinicializa usuarios/datos del proyecto e2e.**

Además de Docker, instalar los motores de audio mediante el setup de Gianna, construir la consola y configurar DeepSeek Cloud en `agent/.env`. En modo Cloud no hace falta Qwen ni Tev local. Los modelos de audio y `nltk/punkt_tab` deben residir en el directorio de datos persistente del usuario. Puede configurarse `GIANNA_DATA_DIR` y `GIANNA_MODEL_DIR` fuera del checkout; los tests toman NLTK desde `GIANNA_DATA_DIR/nltk`. Se usan los puertos temporales 5002/5003 y 7862, sin conectarse a un servicio ajeno. El login usa correo y 2FA reales, incluido su período de espera de 60 segundos. Las pruebas se habilitan sólo con `GIANNA_REAL_E2E=1`; una omisión no es una aprobación.

```powershell
$env:GIANNA_REAL_E2E='1'
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m pytest tests/integration tests/e2e -q
.venv\Scripts\python.exe scripts/audio_regression.py
.venv\Scripts\python.exe scripts/evaluate_decisions.py
```

`test_voice_flow.py` transmite WAV Daniela real desde un micrófono WebAudio controlado en Chromium → WebRTC → RNNoise/Silero/Whisper/SmartTurn → Supervisor, API y MariaDB. Prueba dictado/corrección/confirmación, preview bloqueado ante submit/Enter, un ticket y audit, TV, 120 segundos reales desde playback y voz posterior sin reinicio. Espera el playback real de la revisión antes de confirmar; ante una respuesta mal reconocida sólo repite por voz, hasta tres intentos, comprobando que la carga no cambió y que no hubo envío. El cliente runtime permite exclusivamente los servicios locales y ollama.com en modo Cloud; rechaza llamadas al daemon 11434. El contexto web bloquea HTTPS externo. La API de texto no sustituye STT.

`test_live_audio_commands.py` usa un micrófono WebAudio controlado sólo en el test; transmite WAVs por el transporte real, permite intervenciones durante Piper, lee/muestra/busca/oculta, comprueba recibo después de ocultar y transfiere un formulario manual sin doble envío. Si Whisper omite un campo, el test responde por voz a la pregunta real del agente; no inyecta el catálogo ni una transcripción. Cierra su navegador y verifica el error de superficie propio.

`test_real_recovery.py` pierde intencionalmente la respuesta HTTP **después de un commit real**; cierra y reabre SQLite, cambia sesión hija, verifica comprobante, fuerza 409 concurrente y prueba editar tras una nueva revisión, status/archive/restore/revocación. `test_components.py` detiene y reinicia su propio Piper; prueba endpoints inaccesibles para Tev y tickets, y reconexión al mismo Tev/API. No apaga el daemon Ollama del usuario. `test_console_connection.py` conecta SmallWebRTC con HTTPS externo bloqueado, usando el gestor nativo de micrófono y sin un servicio de medios remoto.

Los unitarios usan reloj/eventos/adaptadores controlados para races y errores: no son pruebas de reconocimiento de voz. Prueban física del worker cancelado, confirmación/sesión/hash, resultados tardíos, incertidumbre 404, explicit retry con misma key, handoff, saturación, barrera en ambos órdenes y pausa/ruido/timer. El fixture de extensión usa HTTP ASGI real pero no modelos.

Regresión de audio: WAV sintético, silencio, impulso, teclado generado, ruido blanco, sí/no/pará, wake y dictado. Se registran todas las transcripciones, incluyendo errores. No se fabricaron grabaciones humanas. Banco de decisiones: 500 textos etiquetados, 100 tune/400 test, mezclados con seed fijo y separación estratificada. Son variaciones de plantillas; no hablantes humanos independientes. Conservar results y matriz de confusión; no modificar umbral usando el test final y declarar el mismo test como independiente.

Prueba del puesto pendiente: teclado completo y lector NVDA con usuario; micrófono real cerca de parlantes, luego auriculares; llamada telefónica con mañana/Diana/menciones y dictado; sí cortos y voz de cada usuario; medir falsos despertares por hora con duración y sesiones independientes. Repetir correcciones, apagar micrófono y tomar control manual durante preparación. Confirmar que el lector no duplica Piper; usar modo silencioso/menos anuncios cuando corresponda. Esas verificaciones necesitan hardware/persona, no pueden acreditarse con un WAV.

CI `checks.yml` separa agent unit/contratos/UI del backend y clientes. `agent-models.yml` requiere un runner Windows self-hosted dedicado marcado `gianna-gpu`, Docker y una clave OLLAMA_API_KEY de Ollama Cloud, modelos y NLTK previamente instalados fuera del checkout y acceso exclusivo a los puertos de pruebas. El job construye la UI, prepara el proyecto aislado y verifica los modelos antes de la suite. Sólo se habilita al seleccionar `models_gpu_ready`; no se ejecutó ese job en CI durante esta entrega. Los resultados locales figuran en acceptance-report.md.


`test_native_microphone.py` utiliza un archivo WAV en el dispositivo nativo de captura de Chromium, sin sustituir getUserMedia ni construir una entrada WebAudio y sin forzar autoplay. Verifica paquetes reales, medidor, dos transcripciones y respuestas separadas con PCM continuo, latencia del cierre de turno, DeepSeek Cloud sin llamadas LLM locales y ausencia de borradores/escrituras. `test_cloud_interpreter.py` valida alias del `.env`, secreto fuera del repr, modelo directo, ausencia de format no soportado, JSON/esquema/etiquetas/confianza y fallos sin fallback local. Los tests históricos de Tev requieren elegir explícitamente backend local y no se ejecutan en el perfil Cloud.


`tests/e2e/test_quiet_voice_reset.py` recrea un borrador viejo de Sociales sólo como preparación. Una frase sintética con RMS 0,005 entra por el dispositivo nativo de Chromium, pasa por la captura y transcripción reales y corrige el pedido a Secretaría General y hojas para las impresoras. El catálogo contiene Secretaría General: el agente reemplaza el origen anterior y revisa ese pedido en lugar de reutilizar Sociales. El test pulsa **Borrar conversación** y verifica ambas consolas vacías, sesión conservada, borrador eliminado y un nuevo canal de micrófono con PCM recibido. No inyecta transcripciones ni hace escrituras de negocio. La ganancia automática del navegador puede elevar la entrada antes de que llegue al normalizador del servidor; la prueba registra esa evidencia y no exige aplicar ganancia dos veces.

```powershell
$env:GIANNA_REAL_E2E='1'
.venv\Scripts\python.exe -m pytest tests/integration/test_semantic_routing.py tests/integration/test_incident_classification.py tests/e2e/test_quiet_voice_reset.py -q
```

## Harness conversacional con herramientas (5/10/2026)

`test_conversation_agent.py` verifica contratos nativos, contexto de la pregunta sin duplicación, herramientas instaladas/disponibles, IDs reales, citas literales, historial separado por actor/sesión, limpieza, resultados tardíos y presupuestos. La preparación de estados por modelo nunca ejecuta el comando canónico como autorización de envío. Cubre motivos/notas, borradores transferidos y respuestas cloud malformadas.

`test_cloud_harness.py` ejecuta nueve conversaciones/consultas con DeepSeek real y catálogos de fixture explícitos: el incidente reportado, catálogos, referencia ordinal, consultas durante revisión, memoria, corrección completa, oficina desconocida, alternativa válida, lectura y cambios de estado. No sustituye una prueba de API/audio ni afirma precisión general.

`test_harness_voice.py` usa la API/DB aislada y captura WAV nativa de Chromium. Las dos frases reportadas pasan por Whisper y DeepSeek, se verifican el catálogo real y el borrador intacto; luego la UI consulta tipos, cambia y corrige el origen y confirma un único ticket. Comprueba el recibo contra API/MariaDB. La entrada es Daniela sintética, sin reemplazar getUserMedia ni forzar autoplay; no acredita por sí sola el micrófono humano. La voz baja puede producir variantes de palabras: el test comprueba oficina, hojas, impresoras y que se conserva la transcripción efectiva, sin sustituirla por el texto del fixture.

```powershell
$env:GIANNA_CLOUD_HARNESS='1'
.venv/Scripts/python.exe -m pytest tests/integration/test_cloud_harness.py -q
$env:GIANNA_REAL_E2E='1'
.venv/Scripts/python.exe -m pytest tests/e2e/test_harness_voice.py tests/e2e/test_quiet_voice_reset.py -q
```
