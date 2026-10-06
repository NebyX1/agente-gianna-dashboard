from gianna.tools.contracts import Tool
from gianna.dialogue.state_machine import State
import json
from gianna.config import ROOT

POSITIVE = {"type": "integer", "minimum": 1}
TEXT = {"type": "string", "minLength": 10, "maxLength": 4000}


def schema(properties, required=()):
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(required),
    }


def install_tools(registry, tickets, browser, supervisor):
    contract = json.loads(
        (ROOT / "contracts/tickets-openapi.snapshot.json").read_text(encoding="utf-8")
    )

    def output(component):
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": "#/components/schemas/" + component,
            "components": contract["components"],
        }

    states = tuple(
        s.value for s in State if s not in {State.STARTING, State.BLOCKED, State.AUTH_REQUIRED}
    )

    async def read(args):
        return await tickets.request("GET", f"/api/v1/tickets/{args['ticket_id']}")

    async def history(args):
        return await tickets.request("GET", f"/api/v1/tickets/{args['ticket_id']}/history")

    async def catalogs(args):
        return await tickets.request("GET", "/api/v1/catalogs")

    async def search(args):
        return await tickets.request("GET", "/api/v1/tickets", query=args)

    read_tools = [
        ("catalogs", schema({}), catalogs),
        (
            "search",
            schema(
                {
                    "q": {"type": "string", "maxLength": 160},
                    "status": {
                        "type": "string",
                        "description": "active: nuevos, en curso y en espera. También admite un estado o varios separados por coma.",
                    },
                    "origin_unit_id": POSITIVE,
                    "destination_unit_id": POSITIVE,
                    "problem_type_id": POSITIVE,
                    "page": POSITIVE,
                    "per_page": {"type": "integer", "minimum": 1, "maximum": 100},
                    "from": {"type": "string", "format": "date"},
                    "to": {"type": "string", "format": "date"},
                }
            ),
            search,
        ),
        ("read", schema({"ticket_id": POSITIVE}, ["ticket_id"]), read),
        ("history", schema({"ticket_id": POSITIVE}, ["ticket_id"]), history),
    ]
    for name, args, handler in read_tools:
        registry.register(
            Tool(
                f"tickets.{name}.v1",
                args,
                f"Consultar {name} de tickets visibles para el usuario",
                "idl_tickets_http_v1",
                ("admin", "operator"),
                states,
                "read",
                "none",
                15,
                0,
                "safe",
                "Respuesta de API autorizada",
                handler,
                output_schema=output(
                    {
                        "catalogs": "Catalogs",
                        "search": "TicketPage",
                        "read": "TicketRead",
                        "history": "EventPage",
                    }[name]
                ),
                examples=(f"Consultar {name} del ticket IDL-TI-000004",),
            )
        )
    fields = {
        "origin_unit_id": POSITIVE,
        "destination_unit_id": POSITIVE,
        "problem_type_id": POSITIVE,
        "description": TEXT,
        "occurred_at": {"type": ["string", "null"], "format": "date-time"},
    }
    writes = {
        "create": schema(
            fields, ["origin_unit_id", "destination_unit_id", "problem_type_id", "description"]
        ),
        "update": schema(
            {**fields, "version": POSITIVE},
            ["version", "origin_unit_id", "destination_unit_id", "problem_type_id", "description"],
        ),
        "status": schema(
            {
                "version": POSITIVE,
                "status": {"enum": ["new", "in_progress", "waiting", "resolved", "cancelled"]},
                "note": {"type": "string", "minLength": 5, "maxLength": 1000},
            },
            ["version", "status"],
        ),
        "archive": schema(
            {"version": POSITIVE, "reason": {"type": "string", "minLength": 5, "maxLength": 1000}},
            ["version", "reason"],
        ),
        "restore": schema(
            {"version": POSITIVE, "reason": {"type": "string", "minLength": 5, "maxLength": 1000}},
            ["version", "reason"],
        ),
    }
    for name, args in writes.items():
        registry.register(
            Tool(
                f"tickets.{name}.v1",
                args,
                f"{name} un ticket con recibo durable. Nunca enviar por UI.",
                "idl_tickets_http_v1",
                ("admin",) if name == "restore" else ("admin", "operator"),
                (State.WAITING_CONFIRMATION, State.EXECUTING),
                "remote_write",
                "exact_revision",
                15,
                0,
                "reconcile_after_dispatch",
                "Recibo servidor ligado al evento",
                tickets.execute,
                output_schema=output("AgentReceipt"),
                resource_lock="actor:ticket",
                examples=(f"Preparar {name} y revisar antes de confirmar",),
            )
        )
    for name in ("open", "show", "filter", "prepare"):

        async def handler(args, name=name):
            if name == "prepare":
                if not supervisor.draft or supervisor.draft.actor_id != supervisor.user["id"]:
                    raise RuntimeError("draft_unavailable")
                return await browser.prepare({"draft": supervisor.draft})
            return await browser.execute({"command": name, **args})

        args = (
            schema({"ticket_id": POSITIVE})
            if name in {"open", "show"}
            else schema({"query": {"type": "string", "maxLength": 160}}, ["query"])
            if name == "filter"
            else schema({})
        )
        registry.register(
            Tool(
                f"browser.{name}.v1",
                args,
                f"{name} en navegador propio con contrato observado",
                "playwright_browser_v1",
                ("admin", "operator"),
                states,
                "local_draft",
                "none",
                20,
                0,
                "before_dispatch",
                "Valores y marcadores UI; no acredita commit",
                handler,
                output_schema=(
                    schema(
                        {
                            "draft_id": {"type": "string"},
                            "revision": POSITIVE,
                            "preview": {"type": "boolean"},
                            "verified": {"const": True},
                        },
                        ["draft_id", "revision", "preview", "verified"],
                    )
                    if name == "prepare"
                    else schema(
                        {"url": {"type": "string"}, "shown": {"const": True}}, ["url", "shown"]
                    )
                ),
            )
        )
    for name in ("repeat", "pause", "resume"):

        async def handler(args, name=name):
            action = {
                "repeat": supervisor.repeat,
                "pause": supervisor.pause,
                "resume": supervisor.activate,
            }[name]
            await action()
            return {"action": name}

        registry.register(
            Tool(
                f"dialogue.{name}.v1",
                schema({}),
                f"{name} conversación local",
                "dialogue",
                ("admin", "operator"),
                states,
                "local_draft",
                "none",
                5,
                0,
                "safe",
                "Estado del supervisor",
                handler,
                output_schema=schema({"action": {"const": name}}, ["action"]),
            )
        )
