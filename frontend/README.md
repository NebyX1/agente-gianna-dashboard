# Frontend operativo

Aplicación independiente para admin/operator: login + OTP, tablero Kanban con arrastre de tarjetas completas, lista en tabla, creación rápida en diálogo, filtros avanzados desplegables, detalle/historial, edición, estado, ocultación, estadísticas y administración. Viewer es rechazado por el servidor y por la guarda de rutas.

El tema claro/nocturno se aplica a todas las vistas y diálogos. Usa la preferencia del sistema al iniciar y guarda la elección en `idl-tickets-theme`; el botón de la barra superior cambia el tema. El tema nocturno usa azul profundo, acciones cian, acentos violeta y bordes neón por estado. El tablero ocupa el ancho disponible y conserva columnas de al menos 280 px con desplazamiento horizontal en pantallas pequeñas. Tarjetas, formularios, tablas, detalle y estadísticas comparten las variables de tema; se conserva el contraste legible y se respeta movimiento reducido.

Las vistas operativas y los diálogos usan todo el ancho disponible, con márgenes de 32 px (16 px en móvil). El navegador visible administrado por Gianna usa el tamaño real de la ventana, sin un viewport emulado fijo; la consola y el visualizador comparten ese comportamiento.

`AppLayout` contiene la navegación común y `ThemeProvider` administra el tema. `features/tickets/` separa tarjetas, tablero, tabla, filtros, creación rápida y política/coordenadas de arrastre. Las páginas se cargan por separado con React.lazy. `TicketsPage` coordina consultas y acciones sin duplicar formularios ni reglas de negocio.

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

Node 22.23.3 fijado en `.nvmrc`. `VITE_API_URL` es una URL absoluta completa que termina en `/api/v1`. Es obligatoria en desarrollo/build. El nombre y la zona tienen defaults documentados en `.env.example`. La zona de presentación es America/Montevideo, 24 horas. Puertos 5173 y `strictPort`; conexión directa cross-origin mediante Bearer, sin cookies.

```sh
docker build --build-arg VITE_API_URL=http://localhost:5000/api/v1 -t idl-tickets-frontend .
docker run --rm -p 5173:80 idl-tickets-frontend
```

En producción pasar la URL pública HTTPS de la API como argumento de build y reconstruir ante cambios. Nginx sirve rutas SPA y `/healthz`; archivos ausentes y `/api/*` devuelven 404. No necesita backend ni carpeta hermana para compilar: contrato y tipos están guardados localmente.

Para actualizar contrato, generar el archivo en backend, ejecutar `scripts/sync-contracts.py` desde la raíz y aquí `npm run contract:update`. `contract:check` detecta modificaciones de los tipos generados. No formatear manualmente `src/types/contract.ts`.

Zustand persiste únicamente token, usuario y expiración bajo `idl-frontend-session`; pending_token vive en memoria. `/auth/me` valida al entrar y periódicamente. Red caída no elimina credenciales. Un 401 o expiración limpia token y Query cache. El logout debe confirmarse en API; un fallo de red conserva la sesión para poder revocarla al reconectar.

Creación usa la misma clave/carga ante respuesta incierta. Los campos quedan congelados hasta reconciliar el intento; no hay reintentos de escritura automáticos. Las ediciones tienen version; al fallar se recarga servidor y se informa que hay que verificar el resultado. Arrastrar una tarjeta entre estados activos permitidos guarda al soltar, con actualización optimista y rollback ante error/conflicto. Resolver, cancelar y reabrir abren el diálogo de nota requerida; una transición inválida no escribe. Durante el arrastre y los diálogos se pausa el polling del tablero y durante una escritura se bloquean movimientos adicionales. La tarjeta tiene una vista flotante y la columna destino se ilumina. Espacio/flechas izquierda-derecha/Espacio permiten mover con teclado; Escape cancela. También se conserva el botón Cambiar estado. Los diálogos nativos contienen foco, admiten Escape y devuelven el foco. La fecha opcional usa un calendario nativo y se convierte desde America/Montevideo a UTC sin depender de la zona del dispositivo.

En Windows, si SWC rechaza la ACL de su caché nativa, ejecutar el script de configuración PowerShell de la raíz en esa sesión. Para una copia completamente separada, definir `SWC_NATIVE_BINDING_CACHE` a un directorio con permisos exclusivos del usuario. No se usan `--force` ni `--legacy-peer-deps`.
