# Perfiles, herramientas y adaptadores

Negocio: `profiles/apps/idl-tickets/profile.json`, aliases.es-UY.json, locators.json y workflows/create.json. Preferencias del puesto: `profiles/users/default-accessibility.json`, luego override validado por actor en SQLite. El esquema de negocio no contiene claves, imports o JavaScript arbitrario.

IDs estables `tickets.create.v1`, `browser.show.v1`, etc. `contracts/tools.catalog.json` exporta el registro instalado: schemas de entrada/salida, rol, estados, capacidad, efecto, confirmación, deadline, cancelación, resource lock y evidencia. `python scripts/export_schemas.py --check` detecta cambios sin regenerar. Los contratos de eventos, comandos, playback, cloud y recibos se encuentran en schemas/.

Para añadir un provider:

1. Implementar `CapabilityProvider` y, para efectos, `ExecutorAdapter` (discover/health/observe/prepare/execute/verify/cancel/close). Separar API de negocio de superficie. Un backend ausente debe devolver unavailable/error, nunca éxito inventado.
2. Registrar Tool con namespace/version estable, JSON schemas estrictos, handler, capacidad, roles/estados, efecto y límites. El handler no decide el actor ni invoca directamente escrituras desde un plan.
3. Instalarlo mediante `registry.install(provider, allowlist={(plugin_id, version)})`. API de plugin v1, versión instalada exacta, sin override de nombres existentes. La allowlist es código instalado por el operador, no un dato del modelo/perfil.
4. Crear perfil validado con sólo herramientas instaladas y locators exactos por label, rol/nombre o test ID; probar el contrato de esa aplicación. Las rutas JSON quedan dentro del root instalado. Los workflows tienen hasta 12 primitivas; argumentos templados se completan desde el borrador canónico, nunca se consideran una escritura ya autorizada.

`profiles/apps/fixture-agenda/` contiene el segundo perfil con aliases, locators y workflow de consulta. `tests/fixtures/second_app.py` y `tests/contracts/test_extension.py` lo cargan y prueban una API web FastAPI de agenda y un provider HTTP real a través del mismo Registry/Dispatcher. No se editó el núcleo para añadir `agenda.read.v1`; se prueban allowlist, versión incompatible y rol viewer rechazado. Es una extensión de consulta probada, no un login ni un diálogo completo de agenda. El adaptador productivo y el diálogo instalado en esta entrega son los de tickets.

Una aplicación futura incorpora su provider, perfil y controlador de dominio; el audio, la sesión, los límites del Dispatcher y la persistencia no necesitan rehacerse. Para Hermes completo, usar un proceso/entorno separado y protocolo de plugin; no importar internals en el loop de audio 3.12. Desktop/files/processes/MCP están declarados UNAVAILABLE y requieren implementar y probar esos providers antes de anunciarlos.
