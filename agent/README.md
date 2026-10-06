# Gianna · Mesa de ayuda de Lavalleja

Aplicación independiente de voz, con consola accesible y navegador propio. Prepara tickets con datos de los catálogos reales, revisa cada escritura, conserva un comprobante durable y vuelve a esperar «Gianna». La API realiza las escrituras; la vista previa del navegador nunca envía el formulario.

Al conversar, `IDL-TI-000025` se llama **ticket número 25**, sin leer letras ni ceros. También podés decir «terminación 25», «ticket veinticinco» o «ticket ciento veintitrés». El número es único y se conserva todos los días. Preguntá «¿Cuántos tickets de Tránsito tengo activos?» o «¿Y de Sociales?»: Gianna consulta la cantidad real por área. [Referencias accesibles y ejemplos](docs/ticket-references.md).

## Inicio en un equipo nuevo

Seguí primero la [guía de instalación rápida](../docs/instalacion-rapida.md). La instalación habitual usa tickets en `http://localhost:5173`, pantalla en `http://localhost:5174` y API en `http://localhost:5000`. El `.env` de **agent/** debe apuntar a esos servicios. Iniciá Docker antes de Gianna. La interpretación usa DeepSeek en Ollama Cloud y no requiere un daemon Ollama local.

```powershell
cd agente-gianna-dashboard\agent
.\scripts\start.ps1
```

Se abre un Chromium exclusivo con tickets y la consola `http://127.0.0.1:7860`. Iniciá sesión **en el navegador de tickets** con el código de correo habitual. Podés abrir la consola en otro navegador: se vincula automáticamente al servicio local y comparte la sesión de tickets del agente. Presioná **Conectar micrófono** en la ventana que quieras usar; ese botón transfiere el único canal de audio desde la ventana anterior. Abrir otra consola por sí solo no cambia el micrófono.

Ejemplo: «Hola Gianna, necesito tu ayuda para registrar un pedido nuevo». Después: «En Tránsito la impresora no imprime». Completá el dato que falte, escuchá la revisión y respondé «Confirmo» o «Sí, eso es todo». También admite nombre y orden en una misma frase; si la activación es dudosa pide repetirla. «Corregí la descripción: …» sustituye el texto; «Agregá …» lo amplía. Una confirmación mal reconocida conserva el borrador y pide aclaración. «Pará» pausa y conserva el borrador. **Tomar el control manual** abre un formulario nuevo editable y transfiere su propiedad. Cerrar con **Cerrar Gianna** o Ctrl+C en el launcher.

## Prueba con administrador ya conectado

También podés empezar con «Gianna» (responde sólo «Hola, soy Gianna y ya estoy activada.») y pedir «¿Qué podés hacer?». «Estoy al teléfono» pausa, «Gianna, seguimos» retoma y «Finalizá la conversación» conserva el borrador sin enviarlo. Para completar un ticket existente, pedí «Resolvé el ticket número …»; revisa el estado, pide motivo y espera confirmación. Más ejemplos: [conversación y solicitudes cotidianas](docs/conversation.md).

La demo opcional ejecuta `scripts/start-testing.ps1`. Abre tickets, visualizador y Gianna como **Administrador de pruebas** (`testing.admin@example.test`), completa automáticamente el ingreso y el código de Mailpit y conecta el micrófono real cuando está disponible. Se puede ejecutar `.\scripts\start-testing.ps1` desde agent/; no es el inicio habitual de una instalación nueva.

Este launcher está acotado a la demo local de puertos 5300/5373/5374 y verifica el proyecto Docker `idl-tickets-e2e` y el entorno development/test. Crea únicamente su cuenta de pruebas; conserva las otras cuentas y tickets. Sus credenciales aleatorias quedan en `%LOCALAPPDATA%\Gianna\testing\admin.json`, con acceso del usuario del puesto. Las sesiones duran lo que indique la API (14 horas en esta demo); volver a abrir el acceso de pruebas inicia sesión automáticamente. Cerrar primero la instancia actual con **Cerrar Gianna** para volver a arrancar.

## Instalación reproducible

Python 3.12, uv, Node 22 y una clave de Ollama Cloud. Windows: `scripts/setup.ps1`; Linux: `bash scripts/setup.sh`. Se instalan `uv.lock`, `ui/package-lock.json`, Chromium y los modelos de audio verificados. La interpretación y selección semántica del catálogo usan DeepSeek Cloud; no se descargan Qwen ni Tev. Whisper, RNNoise, Silero, SmartTurn y Piper siguen procesando el audio en este equipo. CUDA es el perfil predeterminado para Whisper. El inicio diario no descarga modelos.

Copiá `.env.example` a `.env` y configurá los **orígenes completos sin ruta**. Los valores de ejemplo apuntan a API 5000 y web 5173. La ruta `/api/v1` la incorpora el adaptador. Configurá `OLLAMA_API_KEY` y `OLLAMA_MODEL=deepseek-v4.1-flash:cloud`. El `.env` se ignora en Git. El resto de variables del runtime usa `GIANNA_`; `ui/.env.example` sólo contiene `VITE_RUNTIME_URL` público. Nunca pongas claves en `VITE_*` o perfiles.

```powershell
.venv\Scripts\python.exe -m gianna doctor
.venv\Scripts\python.exe -m gianna models verify
.venv\Scripts\python.exe -m gianna profiles validate
.venv\Scripts\python.exe -m gianna run
.venv\Scripts\python.exe -m gianna benchmark
```

CPU es una elección explícita: `GIANNA_STT_DEVICE=cpu`, `GIANNA_STT_COMPUTE_TYPE=int8`, `GIANNA_STT_GRACE_SECONDS=45`; ver `.env.cpu.example`. Usa el mismo Whisper. En este equipo tarda alrededor de 18–20 segundos por dictado del benchmark, por lo que no ofrece la latencia de GPU. No hay fallback automático.

`GIANNA_INTERPRETER_BACKEND=cloud` es el valor predeterminado. El runtime llama directamente a `https://ollama.com` con la clave del `.env`; traduce el alias `:cloud` al nombre de la API y valida cada respuesta JSON. Si Cloud falla, pide aclaración o bloquea el inicio: no cambia a Qwen ni Tev. La misma conexión ofrece propuestas explícitas, por ejemplo «Mejorá la redacción», sin autorizar escrituras.

El micrófono transmite su pista nativa por WebRTC. El botón sólo indica **Micrófono conectado** después de recibir audio en el servidor, y el medidor muestra su nivel. Si pasan cinco segundos sin paquetes, ofrece **Reconectar micrófono**. Cambiar la entrada vuelve a conectar la captura.

**Borrar conversación**, junto al título del chat, limpia el historial local de la cuenta, los borradores sin enviar y el mensaje pendiente. Mantiene la sesión y las preferencias. Interrumpe respuestas pendientes y reconecta el micrófono de la ventana que pulsó el botón. Los tickets registrados y sus operaciones conservan sus datos e historial. Mientras se guarda o comprueba una operación, hay que esperar a conocer el resultado antes de borrar.

Documentación: [arquitectura](docs/architecture.md), [voz](docs/voice.md), [operación y privacidad](docs/operations.md), [API de tickets](docs/tickets-integration.md), [perfiles y extensiones](docs/profiles.md), [pruebas](docs/testing.md), [resultados de aceptación](docs/acceptance-report.md), [referencias y licencias](docs/references.md).
