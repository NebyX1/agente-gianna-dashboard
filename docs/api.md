# Contrato API v1

Base completa: `http://localhost:5000/api/v1`. Cada cliente agrega sufijos como `/tickets`; no agrega otro `/api`. Documento: `backend/contracts/openapi.json` y `GET /api/v1/openapi.json` (público, documento directo). Generación: `python contracts/generate.py`; control de sincronía probado contra rutas registradas, validadores y respuestas reales.

Los éxitos usan `{"ok":true,"data":...,"meta":{"request_id":"..."}}`. Las páginas tienen `data.items/page/per_page/total/pages`. Errores: `{"ok":false,"error":{"code":"validation_error","message":"Revisá los campos indicados","errors":{"description":["..."]}},"meta":{"request_id":"..."}}`. Mensajes en español; campos desconocidos/reservados rechazados. 401 inválido/expirado/revocado; 403 rol; 404 inexistente o ticket oculto no legible; 409 versión/idempotencia/duplicado; 422 validación/transición; 429 cuota/cooldown con Retry-After; 503 correo/readiness no disponibles. Toda respuesta tiene X-Request-ID actual.

## Autenticación

1. `POST /auth/login` con email/password: verifica Argon2 y envía OTP real de seis dígitos. Devuelve pending_token, expires_in=600 y resend_after=60; no autentica rutas de negocio.
2. `POST /auth/verify-2fa` con pending_token/code en JSON: devuelve access_token, expires_in, expires_at y user. Desafío vinculado a cuenta/versión, hash, máximo cinco intentos, un uso y consumo atómico.
3. `POST /auth/resend-2fa` con pending_token: reemplaza desafío tras cooldown; mantiene cuotas agregadas por cuenta e IP.
4. `GET /auth/me` valida la sesión activa; `POST /auth/logout` la revoca. `PUT /auth/change-password` requiere current_password/new_password (12–256 caracteres) y revoca todas las sesiones.

Todas las demás rutas privadas requieren `Authorization: Bearer <access_token>`. Sin cookies, refresh o renovación silenciosa. Duración por defecto 14 h; viewer puede usar una duración separada configurada en servidor. Pending token es sólo para el flujo 2FA. No enviar contraseñas ni OTP en URL.

## Rutas y roles

| Operación | admin | operator | viewer |
|---|---|---|---|
| auth/me, logout, cambio de contraseña propio | Sí | Sí | Sí |
| display/config, display/tickets | Sí | Sí | Sí |
| catalogs | Sí | Sí | No |
| tickets GET/POST, detalle, PATCH, status, archive, history | Sí | Sí (visibles) | No |
| statistics/summary, statistics/problems | Sí | Sí | No |
| admin/tickets/archived, restore | Sí | No | No |
| admin/org-units, problem-types, users GET/POST/PATCH | Sí | No | No |

`GET /catalogs` devuelve unidades/tipos activos, can_receive_tickets, estados/transiciones y default_destination_unit_id. Si el código configurado no resuelve un destino activo habilitado, devuelve null y warnings. El formulario permite selección manual. Catálogos sin destinos impiden crear y explican cómo corregirlo.

`GET /tickets` acepta `q` (código/descripción, hasta 160 caracteres), origin_unit_id, destination_unit_id, problem_type_id, status (estado, lista separada por comas o active), from/to (YYYY-MM-DD), page (>=1), per_page (1–100, default 30). Orden estable por created_at/ID ascendente. Ocultos excluidos. Los días son inclusivos en Montevideo, convertidos a un intervalo UTC semiabierto.

`GET /tickets/{id}` devuelve descripción completa y referencias históricas, incluso desactivadas. Ocultos sólo admin. `PATCH /tickets/{id}` recibe campos de negocio completos más version; no estado ni autor/fecha de creación. Referencias nuevas/cambiadas deben estar activas; conservar una referencia histórica inactiva no bloquea editar la descripción.

`GET /tickets/{id}/history` es paginado y ordena eventos más recientes primero. Cada evento incluye actor descriptivo, timestamp UTC, request_id, canal manual_ui y snapshots de datos relevantes antes/después, nota/motivo. No se crea evento fuera de la transacción de negocio.

## Creación e idempotencia

```sh
curl -X POST http://localhost:5000/api/v1/tickets \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Idempotency-Key: $LOGICAL_ATTEMPT_UUID" \
  -H "Content-Type: application/json" \
  --data '{"origin_unit_id":3,"destination_unit_id":1,"problem_type_id":2,"description":"La impresora no imprime y hace un ruido raro"}'
```

En PowerShell, usar `Invoke-RestMethod` y un hashtable de headers; los IDs siempre deben provenir del catálogo real:

