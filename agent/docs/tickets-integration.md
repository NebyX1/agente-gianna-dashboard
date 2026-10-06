# Contrato con el sistema de tickets

Las sesiones manuales y el login/2FA existentes siguen vigentes. `POST /api/v1/auth/agent-session` acepta únicamente `{}` desde la sesión normal verificada de admin/operator. Entrega una sesión hija del mismo usuario con `client_id=gianna-agent`, scope tickets y vencimiento no mayor que el padre. No acepta elegir actor, rol o canal. Viewer no puede delegar ni escribir.

La hija no administra usuarios/catálogos ni cambia contraseña. Logout del padre, desactivación y cambios de autenticación/rol invalidan su autoridad. Antes de una escritura, el agente vuelve a consultar `/auth/me`; el backend verifica siempre los permisos actuales. El broker sólo observa el contrato normal de 2FA o GET me con Bearer en su propio navegador/origen. No extrae credenciales de otros perfiles, almacenamiento arbitrario o CDP.

Las cinco escrituras —crear, editar, estado, archive y restore— exigen `X-Agent-Operation-ID` e `Idempotency-Key` para la sesión hija. La identidad se liga a actor + cliente lógico + operation ID + key + herramienta + recurso + SHA-256 del JSON enviado validado, ordenado por claves, UTF-8, sin espacios y sin escape ASCII. Los defaults opcionales ausentes no se agregan al hash. Editar exige los campos completos del contrato existente; el agente conserva los campos no corregidos al leer el ticket.

MariaDB reserva las identidades con índices únicos. Mutación, TicketEvent con `channel=voice_agent`, vínculos de eventos y recibo se confirman en una transacción. Concurrencia igual reproduce el mismo recibo; cambiar payload, key, herramienta o recurso da 409. No hay eliminación automática de la identidad a las 48 horas. La respuesta manual conserva su DTO habitual; la hija recibe un comprobante mínimo, sin descripción.

`GET /api/v1/agent/operations/{operation_id}` consulta ese comprobante sólo para el actor actual. Permite conciliar un archive aun cuando el operador ya no pueda leer el ticket. Restore sigue siendo de administrador. El recibo contiene IDs de operación/ticket/eventos, código, versión, estado, hash, instante del commit y request ID del servidor. Navegar a una página nunca acredita el commit.

Migración Alembic `c13a88a4e021` añade parent/client a AuthSession y tablas AgentOperation/AgentOperationEvent. Actualizar con el arranque normal de compose, que ejecuta migraciones. Respaldar el volumen según la política existente antes de una actualización de producción; esta entrega sólo se ejecutó localmente.

`/gianna/preview` implementa `idl.gianna.form.v1`: postMessage de la propia ventana/origen con actor, draft ID, revisión y payload validado. Campos y botón están deshabilitados, y el handler bloquea submit/Enter aun si se dispara por código. `/gianna/manual` crea otro formulario editable sólo después de transferir propiedad durable. El preview anterior nunca se desbloquea. El agente no combina un POST con un clic en Enviar.

OpenAPI y TS de ambos clientes se regeneraron. El visualizer recibe el ticket por su sincronización habitual y conserva el diseño y los controles aprobados de la etapa 1.
