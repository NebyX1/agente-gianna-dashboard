# Pantalla de tickets activos

SPA independiente de sólo lectura. Login + OTP propio, ruta `/pantalla`, reloj/fechas Montevideo, total y contadores, filtro de destino visible, última sincronización y rotación de todos los activos. No importa código del frontend ni contiene operaciones de tickets.

Diseño basado directamente en [plan2026-vizualizer](https://github.com/IntendenciaDeLavalleja/plan2026-vizualizer): fondo `#081122`, escudo y favicon de la referencia, reloj grande, panel central con degradado azul y tarjetas oscuras redondeadas. El panel muestra el ticket con `updated_at` más reciente; ante empate se elige el ID mayor. Es un resumen de seguimiento y no asigna prioridad ni modifica el orden de la cola. Su tarjeta lleva borde azul cuando aparece en la página actual. Login compacto con acentos azules.

```sh
cp .env.example .env
# PowerShell: Copy-Item .env.example .env
npm ci
npm run dev
npm run typecheck
npm run lint
npm test
npm run contract:check
npm run build
```

Node 22.23.3, puerto 5174 fijo. `VITE_API_BASE_URL` obligatorio, absoluto y terminado en `/api/v1`. Equivale al `VITE_API_URL` del frontend. Defaults: nombre `Tickets activos · IDL`, zona America/Montevideo, polling 5000 ms (rango 1000–60000), rotación 15000 ms (5000–60000). Se rechazan números no finitos y URLs incoherentes.

```sh
docker build --build-arg VITE_API_BASE_URL=http://localhost:5000/api/v1 -t idl-tickets-visualizer .
docker run --rm -p 5174:80 idl-tickets-visualizer
```

Nginx puerto 80, fallback de navegación, `/healthz`, assets ausentes 404 y rechazo claro de `/api/*`. Configuración pública incorporada al build; en Coolify marcar `VITE_*` como build variables y reconstruir. No incluir cuentas/tokens en estas variables. El build es autosuficiente con el snapshot OpenAPI y tipos locales.

TanStack Query conserva el último conjunto cuando falla una consulta. La pantalla lo marca desactualizado ante error HTTP, evento offline o más de `max(15 s, 3 × polling)` sin éxito. Primera carga fallida muestra error. Un vacío exitoso muestra la ausencia de activos; un vacío previo durante desconexión se indica como pendiente de confirmar. Navigator online por sí solo no implica conexión sana. 401/403 retiran datos y detienen polling mediante limpieza de sesión.

No filtra por día/hora: los pendientes anteriores permanecen. Orden servidor por created_at/ID. La página se conserva durante polling; cambia únicamente al rotar, cambiar filtro o ajustar capacidad. Cantidad por página calculada según viewport; la tipografía escala en 4K. Fullscreen sólo por botón y maneja rechazo del navegador.

La presentación compacta reduce títulos, reloj, destacado, márgenes y controles. Las tarjetas usan filas de hasta 170 px (300 px en 4K) para evitar que se estiren cuando hay pocos tickets. Capacidad: tres tarjetas en 1366×768, seis en 1920×945, nueve en 1920×1080 y dieciséis en 3840×2160, con espacio para el panel central y los controles. Todas las páginas rotan, incluso si el destacado está en otra página. Durante una falla de conexión se conservan el panel y la grilla, junto al aviso de datos desactualizados.

Persistencia de token separada: `idl-visualizer-session`; pending sólo memoria. Sin refresh token. Tras 14 horas por defecto se solicita login nuevamente; duración viewer ajustable con `DISPLAY_JWT_ACCESS_HOURS` del backend. La cuenta puede cambiar su contraseña o revocar su sesión, sin acceso administrativo.

Actualizar tipos mediante `npm run contract:update` después de sincronizar el contrato local. En PowerShell el script `scripts/windows-toolchain.ps1` soluciona la ACL de caché SWC cuando el entorno la necesita.
