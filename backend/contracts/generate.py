"""Generate OpenAPI from input validators and executable registered routes."""

import json
import sys
from pathlib import Path

from marshmallow import fields, missing, validate

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from app import create_app  # noqa: E402
from app import schemas as s  # noqa: E402


def ref(name):
    return {"$ref": f"#/components/schemas/{name}"}


def obj(props, required=None):
    return {
        "type": "object",
        "properties": props,
        "required": list(props) if required is None else required,
        "additionalProperties": False,
    }


def arr(item):
    return {"type": "array", "items": item}


integer = {"type": "integer", "minimum": 1}
string = {"type": "string"}
nullable_date = {"type": ["string", "null"], "format": "date-time"}
datetime_schema = {"type": "string", "format": "date-time", "example": "2026-10-04T12:00:00Z"}
boolean = {"type": "boolean"}
status = {"type": "string", "enum": list(s.STATUSES)}


def input_schema(cls, exclude=(), partial=False):
    properties, required = {}, []
    for name, field in cls(exclude=exclude).fields.items():
        value = {
            "type": "integer"
            if isinstance(field, fields.Integer)
            else "boolean"
            if isinstance(field, fields.Boolean)
            else "string"
        }
        if isinstance(field, fields.DateTime):
            value["format"] = "date-time"
        if isinstance(field, fields.Email):
            value["format"] = "email"
        for validator in field.validators:
            if isinstance(validator, validate.OneOf):
                value["enum"] = list(validator.choices)
            if isinstance(validator, validate.Range) and validator.min is not None:
                value["minimum"] = validator.min
            if isinstance(validator, validate.Length):
                if validator.min is not None:
                    value["minLength"] = validator.min
                if validator.max is not None:
                    value["maxLength"] = validator.max
            if isinstance(validator, validate.Regexp):
                value["pattern"] = validator.regex.pattern
        if field.allow_none:
            value["type"] = [value["type"], "null"]
        if field.load_default is not missing and not callable(field.load_default):
            value["default"] = field.load_default
        if field.required and not partial:
            required.append(name)
        if "password" in name or name in {"code", "pending_token"} and cls in {s.Verify, s.Resend}:
            value["writeOnly"] = True
        properties[name] = value
    return obj(properties, required)


