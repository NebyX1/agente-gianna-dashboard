"""Small installed toolset for conversation; business commits stay in OperationManager."""

from gianna.dialogue.state_machine import State
from gianna.dialogue.conversation import Intent
from gianna.tools.tickets import schema


class AgentTools:
    reads = {
        "catalogues": "tickets.catalogs.v1",
        "search_tickets": "tickets.search.v1",
        "read_ticket": "tickets.read.v1",
        "ticket_history": "tickets.history.v1",
        "open_board": "browser.open.v1",
        "show_ticket": "browser.show.v1",
        "filter_board": "browser.filter.v1",
    }
    descriptions = {
        "catalogues": "Consultar áreas, oficinas, municipios, destinos y tipos de problema REALES. Usar al preguntar qué áreas hay o si un nombre existe. No buscar tickets para listar áreas.",
        "search_tickets": "Buscar tickets reales por texto o filtros; devuelve códigos e IDs reales.",
        "read_ticket": "Leer un ticket por su ID interno obtenido de search_tickets. El número del código no es el ID.",
        "ticket_history": "Consultar historial real por ID interno obtenido de search_tickets.",
        "open_board": "Abrir el tablero de tickets en el navegador propio.",
        "show_ticket": "Mostrar un ticket real por ID interno previamente encontrado.",
        "filter_board": "Filtrar el tablero por el texto indicado.",
    }

    def __init__(self, supervisor):
        self.s = supervisor

    def definitions(self):
        s = self.s
        tools = []
        context = s.tool_context()
        available = s.dispatcher.registry.available(
            context.capabilities, context.state, context.role
        )
        for name, stable in self.reads.items():
            if stable in s.profile["tools"] and stable in s.dispatcher.registry.tools:
                entry = s.dispatcher.registry.tools[stable]
                if entry in available:
                    tools.append(self.definition(name, self.descriptions[name], entry.schema))
        tools += [
            self.definition(
                "prepare_request",
                "Preparar un ticket nuevo (create), corregir su descripción (replace), agregar detalles (append) o cambiar campos (select). Usá el relato y las aclaraciones del historial: text es una descripción clara que conserva los hechos, no una cita literal. Incluí los IDs del catálogo que identifiquen origen, destino y tipo, también al crear. Si sólo cambia un campo, select conserva la descripción. create requiere solicitud de registrar; offer ofrece registrarlo cuando sólo cuentan un incidente. Sólo prepara: la revisión y el envío se controlan aparte.",
                schema(
                    {
                        "mode": {"enum": ["create", "replace", "append", "offer", "select"]},
                        "text": {"type": "string", "minLength": 10, "maxLength": 4000},
                        "unknown_origin": {"type": "string", "minLength": 1, "maxLength": 200},
                        **{
                            f: {
                                "type": "integer",
                                "minimum": 1,
                                "description": {
                                    "origin_unit_id": "ID del área solicitante o afectada. Todas las áreas pueden ser origen, incluso si can_receive_tickets es false.",
                                    "destination_unit_id": "ID del equipo que atiende el pedido. Por defecto default_destination_unit_id; sólo destinos con can_receive_tickets=true.",
                                    "problem_type_id": "ID de la categoría del incidente, según los tipos del catálogo.",
                                }[f],
                            }
                            for f in ("origin_unit_id", "destination_unit_id", "problem_type_id")
                        },
                    },
                    ["mode"],
                )
                | {
                    "allOf": [
                        {
                            "if": {"properties": {"mode": {"const": "select"}}},
                            "then": {
                                "anyOf": [
                                    {"required": [f]}
                                    for f in (
                                        "origin_unit_id",
                                        "destination_unit_id",
                                        "problem_type_id",
                                        "unknown_origin",
                                    )
                                ],
                                "not": {"required": ["text"]},
                            },
                            "else": {
                                "if": {"properties": {"mode": {"const": "create"}}},
                                "then": {},
                                "else": {"required": ["text"]},
                            },
                        }
                    ]
                },
            ),
            self.definition(
                "request_correction",
                "Sólo si la descripción quedó mal y NO aporta los datos correctos. Si dice 'lo que dije es que...' con el incidente, usar prepare_request mode replace con esa cita, no esta herramienta.",
                schema({}),
            ),
            self.definition(
                "supply_draft_text",
                "Completar la descripción, nota o motivo solicitado del borrador. Conservá los hechos del relato y sus aclaraciones; podés redactarlos con claridad. No usar preguntas ni quejas como datos. Nunca enviar.",
                schema(
                    {
                        "field": {"enum": ["description", "note", "reason"]},
                        "text": {"type": "string", "minLength": 5, "maxLength": 4000},
                    },
                    ["field", "text"],
                ),
            ),
            self.definition(
                "select_draft_status",
                "Elegir estado del borrador de cambio de estado; validar transiciones reales y pedir motivo. Nunca enviar.",
                schema(
                    {
                        "status": {
                            "enum": ["new", "in_progress", "waiting", "resolved", "cancelled"]
                        }
                    },
                    ["status"],
                ),
            ),
            self.definition(
                "prepare_existing_ticket",
                "Preparar edición, cambio de estado, ocultación o restauración de un ticket identificado por su número de código. Sólo prepara revisión, nunca escribe. Restaurar requiere administrador.",
                schema(
                    {
                        "action": {"enum": ["update", "status", "archive", "restore"]},
                        "number": {"type": "integer", "minimum": 1},
                        "text": {
                            "type": "string",
                            "minLength": 5,
                            "maxLength": 4000,
                            "description": "Motivo ya indicado para el cambio de estado, ocultación o restauración; o descripción nueva para una edición. Usá los datos del usuario en este turno y su historial, sin volver a preguntarlos.",
                        },
                        "status": {
                            "enum": ["new", "in_progress", "waiting", "resolved", "cancelled"]
                        },
                    },
                    ["action", "number"],
                ),
            ),
            self.definition(
                "conversation_control",
                "Pausar, retomar, repetir, finalizar charla o hablar más despacio. Usar resume al pedir continuar un borrador: recupera el estado y habilita una nueva revisión para confirmar. Decir que seguimos sin usar esta herramienta no retoma el borrador. Finalizar charla no resuelve ni envía tickets.",
                schema(
                    {
                        "action": {
                            "enum": ["pause", "resume", "repeat", "end_conversation", "slower"]
                        }
                    },
                    ["action"],
                ),
            ),
        ]
        return tools

    @staticmethod
    def definition(name, description, parameters):
        return {
            "type": "function",
            "function": {"name": name, "description": description, "parameters": parameters},
        }

    async def call(self, name, args, text):
        from jsonschema import Draft202012Validator

        definitions = {t["function"]["name"]: t["function"] for t in self.definitions()}
        if name not in definitions:
            raise ValueError("Herramienta no instalada o no disponible")
        Draft202012Validator(definitions[name]["parameters"]).validate(args)
        s = self.s
        if name in self.reads:
            result = await s.tool(self.reads[name], args)
            if name == "catalogues":
                s.catalogs = result
            return result, False
        if s.state in {State.EXECUTING, State.RECONCILING}:
            raise ValueError("Hay una operación pendiente; primero hay que comprobarla")
        if name == "conversation_control":
            await s.converse(Intent(args["action"]))
            return {"state": s.state}, True
        if name == "prepare_request":
            description = args.get("text")
            fields = {
                f: args[f]
                for f in ("origin_unit_id", "destination_unit_id", "problem_type_id")
                if f in args
            }
            for field, value in fields.items():
                rows = s.catalogs["problem_types" if field == "problem_type_id" else "org_units"]
                if field == "destination_unit_id":
                    rows = [r for r in rows if r["can_receive_tickets"]]
                if not any(r["id"] == value for r in rows):
                    raise ValueError("Esa opción no existe en el catálogo")
            if args.get("unknown_origin") and fields.get("origin_unit_id"):
                raise ValueError("Un origen no puede ser conocido y desconocido a la vez")
            if args["mode"] == "offer":
                s.pending_request = {
                    "text": description,
                    "prepared": {**args, "mode": "create"},
                    "actor": s.user["id"],
                    "session": s.session_id,
                    "expires": s.clock() + s.config.confirmation_seconds,
                }
                s.set_state(State.INVITING)
                await s.say("¿Querés que prepare un ticket con ese problema?", arm_idle=True)
            elif args["mode"] == "create":
                await s.start_request(
                    prepared=fields | ({"description": description} if description else {}),
                    unknown_origin=args.get("unknown_origin"),
                )
            else:
                self.owned_draft("tickets.create.v1", "tickets.update.v1")
                if args["mode"] != "select":
                    previous = s.draft.payload.get("description", "")
                    fields["description"] = (
                        previous + " " + description
                        if args["mode"] == "append" and previous
                        else description
                    )
                if not args.get("unknown_origin") and all(
                    s.draft.payload.get(key) == value for key, value in fields.items()
                ):
                    return {"draft": s.snapshot()["draft"], "sent": False, "changed": False}, False
                s.confirmation = s.missing = None
                s.retry_id = None
                if args.get("unknown_origin"):
                    s.draft.payload.pop("origin_unit_id", None)
                    s.unmatched_origin = {"draft_id": s.draft.id, "text": args["unknown_origin"]}
                    if not fields:
                        s.draft.change()
                if fields:
                    s.draft.change(**fields)
                    if "origin_unit_id" in fields:
                        s.unmatched_origin = None
                s.db.save_draft(s.draft)
                await s.resume_draft()
            return {"draft": s.snapshot()["draft"], "sent": False}, True
        if name == "request_correction":
            self.owned_draft("tickets.create.v1", "tickets.update.v1")
            s.confirmation = None
            s.replacing_description = True
            await s.ask_missing("description")
            return {"requested_field": "description", "sent": False}, True
        if name == "supply_draft_text":
            self.owned_draft()
            if s.missing != args["field"]:
                raise ValueError("Ese dato no es el que falta en el borrador vigente")
            s.confirmation = None
            s.retry_id = None
            s.draft.change(**{args["field"]: args["text"]})
            s.db.save_draft(s.draft)
            await s.resume_draft()
            return {"draft": s.snapshot()["draft"], "sent": False}, True
        if name == "select_draft_status":
            self.owned_draft("tickets.status.v1")
            if s.missing != "status":
                raise ValueError("El borrador no está esperando un estado")
            labels = {r["code"]: r["label"] for r in s.catalogs["statuses"]}
            await s.collect(labels[args["status"]])
            return {"draft": s.snapshot()["draft"], "sent": False}, True
        if name == "prepare_existing_ticket":
            if args["action"] == "restore" and s.user["role"] != "admin":
                raise ValueError("Sólo un administrador puede restaurar tickets")
            verbs = {
                "update": "Editá",
                "status": "Pasá",
                "archive": "Ocultá",
                "restore": "Restaurá",
            }
            command = f"{verbs[args['action']]} el ticket número {args['number']}"
            if args["action"] == "status":
                if "status" not in args:
                    raise ValueError("Falta el estado de destino")
                labels = {r["code"]: r["label"] for r in s.catalogs["statuses"]}
                command += " a " + labels[args["status"]]
            await s.resource_command(command, review_only=True, prepared_text=args.get("text"))
            return {"draft": s.snapshot()["draft"], "sent": False}, True
        raise ValueError("Herramienta desconocida")

    def owned_draft(self, *tools):
        d = self.s.draft
        if not d or d.owner != "agent" or d.transferred or d.actor_id != self.s.user["id"]:
            raise ValueError("No hay un borrador propio disponible")
        if tools and d.tool not in tools:
            raise ValueError("Ese campo no corresponde a la operación del borrador")
