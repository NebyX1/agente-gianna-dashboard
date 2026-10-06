# Instalación rápida · Gianna en otro PC

Esta guía prepara una instalación nueva en Windows: el tablero, el visualizador, la base de datos y Gianna. No necesitás editar código. La descarga inicial requiere Internet; la conversación también utiliza Ollama Cloud.

**Cómo ejecutar los comandos:** buscá «PowerShell» en Inicio y abrilo. Copiá una línea, pegala y presioná Enter. Esperá a que termine antes de seguir. Elegí una carpeta donde tengas permiso para guardar el proyecto. No hace falta instalar Codex ni otra herramienta de asistencia para desarrolladores.

## 1. Instalá los programas necesarios

| Programa | Qué instalar y para qué |
|---|---|
| [Git](https://git-scm.com/downloads) | Copia y actualiza el proyecto desde GitHub. Las opciones predeterminadas del instalador son suficientes. |
| [Docker Desktop para Windows](https://docs.docker.com/desktop/setup/install/windows-install/) | Ejecuta la base de datos y las webs. Seguí su asistente para WSL 2 y usá el motor de contenedores Linux. Abrilo y esperá a que el motor esté activo. |
| [Python](https://www.python.org/downloads/) | Instalá Python **3.12**, de 64 bits, y marcá «Add python.exe to PATH». Se usa para preparar la configuración. |
| [Node.js 22.23.3](https://nodejs.org/download/release/v22.23.3/) | En Windows de 64 bits, elegí el instalador `node-v22.23.3-x64.msi`. Incluye npm y permite construir la consola de Gianna. |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | Instala las versiones de Python y sus dependencias fijadas por el proyecto. |

Para instalar uv con el administrador de paquetes de Windows:

```powershell
winget install --id astral-sh.uv -e
```

Cerrá PowerShell y abrilo de nuevo después de instalar esos programas. Comprobá que estén disponibles:

```powershell
git --version
python --version
node --version
uv --version
docker compose version
docker info
```

Python debe indicar 3.12 y Node debe indicar una versión 22.13 o posterior dentro de la rama 22; la recomendada es 22.23.3. Docker Compose debe ser 2.24.4 o posterior. Si `python` abre Microsoft Store o muestra otra versión, usá `py -3.12` en lugar de `python` para ejecutar `scripts/init-local.py`.

### Elegí cómo procesar la voz

**Con GPU NVIDIA:** es el modo predeterminado. Necesitás un controlador compatible, las bibliotecas cuBLAS de CUDA 12 y cuDNN 9 accesibles en el `PATH`, además del runtime de Visual C++ que requiere CTranslate2. Seguí las instrucciones de [faster-whisper para GPU](https://github.com/SYSTRAN/faster-whisper#gpu) y [CTranslate2 para Windows](https://opennmt.net/CTranslate2/installation.html). El instalador de Gianna no instala los controladores ni CUDA; `doctor` comprobará si el modelo puede cargarse.

**Sin GPU compatible:** elegí CPU. La configuración está en el paso 4; no requiere CUDA. El reconocimiento de voz puede tardar bastante más que con GPU. No hay un cambio automático a CPU cuando falla CUDA.

## 2. Descargá el proyecto y prepará las webs

Desde la carpeta elegida para guardar el proyecto:

```powershell
git clone https://github.com/NebyX1/agente-gianna-dashboard.git
cd agente-gianna-dashboard
python scripts/init-local.py
docker compose --profile development up -d --build --wait
docker compose exec backend flask --app wsgi seed-catalogs
docker compose exec backend flask --app wsgi create-admin
```

La primera construcción puede demorar varios minutos según el equipo y la conexión. Esperá a que termine sin errores.

- El preparador crea los archivos `.env` y secretos propios de esta instalación. **Conservalos**; no reemplaza los que ya existan.
- Los catálogos contienen áreas, categorías y estados iniciales. Podés ajustarlos después desde Administración. Ejecutar nuevamente `seed-catalogs` agrega los datos iniciales faltantes sin sustituir los existentes.
- El último comando pide correo, nombre y contraseña del primer administrador. La contraseña debe tener al menos 12 caracteres; escribila dos veces. No aparece en pantalla mientras la tipeás. Elegí una que recuerdes y guardala en un lugar seguro.

Creá el administrador una sola vez. Si el correo ya existe, el comando lo informa y no reemplaza esa cuenta.

## 3. Comprobá el ingreso

1. Abrí el [tablero](http://localhost:5173) e ingresá con el correo y contraseña recién creados.
2. Cuando solicite el código por correo, abrí [Mailpit](http://localhost:8025), entrá al mensaje más reciente y copiá el código.
3. Volvé al tablero y completá el ingreso.
4. Abrí el [visualizador](http://localhost:5174). Tiene su propio ingreso; usá la misma cuenta o creá una cuenta de visualizador desde Administración.

Mailpit es un buzón de desarrollo dentro de tu PC: los mensajes no llegan a tu casilla real. Las cuentas adicionales se crean desde **Administración → Usuarios**. El administrador gestiona el sistema; el operador trabaja con tickets y el visualizador consulta sin modificarlos.

## 4. Instalá y configurá Gianna

En PowerShell, desde la raíz `agente-gianna-dashboard`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\agent\scripts\setup.ps1
notepad .\agent\.env
```

El permiso de ejecución se aplica a ese proceso de PowerShell; no cambia la política global de Windows. El instalador prepara Python 3.12, dependencias, Chromium, la consola y los modelos. Los modelos ocupan varios GB y se descargan una sola vez. No los guarda dentro del repositorio. Si ya hay un `agent/.env`, lo conserva.

Obtené tu clave en [Ollama Cloud](https://ollama.com/settings/keys). En el archivo que abrió el Bloc de notas, buscá estas líneas y dejalas así, usando **tu propia clave**:

```dotenv
GIANNA_TICKETS_API=http://localhost:5000
GIANNA_TICKETS_WEB=http://localhost:5173
GIANNA_INTERPRETER_BACKEND=cloud
OLLAMA_API_KEY=pegá_aquí_tu_clave
OLLAMA_MODEL=deepseek-v4.1-flash:cloud
```

Guardá el archivo. Las direcciones no llevan `/api/v1`: Gianna agrega esa ruta al consultar. No hace falta instalar un servidor Ollama local. La clave pertenece al archivo privado `agent/.env`; no debe ponerse en variables `VITE_*`, capturas ni archivos que se suban a GitHub. El servicio remoto recibe el texto y contexto de conversación; el audio se procesa en este equipo.

### Si elegiste CPU

En el mismo `agent/.env`, cambiá estas tres líneas; si alguna no existe, agregala:

```dotenv
GIANNA_STT_DEVICE=cpu
GIANNA_STT_COMPUTE_TYPE=int8
GIANNA_STT_GRACE_SECONDS=45
```

Conservá el resto del archivo y tu clave. `agent/.env.cpu.example` es una referencia de estas opciones, no un reemplazo de toda la configuración.

## 5. Verificá y empezá a conversar

Con Docker activo y Gianna todavía cerrada:

```powershell
cd agent
.\.venv\Scripts\python.exe -m gianna doctor
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

Si `doctor` informa un componente no disponible, resolvé ese punto antes de continuar. Comprueba servicios, configuración y modelos; no reemplaza la prueba con tu micrófono.

Se abrirá el navegador propio de Gianna con tickets y la consola. **Iniciá sesión en su pestaña de tickets**, incluso si ya entraste desde otro navegador. Cada navegador conserva su propia sesión. Usá el código de Mailpit cuando te lo pida.

En la consola, presioná **Conectar micrófono**, permití el acceso y comprobá que el medidor se mueva al hablar. Decí:

> «Gianna, quiero registrar un ticket de Sociales: necesitan cambiar las hojas de una impresora».

Revisá lo que prepara, respondé las preguntas necesarias y confirmá cuando los datos sean correctos. La operación debe aparecer guardada en el tablero y acompañada por un comprobante. También podés enviar un mensaje de texto desde la consola.

## Inicio y cierre de cada día

No necesitás volver a instalar ni descargar los modelos. Abrí Docker Desktop y, desde la raíz del proyecto, ejecutá:

```powershell
docker compose --profile development up -d --wait
powershell -NoProfile -ExecutionPolicy Bypass -File .\agent\scripts\start.ps1
```

Para terminar, presioná **Cerrar Gianna** y después, desde la raíz:

```powershell
docker compose down
```

**No uses `docker compose down -v` para cerrar:** borra los volúmenes donde viven los datos. Podés usar el tablero y el visualizador sin iniciar Gianna.

## Si algo no funciona

| Síntoma | Qué revisar |
|---|---|
| «El comando no se reconoce» | Confirmá que el programa esté instalado y abrí una terminal nueva. Para Python probá `py -3.12`. |
| Docker no responde | Abrí Docker Desktop, completá su configuración de WSL 2 y esperá a que el motor Linux esté activo. Revisá `docker info`. |
| Una web no abre | Ejecutá `docker compose ps` desde la raíz. Los servicios deben estar activos; revisá los errores con `docker compose logs --tail 80 backend`. |
| «El puerto ya está en uso» | Cerrá otra instalación que esté usando esos puertos. La instalación habitual usa 5000, 5173, 5174, 8025, 3307 y 6379; Gianna usa 7860 y Piper 5001. |
| No llega el código | En desarrollo buscá el mensaje en Mailpit, puerto 8025. Usá el perfil `development` al iniciar Docker para habilitarlo. |
| Se agotaron los intentos de ingreso | Esperá el tiempo indicado por el sistema antes de solicitar otro código o intentar nuevamente. |
| Fallan CUDA o cuDNN | Comprobá las bibliotecas GPU y reiniciá la terminal para actualizar el `PATH`, o configurá CPU como se indica arriba. |
| Falla Ollama Cloud | Revisá la clave, la conexión a Internet y que la cuenta permita utilizar el modelo configurado. |
| Gianna no recibe voz | Revisá el permiso del navegador, elegí el micrófono correcto y usá **Reconectar micrófono**. El medidor confirma si llega audio. |
| La apariencia no se actualiza | Recargá con Ctrl+F5 después de reconstruir o actualizar las webs. |

## ¿Querés trasladar datos o publicar para más personas?

Esta guía crea **una instalación nueva**. Clonar GitHub no copia los tickets ni las cuentas de otro PC. Para trasladarlos, hacé una copia de seguridad de MariaDB y restaurala en el nuevo destino; no copies archivos de un volumen mientras la base está funcionando. Consultá [copias y restauración](coolify.md).

Para varios puestos, desplegá las webs y la API con dominios HTTPS y un proveedor de correo real. Gianna permanece en el PC del micrófono y se conecta a esos dominios. La [guía de Coolify](coolify.md) describe ese despliegue.

La demo usada durante el desarrollo tiene otros puertos: API 5300, tablero 5373 y visualizador 5374. `start-testing.ps1` pertenece a esa demo. Para un PC nuevo usá las direcciones y el inicio normal de esta guía. Los preparadores E2E reinician datos descartables de pruebas; no son instaladores para tu base de trabajo.

En Linux están disponibles `bash agent/scripts/setup.sh` y `bash agent/scripts/start.sh`; instalá los mismos requisitos y verificá el audio y `doctor` en ese equipo. Las pruebas de voz real realizadas en este proyecto corresponden a Windows.