```powershell
$headers = @{ Authorization = "Bearer $accessToken"; 'Idempotency-Key' = [guid]::NewGuid().ToString() }
$payload = @{ origin_unit_id = $originId; destination_unit_id = $destinationId; problem_type_id = $typeId; description = 'La impresora no imprime y hace un ruido raro' }
Invoke-RestMethod -Method Post -Uri 'http://localhost:5000/api/v1/tickets' -Headers $headers -ContentType 'application/json' -Body ($payload | ConvertTo-Json)
```

201 devuelve código persistido, UTC/autor asignados por servidor y version. description se recorta y admite 10–4000 caracteres. occurred_at es opcional/null, requiere ISO con Z/offset y no puede ser futuro. created_at, created_by, archived_at y source_channel enviados libremente se rechazan.

Idempotency-Key es obligatorio al crear y archivar, 16–64 caracteres alfanuméricos/guion/underscore; UUID recomendado. Ámbito: usuario + operación/recurso. Reserva única, hash de carga normalizada, ticket/evento/resultado se confirman juntos. Misma clave/carga devuelve resultado original (incluida la versión original) con request_id nuevo. Misma clave/otra carga: 409 idempotency_conflict. La clave no sustituye autorización. Se conservan al menos 24 h; mantenimiento elimina sólo anteriores a 48 h. Tras una respuesta perdida, reintentar **con la misma carga/clave** antes de iniciar otra operación.

## Versiones, estados y ocultación

`PATCH /tickets/{id}/status`:

```json
{"status":"resolved","version":3,"note":"Se retiró el papel atascado y se probó la impresión"}
```

| Estado | Transiciones |
|---|---|
| new / Nuevo | in_progress, cancelled |
| in_progress / En curso | waiting, resolved, cancelled |
| waiting / En espera | in_progress, resolved, cancelled |
| resolved / Resuelto | in_progress (reabrir) |
| cancelled / Cancelado | new (reabrir) |

Resolver exige solución; cancelar/reabrir exigen motivo (3–1000 caracteres). first_response_at guarda la primera entrada a En curso; reapertura elimina resolved_at/cancelled_at del cierre anterior, que sigue en historia. Una transición repetida con versión vieja falla; no duplica eventos.

`POST /tickets/{id}/archive` requiere clave, version y reason. Oculta sin borrar ni cambiar estado. Devuelve comprobante mínimo ticket_id/operation/archived_at/version. El mismo usuario puede reproducir ese comprobante aunque ya no pueda leer el oculto. No habilita lectura de otros ocultos.

`POST /admin/tickets/{id}/restore` requiere version/reason, conserva estado y quita datos de ocultación. Un resuelto restaurado sigue fuera de TV. Ocultos no aceptan edición ordinaria. El listado y la historia administrativos siguen disponibles sólo al admin.

version es la esperada por el cliente; comprobación/incremento atómicos en DB. Ante 409 version_conflict se devuelve current_version/ticket_id cuando está disponible. Recargar detalle/historia y pedir revisión; no sobrescribir ni reintentar a ciegas. Frente a resultado incierto de otras escrituras, recargar para verificar; si ya no hay permiso, informar que no se pudo confirmar.

## Pantalla y estadísticas

`GET /display/tickets` entrega **todos** los activos new/in_progress/waiting no archivados, sin límite silencioso ni filtro de fecha. Único filtro: destination_unit_id. items/total/generated_at; proyección code/status/origin/destination/problem_type/created_at/updated_at/description_preview<=400. No contiene emails, usuarios, historial o notas internas. `/display/config` entrega estados y destinos habilitados.

`GET /statistics/summary` y `/statistics/problems` usan cohorte completa por created_at; from/to, origen/destino/tipo y demás filtros operativos documentados. Incluyen archivados/cancelados en altas y distribuciones. Resueltos/cancelados se cuentan por estado vigente de esa cohorte. Promedio desde creación al cierre vigente de actualmente resueltos; cancelados excluidos, null cuando no hay datos. Reaperturas sacan el ticket del promedio hasta el próximo cierre. Activos actuales son globales e independientes del período, excluyendo ocultos. Agrupaciones por ID con etiqueta actual; historia conserva anteriores.

## Administración y salud

POST catálogos requiere code/name; unidad también kind. PATCH por ID no admite code. Sin DELETE físico. parent_id rechaza ciclos; can_receive_tickets editable. POST usuarios requiere nombre/email/rol/password inicial, PATCH admite nombre/rol/actividad. Cambios de rol/actividad invalidan sesiones. No se permite eliminar al último admin activo, tampoco mediante cambios simultáneos. Restablecimiento por CLI `reset-password`, contraseña oculta y entrega por canal seguro; sin contraseñas en listados.

Fuera del prefijo: `/healthz` proceso vivo; `/readyz` DB/esquema/limiter listos o 503. CORS admite orígenes exactos configurados, Authorization/Content-Type/X-Request-ID/Idempotency-Key, expone request ID y Retry-After, y permite OPTIONS sin login. No reemplaza permisos de servidor.
