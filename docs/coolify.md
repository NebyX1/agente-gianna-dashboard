# Despliegue en Coolify

No se publicó a producción. Se consultó la [documentación oficial Dockerfile de Coolify](https://coolify.io/docs/applications/builds/dockerfile) el 4/10/2026: Base Directory define el contexto; Dockerfile Location se interpreta relativo a ese directorio. No había una instancia/version de Coolify del usuario disponible para comprobar su UI concreta. Revisar que el log del build use exactamente los contextos de la tabla; algunas versiones muestran `/Dockerfile` en el campo, relativo a Base Directory.

Crear tres recursos de aplicación del mismo repositorio, con Build Pack Dockerfile:

| Recurso | Base Directory / Dockerfile Location | Puerto | Dominio de ejemplo reemplazable | Variables build | Runtime / dependencias | Salud |
|---|---|---|---|---|---|---|
| backend | `/backend` / `Dockerfile` | 5000 | `https://api.tickets.example.com` | Ninguna credencial | DB MariaDB, Redis compartido, SMTP, secretos y CORS | `/healthz`; controlar `/readyz` |
| frontend | `/frontend` / `Dockerfile` | 80 | `https://tickets.example.com` | VITE_API_URL=`https://api.tickets.example.com/api/v1`, nombre/zona | Nginx; API accesible desde navegador | `/healthz` |
| visualizer | `/visualizer` / `Dockerfile` | 80 | `https://pantalla.tickets.example.com` | VITE_API_BASE_URL con la misma URL; nombre/zona/polling/rotación | Nginx; misma API | `/healthz` |

Estos dominios son ejemplos bajo example.com, no direcciones reales de IDL. Configurar DNS, TLS y orígenes propios. Los tres Dockerfiles se construyen con `docker build ... ./carpeta`; ninguno copia código de otra carpeta.

## Variables

Marcar `VITE_*` como **build variables** en Coolify. Se consumen en el stage Node por ARG/ENV y quedan en JavaScript. Modificarlas exige reconstruir. El navegador debe resolver la API pública HTTPS; jamás colocar `backend`, `mariadb`, `redis` ni un hostname privado Docker en VITE_API_URL. Esas variables son públicas: nunca tokens, passwords o credenciales de usuarios.

Backend, runtime (reemplazar todos los marcadores y URL-encodear la contraseña de la URI):

```dotenv
APP_ENV=production
PORT=5000
DATABASE_URI=mariadb+mariadbconnector://idl_tickets:<PASSWORD_URL_ENCODED>@<DB_PRIVADA>:3306/idl_tickets
SECRET_KEY=<SECRETO_ALEATORIO_FUERTE>
JWT_SECRET_KEY=<OTRO_SECRETO_ALEATORIO_FUERTE>
JWT_ACCESS_HOURS=14
DISPLAY_JWT_ACCESS_HOURS=14
FRONTEND_URL=https://tickets.example.com
CORS_ORIGINS=https://tickets.example.com,https://pantalla.tickets.example.com
DASHBOARD_ALLOWED_ORIGIN=https://pantalla.tickets.example.com
RATELIMIT_STORAGE_URI=redis://<REDIS_PRIVADO>:6379/0
MAIL_SERVER=<SMTP_REAL>
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USE_SSL=false
MAIL_USERNAME=<CUENTA_SMTP>
MAIL_PASSWORD=<PASSWORD_SMTP>
MAIL_DEFAULT_SENDER=Tickets IDL <tickets@<DOMINIO_PROPIO>>
MAIL_TIMEOUT=10
DEFAULT_DESTINATION_UNIT_CODE=TI
RUN_MIGRATIONS=true
TRUSTED_PROXY_HOPS=0
GUNICORN_WORKERS=2
GUNICORN_THREADS=4
GUNICORN_TIMEOUT=45
```

Generar secretos distintos de al menos 32 caracteres, por ejemplo `python -c "import secrets; print(secrets.token_hex(32))"` en un canal privado. No copiar `.env` de desarrollo a la imagen ni al repositorio. MariaDB y Redis son infraestructura adicional, con red privada común al backend; no crear DB por SPA. Usar volumen persistente en DB, backups y Redis compartido para múltiples workers/réplicas. Mailpit sólo es desarrollo: producción utiliza SMTP real.

CORS requiere origen exacto sin rutas, sin `/api/v1` y sin wildcard. Cliente sin withCredentials y servidor supports_credentials=False. Mantener Authorization/Idempotency-Key/X-Request-ID y OPTIONS públicos. Todas las escrituras siguen verificando JWT/rol/versión en servidor.

ProxyFix no confía en X-Forwarded-For por defecto. Sólo configurar `TRUSTED_PROXY_HOPS=1` (o la longitud comprobada de la cadena) cuando el tráfico al contenedor sólo provenga del proxy confiable por red privada. No exponer directamente el puerto backend al público si se habilita esa confianza. [Flask-Limiter documenta la configuración detrás de proxy](https://flask-limiter.readthedocs.io/en/stable/recipes.html#deploying-an-application-behind-a-proxy).

## Primer despliegue

1. Preparar DB MariaDB 11.4 y Redis compartido, credenciales/red/volumen y SMTP. Configurar variables runtime y dominios.
2. Para una réplica, dejar RUN_MIGRATIONS=true: el entrypoint portable aplica migraciones una vez antes de Gunicorn y aborta si fallan. No se ejecutan por worker.
3. Para varias réplicas, correr `flask --app wsgi db upgrade` como job único con la misma imagen/configuración/red y RUN_MIGRATIONS=false en réplicas. No depender sólo del hook previo de Coolify: [no se ejecuta en el primer despliegue sin contenedor existente](https://coolify.io/docs/applications/builds/dockerfile).
4. En terminal del backend: `flask --app wsgi seed-catalogs`, después `flask --app wsgi create-admin` de forma interactiva. No activar demo/test-users ni resetear passwords al arrancar.
5. Construir ambas SPAs con URLs públicas completas. Verificar `/healthz`, `/readyz`, OPTIONS desde ambos orígenes y ausencia de Access-Control-Allow-Origin para un origen no permitido.
6. Login con OTP recibido en SMTP real; crear ticket, comprobar pantalla en otro navegador, transición/resolución, ocultación e historia/restauración. Crear viewer y comprobar rechazo de escrituras HTTP.

Backend corre no root, logs stdout/stderr, sin cuerpos/querystrings sensibles, cierre ordenado Gunicorn y healthcheck Python presente. Nginx devuelve 404 para assets ausentes y `/api/*`, index sin caché y sólo assets con hash immutable. No necesita servicios externos para renderizar.

## Actualizaciones y recuperación

Respaldar MariaDB antes de migrar. Probar nuevas migraciones en una copia aislada, actualizar imagen, migrar una sola vez y desplegar réplicas. Ejecutar `flask --app wsgi db check` para drift. Las SPAs pueden actualizarse independientemente mientras respeten el contrato. Guardar versiones/digests de imágenes y backup asociado; revertir imágenes no implica revertir datos automáticamente.

Desde una terminal privada del recurso DB, exportar con `mariadb-dump --single-transaction --routines --triggers -u <USUARIO_BACKUP> -p idl_tickets > backup.sql` (contraseña solicitada, no en comando). Guardar copia cifrada fuera del servidor, verificar restore en otra DB y controlar retención. Restaurar un dump en una **base nueva** con `mariadb -u <USUARIO_RESTORE> -p idl_tickets_restore < backup.sql`; apuntar primero un backend aislado para verificar conteos, historia y sesiones. PowerShell puede ejecutar estas redirecciones dentro del contenedor Linux, evitando conversión de encoding por versiones antiguas del shell.

Desactivar usuario, cambiar rol o contraseña invalida sesiones en DB. `reset-password` solicita la nueva contraseña oculta y requiere entrega segura. El sistema protege al último admin activo. La TV inicia sesión por jornada; configurar duración viewer si corresponde, sin tokens públicos de acceso permanente.

## Equivalencia local

Compose expone sólo loopback: DB 3307, Redis 6379, SMTP 1025, Mailpit 8025, API 5000, SPAs 5173/5174. `scripts/init-local.py` genera claves hex seguras para URI. Dentro del contenedor se usan nombres privados; las variables Vite siguen apuntando a localhost:5000 porque las consume el navegador del host. No cambiar esos valores a DNS interno Docker.
