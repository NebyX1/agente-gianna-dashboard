# Pruebas y evidencia

## Corrección de la primera ejecución en GitHub · 6 de octubre de 2026

La ejecución de `b7c7ac9` aprobó el agente, ambos clientes y los 57 tests del backend, pero se detuvo en el cuarto escenario de Playwright. Una aserción visual todavía esperaba un fondo plano del diseño anterior: el formulario nocturno actual tiene un degradado opaco. También quedaba la expectativa de 27 px en 4K, anterior al ajuste compacto a 24 px.

Se actualizaron esas dos comprobaciones para verificar el diseño vigente; no se eliminaron escenarios, se ampliaron plazos ni se agregaron reintentos. La suite completa volvió a ejecutarse sobre una instalación nueva con MariaDB, Flask, Redis, Mailpit y las webs de producción: **8 passed en 44.5 s**. Esa ejecución utilizó un proyecto Docker descartable separado, con API 5500, frontend 5483 y visualizador 5484, para conservar las bases y sesiones de la demo.

La comprobación remota correspondiente se publica mediante el flujo [Verificación en GitHub Actions](https://github.com/NebyX1/agente-gianna-dashboard/actions/workflows/checks.yml). Los resultados anteriores de esta página son históricos y se conservan con sus fechas y alcance.

La siguiente ejecución, `e0473fc`, detectó una carrera intermitente del E2E de teclado: la prueba esperaba la tarjeta flotante, pero enviaba ArrowLeft antes de esperar que el arrastre hubiera marcado su columna inicial. El E2E ahora espera esa condición real antes de mover. Se mantienen la comprobación de la columna de destino y la lectura del estado guardado en la API. Se verificaron cinco ciclos consecutivos de movimiento con Chromium ralentizado 4× por CDP, usando un solo ingreso normal con OTP: **3 escenarios passed en 32.1 s**, incluido el escenario ampliado de cinco ciclos. Un intento anterior de repetir todos los ingresos encontró el cooldown real de correo de 60 segundos; se conserva como fallido y no cuenta como validación del arrastre. No se desactivaron las protecciones de ingreso.

En `ce7d9db`, GitHub aprobó los ocho escenarios de navegador y la persistencia, pero la prueba de caída de MariaDB agotó sus 15 segundos esperando `/readyz`. El sondeo usaba I/O de base de datos sin un plazo externo. Ahora el servidor limita la espera a 3 segundos y conserva un único sondeo pendiente por proceso, sin abandonar su conexión ni iniciar más llamadas nativas mientras esté bloqueado. La prueba exige una respuesta `503 not_ready` en menos de 5 segundos y comprueba la recuperación con un plazo acotado, usando la dirección IPv4 que publica Compose.

La reparación aprobó **59 tests del backend con MariaDB real**. También se congeló MariaDB con `docker compose pause` en un proyecto descartable: tres consultas sucesivas recibieron 503 en aproximadamente 3 segundos, `/healthz` siguió disponible y `/readyz` volvió a 200 al reanudarla. Se comprobaron además las caídas reales de Redis y MariaDB y la conservación de registros tras reiniciar. Los tests unitarios cubren el sondeo bloqueado, el límite de un trabajador, su recuperación y el error HTTP uniforme. No se modifican los plazos de las operaciones de tickets.

## Verificación local del 4 de octubre

Verificación local ejecutada el 4 de octubre de 2026 en Windows/PowerShell, Docker Desktop con contenedores Linux y Chromium de Playwright. API de integración: Python 3.12.12, MariaDB 11.4.8, Redis 7.4.8, Mailpit 1.27.8; SPAs de producción servidas por Nginx 1.28.0. El host usó Python 3.12.14 y Node 22.15.1; los builds Docker usaron Node 22.23.3. Versiones y referencias completas en [arquitectura](architecture.md).

## Resultado ejecutado

| Verificación | Resultado |
|---|---|
| Instalaciones independientes con lockfiles, `npm ci` y dependencias Python fijadas | Aprobado; ambas SPAs y wheels del backend construidos en sus propios contextos |
| Ruff de backend/scripts | Aprobado |
| Unidad SQLite aislada en host Windows | **49 passed, 3 skipped**, 40.64 s; las tres omitidas están cubiertas por la ejecución real de MariaDB |
| Backend completo en MariaDB real | **52 passed**, 83.41 s; incluye contratos, dominio, auth, cuotas, permisos, auditoría, estadísticas y concurrencia |
| Frontend: typecheck, lint TS/TSX, Vitest, contrato y build | Aprobado; **12 tests**, incluidos tema persistente, política de arrastre y calendario Montevideo/UTC |
| Visualizer: typecheck, lint TS/TSX, Vitest, contrato y build | Aprobado; **10 tests**, incluida selección del destacado y conservación de panel/grilla con datos desactualizados |
| Vitest de ambas SPAs con host UTC y Pacific/Auckland | Aprobado en ambas zonas; Montevideo explícito, Z y offset equivalentes |
| `npm audit` en ambas SPAs | **0 vulnerabilities** |
| Playwright sobre Flask/MariaDB/SMTP/Nginx reales | **8 passed**, 49.2 s, repetido con el rediseño operativo y el visualizador |
| Migración desde base vacía, upgrade repetido, seed repetido y `flask db check` | Aprobado con MariaDB; sin drift, pérdida de ticket ni duplicados de catálogos |
| Tres Dockerfiles con contextos independientes | Aprobado; backend/frontend/visualizer construidos y arrancados |
| Compose config, healthchecks y readiness | Aprobado |
| `down`/`up` sin eliminar volúmenes | Aprobado: **18 tickets y 26 eventos** antes/después |
| Pérdida real de Redis y MariaDB en E2E aislado | `/readyz` devuelve **503 not_ready** con cada dependencia detenida y vuelve a **200** al recuperarla |
| Capturas TV 1366×768, 1920×1080, 3840×2160 | Aprobado e inspeccionado; sin desbordamiento horizontal/vertical; etiquetas, destinos, fechas y pie visibles |
| Axe WCAG 2 A/AA en tablero, formulario, estadísticas y pantalla | Sin violaciones serious/critical en las vistas recorridas, incluidos tablero claro/nocturno y móvil; revisión manual de capturas y recorrido de teclado incluidos |

La comprobación de 49.2 s incluye arrastre de toda la tarjeta con mouse, persistencia tras recarga, movimiento entre columnas con teclado, rechazo de transiciones inválidas y nota requerida al cerrar. También verifica cambio/persistencia de tema, diálogos oscuros, filtros desplegables, lista en tabla y ancho móvil de 375 px sin desbordamiento de la página. Incluye polling continuo, propagación entre dos contextos, rotación completa de una cola de 18 tickets, un HTTP 500 con navegador online, desconexión real del contexto y recuperación. La repetición del rediseño utilizó el proyecto aislado `idl-tickets-design-check` en los puertos 5400/5473/5474/8027; conservó los tickets y las sesiones del demo manual en 5373/5374. Los E2E admiten `E2E_API_URL`, `E2E_FRONTEND_URL`, `E2E_DISPLAY_URL`, `E2E_MAIL_URL` y `E2E_CREDENTIALS_FILE` para esa separación. Usa polling de 1 s y rotación de 5 s sólo en el entorno E2E; la configuración normal es 5 s/15 s. No se ejecutó un soak de 12 horas. Los resultados de backend, readiness y persistencia de volúmenes corresponden a la verificación anterior de esta entrega; este rediseño repitió frontend e integración de producto.

**Fallidos vigentes:** ninguno en los comandos de entrega. Las revisiones visuales y Axe detectaron contraste insuficiente, colisiones de clases con DaisyUI, tarjetas que excedían el alto disponible y una regla global que anulaba la tipografía 4K; se corrigieron y se repitieron los E2E y capturas. El frontend operativo ahora carga páginas por separado y su build ya no emite el aviso de chunk mayor a 500 kB. Persisten avisos no bloqueantes de anotaciones PURE de Zod; tipado, lint, tests y build finalizan correctamente.

**Verificación externa pendiente:** no hay despliegue en una instancia Coolify del usuario ni SMTP institucional configurado. No se afirma verificación en producción. La configuración y el bootstrap están documentados en [Coolify](coolify.md); esos valores se completan al desplegar. La CI fue escrita para reproducir estas pruebas, pero no se afirmó una ejecución remota en GitHub Actions.

## Reproducir integración

Desde una copia nueva y la raíz del repositorio, con Docker iniciado:

```sh
python scripts/init-local.py
python scripts/test-backend.py
python scripts/start-e2e.py
cd e2e
npm ci
npx playwright install chromium
npm test
cd ..
python scripts/verify-persistence.py
python scripts/verify-readiness.py
```

`init-local.py` genera secretos locales ignorados y se niega a reemplazarlos. Si ya existe `.env`, conservarlo y omitir ese primer comando. `test-backend.py` crea una red y MariaDB temporales con contraseña aleatoria, ejecuta la suite completa y elimina sólo esos recursos temporales. Cada fixture migra su esquema con Alembic, sin `create_all`. Las tres pruebas marcadas integration necesitan MariaDB: carreras de creación/versión/archive, consumo simultáneo de OTP y upgrade/seed/drift.

`start-e2e.py` usa exclusivamente el proyecto fijo **idl-tickets-e2e**, con volúmenes/puertos distintos. **Borra y reconstruye su esquema de prueba**, genera usuarios aleatorios explícitos y carga un ticket pendiente del día anterior. Nunca usar esa base como operación real. Los puertos son API 5300, frontend 5373, visualizer 5374, Mailpit 8026. Los E2E completan login y leen el OTP entregado por SMTP Mailpit; no hay bypass de autenticación.

`verify-persistence.py` cuenta tickets/eventos, detiene y recrea ese proyecto sin `-v`, y exige el mismo conteo. `verify-readiness.py` detiene Redis y MariaDB de ese proyecto de forma secuencial, comprueba el error HTTP uniforme y los recupera en `finally`. No detienen servicios del proyecto local normal.

## Qué cubren los escenarios

1. Arrastre real de Impresoras → Tránsito, formulario precompletado sin alta automática, confirmación con doble clic y un único código/evento; aparición en TV en un polling de 1 s más tolerancia local explícita de 9 s.
2. Edición, En curso, En espera, resolución y reapertura; propagación automática y retiro/reaparición en TV.
3. Arrastre desde el cuerpo de una tarjeta: guardado directo, propagación y persistencia tras recarga. Espacio/flecha izquierda/Espacio mueve con teclado. Transición inválida conserva versión; arrastrar a Resuelto pide nota y Escape conserva el estado.
4. Filtros adicionales desplegables y limpieza, lista real en tabla, tema nocturno guardado al recargar, formulario oscuro, móvil de 375×812 y Axe en ambos temas, formulario, móvil y estadísticas.
5. Ocultación, denegación del historial al operador, lectura del historial/ocultos por admin, restauración y conservación de historia.
6. Dos escrituras paralelas sobre la misma versión: exactamente 200/409; rechazo directo de viewer; HTTP 500, offline y recuperación conservando datos; Enter/Escape y devolución de foco del diálogo.
7. Dieciséis altas adicionales con nombres/descripciones largos; todos sus códigos durante la rotación; pendiente anterior visible; capturas y Axe.
8. Recarga directa de rutas SPA, assets ausentes y `/api/*` devuelven 404, healthchecks y revocación de sesión de TV que retira datos y vuelve al login.

Pytest agrega entradas inválidas/reservadas, referencias inactivas, destinos, fechas UTC/límites Montevideo, texto seguro, transiciones/motivos/timestamps, auditoría atómica ante fallos inducidos, idempotencia persistente/simultánea/tras respuesta perdida y conflicto de carga. También verifica las clases de escritura/consulta administrativa por HTTP con viewer, challenge/expiración/cuotas/reenvíos/SMTP, cambios de rol/password, revocación, catálogos/ciclos y estadísticas sobre cohortes conocidas con archivados/cancelados/reaperturas. Los errores inducidos en unidad no se presentan como sustitutos de la integración MariaDB o las desconexiones reales.

## Comprobaciones por aplicación

Dentro de `frontend/` y después en `visualizer/`:

```sh
npm ci
npm run typecheck
npm run lint
npm test
npm run contract:check
npm run build
npm audit --audit-level=moderate
```

Fechas en Linux/macOS: `TZ=UTC npm test` y `TZ=Pacific/Auckland npm test`. En PowerShell:

```powershell
$env:TZ='UTC'; npm test
$env:TZ='Pacific/Auckland'; npm test
Remove-Item Env:TZ
```

Si el SWC del host Windows rechaza permisos de caché, ejecutar `. ./scripts/windows-toolchain.ps1` desde la raíz antes de entrar a la carpeta del cliente. No afecta a los builds Linux ni requiere flags de incompatibilidad.

Backend, después de instalar `requirements-dev.txt` en su propio entorno Python:

```sh
ruff check . ../scripts
pytest -q
python contracts/generate.py --check
```

Sin `TEST_DATABASE_URI`, pytest usa SQLite aislada y omite únicamente las pruebas MariaDB; el comando de integración anterior las ejecuta realmente. Si se proporciona una URI propia, debe terminar en `_test` y apuntar a una base descartable: las fixtures hacen downgrade/upgrade. Los contratos de ambos clientes se guardan localmente, se generan con openapi-typescript y `contract:check` detecta drift; no formatear manualmente tipos generados.

## Evidencia visual conservada

Capturas con usuarios y datos de prueba, después de las correcciones:

- [Tablero operativo](evidence/operacion.png) y [formulario precompletado](evidence/formulario.png).
- [Tablero claro](evidence/operacion-clara.png), [modo nocturno neón](evidence/operacion-neon.png) y [móvil](evidence/operacion-movil.png).
- [TV 1366×768](evidence/pantalla-1366.png), [TV 1920×1080](evidence/pantalla-1920.png) y [TV 3840×2160](evidence/pantalla-3840.png).
- [TV sin conexión, conservando la última información](evidence/pantalla-sin-conexion.png).

Playwright conserva capturas/traces de fallos en `e2e/test-results/` y su informe en `e2e/playwright-report/`, ambos ignorados. La CI adjunta esa evidencia cuando corre; los logs locales `artifacts-*.log` también están ignorados. Las capturas de esta entrega se conservaron en `docs/evidence/` para que otro desarrollador pueda revisarlas sin credenciales.
