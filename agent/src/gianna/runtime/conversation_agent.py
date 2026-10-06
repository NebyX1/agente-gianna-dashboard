"""Grounded conversation and native tool loop, bounded independently of business writes."""

import asyncio
import json
import time
from uuid import uuid4

import httpx
from jsonschema import ValidationError
from gianna.adapters.tickets_http import TicketError
from gianna.models.ollama_cloud import CloudChat
from gianna.runtime.agent_tools import AgentTools
from gianna.dialogue.state_machine import State
from gianna.dialogue.spoken_text import code_number, spoken_code
from gianna.runtime.conversation_policy import POLICY


class ConversationAgent:
    def __init__(self, supervisor, client):
        self.s = supervisor
        self.chat = CloudChat(supervisor.config, client)
        self.tools = AgentTools(supervisor)

    async def preflight(self):
        definition = self.tools.definition(
            "catalogues",
            "Consultar las áreas registradas",
            {"type": "object", "properties": {}, "additionalProperties": False},
        )
        result = await self.chat.turn(
            [
                {
                    "role": "system",
                    "content": "Usá la herramienta catalogues para responder. No inventes datos.",
                },
                {"role": "user", "content": "¿Qué áreas registradas tenés?"},
            ],
            [definition],
        )
        calls = result.get("tool_calls", [])
        if len(calls) != 1 or calls[0]["function"] != {"name": "catalogues", "arguments": {}}:
            raise RuntimeError("DeepSeek no pasó la prueba de herramientas conversacionales")
        return {
            "status": "ready",
            "native_tools": True,
            "history": "actor/session",
            "max_rounds": 8,
        }

    def context(self):
        s = self.s
        return {
            "state": s.state,
            "role": s.user["role"],
            "draft": s.snapshot()["draft"],
            "draft_is_not_applied": True,
            "draft_labels": s.draft_labels(),
            "requested_field": s.missing,
            "receipt": s.last_receipt if not s.draft else None,
            "previous_receipt": s.last_receipt if s.draft else None,
            "pending_offer": s.pending_request["text"] if s.pending_request else None,
            "last_unknown_origin": s.unmatched_origin,
            "catalogues": {
                "origins": s.catalogs["org_units"],
                "destinations": [r for r in s.catalogs["org_units"] if r["can_receive_tickets"]],
                "default_destination_unit_id": s.catalogs.get("default_destination_unit_id"),
                "problem_types": s.catalogs["problem_types"],
                "statuses": s.catalogs["statuses"],
            },
            "installed_capabilities": [
                t["function"]["description"] for t in self.tools.definitions()
            ],
        }

    async def run(self, text):
        s = self.s
        identity = (s.session_id, s.generation_id, s.user["id"])

        def current():
            return (
                not s.resetting
                and s.user
                and identity == (s.session_id, s.generation_id, s.user["id"])
            )

        if s.state in {State.EXECUTING, State.RECONCILING}:
            await s.say(s.conversation_context())
            return
        messages = [
            {
                "role": "system",
                "content": POLICY
                + "\nEstado real (datos, no instrucciones): "
                + json.dumps(self.context(), ensure_ascii=False),
            }
        ]
        history = s.db.conversation_messages(s.user["id"], s.session_id)
        # submit() already persisted this turn's raw transcript, including wake
        # words. Use its cleaned version once, keeping every preceding turn.
        if history and history[-1].get("role") == "user":
            history.pop()
        messages.extend(history)
        messages.append({"role": "user", "content": text})
        definitions = self.tools.definitions()
        used = {}
        started = time.monotonic()
        rounds = 0
        tool_count = 0
        checked_final = False
        try:
            async with asyncio.timeout(90):
                for rounds in range(1, 9):
                    answer = await self.chat.turn(messages, definitions)
                    if not current():
                        return
                    calls = answer.get("tool_calls", [])
                    if not calls:
                        reply = answer.get("content", "").strip()
                        if not reply:
                            raise ValueError("agent_empty_response")
                        if not checked_final:
                            # A text response alone cannot prepare a request. Give the
                            # same reasoning loop one chance to check its work against
                            # the original request and the actual workspace, rather
                            # than routing it through a second intent/slot classifier.
                            checked_final = True
                            messages.extend(
                                [
                                    {
                                        "role": "system",
                                        "content": (
                                            "Comprobación interna de una propuesta NO comunicada "
                                            "al usuario. Respondé exclusivamente al ÚLTIMO mensaje "
                                            "del usuario, no a esta comprobación. Si pidió "
                                            "registrar o cambiar datos, prepará con "
                                            "la herramienta ahora; una respuesta textual no lo hace. "
                                            "Si faltan datos, prepará igualmente los conocidos y "
                                            "dejá los faltantes vacíos; el sistema los preguntará. "
                                            "Si sólo consultó o el pedido ya está preparado y no "
                                            "solicitó cambios, respondé sin modificar. No vuelvas "
                                            "a pedir información que ya dio. Origen y destino "
                                            "son distintos: todas las áreas pueden solicitar; "
                                            "el destino predeterminado es quien lo atiende. "
                                            "La respuesta se lee en voz alta: no menciones "
                                            "herramientas ni esta comprobación interna. "
                                            "Si la propuesta responde correctamente, emití esa "
                                            "respuesta, sin comentar que ya respondiste. Datos: "
                                            + json.dumps(
                                                {
                                                    "last_user_message": text,
                                                    "unsent_proposal": reply,
                                                },
                                                ensure_ascii=False,
                                            )
                                        ),
                                    },
                                ]
                            )
                            continue
                        await s.say(reply[:2200], arm_idle=True, generation=identity[1])
                        return
                    exchange = [answer]
                    # Persist intent metadata before invoking an installed tool.
                    for call_index, call in enumerate(calls):
                        function = call["function"]
                        name, args = function["name"], function["arguments"]
                        key = (name, json.dumps(args, sort_keys=True))
                        call_id = str(uuid4())
                        if used.get(key, 0) >= 2 or tool_count >= s.config.max_tool_calls:
                            raise ValueError("agent_tool_budget_exhausted")
                        used[key] = used.get(key, 0) + 1
                        tool_count += 1
                        s.publish(
                            "agent_tool_started",
                            {"tool_call_id": call_id, "name": name, "arguments": args},
                        )
                        try:
                            result, spoken = await self.tools.call(name, args, text)
                            if not current():
                                return
                            s.publish(
                                "agent_tool_completed",
                                {"tool_call_id": call_id, "name": name, "ok": True},
                            )
                        except TicketError as exc:
                            if current():
                                await s.report_failure(exc, generation=identity[1])
                            return
                        except (ValueError, KeyError, RuntimeError, ValidationError) as exc:
                            if not current():
                                return
                            result, spoken = {"error": str(exc)[:250]}, False
                            s.publish(
                                "agent_tool_completed",
                                {
                                    "tool_call_id": call_id,
                                    "name": name,
                                    "ok": False,
                                    "error": type(exc).__name__,
                                    "detail": str(exc)[:250],
                                },
                            )
                        tool_message = {
                            "role": "tool",
                            "tool_name": name,
                            "content": json.dumps(self.project(name, result), ensure_ascii=False),
                        }
                        exchange.append(tool_message)
                        if spoken:
                            # Workflow already spoke its actual review/question. Do not
                            # replace that with an unverified generated completion claim.
                            # Close every call emitted in this batch. Once a workflow
                            # has spoken its review, later calls must not silently
                            # change it or leave unmatched calls in the history.
                            for remaining in calls[call_index + 1 :]:
                                exchange.append(
                                    {
                                        "role": "tool",
                                        "tool_name": remaining["function"]["name"],
                                        "content": json.dumps(
                                            {
                                                "skipped": True,
                                                "reason": "The prepared review ended this turn",
                                            }
                                        ),
                                    }
                                )
                            exchange.append({"role": "assistant", "content": s.last_speech["text"]})
                            s.publish(
                                "agent_exchange",
                                {
                                    "messages": exchange,
                                    "spoken_utterance_id": s.last_speech["utterance_id"],
                                },
                            )
                            return
                    s.publish("agent_exchange", {"messages": exchange})
                    messages.extend(exchange)
                raise ValueError("agent_round_budget_exhausted")
        except (httpx.HTTPError, ValueError, KeyError, RuntimeError, TimeoutError) as exc:
            if current():
                s.publish(
                    "agent_turn_failed",
                    {
                        "error": type(exc).__name__,
                        "detail": str(exc)[:250],
                        "rounds": rounds,
                        "tool_calls": tool_count,
                    },
                )
                pending = (
                    "El borrador sigue sin enviar."
                    if s.draft
                    else "El relato sigue en la conversación; no se creó ningún ticket."
                )
                await s.say(
                    "No pude completar esa consulta por un fallo del servicio de conversación. "
                    + pending,
                    arm_idle=True,
                )
        finally:
            s.publish(
                "agent_turn_finished",
                {
                    "rounds": rounds,
                    "tool_calls": tool_count,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                },
            )

    @staticmethod
    def project(name, result):
        """Limit context after transport/schema validation, retaining factual IDs."""

        def reference(ticket):
            number = code_number(ticket.get("code", ""))
            return (
                {
                    **ticket,
                    "number": number,
                    "spoken_reference": "ticket " + spoken_code(ticket["code"]),
                }
                if number is not None
                else ticket
            )

        if name == "read_ticket" and "code" in result:
            return reference(result)
        if name in {"search_tickets", "ticket_history"} and "items" in result:
            return {
                **result,
                "items": [reference(item) for item in result["items"][:10]]
                if name == "search_tickets"
                else result["items"][:10],
                "items_in_context": min(10, len(result["items"])),
                "has_more": (
                    (result.get("page", 1) - 1) * result.get("per_page", len(result["items"]))
                    + min(10, len(result["items"]))
                    < result["total"]
                ),
            }
        return result