def generate():
    schemas = {
        cls.__name__: input_schema(cls)
        for cls in [
            s.TicketCreate,
            s.TicketUpdate,
            s.TicketStatusChange,
            s.TicketArchive,
            s.TicketRestore,
            s.Login,
            s.Verify,
            s.Resend,
            s.PasswordChange,
            s.OrgUnitCreate,
            s.ProblemTypeCreate,
            s.UserCreate,
            s.UserUpdate,
        ]
    }
    schemas["OrgUnitUpdate"] = input_schema(s.OrgUnitCreate, ("code",), partial=True)
    schemas["ProblemTypeUpdate"] = input_schema(s.ProblemTypeCreate, ("code",), partial=True)
    schemas["OrgUnit"] = obj({"id": integer, **schemas["OrgUnitCreate"]["properties"]})
    schemas["ProblemType"] = obj(
        {
            "id": integer,
            "code": string,
            "name": string,
            "description": {"type": ["string", "null"]},
            "is_active": boolean,
        }
    )
    schemas["User"] = obj(
        {
            "id": integer,
            "email": {"type": "string", "format": "email"},
            "name": string,
            "role": {"type": "string", "enum": ["admin", "operator", "viewer"]},
            "is_active": boolean,
        }
    )
    schemas["StatusDefinition"] = obj({"code": status, "label": string, "transitions": arr(status)})
    schemas["TicketRead"] = obj(
        {
            "id": integer,
            "code": string,
            "origin_unit_id": integer,
            "destination_unit_id": integer,
            "problem_type_id": integer,
            "origin": ref("OrgUnit"),
            "destination": ref("OrgUnit"),
            "problem_type": ref("ProblemType"),
            "description": {"type": "string", "minLength": 10, "maxLength": 4000},
            "status": status,
            "version": integer,
            "created_by_user_id": integer,
            "created_at": datetime_schema,
            "updated_at": datetime_schema,
            **{
                k: nullable_date
                for k in [
                    "first_response_at",
                    "resolved_at",
                    "cancelled_at",
                    "occurred_at",
                    "archived_at",
                ]
            },
            "archived_by_user_id": {"type": ["integer", "null"]},
            "archive_reason": {"type": ["string", "null"]},
        }
    )
    for value in schemas["TicketRead"]["properties"].values():
        value["readOnly"] = True
    label = obj({"id": integer, "name": string})
    schemas["DisplayTicket"] = obj(
        {
            "id": integer,
            "code": string,
            "status": status,
            "origin": label,
            "destination": label,
            "problem_type": label,
            "created_at": datetime_schema,
            "updated_at": datetime_schema,
            "description_preview": {"type": "string", "maxLength": 400},
        }
    )
    schemas["TicketEvent"] = obj(
        {
            "id": integer,
            "ticket_id": integer,
            "actor_user_id": integer,
            "actor_name": string,
            "event_type": {
                "type": "string",
                "enum": ["created", "edited", "status_changed", "reopened", "archived", "restored"],
            },
            "timestamp": datetime_schema,
            "request_id": string,
            "channel": {"type": "string", "enum": ["manual_ui", "voice_agent"]},
            "before": {"anyOf": [ref("TicketRead"), {"type": "null"}]},
            "after": ref("TicketRead"),
            "note": {"type": ["string", "null"]},
        }
    )
    schemas["Error"] = obj(
        {
            "ok": {"const": False},
            "error": obj(
                {
                    "code": string,
                    "message": string,
                    "errors": {"type": "object", "additionalProperties": arr(string)},
                    "details": {},
                },
                ["code", "message", "errors"],
            ),
            "meta": obj({"request_id": string}),
        }
    )
    schemas["Pagination"] = obj(
        {
            "page": integer,
            "per_page": {"type": "integer", "minimum": 1, "maximum": 100},
            "total": {"type": "integer", "minimum": 0},
            "pages": {"type": "integer", "minimum": 0},
        }
    )

    def page(name):
        return obj({"items": arr(ref(name)), **schemas["Pagination"]["properties"]})

    schemas["TicketPage"], schemas["EventPage"] = page("TicketRead"), page("TicketEvent")
    schemas["Catalogs"] = obj(
        {
            "org_units": arr(ref("OrgUnit")),
            "problem_types": arr(ref("ProblemType")),
            "statuses": arr(ref("StatusDefinition")),
            "default_destination_unit_id": {"type": ["integer", "null"]},
            "warnings": arr(string),
        }
    )
    schemas["PendingAuth"] = obj(
        {"pending_token": string, "expires_in": integer, "resend_after": integer}
    )
    schemas["SessionAuth"] = obj(
        {
            "access_token": string,
            "expires_in": integer,
            "expires_at": datetime_schema,
            "user": ref("User"),
        }
    )
    schemas["Message"] = obj({"message": string})
    schemas["AgentSessionInput"] = obj({})
    schemas["AgentSession"] = obj({"access_token": string, "expires_at": datetime_schema,
        "client_id": {"const": "gianna-agent"}, "scope": {"const": ["tickets"]}, "user": ref("User")})
    schemas["AgentReceipt"] = obj({"operation_id": string, "tool": string,
        "payload_hash": {"type": "string", "pattern": "^[a-f0-9]{64}$"}, "ticket_id": integer,
        "code": string, "version": integer, "status": string, "event_ids": arr(integer),
        "committed_at": datetime_schema, "server_request_id": string})
    schemas["DisplayConfig"] = obj(
        {
            "statuses": arr(ref("StatusDefinition")),
            "destinations": arr(label),
            "timezone": {"const": "America/Montevideo"},
        }
    )
    schemas["DisplayResult"] = obj(
        {
            "items": arr(ref("DisplayTicket")),
            "total": {"type": "integer", "minimum": 0},
            "generated_at": datetime_schema,
        }
    )
    schemas["ArchiveReceipt"] = obj(
        {
            "ticket_id": integer,
            "operation": {"const": "archive"},
            "archived_at": datetime_schema,
            "version": integer,
        }
    )
    schemas["Group"] = obj(
        {"id": integer, "name": string, "count": {"type": "integer", "minimum": 0}}
    )
    schemas["Problems"] = obj({"items": arr(ref("Group"))})
    schemas["Summary"] = obj(
        {
            "created": {"type": "integer"},
            "resolved": {"type": "integer"},
            "cancelled": {"type": "integer"},
            "archived": {"type": "integer"},
            "average_resolution_seconds": {"type": ["number", "null"]},
            "active_by_status": obj({key: {"type": "integer"} for key in s.ACTIVE}),
            "daily": arr(
                obj({"date": {"type": "string", "format": "date"}, "count": {"type": "integer"}})
            ),
            "origins": arr(ref("Group")),
            "destinations": arr(ref("Group")),
            "definition": string,
        }
    )
    for name in ["OrgUnit", "ProblemType", "User"]:
        schemas[name + "List"] = obj({"items": arr(ref(name))})
    mapping = {
        "auth.agent_session": ("authAgentSession", "AgentSessionInput", "AgentSession", ["admin", "operator"],
            "Delegar la sesión 2FA al mismo usuario, client_id gianna-agent y scope tickets. Sin selección de actor/rol/canal. Vence con el padre y se revoca por logout o cambio de autorización."),
        "domain.agent_receipt": ("agentOperationReceipt", None, "AgentReceipt", ["admin", "operator"],
            "Consultar sólo recibo mínimo del mismo actor. Conservado mientras exista historia. No revela descripción ni notas de tickets ocultos."),
        "auth.auth_login": (
            "authLogin",
            "Login",
            "PendingAuth",
            [],
            "Validar contraseña Argon2 y enviar OTP por correo. No crea una sesión.",
        ),
        "auth.verify_2fa": (
            "authVerify2fa",
            "Verify",
            "SessionAuth",
            [],
            "Consumir atómicamente el desafío vigente y emitir una sesión Bearer.",
        ),
        "auth.resend_2fa": (
            "authResend2fa",
            "Resend",
            "PendingAuth",
            [],
            "Reenviar tras cooldown de 60 segundos. Invalida el desafío anterior sin reiniciar cuotas.",
        ),
        "auth.me": (
            "authMe",
            None,
            "User",
            ["admin", "operator", "viewer"],
            "Validar sesión persistida y consultar su usuario activo.",
        ),
        "auth.logout": (
            "authLogout",
            None,
            "Message",
            ["admin", "operator", "viewer"],
            "Revocar la sesión actual en MariaDB.",
        ),
        "auth.change_password": (
            "authChangePassword",
            "PasswordChange",
            "Message",
            ["admin", "operator", "viewer"],
            "Cambiar contraseña con la actual e invalidar todas las sesiones.",
        ),
        "domain.catalogs": (
            "catalogs",
            None,
            "Catalogs",
            ["admin", "operator"],
            "Catálogos activos, destino predeterminado real y transiciones permitidas.",
        ),
        "domain.tickets_list": (
            "ticketsList",
            None,
            "TicketPage",
            ["admin", "operator"],
            "Listar tickets visibles con filtros y orden estable por creación e ID.",
        ),
        "domain.tickets_create": (
            "ticketsCreate",
            "TicketCreate",
            "TicketRead",
            ["admin", "operator"],
            "Crear ticket y evento en una transacción. Requiere Idempotency-Key; misma carga reproduce el resultado original. Retención mínima 24 horas.",
        ),
        "domain.tickets_detail": (
            "ticketsDetail",
            None,
            "TicketRead",
            ["admin", "operator"],
            "Consultar detalle. Los ocultos sólo pueden ser leídos por admin.",
        ),
        "domain.tickets_edit": (
            "ticketsEdit",
            "TicketUpdate",
            "TicketRead",
            ["admin", "operator"],
            "Editar referencias y descripción. version es la esperada; 409 si cambió. No admite ocultos.",
        ),
        "domain.tickets_status": (
            "ticketsStatus",
            "TicketStatusChange",
            "TicketRead",
            ["admin", "operator"],
            "Cambiar estado según transiciones. Resolver requiere solución, cancelar y reabrir requieren motivo. Reabrir limpia el cierre vigente y conserva first_response_at.",
        ),
        "domain.tickets_archive": (
            "ticketsArchive",
            "TicketArchive",
            "ArchiveReceipt",
            ["admin", "operator"],
            "Ocultar sin borrar. Idempotency-Key reproduce comprobante incluso después de perder lectura del ticket; requiere autorización vigente y version.",
        ),
        "domain.tickets_history": (
            "ticketsHistory",
            None,
            "EventPage",
            ["admin", "operator"],
            "Historia con snapshots de IDs y etiquetas. Ocultos sólo admin.",
        ),
        "domain.archived_list": (
            "archivedList",
            None,
            "TicketPage",
            ["admin"],
            "Listar tickets ocultos sin borrar historia.",
        ),
        "domain.tickets_restore": (
            "ticketsRestore",
            "TicketRestore",
            "TicketRead",
            ["admin"],
            "Restaurar con version y motivo; conserva estado. Sólo activos reaparecen en TV.",
        ),
        "domain.display_config": (
            "displayConfig",
            None,
            "DisplayConfig",
            ["admin", "operator", "viewer"],
            "Configuración de pantalla sin datos privados.",
        ),
        "domain.display_tickets": (
            "displayTickets",
            None,
            "DisplayResult",
            ["admin", "operator", "viewer"],
            "Conjunto activo completo; incluye días anteriores y excluye ocultos. Proyección de hasta 400 caracteres sin emails, usuarios o notas internas.",
        ),
        "domain.summary": (
            "statisticsSummary",
            None,
            "Summary",
            ["admin", "operator"],
            "Cohorte por created_at; días de Montevideo; incluye ocultos y cancelados. Media sólo de actualmente resueltos, cierre vigente. Activos actuales independientes del período.",
        ),
        "domain.problems": (
            "statisticsProblems",
            None,
            "Problems",
            ["admin", "operator"],
            "Agrupar toda la cohorte por ID de tipo, con etiquetas actuales.",
        ),
        "domain.openapi": (
            "openapi",
            None,
            None,
            [],
            "Especificación OpenAPI 3.1 directa, sin envelope.",
        ),
    }
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SECRET_KEY": "contract-generation-no-server",
            "JWT_SECRET_KEY": "contract-generation-no-server",
            "RATELIMIT_ENABLED": False,
            "CORS_ORIGINS": [],
        }
    )
    paths = {}
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        if not rule.rule.startswith("/api/v1/"):
            continue
        path = (
            rule.rule[7:]
            .replace("<int:ticket_id>", "{ticket_id}")
            .replace("<int:item_id>", "{item_id}")
            .replace("<string:operation_id>", "{operation_id}")
        )
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            endpoint = rule.endpoint
            if endpoint in ["domain.admin_units", "domain.admin_types", "domain.admin_users"]:
                name = {
                    "domain.admin_units": "OrgUnit",
                    "domain.admin_types": "ProblemType",
                    "domain.admin_users": "User",
                }[endpoint]
                operation, inp, out, roles, description = (
                    name[0].lower() + name[1:] + method.title(),
                    None
                    if method == "GET"
                    else name + ("Update" if method == "PATCH" else "Create"),
                    name + "List" if method == "GET" else name,
                    ["admin"],
                    "Administrar registros. Códigos inmutables; desactivación lógica. Cambiar rol/actividad invalida sesiones. Se conserva al menos un admin activo. No hay borrado físico.",
                )
            else:
                operation, inp, out, roles, description = mapping[endpoint]
            success_code = (
                "201"
                if method == "POST"
                and (endpoint == "domain.tickets_create" or endpoint.startswith("domain.admin_"))
                else "200"
            )
            response_schema = (
                {}
                if out is None
                else obj(
                    {"ok": {"const": True}, "data": ref(out), "meta": obj({"request_id": string})}
                )
            )
            agent_writes = {"domain.tickets_create", "domain.tickets_edit", "domain.tickets_status",
                            "domain.tickets_archive", "domain.tickets_restore"}
            if endpoint in agent_writes:
                response_schema["properties"]["data"] = {"anyOf": [ref(out), ref("AgentReceipt")]}
            responses = {
                success_code: {
                    "description": "Operación confirmada",
                    "content": {"application/json": {"schema": response_schema}},
                    "headers": {"X-Request-ID": {"schema": string}},
                }
            }
            for code, desc in [
                ("401", "Sesión inválida, expirada o revocada"),
                ("403", "Rol sin permiso"),
                ("404", "Registro o ruta no encontrada"),
                ("409", "Conflicto de versión, idempotencia o unicidad"),
                ("422", "Validación o transición inválida"),
                ("429", "Cuota de cuenta/IP o cooldown"),
                ("503", "Dependencia no disponible"),
            ]:
                responses[code] = {
                    "description": desc,
                    "content": {"application/json": {"schema": ref("Error")}},
                    "headers": {
                        "X-Request-ID": {"schema": string},
                        "Retry-After": {
                            "schema": {"type": "integer"},
                            "description": "Segundos de espera para 429",
                        },
                    },
                }
            parameters = [
                {"name": key, "in": "path", "required": True, "schema": integer}
                for key in ["ticket_id", "item_id"]
                if "{" + key + "}" in path
            ]
            if "{operation_id}" in path:
                parameters.append({"name": "operation_id", "in": "path", "required": True, "schema": string})
            if endpoint in agent_writes:
                parameters.append({"name": "X-Agent-Operation-ID", "in": "header", "schema": {
                    "type": "string", "pattern": "^[A-Za-z0-9_-]{16,64}$"},
                    "description": "Obligatorio para sesiones gianna-agent. Identidad durable independiente de JWT. Reutilizar con otro recurso/carga/clave devuelve 409."})
                if endpoint not in {"domain.tickets_create", "domain.tickets_archive"}:
                    parameters.append({"name": "Idempotency-Key", "in": "header", "schema": string,
                        "description": "Obligatorio en TODAS las escrituras de gianna-agent. Manual UI conserva su contrato."})
            parameters.append(
                {
                    "name": "X-Request-ID",
                    "in": "header",
                    "schema": {"type": "string", "maxLength": 64},
                    "description": "Trazabilidad por petición; no garantiza idempotencia.",
                }
            )
            if endpoint in {"domain.tickets_create", "domain.tickets_archive"}:
                parameters.append(
                    {
                        "name": "Idempotency-Key",
                        "in": "header",
                        "required": True,
                        "schema": {"type": "string", "pattern": "^[A-Za-z0-9_-]{16,64}$"},
                        "example": "ab921b48-55c8-493e-b64e-c987162a5b63",
                    }
                )
            if endpoint in {
                "domain.tickets_list",
                "domain.archived_list",
                "domain.summary",
                "domain.problems",
            }:
                for key in [
                    "q",
                    "origin_unit_id",
                    "destination_unit_id",
                    "problem_type_id",
                    "status",
                    "from",
                    "to",
                ]:
                    parameters.append(
                        {
                            "name": key,
                            "in": "query",
                            "schema": integer if key.endswith("_id") else {"type": "string"},
                            "description": "Fecha de creación; from/to YYYY-MM-DD inclusivos en America/Montevideo."
                            if key in {"from", "to"}
                            else "Filtro opcional.",
                        }
                    )
            if out in {"TicketPage", "EventPage"}:
                parameters.extend(
                    [
                        {"name": "page", "in": "query", "schema": integer},
                        {
                            "name": "per_page",
                            "in": "query",
                            "schema": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 100,
                                "default": 30,
                            },
                        },
                    ]
                )
            if endpoint == "domain.display_tickets":
                parameters.append({"name": "destination_unit_id", "in": "query", "schema": integer})
            item = {
                "operationId": operation,
                "summary": description.split(".")[0],
                "description": description,
                "x-roles": roles,
                "security": [{"bearerAuth": []}] if roles else [],
                "parameters": parameters,
                "responses": responses,
            }
            if inp:
                item["requestBody"] = {
                    "required": True,
                    "content": {"application/json": {"schema": ref(inp)}},
                }
            paths.setdefault(path, {})[method.lower()] = item
    schemas = json.loads(json.dumps(schemas))  # Independent property metadata (no shared aliases).
    descriptions = {
        "id": "Identificador estable asignado por la base de datos.",
        "code": "Código legible; en catálogos es único e inmutable.",
        "name": "Etiqueta descriptiva actual.",
        "origin_unit_id": "Unidad solicitante activa; distinta del destino responsable.",
        "destination_unit_id": "Unidad responsable activa y habilitada para recibir tickets.",
        "problem_type_id": "Tipo de problema activo del catálogo.",
        "description": "Texto plano recortado, nunca HTML; entre 10 y 4000 caracteres en tickets.",
        "description_preview": "Primeros 400 caracteres determinísticos de la descripción, texto plano.",
        "version": "Versión esperada en escrituras; DB comprueba e incrementa atómicamente. Conflicto devuelve 409.",
        "status": "Estado vigente; sólo admite las transiciones publicadas por el contrato.",
        "note": "Solución obligatoria al resolver; motivo obligatorio al cancelar o reabrir.",
        "reason": "Motivo obligatorio de ocultación o restauración.",
        "created_at": "Instante UTC de registro, inmutable y asignado por servidor. JSON con Z u offset.",
        "updated_at": "Instante UTC de última operación confirmada.",
        "occurred_at": "Inicio opcional del problema; requiere zona horaria, no futuro; no reemplaza fecha de registro.",
        "created_by_user_id": "Usuario de sesión autenticada, asignado por servidor.",
        "first_response_at": "Primera entrada a En curso; se conserva al reabrir.",
        "resolved_at": "Cierre resuelto vigente; al reabrir se limpia y queda en historia.",
        "cancelled_at": "Cierre cancelado vigente; al reabrir se limpia y queda en historia.",
        "archived_at": "Ocultación lógica separada del estado; excluye de operación y pantalla.",
        "can_receive_tickets": "Habilitación explícita como destino, editable por admin.",
        "parent_id": "Relación opcional de unidad; se rechazan ciclos.",
        "pending_token": "JWT restringido al desafío 2FA vigente; no autoriza negocio y sólo debe persistirse en memoria.",
        "password": "Contraseña enviada exclusivamente por HTTPS, nunca en URL o logs.",
        "email": "Email de la cuenta para autenticación y entrega del OTP.",
        "is_active": "Desactivación lógica: conserva referencias; usuarios desactivados pierden sesiones.",
    }
    for definition in schemas.values():
        for name, field in definition.get("properties", {}).items():
            field.setdefault(
                "description",
                descriptions.get(name, "Campo del resultado documentado de esta operación."),
            )
    schemas["TicketCreate"]["example"] = {
        "origin_unit_id": 3,
        "destination_unit_id": 1,
        "problem_type_id": 2,
        "description": "La impresora no imprime y hace un ruido raro",
        "occurred_at": None,
    }
    schemas["TicketStatusChange"]["example"] = {
        "status": "resolved",
        "version": 3,
        "note": "Se retiró papel atascado y se probó impresión",
    }
    schemas["TicketArchive"]["example"] = {"version": 3, "reason": "Pedido duplicado confirmado"}
    schemas["TicketRestore"]["example"] = {
        "version": 4,
        "reason": "Restauración autorizada para seguimiento",
    }
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Mesa de ayuda · IDL",
            "version": "1.0.0",
            "description": "Fechas UTC con Z/offset. Días y presentación America/Montevideo. Bearer JWT y OTP por correo; sin refresh. Estados y transiciones disponibles en catalogs/display/config.",
        },
        "servers": [{"url": "/api/v1"}],
        "paths": paths,
        "components": {
            "schemas": schemas,
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
            },
        },
        "x-transitions": s.STATUSES,
    }


if __name__ == "__main__":
    output = json.dumps(generate(), ensure_ascii=False, indent=2) + "\n"
    path = root / "contracts/openapi.json"
    if "--check" in sys.argv:
        if path.read_text(encoding="utf-8") != output:
            raise SystemExit("OpenAPI fuera de sincronía; ejecutar python contracts/generate.py")
    else:
        path.write_text(output, encoding="utf-8")
