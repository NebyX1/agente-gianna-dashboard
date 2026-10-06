# Arquitectura y decisiones

Revisión del 4 de octubre de 2026. El directorio inicial estaba vacío. Las tres referencias se clonaron como lecturas locales ignoradas, sin modificar archivos ni despliegues de esos proyectos.

| Referencia | HEAD efectivamente consultado | Comparación con snapshot pedido |
|---|---|---|
| [Civic Flow](https://github.com/IntendenciaDeLavalleja/civic-flow-frontend) | `e156773d7bf75c2c1b6ea3c36c67ce10f0254680` | Igual |
| [plan2026-vizualizer](https://github.com/IntendenciaDeLavalleja/plan2026-vizualizer) | `16d3b7cf1fd023bde8fed8d6841d0e8ad29a596e` | Igual |
| [plan2026-backend](https://github.com/IntendenciaDeLavalleja/plan2026-backend) | `33c45d291d335546bb5ffb89ed44bcd651b6649b` | Igual |

Se contrastaron manifests/lockfiles, clientes Axios y Query, auth/hooks/store/rutas, Board/formularios/validadores/CSS, configuración Vite/TS/ESLint/env, DisplayPage/fechas/estados/conexión/tests y Docker/Nginx. Del API se revisaron factory, config/extensions, rutas auth/dominio, JWT/responses, modelos/schemas/services, comandos, migraciones, requirements, entrypoint/Gunicorn y tests. Los README no se usaron como contrato.

## Adaptación

Civic aporta la separación Axios, Query, Zustand, rutas protegidas, RHF/Zod y dnd-kit. Se cambia el dominio de tareas por tickets y se distingue origen de destino. Las URL se validan estrictamente: no se copia su fallback `/api` ni su agregado automático de prefijo. Se agregan control de versión, polling operativo y validación de sesión persistida. Se evita el arrastre de toda la tarjeta sobre controles: cada tarjeta tiene un handle y acciones semánticas.

El visualizador aporta carpetas por feature, auth independiente y polling. Se reemplaza Fluent por Tailwind 4/DaisyUI 5, se eliminan las operaciones de turnos y filtros horarios. La conexión se deduce de éxito/error HTTP y antigüedad de los datos, corrigiendo el hook de referencia que devolvía conectado aun cuando no había éxito. No se copian instrucciones antiguas de cookies/CSRF: ambos clientes usan Bearer.

La composición visual sigue su `DisplayPage`: fondo azul oscuro `#081122`, escudo institucional, reloj, fecha, panel central azul y tarjetas con fondo blanco al 6 %, bordes tenues y radios de 16/20 px. Se reutilizan `Logo.webp` y `favicon.ico` de la referencia. En tickets de soporte el panel central informa la actualización más reciente (`updated_at`, desempate por ID); no es un llamado de turnos. La grilla conserva todos los pendientes y el orden del servidor. Los estados, filtro, conexión y controles se adaptan a esa misma paleta; el login adopta una tarjeta compacta con botones azules.

Flask conserva factory/extensiones desacopladas/blueprints/modelos/schemas/servicios/CLI/Alembic. Se excluyen Flask-Login, Jinja forms, MinIO y recursos del sistema de turnos. El correo es síncrono con timeout y error controlado; no se copia el thread que ocultaba fallos SMTP ni códigos universales de desarrollo. La migración es nueva, probada en MariaDB vacía y sin drift; no se copia la cadena histórica divergente.

## Versiones finales

Versiones resueltas verificadas en los lockfiles de referencia (no sólo los rangos de sus manifests):

| Dependencia | Civic | Visualizador de referencia | Entrega, ambos clientes |
|---|---|---|---|
| React | 19.2.4 | 19.2.8 | 19.2.4 |
| Vite / plugin SWC | 6.0.11 / 3.7.2 | 7.3.6 / 4.3.3 | 7.3.6 / 4.3.3 |
| TypeScript | 5.9.3 | 5.9.3 | 5.9.3 |
| Tailwind | 4.0.0 | No usado; Fluent UI | 4.3.3 + DaisyUI 5.7.47 |
| Query / Axios | 5.90.21 / 1.7.9 | 5.101.4 / 1.19.0 | 5.104.1 / 1.20.0 |
| Zustand | 5.0.11 | 5.0.14 | 5.0.15 |
| ESLint / Vitest | 9.18.0 / no usado | 9.39.5 / 4.1.10 | 10.12.0 / 4.1.11 |

Se unificó React con la versión de Civic y Vite/SWC con las versiones resueltas del visualizador. El backend conserva las versiones principales de su referencia; sustituye `mariadb>=1.1.0` por el conector exacto 1.1.14 y elimina dependencias de turnos, almacenamiento de archivos y formularios de servidor.

- Runtime backend Docker: Python `3.12.12-slim-bookworm`. Pruebas de unidad Windows en 3.12.14; integración y API en el runtime Docker. Flask 3.1.2, SQLAlchemy 2.0.46, Flask-SQLAlchemy 3.1.1, Migrate 4.1.0/Alembic 1.18.1, Marshmallow 4.0.1, JWT Extended 4.7.1, Argon2 25.1.0, Mail 0.10.0, CORS 6.0.2, Limiter 4.1.1, Connector MariaDB 1.1.14, Redis client 5.2.1, Gunicorn 24.1.1. Transitivas exactas en requirements; build real del conector contra Connector/C.
- Node `22.23.3-alpine` en ambas imágenes; `.nvmrc` idéntico. El host de verificación tiene Node 22.15.1, compatible con los mínimos Vite/ESLint. React/DOM 19.2.4, TypeScript 5.9.3, Vite 7.3.6, SWC plugin 4.3.3, Tailwind/Vite plugin 4.3.3, DaisyUI 5.7.47, Router 7.18.4, Query 5.104.1, Axios 1.20.0, Zustand 5.0.15 y Lucide 1.51.0.
- Frontend: RHF 7.89.0, resolvers 5.9.1, Zod 4.6.5, dnd-kit/core 6.3.1 y utilities 3.2.2. Fechas con Intl explícito. Estadísticas con barras CSS y tablas accesibles, sin agregar otra biblioteca gráfica.
- Vitest 4.1.11, Testing Library 16.3.3, ESLint 10.12.0/typescript-eslint 8.71.0. Se actualizó ESLint por mantenimiento y Vitest por avisos de seguridad detectados en versiones anteriores; `npm audit` final sin vulnerabilidades. Lockfiles propios y `npm ci`, sin flags de incompatibilidad. El npm 11.4.1 del host falló al resolver peers opcionales; npm 11.21.0 resolvió normalmente. La instalación limpia con `npm ci` y los builds Docker se verificaron.
- Infraestructura local: MariaDB 11.4.8, Redis 7.4.8, Mailpit 1.27.8. SPAs sobre Nginx 1.28.0. Playwright 1.58.2, Axe 4.11.1.

Se retuvo Vite 7.3.6 del lockfile de la referencia; ambos clientes usan exactamente la misma combinación. Se consultaron [requisitos oficiales Vite](https://vite.dev/guide/), [política de releases](https://vite.dev/releases), [soporte Node](https://nodejs.org/en/about/previous-releases), [integración DaisyUI/Vite](https://daisyui.com/docs/install/vite/) y [Flask](https://flask.palletsprojects.com/en/stable/installation/). Los manifests del registro confirmaron engines y peers; instalación, tipado y builds comprobaron compatibilidad efectiva.

## Frontend operativo

El frontend operativo separa la estructura común (`AppLayout`), el tema persistente (`ThemeProvider`) y los componentes del flujo de tickets (`features/tickets/`). El tablero admite arrastre de toda la tarjeta, vista flotante y destinos resaltados; la lista utiliza una tabla. El polling se pausa durante los diálogos/arrastre. Los cambios activos válidos usan la mutación con versión y rollback; cerrar o reabrir requiere el diálogo con nota antes de escribir. La creación rápida está en un diálogo y los filtros avanzados se despliegan a demanda. El tema nocturno comparte tokens con formularios, estadísticas, administración y autenticación; no modifica el diseño independiente del visualizador. Las páginas se cargan por rutas con React.lazy.

## Persistencia y seguridad

MariaDB es la única fuente de verdad: tickets, eventos, usuarios, desafíos, sesiones e idempotencia. Redis comparte cuotas por cuenta e IP entre workers; no es cola ni base de tickets. SMTP tiene timeout de 10 s configurable. Cuenta: 40 acciones auth/hora agregadas entre login/verify/resend; IP: 300/hora. Desafío: cinco intentos, 10 minutos, un uso; reenvío y nuevo login respetan cooldown de 60 s. El usuario se bloquea y refresca desde DB; el desafío se lee con lock, evitando que el identity map o snapshot de una consulta previa permita doble consumo.

JWT incluye propósito: pending 2fa no puede autenticar rutas de negocio. Sesión en DB con auth_version permite logout y revocación de todas las sesiones ante cambio de contraseña/rol/actividad. Roles se verifican en cada endpoint. No hay refresh. Tokens en localStorage tienen el riesgo habitual ante XSS; se renderiza texto con React, sin HTML de usuario. Query cache y credenciales se limpian al perder autorización; fallos de red conservan la información marcada como antigua.

Ticket code usa auto-increment real (puede haber huecos tras rollback; nunca MAX+1). SQLAlchemy version_id_col y lock con comprobación explícita protegen escrituras. Ticket/evento/idempotencia se confirman juntos. La restricción única usuario/scope/clave serializa intentos simultáneos. El resultado original se guarda en JSON y se envuelve con request_id nuevo al reproducir; archivo devuelve sólo comprobante. Limpieza explícita de claves después de 48 h, garantía mínima 24 h.

UTC se guarda en DATETIME(6); el TypeDecorator sólo acepta datetimes conscientes y normaliza la lectura. JSON tiene Z. Días de filtros/cohortes se convierten desde America/Montevideo; los intervalos son [inicio, siguiente medianoche). occurred_at es opcional, requiere zona y no puede ser futuro.

Los eventos guardan actor, etiquetas/IDs antes/después, nota y canal manual_ui asignado por servidor. El archivado es separado del estado, oculta para todas las vistas operativas y TV, conserva estadísticas y restringe lectura/historia al admin. Restaurar conserva estado. Reabrir conserva primera respuesta y elimina timestamps del cierre vigente; historia conserva el cierre anterior.

Las consultas de tickets cargan relaciones por joined loading para evitar N+1. Las estadísticas básicas recorren la cohorte completa en backend con relaciones cargadas, nunca una página del cliente. Para volúmenes mayores se puede migrar su agrupación a SQL sin cambiar el contrato; no hay SLA/BI en esta etapa.

## Fronteras de despliegue

Cada SPA guarda contrato/tipos locales; no necesita carpetas hermanas, servidor ni descarga de schema para build. Los scripts de raíz orquestan y sincronizan snapshots deliberadamente. `/api/v1` es canónico para todos. CORS exacto para ambas SPAs; preflight público; sin credentials/cookies. ProxyFix tiene cero hops por defecto: sólo habilitar con red privada protegida y cadena de proxy conocida.

Gianna recibe como preparación API operativa, OpenAPI 3.1 generado desde rutas/validadores, tipos sincronizados, errores uniformes, idempotencia/concurrencia y controles DOM accesibles. No se incorpora un framework ni integración simulada.
