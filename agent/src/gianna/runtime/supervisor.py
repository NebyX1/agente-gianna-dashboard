import asyncio
from dataclasses import asdict
import time
import re
import json
import httpx
from uuid import uuid4
from gianna.dialogue.activation import WAKE, candidate, normalize
from gianna.dialogue.state_machine import State
from gianna.dialogue.draft import Draft
from gianna.dialogue.confirmations import Confirmation
from gianna.dialogue.interpretation import (
    Reply,
    control_text,
    creation_request,
    data_text,
    discard_request,
    review_reply,
)
from gianna.dialogue.slots import matches, resolve, catalogue_answer
from gianna.dialogue.spoken_text import review, spoken_code
from gianna.dialogue.numbers import ticket_number
from gianna.dialogue.conversation import (
    FIELD_PROMPTS,
    Intent,
    conversational_intent,
    missing_field,
    terminal_ticket_request,
)
from gianna.persistence.database import utc
from gianna.adapters.tickets_http import TicketError
from gianna.runtime.errors import ErrorCode, MESSAGES, classify


WELCOME = "Hola, soy Gianna y ya estoy activada."


class Supervisor:
    """Only owner of public dialogue, generation changes, confirmations and speech authority."""

    def __init__(
        self, config, db, bus, tickets, tev, operations, profile, cloud, *, clock=time.monotonic
    ):
        self.config, self.db, self.bus, self.tickets, self.tev = config, db, bus, tickets, tev
        self.operations, self.profile, self.cloud, self.clock = operations, profile, cloud, clock
        self.session_id, self.turn_id, self.generation_id = str(uuid4()), str(uuid4()), str(uuid4())
        self.state = State.STARTING
        self.draft = self.confirmation = self.user = self.catalogs = None
        self.browser = None
        self.speak_callback = self.stop_callback = None
        self.last_speech = self.last_receipt = None
        self.idle_deadline = None
        self.idle_version = 0
        self.idle_task = None
        self.speech_candidate_at = None
        self.candidate_grace_deadline = None
        self.pending_question = None
        self.tasks = set()
        self.errors = []
        self.quiet = False
        self.voice_speed = 1
        self.missing = None
        self.interpreter = None
        self.pending_request = None
        self.replacing_description = False
        self.unmatched_origin = None
        self.playing = self.interrupted = None
        self.resetting = False

    async def tool(self, name, arguments):
        """Installed read/surface tools share the same validation and per-turn budget."""
        if not hasattr(self, "dispatcher"):
            # Unit fixtures deliberately omit transports; production always installs dispatcher.
            raise RuntimeError("tool_dispatcher_unavailable")
        if name not in self.profile["tools"]:
            raise RuntimeError("tool_not_in_profile")
        context = self.tool_context()
        call_id = str(uuid4())
        generation = self.generation_id
        self.publish("tool_started", {"tool_call_id": call_id, "tool_id": name})
        result = await self.dispatcher.call(name, arguments, context)
        self.publish(
            "tool_completed",
            {"tool_call_id": call_id, "tool_id": name, "current": generation == self.generation_id},
        )
        if generation != self.generation_id:
            raise RuntimeError("stale_generation")
        return result

    def tool_context(self):
        from types import SimpleNamespace

        return SimpleNamespace(
            state=self.state,
            role=self.user["role"] if self.user else "",
            capabilities={"dialogue"}
            | {
                c.name
                for adapter in (self.tickets, self.browser)
                if adapter
                for c in adapter.discover()
                if c.available
            },
        )

    async def report_failure(self, exc, *, generation=None):
        if generation is not None and generation != self.generation_id:
            return
        code = classify(exc)
        event = {"code": code, "message": MESSAGES[code]}
        self.errors.append(event)
        self.publish("tool_error", event)
        if code == ErrorCode.AUTH:
            await self.auth_invalidated()
        await self.say(MESSAGES[code], arm_idle=True)

    def snapshot(self):
        return {
            "state": self.state,
            "user": self.user,
            "profile": self.profile["profile_id"],
            "profile_version": self.profile["version"],
            "capabilities": [
                asdict(c)
                for adapter in (self.tickets, self.browser)
                if adapter and hasattr(adapter, "discover")
                for c in adapter.discover()
            ]
            + [
                {
                    "name": name,
                    "version": "1",
                    "available": False,
                    "reason": "Adaptador no instalado",
                }
                for name in ("desktop", "files", "processes", "mcp")
            ],
            "draft": asdict(self.draft) if self.draft else None,
            "receipt": self.last_receipt,
            "errors": self.errors[-4:],
            "audio_connected": self.speak_callback is not None,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "generation_id": self.generation_id,
            "preferences": self.db.preferences(self.user["id"]) if self.user else None,
            "draft_labels": self.draft_labels(),
            "pending_request": self.pending_request["text"] if self.pending_request else None,
            "requested_field": self.missing,
        }

    def draft_labels(self):
        if not self.draft or not self.catalogs:
            return {}
        result = {}
        for field, collection in (
            ("origin_unit_id", "org_units"),
            ("destination_unit_id", "org_units"),
            ("problem_type_id", "problem_types"),
        ):
            result[field] = next(
                (
                    r["name"]
                    for r in self.catalogs[collection]
                    if r["id"] == self.draft.payload.get(field)
                ),
                "Sin elegir",
            )
        result["status"] = next(
            (
                s["label"]
                for s in self.catalogs["statuses"]
                if s["code"] == self.draft.payload.get("status")
            ),
            "Sin elegir",
        )
        return result

    def publish(self, kind, data):
        event = {
            "schema_version": "1",
            "kind": kind,
            "data": data,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "generation_id": self.generation_id,
            "at": utc(),
        }
        event["event_id"] = self.db.event(
            self.session_id,
            self.generation_id,
            kind,
            data,
            self.turn_id,
            actor_id=self.user["id"] if self.user else None,
        )
        self.bus.publish(event)

    def set_state(self, state):
        self.state = state
        self.publish("state", self.snapshot())

    def invalidate(self):
        self.generation_id = str(uuid4())
        self.turn_id = str(uuid4())

    def cancel_idle(self):
        self.idle_version += 1
        if self.idle_task:
            try:
                current = asyncio.current_task()
            except RuntimeError:
                current = None
            if self.idle_task is not current:
                self.idle_task.cancel()
        self.idle_deadline = None

    async def say(self, text, *, arm_idle=False, generation=None):
        generation = generation or self.generation_id
        if generation != self.generation_id:
            return
        utterance_id = str(uuid4())
        message = {
            "text": text,
            "utterance_id": utterance_id,
            "generation_id": generation,
            "arm_idle": arm_idle,
            "silent": self.quiet or self.speak_callback is None,
        }
        self.last_speech = message
        self.playing = (utterance_id, self.clock() + 3 + len(text) / 10)
        self.publish("speech", message)
        if self.speak_callback and not self.quiet:
            await self.speak_callback(message)
        # No synthetic timer start from server synthesis or publication.
        # Without audio, console sends a deliberate text-presentation completion event.

    async def playback_complete(self, utterance_id, generation_id):
        m = self.last_speech
        if not m or m["utterance_id"] != utterance_id or generation_id != self.generation_id:
            return
        self.playing = self.interrupted = None
        self.publish(
            "playback_complete", {"utterance_id": utterance_id, "generation_id": generation_id}
        )
        if self.state == State.CLOSING:
            if self.last_receipt:
                with self.db.transaction() as c:
                    c.execute(
                        "UPDATE operations SET spoken_ack=1 WHERE operation_id=? AND actor_id=? AND status='succeeded'",
                        (self.last_receipt["operation_id"], self.user["id"] if self.user else -1),
                    )
            self.set_state(State.DORMANT)
        if m["arm_idle"] and self.state in {
            State.INVITING,
            State.WAITING_INITIAL_INPUT,
            State.ASKING_MISSING_FIELD,
            State.WAITING_CONFIRMATION,
            State.REVIEWING_DRAFT,
        }:
            if self.state == State.INVITING:
                self.set_state(State.WAITING_INITIAL_INPUT)
            self.cancel_idle()
            self.idle_deadline = self.clock() + self.config.idle_seconds
            self.idle_task = asyncio.create_task(self.idle_watch(self.idle_version))

    async def idle_watch(self, version):
        while version == self.idle_version and self.idle_deadline is not None:
            now = self.clock()
            deadline = self.idle_deadline
            if self.speech_candidate_at is not None and self.speech_candidate_at < deadline:
                deadline = max(deadline, self.candidate_grace_deadline or deadline)
            if now >= deadline:
                await self.expire_idle(version)
                return
            await asyncio.sleep(min(0.25, max(0.01, deadline - now)))

    async def expire_idle(self, version):
        if version != self.idle_version or self.state in {
            State.EXECUTING,
            State.RECONCILING,
            State.COLLECTING_DRAFT,
        }:
            return
        initial_empty = self.state in {State.INVITING, State.WAITING_INITIAL_INPUT} and (
            not self.draft or not self.draft.payload.get("description")
        )
        self.pending_request = None
        if self.draft and not initial_empty:
            self.db.save_draft(self.draft)
        if initial_empty:
            self.draft = None
        self.confirmation = None
        self.cancel_idle()
        self.set_state(State.DORMANT)
        await self.say(
            "Cuando necesites algo, llamame."
            if initial_empty
            else "Dejé el borrador sin enviar. Cuando necesites seguir, llamame de nuevo."
        )

    async def vad_started(self):
        if self.resetting:
            return
        self.speech_candidate_at = self.speech_candidate_at or self.clock()
        self.candidate_grace_deadline = (
            self.speech_candidate_at + self.config.max_turn_seconds + self.config.stt_grace_seconds
        )
        if self.playing and self.playing[1] > self.clock() and self.last_speech:
            # Remember what the noise may have cut off, in case it was not speech.
            self.interrupted = self.last_speech
        self.playing = None
        if self.stop_callback:
            await self.stop_callback()
        # Acoustic interruption does NOT change semantic generation or confirmation.
        self.publish("audio_interrupted", {})

    async def vad_stopped(self):
        if self.speech_candidate_at is not None:
            self.candidate_grace_deadline = min(
                self.speech_candidate_at
                + self.config.max_turn_seconds
                + self.config.stt_grace_seconds,
                self.clock() + self.config.stt_grace_seconds,
            )

    async def rejected_audio(self, evidence):
        if self.resetting:
            return
        self.speech_candidate_at = self.candidate_grace_deadline = None
        self.publish("stt_rejected", evidence)
        interrupted, self.interrupted = self.interrupted, None
        if self.state in {State.DORMANT, State.PAUSED, State.EXECUTING, State.RECONCILING}:
            return
        if interrupted and interrupted["generation_id"] == self.generation_id:
            # Noise, not speech: say again what it cut off.
            await self.say(interrupted["text"], arm_idle=interrupted["arm_idle"])
        elif self.last_speech and (evidence or {}).get("active_ms", 0) >= 700:
            await self.say("No te escuché bien. ¿Podés repetirlo?", arm_idle=False)
        # Original idle deadline remains intact.

    async def authenticated(self, user):
        self.pending_request = None
        self.invalidate()
        generation = self.generation_id
        if self.user and self.user["id"] != user["id"]:
            self.draft = None
        self.user = user
        self.confirmation = None
        self.cancel_idle()
        self.catalogs = self.last_receipt = self.last_speech = None
        preferences = self.db.preferences(user["id"])
        self.voice_speed, self.quiet = preferences["speed"], preferences["quiet"]
        catalogs = await self.tickets.request("GET", "/api/v1/catalogs")
        if self.user is not user or generation != self.generation_id:
            return
        results = await self.operations.recover(user["id"])
        if self.user is not user or generation != self.generation_id:
            return
        self.catalogs = catalogs
        unresolved = any(r.get("status") == "outcome_unknown" for r in results)
        saved = self.db.load_drafts(user["id"])
        self.draft = next((d for d in saved if not d.transferred and d.owner == "agent"), None)
        committed = [
            r
            for r in self.db.operations(user["id"])
            if r["status"] == "succeeded"
            and r["receipt"]
            and r["updated_at"] >= self.db.conversation_start(user["id"])
        ]
        self.last_receipt = json.loads(committed[-1]["receipt"]) if committed else None
        self.set_state(State.RECONCILING if unresolved else State.DORMANT)
        self.publish("authenticated", {"user": user, "recovery": results})

    async def auth_invalidated(self):
        self.pending_request = None
        self.invalidate()
        self.confirmation = None
        self.cancel_idle()
        if self.draft:
            self.db.save_draft(self.draft)
        self.user = self.catalogs = self.draft = self.last_receipt = self.last_speech = None
        self.proposal = None
        self.missing = None
        self.tickets.token = None
        self.set_state(State.AUTH_REQUIRED)

    async def activate(self, *, initial="", owns_generation=False):
        initial = initial.strip(" ,.:;!¿?¡")
        if not owns_generation:
            self.invalidate()
        if self.state == State.BLOCKED:
            return
        if not self.user:
            self.set_state(State.AUTH_REQUIRED)
            await self.say(
                "Abrí el sistema de tickets e iniciá sesión con tu código de verificación."
            )
            return
        if not initial and self.state != State.RECONCILING:
            await self.welcome()
            return
        if discard_request(initial):
            await self.discard_draft()
            return
        request = creation_request(initial)
        if request and not hasattr(self, "conversation_agent"):
            await self.start_request(request.content)
            return
        reply = review_reply(
            initial,
            tool=self.draft.tool if self.draft else None,
            status=self.draft.payload.get("status") if self.draft else None,
        )
        if reply.kind == Reply.APPROVE:
            await self.no_review()
            return
        intent = conversational_intent(initial)
        if intent in {Intent.HELP, Intent.CREATE} and hasattr(self, "conversation_agent"):
            intent = None
        if intent:
            await self.converse(intent)
            return
        if self.state == State.RECONCILING:
            await self.reconcile()
            return
        self.cancel_idle()
        self.set_state(State.INVITING)
        repeat_request = normalize(initial).strip(" ,.!?¿¡")
        if repeat_request in {"repeti", "repite", "repetir", "repeti el codigo"}:
            await self.repeat(code_only=repeat_request == "repeti el codigo")
            return
        if hasattr(self, "conversation_agent"):
            await self.conversation_agent.run(data_text(initial))
            return
        if initial and await self.resource_command(initial.strip(" ,.:")):
            return
        if self.draft and not self.draft.transferred:
            if normalize(initial).strip(" ,.!?") in {
                "continuemos",
                "continua",
                "continuar",
                "retomar",
                "segui",
            }:
                await self.resume_draft()
                return
            if initial:
                await self.route_turn(initial)
                return
            await self.welcome()
            return
        await self.route_turn(initial)

    async def welcome(self):
        """Activation is only a greeting: it confirms Gianna is on and nothing else."""
        if self.state in {
            State.COLLECTING_DRAFT,
            State.ASKING_MISSING_FIELD,
            State.REVIEWING_DRAFT,
            State.WAITING_CONFIRMATION,
        }:
            await self.say(self.conversation_context(), arm_idle=True)
            return
        self.cancel_idle()
        pending = self.draft and not self.draft.transferred and self.draft.owner == "agent"
        if pending:
            self.missing = missing_field(self.draft)
            self.set_state(State.ASKING_MISSING_FIELD if self.missing else State.COLLECTING_DRAFT)
        else:
            self.set_state(State.INVITING)
        await self.say(
            WELCOME + (" Tenés un borrador sin enviar." if pending else ""), arm_idle=True
        )

    async def submit(self, text, *, source="text", evidence=None):
        text = text.strip()
        if not text or len(text) > 4000 or self.state == State.BLOCKED or self.resetting:
            return
        self.publish(
            "stt_final" if source == "voice" else "input_final",
            {"text": text, "source": source, "evidence": evidence},
        )
        if hasattr(self, "dispatcher"):
            self.dispatcher.calls = 0
        self.speech_candidate_at = self.candidate_grace_deadline = None
        if (
            discard_request(text)
            and self.user
            and (
                source == "text"
                or self.state not in {State.DORMANT, State.PAUSED, State.AUTH_REQUIRED}
            )
        ):
            await self.discard_draft()
            return
        if self.state in {State.DORMANT, State.PAUSED, State.AUTH_REQUIRED}:
            remainder = candidate(text)
            # Typing in the dedicated console is direct address. Ambient voice
            # still requires the original wake + Tev activation gate.
            if source == "text" and remainder is None:
                remainder = text
            if source == "voice" and remainder is None:
                self.publish("ignored", {"reason": "no_direct_activation"})
                return
            self.invalidate()
            self.publish("transcript", {"text": text, "source": source, "evidence": evidence})
            if conversational_intent(remainder or "") in {Intent.GREETING, Intent.PRESENCE}:
                remainder = ""
            await self.activate(initial=remainder or "", owns_generation=True)
            return
        if self.pending_request:
            pending, self.pending_request = self.pending_request, None
            answer = review_reply(text, tool="tickets.create.v1")
            valid = self.user and (
                pending["actor"] == self.user["id"]
                and pending["session"] == self.session_id
                and pending["expires"] > self.clock()
            )
            if valid and answer.kind == Reply.APPROVE:
                self.invalidate()
                self.cancel_idle()
                self.publish("transcript", {"text": text, "source": source, "evidence": evidence})
                if hasattr(self, "conversation_agent") and pending.get("prepared"):
                    await self.conversation_agent.tools.call(
                        "prepare_request", pending["prepared"], text
                    )
                else:
                    await self.start_request(pending["text"])
                return
            self.publish("state", self.snapshot())
        reply = review_reply(
            text,
            tool=self.draft.tool if self.draft else None,
            status=self.draft.payload.get("status") if self.draft else None,
        )
        if (
            reply.kind == Reply.UNKNOWN
            and self.state == State.WAITING_CONFIRMATION
            and getattr(self, "review_interpreter", None)
            and self.draft
            and self.confirmation
            and self.user
            and self.confirmation.valid(self.draft, self.user["id"], self.clock, self.session_id)
        ):
            # Meaning may take a network round trip. Bind it to this exact review;
            # a pause, edit, account change or newer turn makes the answer obsolete.
            draft, confirmation, generation = self.draft, self.confirmation, self.generation_id
            try:
                reply, meaning = await self.review_interpreter.interpret(
                    text, asdict(draft), source=source
                )
            except Exception as exc:
                self.publish("review_interpretation_failed", {"error": type(exc).__name__})
            else:
                self.publish("review_interpreted", meaning.model_dump())
            if (
                self.generation_id != generation
                or self.state != State.WAITING_CONFIRMATION
                or self.draft is not draft
                or self.confirmation is not confirmation
                or not self.user
                or not confirmation.valid(draft, self.user["id"], self.clock, self.session_id)
            ):
                self.publish("review_interpretation_discarded", {"reason": "review_changed"})
                return
        if self.state == State.WAITING_CONFIRMATION and reply.kind != Reply.UNKNOWN:
            self.invalidate()
            self.cancel_idle()
            self.publish("transcript", {"text": text, "source": source, "evidence": evidence})
            self.publish("interpretation", {"meaning": reply.kind, "context": "review"})
            if reply.kind == Reply.APPROVE:
                await self.commit()
            elif reply.kind == Reply.HOLD:
                await self.pause()
            else:
                self.confirmation = None
                self.set_state(State.COLLECTING_DRAFT)
                if reply.kind == Reply.CORRECT:
                    self.missing = None
                    if hasattr(self, "conversation_agent"):
                        await self.conversation_agent.run(text)
                    else:
                        await self.collect(reply.correction)
                else:
                    await self.say("Decime qué querés corregir o agregar.", arm_idle=True)
            return
        if reply.kind in {Reply.HOLD, Reply.DECLINE, Reply.CORRECT}:
            if self.state not in {State.EXECUTING, State.RECONCILING}:
                self.invalidate()
                self.cancel_idle()
            self.publish("transcript", {"text": text, "source": source, "evidence": evidence})
            if reply.kind == Reply.HOLD:
                await self.pause()
            elif self.state in {State.EXECUTING, State.RECONCILING}:
                await self.say(self.conversation_context())
            elif (
                reply.kind == Reply.CORRECT
                and self.draft
                and not self.draft.transferred
                and self.draft.owner == "agent"
            ):
                self.confirmation = self.missing = None
                if hasattr(self, "conversation_agent"):
                    await self.conversation_agent.run(text)
                else:
                    await self.collect(reply.correction)
            else:
                await self.say("Está bien. " + self.conversation_context(), arm_idle=True)
            return
        if reply.kind == Reply.APPROVE:
            # A repeated yes during dispatch cannot revoke a previously
            # authorized generation or reserve another operation.
            if self.state not in {State.EXECUTING, State.RECONCILING}:
                self.invalidate()
                self.cancel_idle()
            self.publish("transcript", {"text": text, "source": source, "evidence": evidence})
            await self.no_review()
            return
        request = creation_request(text)
        if request and not hasattr(self, "conversation_agent"):
            if self.state not in {State.EXECUTING, State.RECONCILING}:
                self.invalidate()
                self.cancel_idle()
            self.publish("transcript", {"text": text, "source": source, "evidence": evidence})
            await self.start_request(request.content)
            return
        intent = conversational_intent(WAKE.sub(" ", text))
        if intent in {Intent.HELP, Intent.CREATE} and hasattr(self, "conversation_agent"):
            intent = None
        if intent:
            # Social replies must not revoke an authorized operation's generation
            # while its reservation or HTTP response is still in flight.
            if self.state not in {State.EXECUTING, State.RECONCILING}:
                self.invalidate()
            self.cancel_idle()
            self.publish("transcript", {"text": text, "source": source, "evidence": evidence})
            await self.converse(intent)
            return
        self.invalidate()  # Only final ACCEPTED transcript enters here.
        generation = self.generation_id
        self.cancel_idle()
        self.publish("transcript", {"text": text, "source": source, "evidence": evidence})
        text = data_text(text)
        n = control_text(text)
        if n in {"para", "parate", "detenete", "cancelar", "cancela", "pausa", "pausar"}:
            await self.pause()
            return
        if n in {"repeti", "repite", "repetir", "repeti el codigo"}:
            await self.repeat(code_only=n == "repeti el codigo")
            return
        if self.state == State.RECONCILING and n == "reintentar la misma operacion":
            pending = self.db.operations(self.user["id"], nonterminal=True)
            if len(pending) == 1 and pending[0]["status"] == "outcome_unknown":
                row = pending[0]
                self.draft = Draft(
                    row["actor_id"],
                    id=row["draft_id"],
                    revision=row["revision"],
                    tool=row["tool"],
                    resource=row["resource"],
                    payload=__import__("json").loads(row["payload"]),
                )
                self.retry_id = row["operation_id"]
                await self.say(
                    "Voy a revisar el mismo intento. Conservo su clave para comprobar o ejecutar una sola operación."
                )
                await self.review()
            else:
                await self.reconcile()
            return
        if self.state in {State.EXECUTING, State.RECONCILING}:
            await self.reconcile()
            return
        if n in {"retomar", "retoma", "segui", "continuar"} and self.draft:
            await self.resume_draft()
            return
        if n in {"nuevo ticket", "otro ticket"} and not hasattr(self, "conversation_agent"):
            self.draft = None
            self.confirmation = None
            await self.start_request()
            return
        if n in {"tomar el control", "yo continuo", "lo hago yo"}:
            await self.handoff()
            return
        if n in {"abrir tablero", "abri el tablero", "mostra el tablero", "mostrame el tablero"}:
            await self.tool("browser.open.v1", {})
            await self.say("Abrí el tablero.", arm_idle=True)
            return
        if re.match(r"^(?:razona|analiza|explicame|explica|mejora la redaccion|resumi)\b", n):
            try:
                original = self.draft.payload.get("description") if self.draft else None
                async with asyncio.timeout(60):
                    proposal = await self.cloud.reason(
                        text,
                        explicit=True,
                        description=original,
                        registry=getattr(self.operations, "registry", None),
                    )
                if generation != self.generation_id:
                    return
                self.proposal = {
                    "actor_id": self.user["id"],
                    "session_id": self.session_id,
                    "expires": self.clock() + self.config.confirmation_seconds,
                    "draft_id": self.draft.id if self.draft else None,
                    "revision": self.draft.revision if self.draft else None,
                    "original": original,
                    "proposal": proposal.model_dump(),
                }
                self.publish("proposal", self.proposal)
                await self.say(
                    proposal.explanation
                    + (
                        " Decí aplicar propuesta para revisar la nueva descripción."
                        if proposal.kind == "rewrite"
                        else " Decí aplicar plan para revisar sus pasos; una escritura requiere otra confirmación."
                        if proposal.kind == "plan"
                        else ""
                    ),
                    arm_idle=True,
                    generation=generation,
                )
            except Exception:
                await self.say(
                    "El razonamiento remoto no está disponible. Podemos seguir con los tickets.",
                    arm_idle=True,
                )
            return
        if n == "aplicar plan" and getattr(self, "proposal", None):
            p = self.proposal
            if (
                not self.user
                or p["actor_id"] != self.user["id"]
                or p["session_id"] != self.session_id
                or p["expires"] <= self.clock()
                or p["proposal"]["kind"] != "plan"
                or (p["draft_id"], p["revision"])
                != (
                    self.draft.id if self.draft else None,
                    self.draft.revision if self.draft else None,
                )
            ):
                self.proposal = None
                await self.say("El plan cambió o venció. Pedime uno nuevo.", arm_idle=True)
                return
            self.proposal = None
            try:
                async with asyncio.timeout(60):
                    for step in p["proposal"]["steps"]:
                        tool = self.operations.registry.validate(step["tool_id"], step["arguments"])
                        if (
                            tool.name not in self.profile["tools"]
                            or self.user["role"] not in tool.roles
                        ):
                            raise RuntimeError("plan_permission_denied")
                        if generation != self.generation_id:
                            return
                        if tool.effect == "remote_write":
                            resource = step["resource"]
                            if (tool.name == "tickets.create.v1" and resource != "tickets") or (
                                tool.name != "tickets.create.v1"
                                and not re.fullmatch(r"tickets/[1-9][0-9]*", resource or "")
                            ):
                                raise RuntimeError("plan_resource_identity_invalid")
                            if resource != "tickets":
                                current = await self.tickets.observe(resource)
                                if generation != self.generation_id:
                                    return
                                if current["version"] != step["arguments"].get("version"):
                                    raise RuntimeError("plan_version_changed")
                            self.draft = Draft(
                                self.user["id"],
                                tool=tool.name,
                                resource=resource,
                                payload=step["arguments"],
                            )
                            await self.review()
                            return
                        await self.tool(tool.name, step["arguments"])
                await self.say("Completé las consultas del plan.", arm_idle=True)
            except Exception:
                if generation == self.generation_id:
                    await self.say(
                        "El plan se detuvo. Revisá el resultado y los datos antes de seguir.",
                        arm_idle=True,
                    )
            return
        if n == "aplicar propuesta" and getattr(self, "proposal", None):
            p = self.proposal
            if (
                self.draft
                and self.user
                and p["session_id"] == self.session_id
                and p["expires"] > self.clock()
                and (p["actor_id"], p["draft_id"], p["revision"])
                == (self.user["id"], self.draft.id, self.draft.revision)
                and p["proposal"]["kind"] == "rewrite"
            ):
                self.draft.change(description=p["proposal"]["description"])
                self.confirmation = None
                self.proposal = None
                await self.review()
            else:
                await self.say(
                    "La propuesta ya no corresponde al borrador vigente. Conservé tus datos.",
                    arm_idle=True,
                )
            return
        if terminal_ticket_request(n):
            if await self.resource_command(n):
                return
        if self.state == State.WAITING_CONFIRMATION:
            # An unknown qualifier is neither consent nor incident dictation.
            # Keep the original review and expiry; explicit edits were handled
            # by the context-aware interpreter before conversational commands.
            if hasattr(self, "conversation_agent"):
                await self.conversation_agent.run(text)
            else:
                await self.route_turn(text)
            return
        # Explicit resource commands are handled only outside free dictation.
        if (
            n == "revisar cambio"
            and getattr(self, "conflicting_version", None)
            and self.draft
            and getattr(self, "conflicting_draft_id", None) == self.draft.id
        ):
            self.draft.change(version=self.conflicting_version)
            self.conflicting_version = None
            await self.review()
            return
        if hasattr(self, "conversation_agent"):
            await self.conversation_agent.run(text)
            return
        if self.state in {State.INVITING, State.WAITING_INITIAL_INPUT, State.CLOSING}:
            if await self.resource_command(text):
                return
        await self.route_turn(text)

    async def route_turn(self, text):
        """Unknown speech is never implicit dictation or write authorization."""
        if self.state in {State.EXECUTING, State.RECONCILING}:
            await self.say(self.conversation_context())
            return
        generation, actor, session = self.generation_id, self.user["id"], self.session_id
        draft_context = (self.draft.id, self.draft.revision) if self.draft else None
        collections = {
            "origin_unit_id": "org_units",
            "destination_unit_id": "org_units",
            "problem_type_id": "problem_types",
        }
        owned = bool(self.draft and self.draft.owner == "agent" and not self.draft.transferred)
        answers_catalogue = bool(
            owned
            and self.missing in collections
            and catalogue_answer(
                text,
                self.catalogs[collections[self.missing]],
                self.profile["aliases_data"].get(self.missing, {}),
            )
        )
        if answers_catalogue:
            # A requested catalogue name needs no model to be understood.
            is_data = True
        elif self.interpreter:
            meaning = await self.interpreter.classify(
                text,
                field=self.missing,
                has_draft=bool(
                    self.draft and self.draft.owner == "agent" and not self.draft.transferred
                ),
                draft=self.draft.payload if owned else None,
            )
            if (
                generation != self.generation_id
                or session != self.session_id
                or not self.user
                or actor != self.user["id"]
                or draft_context != ((self.draft.id, self.draft.revision) if self.draft else None)
            ):
                return
            self.publish(
                "turn_interpreted",
                {"intent": meaning.intent, "engine": self.config.conversation_model},
            )
            if meaning.intent in {"repair_request", "append_request", "feedback"}:
                if owned and self.draft.tool in {"tickets.create.v1", "tickets.update.v1"}:
                    self.confirmation = None
                    self.replacing_description = meaning.intent != "append_request"
                    if meaning.intent in {"repair_request", "append_request"} and meaning.content:
                        self.missing = None
                        prefix = (
                            "Agregá: "
                            if meaning.intent == "append_request"
                            else "Corregí la descripción: "
                        )
                        await self.collect(prefix + meaning.content)
                    else:
                        self.missing = "description"
                        self.set_state(State.ASKING_MISSING_FIELD)
                        await self.say(
                            "La descripción no quedó como querías. Contame de nuevo quién lo solicita "
                            "y qué necesita; voy a reemplazarla antes de revisar el pedido.",
                            arm_idle=True,
                        )
                else:
                    await self.say(
                        "Decime qué entendí mal y qué necesitás que escriba.", arm_idle=True
                    )
                return
            if self.state == State.WAITING_CONFIRMATION and meaning.intent in {
                Intent.CREATE,
                Intent.END,
                Intent.PAUSE,
                Intent.RESUME,
                Intent.HANDOFF,
            }:
                await self.say(
                    "Conservé la revisión y no envié el pedido. Podés decir confirmo, corregí y el dato, o finalizar la conversación.",
                    arm_idle=True,
                )
                return
            if meaning.intent == Intent.CREATE:
                if self.draft:
                    # A model hypothesis must not replace the request already in progress.
                    await self.say(
                        "Conservé el pedido actual. Para empezar otro, decí quiero registrar un nuevo ticket.",
                        arm_idle=True,
                    )
                else:
                    # Opening a draft writes nothing: review and confirmation still follow.
                    self.invalidate()
                    await self.start_request(meaning.content)
                return
            if meaning.intent not in {"incident", "field_data", "clarify"}:
                await self.converse(Intent(meaning.intent))
                return
            is_data = meaning.intent in {"incident", "field_data"}
        else:
            # Without a semantic engine only an exact requested catalogue answer
            # is acceptable. Unrecognized prose cannot silently become a ticket.
            is_data = False
        if is_data and not self.draft:
            if self.user["role"] not in {"admin", "operator"}:
                await self.say(
                    "Para registrar este problema necesitás una cuenta operadora. Podés consultar tickets.",
                    arm_idle=True,
                )
                return
            self.pending_request = {
                "text": text,
                "actor": actor,
                "session": session,
                "expires": self.clock() + self.config.confirmation_seconds,
            }
            self.publish("state", self.snapshot())
            await self.say(
                "Entendí que me contás un problema de trabajo. ¿Querés que abra un nuevo ticket con eso?",
                arm_idle=True,
            )
        elif (
            is_data
            and self.draft
            and self.draft.owner == "agent"
            and not self.draft.transferred
            and self.state != State.WAITING_CONFIRMATION
        ):
            await self.collect(text)
        elif self.state == State.WAITING_CONFIRMATION:
            await self.say(
                "El borrador sigue igual y no lo envié. Podés confirmarlo, corregirlo o seguir conversando conmigo.",
                arm_idle=True,
            )
        else:
            await self.say(
                "No me quedó claro qué necesitás. Podés pedirme un nuevo ticket, consultar uno por su número o decirme en qué te ayudo.",
                arm_idle=True,
            )

    async def collect(self, text, *, defer_review=False):
        if not self.user:
            await self.auth_invalidated()
            return
        if not self.draft or self.draft.transferred or self.draft.owner != "agent":
            await self.say("Para comenzar un pedido, decime nuevo ticket.", arm_idle=True)
            return
        self.confirmation = None
        self.retry_id = None
        self.set_state(State.COLLECTING_DRAFT)
        d, c = self.draft, self.catalogs
        generation = self.generation_id
        aliases = self.profile["aliases_data"]
        missing = self.missing
        if missing in {"origin_unit_id", "destination_unit_id", "problem_type_id"}:
            rows = c["problem_types" if missing == "problem_type_id" else "org_units"]
            if not catalogue_answer(text, rows, aliases.get(missing, {})):
                # A narrative may answer several fields at once. Keep every fact,
                # rather than throwing away everything except a category word.
                missing = None
        if d.tool in {"tickets.create.v1", "tickets.update.v1"} and normalize(text).startswith(
            "fecha del incidente"
        ):
            from datetime import datetime

            value = re.sub(r"^fecha del incidente\s*:?\s*", "", text, flags=re.I).strip()
            try:
                date = datetime.fromisoformat(value)
                if date.tzinfo is None:
                    raise ValueError("timezone_missing")
                d.change(occurred_at=date.isoformat())
                self.db.save_draft(d)
                for key in [
                    "origin_unit_id",
                    "destination_unit_id",
                    "problem_type_id",
                    "description",
                ]:
                    if not d.payload.get(key) or (
                        key == "description" and len(d.payload[key]) < 10
                    ):
                        await self.ask_missing(key)
                        return
                await self.review()
            except ValueError:
                await self.say(
                    "Necesito una fecha y hora inequívoca con zona, por ejemplo 2026-10-03T14:30:00-03:00. También podés elegirla en el formulario manual.",
                    arm_idle=True,
                )
            return
        if missing == "status":
            selected = [
                s["code"]
                for s in c["statuses"]
                if normalize(s["label"]) == normalize(text).strip(" .!?")
            ]
            if len(selected) != 1:
                await self.ask_missing("status")
                return
            context = getattr(self, "status_context", None)
            if (
                context
                and context["draft_id"] == d.id
                and not await self.allowed_status(context["current"], selected[0], context["code"])
            ):
                return
            d.change(status=selected[0])
            self.db.save_draft(d)
            await self.ask_missing("note")
            return
        elif missing in {"origin_unit_id", "destination_unit_id", "problem_type_id"}:
            rows = c["problem_types" if missing == "problem_type_id" else "org_units"]
            if missing == "destination_unit_id":
                rows = [r for r in rows if r["can_receive_tickets"]]
            selected = await resolve(text, rows, aliases.get(missing, {}), self.tev, missing)
            if generation != self.generation_id or self.draft is not d or not self.user:
                return
            if selected:
                d.change(**{missing: selected})
                if missing == "origin_unit_id":
                    self.unmatched_origin = None
            else:
                await self.ask_missing(missing)
                return
        elif d.tool in {"tickets.create.v1", "tickets.update.v1"}:
            # Literal description is preserved; imperative words inside it remain content.
            field_correction = re.match(
                r"^(?:correg[ií]|cambi[aá])\s+(?:el\s+)?(origen|destino|tipo)\s*(?:a|por|es|:)\s+(.+)",
                text,
                flags=re.I,
            )
            if field_correction:
                field = {
                    "origen": "origin_unit_id",
                    "destino": "destination_unit_id",
                    "tipo": "problem_type_id",
                }[field_correction[1].lower()]
                rows = c["problem_types" if field == "problem_type_id" else "org_units"]
                if field == "destination_unit_id":
                    rows = [row for row in rows if row["can_receive_tickets"]]
                selected = await resolve(
                    field_correction[2], rows, aliases.get(field, {}), self.tev, field
                )
                if generation != self.generation_id or self.draft is not d:
                    return
                if not selected:
                    await self.ask_missing(field)
                    return
                d.change(**{field: selected})
                self.db.save_draft(d)
                await self.resume_draft()
                return
            correction = re.match(
                r"^(?:corrige|correg[ií]|cambi[aá])(?: la descripci[oó]n)?\s*[.,:;]?\s*(.*)|^descripci[oó]n\s*[.,:;]?\s*(.*)",
                text,
                flags=re.I,
            )
            desc = (
                next((group for group in correction.groups() if group), text)
                if correction
                else text
            )
            addition = re.match(
                r"^(?:s[ií][, ]+pero\s+)?agreg[aá]\s*[:,]?\s*(.+)", text, flags=re.I
            )
            if addition:
                desc = addition[1]
            previous = d.payload.get("description", "")
            context = None
            if hasattr(self.interpreter, "incident_context"):
                try:
                    context = await self.interpreter.incident_context(desc)
                except (httpx.HTTPError, ValueError, KeyError, TypeError, RuntimeError):
                    if generation != self.generation_id or self.draft is not d or not self.user:
                        return
                    await self.say(
                        "No pude interpretar los datos del pedido. Conservé el borrador; repetí el dato que querés cambiar.",
                        arm_idle=True,
                    )
                    return
                if generation != self.generation_id or self.draft is not d or not self.user:
                    return
            d.change(
                description=desc
                if correction
                or self.replacing_description
                or not previous
                or d.tool == "tickets.update.v1"
                else previous + " " + desc
            )
            self.replacing_description = False
            if context:
                for field, mention in [
                    ("origin_unit_id", context.origin),
                    ("destination_unit_id", context.destination),
                ]:
                    if not mention:
                        continue
                    rows = c["org_units"]
                    if field == "destination_unit_id":
                        rows = [r for r in rows if r["can_receive_tickets"]]
                    found = matches(mention, rows, aliases.get(field, {}))
                    if len(found) == 1:
                        d.change(**{field: found[0]["id"]})
                        if field == "origin_unit_id":
                            self.unmatched_origin = None
                    else:
                        d.payload.pop(field, None)
                        if field == "origin_unit_id":
                            self.unmatched_origin = {"draft_id": d.id, "text": mention}
            for key, rows in [
                ("origin_unit_id", c["org_units"]),
                ("problem_type_id", c["problem_types"]),
            ]:
                if key == "origin_unit_id" and context:
                    continue
                found = matches(text, rows, aliases.get(key, {}))
                if len(found) == 1:
                    d.change(**{key: found[0]["id"]})
                elif not found and key == "problem_type_id" and not d.payload.get(key):
                    # Classify the incident against real catalogue candidates;
                    # retain the literal transcript, including STT spelling.
                    selected = await resolve(text, rows, aliases.get(key, {}), self.tev, key)
                    if generation != self.generation_id or self.draft is not d or not self.user:
                        return
                    if selected:
                        d.change(**{key: selected})
            if not d.payload.get("destination_unit_id") and c.get("default_destination_unit_id"):
                d.change(destination_unit_id=c["default_destination_unit_id"])
        else:
            key = (
                "note"
                if d.tool == "tickets.status.v1"
                else "reason"
                if d.tool in {"tickets.archive.v1", "tickets.restore.v1"}
                else "description"
            )
            d.change(**{key: text})
        self.missing = None
        self.db.save_draft(d)
        if defer_review:
            return True
        if d.tool == "tickets.create.v1":
            for key in ["origin_unit_id", "destination_unit_id", "problem_type_id", "description"]:
                if not d.payload.get(key) or (key == "description" and len(d.payload[key]) < 10):
                    await self.ask_missing(key)
                    return
        await self.review()

    async def ask_missing(self, key):
        self.missing = key
        self.set_state(State.ASKING_MISSING_FIELD)
        question = {
            "origin_unit_id": "¿De qué oficina, área o municipio viene el pedido?",
            "destination_unit_id": "¿Qué equipo debe recibir el pedido?",
            "problem_type_id": "¿Qué tipo de problema es?",
            "description": "Decime qué sucede, con los detalles necesarios.",
            "status": "¿A qué estado querés pasar el ticket: nuevo, en curso, en espera, resuelto o cancelado?",
        }.get(key, "¿Cuál es el motivo?")
        if (
            key == "origin_unit_id"
            and self.unmatched_origin
            and self.unmatched_origin["draft_id"] == self.draft.id
        ):
            question = (
                "Escuché que el pedido viene de "
                + self.unmatched_origin["text"]
                + ", pero esa oficina no figura en el catálogo. ¿A qué área registrada corresponde?"
            )
        await self.say(question, arm_idle=True)

    async def review(self):
        if not self.draft or not self.user:
            return
        self.set_state(State.REVIEWING_DRAFT)
        self.confirmation = Confirmation.issue(
            self.draft, self.clock, self.config.confirmation_seconds, self.session_id
        )
        self.db.save_draft(self.draft)
        self.set_state(State.WAITING_CONFIRMATION)
        await self.say(review(self.draft, self.catalogs), arm_idle=True)
        if (
            self.browser
            and not self.browser.human_control
            and self.draft.tool == "tickets.create.v1"
        ):
            try:
                evidence = await self.browser.prepare({"draft": self.draft})
                self.publish("browser_evidence", evidence)
            except Exception as exc:
                self.publish("browser_error", {"code": str(exc)[:150]})

    async def commit(self):
        d, confirmation = self.draft, self.confirmation
        if (
            not d
            or not confirmation
            or not self.user
            or not confirmation.valid(d, self.user["id"], self.clock, self.session_id)
        ):
            self.confirmation = None
            await self.say("La revisión venció o cambió. Voy a revisarla de nuevo.")
            await self.review()
            return
        generation = self.generation_id
        try:
            if getattr(self, "retry_id", None):
                previous = next(
                    row
                    for row in self.db.operations(d.actor_id)
                    if row["operation_id"] == self.retry_id
                )
                row = self.operations.prepare_retry(self.session_id, previous, d, confirmation)
            else:
                row = self.operations.prepare(self.session_id, d, confirmation, self.profile)
            self.set_state(State.EXECUTING)
            task = asyncio.create_task(self.execute_operation(row, d, confirmation, generation))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        except Exception as exc:
            if str(exc) == "reconciliation_required":
                self.set_state(State.RECONCILING)
                await self.say("Hay un intento pendiente. Primero voy a comprobar su resultado.")
            else:
                self.confirmation = None
                self.set_state(State.COLLECTING_DRAFT)
                await self.report_failure(exc, generation=generation)

    async def execute_operation(self, row, draft, confirmation, generation):
        try:
            receipt = await self.operations.dispatch(
                row,
                draft,
                confirmation,
                lambda: (
                    generation == self.generation_id
                    and self.user
                    and self.user["id"] == draft.actor_id
                    and self.state == State.EXECUTING
                    and self.draft is draft
                    and self.confirmation is confirmation
                ),
            )
            draft.owner = "completed"
            self.db.save_draft(draft)
            if not self.user or self.user["id"] != draft.actor_id:
                return
            self.last_receipt = receipt
            self.publish(
                "receipt", receipt
            )  # Durable fact may be reported even after interruption.
            if generation != self.generation_id:
                if self.draft is draft:
                    self.draft = None
                return
            self.confirmation = None
            self.retry_id = None
            draft.owner = "completed"
            self.db.save_draft(draft)
            self.draft = None
            self.set_state(State.CLOSING)
            code = spoken_code(receipt["code"])
            action = {
                "tickets.create.v1": "Guardé",
                "tickets.update.v1": "Actualicé",
                "tickets.status.v1": "Cambié el estado del",
                "tickets.archive.v1": "Oculté",
                "tickets.restore.v1": "Restauré",
            }[draft.tool]
            if draft.tool == "tickets.status.v1":
                if draft.payload.get("status") == "resolved":
                    action = "Marqué como resuelto"
                elif draft.payload.get("status") == "cancelled":
                    action = "Cancelé"
            article = "ticket" if action.endswith("del") else "el ticket"
            await self.say(
                f"{action} {article} {code}. Cuando necesites otro pedido, llamame de nuevo.",
                generation=generation,
            )
            if self.browser and not self.browser.human_control:
                try:
                    await self.browser.show(
                        None if draft.tool == "tickets.archive.v1" else receipt["ticket_id"]
                    )
                except Exception:
                    self.publish("browser_error", {"code": "receipt_committed_surface_unavailable"})
        except TicketError as exc:
            if generation != self.generation_id:
                return
            self.confirmation = None
            if exc.status == 401:
                await self.auth_invalidated()
            elif exc.status == 409:
                self.set_state(State.COLLECTING_DRAFT)
                if draft.resource != "tickets":
                    try:
                        latest = await self.tickets.observe(draft.resource)
                        if generation != self.generation_id or self.draft is not draft:
                            return
                        self.publish(
                            "version_conflict",
                            {
                                "current_version": latest["version"],
                                "expected_version": draft.payload.get("version"),
                            },
                        )
                        self.conflicting_version = latest["version"]
                        self.conflicting_draft_id = draft.id
                        await self.say(
                            "El ticket cambió. Leí la versión actual. Decí revisar cambio para revisar tus datos sobre esa versión; todavía no lo envié.",
                            generation=generation,
                        )
                    except TicketError:
                        await self.say(
                            "El ticket cambió y no pude leerlo con tus permisos actuales. Conservé el cambio sin enviar.",
                            generation=generation,
                        )
                else:
                    await self.say(
                        "La identidad del intento entró en conflicto. Conservé el borrador sin otro envío.",
                        generation=generation,
                    )
            else:
                self.set_state(State.RECONCILING if exc.status >= 500 else State.COLLECTING_DRAFT)
                if exc.status >= 500:
                    self.publish("operation_error", {"code": ErrorCode.UNKNOWN})
                    await self.say(MESSAGES[ErrorCode.UNKNOWN], generation=generation)
                else:
                    await self.report_failure(exc, generation=generation)
        except Exception as exc:
            if generation != self.generation_id:
                return
            self.confirmation = None
            self.set_state(State.RECONCILING)
            self.publish("operation_error", {"code": str(exc)[:100]})
            if generation == self.generation_id:
                await self.say(
                    "No tengo un resultado confirmado. Voy a comprobar el recibo; no voy a crear otro ticket."
                )

    async def reconcile(self):
        if not self.user:
            await self.auth_invalidated()
            return
        if any(not task.done() for task in self.tasks):
            await self.say(
                "La operación todavía está en curso. Espero su comprobante antes de informar el resultado."
            )
            return
        generation, actor, draft = self.generation_id, self.user["id"], self.draft
        results = await self.operations.recover(actor)
        if generation != self.generation_id or not self.user or self.user["id"] != actor:
            return
        unresolved = any(r.get("status") == "outcome_unknown" for r in results)
        self.publish("recovery", {"operations": results})
        if unresolved:
            self.set_state(State.RECONCILING)
            await self.say(
                "El resultado sigue pendiente. Conservé la identidad del intento y no envié otro."
            )
            return
        receipts = [r for r in results if r.get("code")]
        if draft:
            # An older receipt is not proof that the CURRENT pending request
            # succeeded. Only its bound durable operation can close this draft.
            matching = [
                r
                for r in self.db.operations(actor)
                if r["draft_id"] == draft.id
                and r["payload_hash"] == draft.digest
                and r["status"] == "succeeded"
                and r["receipt"]
            ]
            receipts = [json.loads(r["receipt"]) for r in matching]
            if not receipts:
                self.confirmation = None
                self.set_state(State.COLLECTING_DRAFT)
                await self.say(
                    "No tengo un comprobante de éxito para este pedido. Conservé el borrador sin otro envío. Decí retomar para revisarlo.",
                    arm_idle=True,
                )
                return
        if receipts:
            self.last_receipt = receipts[-1]
        if self.last_receipt:
            await self.say(
                "La operación quedó guardada en el ticket "
                + spoken_code(self.last_receipt["code"])
                + "."
            )
            if self.draft:
                self.draft.owner = "completed"
                self.db.save_draft(self.draft)
            self.draft = None
        self.set_state(State.DORMANT)

    async def repeat(self, *, code_only=False):
        if not code_only and self.draft and not self.draft.transferred:
            if self.state == State.WAITING_CONFIRMATION:
                if not self.confirmation or not self.confirmation.valid(
                    self.draft, self.user["id"], self.clock, self.session_id
                ):
                    await self.resume_draft()
                else:
                    await self.say(review(self.draft, self.catalogs), arm_idle=True)
            else:
                await self.say(self.conversation_context(), arm_idle=True)
            return
        if (
            not code_only
            and self.last_speech
            and self.state
            in {
                State.ASKING_MISSING_FIELD,
                State.REVIEWING_DRAFT,
                State.WAITING_CONFIRMATION,
                State.COLLECTING_DRAFT,
                State.WAITING_INITIAL_INPUT,
            }
        ):
            await self.say(self.last_speech["text"], arm_idle=True)
        elif self.last_receipt:
            await self.say(
                "El código es " + spoken_code(self.last_receipt["code"]) + ".", arm_idle=True
            )
        elif self.last_speech:
            await self.say(self.last_speech["text"], arm_idle=True)

    def ensure_reset_allowed(self):
        if self.resetting:
            raise ValueError("La conversación ya se está limpiando.")
        if self.state in {State.EXECUTING, State.RECONCILING} or (
            self.user and self.db.operations(self.user["id"], nonterminal=True)
        ):
            raise ValueError(
                "Esperá a que termine de guardarse o comprobarse el ticket para borrar la conversación."
            )

    async def reset_conversation(self, close_audio=None):
        self.ensure_reset_allowed()
        self.resetting = True
        blocked = self.state == State.BLOCKED
        self.invalidate()
        self.cancel_idle()
        actor = self.user["id"] if self.user else None
        session, generation = self.session_id, self.generation_id
        try:
            if self.stop_callback:
                await self.stop_callback()
            if close_audio:
                await close_audio()
            if (
                actor != (self.user["id"] if self.user else None)
                or session != self.session_id
                or generation != self.generation_id
            ):
                raise ValueError(
                    "La sesión cambió mientras se limpiaba el audio. Volvé a borrar la conversación desde la cuenta actual."
                )
            self.db.clear_conversation(actor, session)
            self.session_id = str(uuid4())
            self.draft = self.confirmation = self.pending_question = self.pending_request = None
            self.last_speech = self.last_receipt = self.playing = self.interrupted = None
            self.speech_candidate_at = self.candidate_grace_deadline = self.missing = None
            self.proposal = self.unmatched_origin = None
            self.retry_id = None
            self.conflicting_version = self.conflicting_draft_id = self.status_context = None
            self.replacing_description = False
            self.errors.clear()
            self.bus.clear()
            self.state = (
                State.BLOCKED if blocked else State.DORMANT if self.user else State.AUTH_REQUIRED
            )
            self.publish("conversation_reset", self.snapshot())
            self.publish("state", self.snapshot())
        finally:
            self.resetting = False

    async def pause(self):
        self.pending_request = None
        self.invalidate()
        self.confirmation = None
        self.cancel_idle()
        if self.stop_callback:
            await self.stop_callback()
        if self.draft:
            self.db.save_draft(self.draft)
        if self.state in {State.EXECUTING, State.RECONCILING}:
            self.set_state(State.RECONCILING)
            await self.say(
                "Pausé la conversación. El intento enviado se comprobará antes de cualquier otro."
            )
        else:
            self.set_state(State.PAUSED)
            await self.say(
                "Pausé la conversación. "
                + ("Conservé el borrador sin enviarlo. " if self.draft else "")
                + "Cuando estés listo, decí: Gianna, seguimos."
            )

    def conversation_context(self):
        if self.state == State.EXECUTING:
            return "Estoy procesando el pedido confirmado. Te aviso cuando tenga el resultado."
        if self.state == State.RECONCILING:
            return "Estoy comprobando el resultado del intento anterior. Todavía no tengo un resultado confirmado."
        if self.draft and (self.draft.transferred or self.draft.owner == "human"):
            return "El formulario está bajo tu control manual. Podés terminarlo allí o pedirme otra consulta."
        if self.draft:
            if self.state == State.WAITING_CONFIRMATION:
                return "El cambio está preparado y todavía no lo envié. Decime si querés guardarlo ahora; también podés corregir los datos."
            missing = self.missing or missing_field(self.draft)
            if missing:
                return "Conservé lo que me contaste. " + FIELD_PROMPTS[missing]
            return "Hay un borrador sin enviar. Decí retomar para revisarlo antes de confirmar."
        if self.user and self.user["role"] == "viewer":
            return (
                "¿En qué te puedo ayudar? Podés buscar tickets, leerlos o consultar su historial."
            )
        return "¿En qué te puedo ayudar? Podés registrar un pedido, consultar un ticket o cambiar su estado."

    async def no_review(self):
        if self.state in {State.DORMANT, State.PAUSED, State.CLOSING}:
            self.set_state(State.INVITING)
        if self.state in {State.EXECUTING, State.RECONCILING}:
            await self.say(self.conversation_context())
        elif not self.draft and self.last_receipt:
            await self.say(
                "La última operación ya quedó guardada en el ticket "
                + spoken_code(self.last_receipt["code"])
                + ". No hay otra revisión pendiente. "
                + self.conversation_context(),
                arm_idle=True,
            )
        else:
            await self.say(
                "Todavía no hay una revisión lista para confirmar. " + self.conversation_context(),
                arm_idle=True,
            )

    async def start_request(self, content="", *, prepared=None, unknown_origin=None):
        self.pending_request = None
        if self.state in {State.EXECUTING, State.RECONCILING}:
            await self.say(self.conversation_context())
            return
        if self.user["role"] not in {"operator", "admin"}:
            await self.say(
                "Tu cuenta permite consultar tickets. Para registrar un pedido necesitás una cuenta operadora o administradora.",
                arm_idle=True,
            )
            return
        if self.draft and self.draft.owner == "agent" and not self.draft.transferred:
            if not any(
                key != "destination_unit_id" and value for key, value in self.draft.payload.items()
            ):
                self.draft.owner = "discarded"
            self.db.save_draft(self.draft)
            self.publish("draft_saved", {"draft_id": self.draft.id, "reason": "new_create_request"})
        self.confirmation = self.missing = None
        self.replacing_description = False
        self.unmatched_origin = None
        self.draft = Draft(self.user["id"])
        if self.catalogs.get("default_destination_unit_id"):
            self.draft.change(destination_unit_id=self.catalogs["default_destination_unit_id"])
        self.db.save_draft(self.draft)
        if prepared is not None:
            self.draft.change(**prepared)
            if unknown_origin and not prepared.get("origin_unit_id"):
                self.unmatched_origin = {"draft_id": self.draft.id, "text": unknown_origin}
            self.db.save_draft(self.draft)
            await self.resume_draft()
        elif content:
            await self.collect(content)
        else:
            await self.ask_missing("description")

    async def discard_draft(self):
        if self.state in {State.EXECUTING, State.RECONCILING}:
            await self.say(self.conversation_context())
            return
        self.invalidate()
        self.cancel_idle()
        self.pending_request = None
        if self.draft and self.draft.owner == "agent" and not self.draft.transferred:
            self.draft.owner = "discarded"
            self.db.save_draft(self.draft)
            self.draft = self.confirmation = self.missing = None
            self.set_state(State.INVITING)
            await self.say("Descarté el borrador. ¿En qué más te puedo ayudar?", arm_idle=True)
        else:
            await self.say(
                "No hay un borrador a mi cargo para descartar. " + self.conversation_context(),
                arm_idle=True,
            )

    async def resume_draft(self):
        if not self.draft and self.user:
            self.draft = next(
                (
                    d
                    for d in self.db.load_drafts(self.user["id"])
                    if d.owner == "agent" and not d.transferred
                ),
                None,
            )
        if not self.draft:
            self.set_state(State.INVITING)
            await self.say("Seguimos. " + self.conversation_context(), arm_idle=True)
        elif self.draft.transferred or self.draft.owner != "agent":
            await self.say(self.conversation_context(), arm_idle=True)
        elif getattr(self, "conflicting_draft_id", None) == self.draft.id and getattr(
            self, "conflicting_version", None
        ):
            await self.say(
                "El ticket cambió mientras trabajábamos. Decí revisar cambio para revisar los datos sobre la versión actual.",
                arm_idle=True,
            )
        elif missing := missing_field(self.draft):
            await self.ask_missing(missing)
        else:
            self.missing = None
            await self.review()

    async def end_conversation(self):
        self.pending_request = None
        if self.state in {State.EXECUTING, State.RECONCILING}:
            await self.pause()
            return
        self.confirmation = None
        self.cancel_idle()
        if self.draft:
            self.db.save_draft(self.draft)
        self.set_state(State.DORMANT)
        await self.say(
            "Hasta luego. "
            + (
                "Conservé el borrador sin enviarlo. "
                if self.draft and not self.draft.transferred
                else ""
            )
            + "Cuando necesites algo, llamame."
        )

    async def converse(self, intent):
        """Conversation changes no ticket payload and grants no write permission."""
        self.publish("conversation_intent", {"intent": intent.value})
        if not self.user:
            self.set_state(State.AUTH_REQUIRED)
            await self.say("Sí, estoy acá. Para trabajar con tickets, iniciá sesión en el sistema.")
            return
        busy = self.state in {State.EXECUTING, State.RECONCILING}
        if intent == Intent.END:
            await self.end_conversation()
            return
        if intent == Intent.PAUSE:
            await self.pause()
            return
        if intent in {Intent.RESUME, Intent.RESUME_PREVIOUS}:
            if busy:
                await self.say(self.conversation_context())
            else:
                if intent == Intent.RESUME_PREVIOUS:
                    previous = next(
                        (
                            d
                            for d in self.db.load_drafts(self.user["id"])
                            if d.owner == "agent"
                            and not d.transferred
                            and (not self.draft or d.id != self.draft.id)
                        ),
                        None,
                    )
                    if not previous:
                        await self.say(
                            "No hay otro borrador pendiente para retomar. "
                            + self.conversation_context(),
                            arm_idle=True,
                        )
                        return
                    if self.draft and self.draft.owner == "agent" and not self.draft.transferred:
                        self.db.save_draft(self.draft)
                    self.draft, self.confirmation = previous, None
                await self.resume_draft()
            return
        if intent == Intent.PROGRESS and self.state == State.RECONCILING:
            await self.reconcile()
            return
        if intent in {Intent.CREATE, Intent.BOARD, Intent.HANDOFF}:
            if busy:
                await self.say(self.conversation_context())
            elif intent == Intent.CREATE:
                await self.start_request()
            elif intent == Intent.BOARD:
                await self.tool("browser.open.v1", {})
                if self.state in {State.DORMANT, State.PAUSED, State.CLOSING}:
                    self.set_state(State.INVITING)
                await self.say("Abrí el tablero. " + self.conversation_context(), arm_idle=True)
            elif self.draft:
                await self.handoff()
            else:
                await self.say(
                    "Todavía no hay un borrador para pasar al formulario manual. Podés abrir el tablero o contarme el pedido.",
                    arm_idle=True,
                )
            return
        if self.state in {State.DORMANT, State.PAUSED, State.CLOSING} and not busy:
            if self.draft and not self.draft.transferred and self.draft.owner == "agent":
                self.missing = missing_field(self.draft)
                self.set_state(
                    State.ASKING_MISSING_FIELD if self.missing else State.COLLECTING_DRAFT
                )
            else:
                self.set_state(State.INVITING)
        if intent == Intent.REPEAT:
            if busy:
                await self.say(self.conversation_context())
            elif not self.last_speech:
                await self.say(self.conversation_context(), arm_idle=True)
            else:
                await self.repeat()
            return
        if intent == Intent.SLOWER:
            self.voice_speed = 0.85
            prefs = self.db.preferences(self.user["id"])
            prefs["speed"] = self.voice_speed
            self.db.save_preferences(self.user["id"], prefs)
            self.publish("state", self.snapshot())
        context = self.conversation_context()
        if intent == Intent.HELP:
            tools = set(self.profile["tools"])
            options = []
            if "tickets.create.v1" in tools and self.user["role"] in {"operator", "admin"}:
                options.append("registrar pedidos")
            if "tickets.search.v1" in tools:
                options.append("buscar y leer tickets")
            if "tickets.history.v1" in tools:
                options.append("consultar su historial")
            if "tickets.status.v1" in tools and self.user["role"] in {"operator", "admin"}:
                options.append("cambiar su estado, incluso marcarlos como resueltos")
            text = (
                ("Puedo " + ", ".join(options) + ". " if options else "Podemos conversar. ")
                + "Decime el número para trabajar con un ticket existente. Podés pedirme que repita, esperar, retomar o terminar la conversación. "
                + context
            )
        elif intent == Intent.PROGRESS:
            if self.draft or busy:
                text = context
            elif self.last_receipt:
                text = (
                    "La última operación quedó guardada en el ticket "
                    + spoken_code(self.last_receipt["code"])
                    + ". "
                    + context
                )
            else:
                text = "Todavía no envié ningún pedido en esta conversación. " + context
        elif intent == Intent.FINISH:
            if not self.draft and not busy:
                await self.end_conversation()
                return
            text = (
                "¿Querés terminar la conversación o completar el pedido? Decí terminar la conversación para dejarlo guardado sin enviar, o retomar para revisarlo. Para resolver un ticket existente, necesito su número. "
                + context
            )
        else:
            opening = {
                Intent.PRESENCE: "Sí, estoy acá y te escucho.",
                Intent.GREETING: "Hola, acá estoy.",
                Intent.WELLBEING: "Todo bien, gracias. Estoy lista para ayudarte.",
                Intent.THANKS: "De nada, con gusto.",
                Intent.APOLOGY: "No pasa nada. Podemos corregirlo juntos; decime qué querés cambiar.",
                Intent.NEXT: "Vamos paso a paso.",
                Intent.SLOWER: "Claro, voy a hablar más despacio.",
                Intent.ACK: "Bien, seguimos cuando quieras.",
            }[intent]
            text = opening + " " + context
        await self.say(text, arm_idle=not busy)

    async def handoff(self):
        self.invalidate()
        if not self.draft or not self.user:
            return
        self.invalidate()
        self.confirmation = None
        self.cancel_idle()
        try:
            result = await self.operations.handoff(self.draft)
            if result.get("committed"):
                self.last_receipt = result["committed"]
                await self.browser.show(self.last_receipt["ticket_id"])
                await self.say("La operación ya quedó guardada. Abrí el ticket existente.")
            else:
                await self.browser.handoff(self.draft)
                self.publish("handoff", {"draft_id": self.draft.id, "transferred": True})
                await self.say(
                    "Te dejé un formulario manual nuevo con el borrador. Ahora vos tenés el control."
                )
            self.set_state(State.PAUSED)
        except Exception as exc:
            self.set_state(State.RECONCILING)
            self.publish("handoff_error", {"code": str(exc)[:100]})
            await self.say(
                "Primero necesito comprobar el intento pendiente. El formulario de vista previa sigue bloqueado."
            )

    async def allowed_status(self, current, target, code):
        metadata = next((s for s in self.catalogs["statuses"] if s["code"] == current), None)
        labels = {s["code"]: s["label"] for s in self.catalogs["statuses"]}
        if current == target:
            await self.say(
                f"Ese ticket ya está {labels.get(current, current)}. No hace falta repetir el cambio.",
                arm_idle=True,
            )
            return False
        if metadata and "transitions" in metadata and target not in metadata["transitions"]:
            options = ", ".join(labels[s] for s in metadata["transitions"])
            text = f"Ese ticket está {labels[current]} y no puede pasar directamente a {labels.get(target, target)}. Puede pasar a {options}."
            if current == "new" and target == "resolved":
                text += f" Para resolverlo, primero decí: pasá el ticket número {code} a En curso. Después pedime finalizarlo."
            await self.say(text, arm_idle=True)
            return False
        return True

    async def resource_command(self, text, *, review_only=False, prepared_text=None):
        if not self.user:
            return False
        generation, actor = self.generation_id, self.user["id"]
        n = normalize(text).strip(" .,!¿?¡")
        n = re.sub(r"^hola\s*[, ]+", "", n).strip()
        n = re.sub(
            r"^\s*(?:por favor\s*)?(?:(?:quiero|necesito|podes|puedes) (?:que\s+)?(?:me\s+)?)?",
            "",
            n,
        ).strip(" ,")
        if re.match(
            r"^(?:abre|abri|abrir|mostra|edita|guarda)\b.*\b(?:word|excel|archivo|carpeta|documento)\b",
            n,
        ):
            await self.say(
                "No tengo instalado un adaptador para esa aplicación o archivo. Puedo ayudarte con tickets.",
                arm_idle=True,
            )
            return True
        if re.match(r"^(?:busca|buscame|buscar|filtra)\b", n):
            q = re.sub(
                r"^(?:busca|buscame|buscar|filtra)\s+(?:los\s+)?(?:tickets?\s+)?(?:que contengan\s+)?(?:con\s+)?(?:la palabra\s+|el texto\s+)?(?:de\s+)?",
                "",
                n,
            ).strip()
            marker = re.search(r"\b(?:la palabra|el texto)\s+(.+)$", n)
            if marker:
                q = marker[1].strip()
            rows = await self.tool("tickets.search.v1", {"q": q[:160]})
            await self.tool("browser.filter.v1", {"query": q[:160]})
            await self.say(f"Encontré {rows['total']} tickets con ese filtro.", arm_idle=True)
            return True
        code = ticket_number(n)
        verbs = {
            "archive": r"^(archiva|archivar|oculta|ocultar)\b",
            "restore": r"^(restaura|restaurar)\b",
            "read": r"^(lee|leeme|mostra|mostrame|muestra|muestrame|abre|abri)\b",
            "history": r"^(historial|historia)\b",
            "status": r"^(pasa|cambia|pone|pon|marca|marcar|finaliza|finalizar|termina|terminar|cerra|cierra|cerrar|resuelve|resolve|resolver|soluciona|cancela|cancelar)\b",
            "update": r"^(edita|editar|corrige|corregi)\b",
        }
        kind = next((k for k, pattern in verbs.items() if re.match(pattern, n)), None)
        if not kind:
            return False
        if kind == "status" and terminal_ticket_request(text) and self.draft:
            if self.draft.owner == "agent" and not self.draft.transferred:
                self.db.save_draft(self.draft)
                self.publish(
                    "draft_saved", {"draft_id": self.draft.id, "reason": "new_resource_request"}
                )
            self.draft = self.confirmation = self.missing = None
            self.set_state(State.INVITING)
        if code is None:
            await self.say(
                "Necesito el código del ticket para identificarlo. Repetí la orden con su número.",
                arm_idle=True,
            )
            return True
        try:
            endpoint = "/api/v1/admin/tickets/archived" if kind == "restore" else "/api/v1/tickets"
            if kind == "restore" and self.user["role"] != "admin":
                await self.say(
                    "Sólo un administrador puede restaurar tickets ocultos.", arm_idle=True
                )
                return True
            search = (
                await self.tickets.request("GET", endpoint, query={"q": f"IDL-TI-{code:06d}"})
                if kind == "restore"
                else await self.tool("tickets.search.v1", {"q": f"IDL-TI-{code:06d}"})
            )
            rows = search["items"]
            if generation != self.generation_id or not self.user or self.user["id"] != actor:
                return True
            if len(rows) != 1:
                await self.say("No encontré un único ticket visible con ese código.", arm_idle=True)
                return True
            ticket = rows[0]
            requested_status = None
            if kind == "status":
                labels = {normalize(s["label"]): s["code"] for s in self.catalogs["statuses"]}
                requested_status = next((v for k, v in labels.items() if k in n), None)
                if not requested_status and re.match(
                    r"^(?:finaliza|finalizar|termina|terminar|cerra|cierra|cerrar|resuelve|resolve|resolver|soluciona)\b",
                    n,
                ):
                    requested_status = "resolved"
                if not requested_status and re.match(r"^(?:cancela|cancelar)\b", n):
                    requested_status = "cancelled"
                if requested_status and not await self.allowed_status(
                    ticket["status"], requested_status, code
                ):
                    return True
            if kind == "read":
                await self.tool("browser.show.v1", {"ticket_id": ticket["id"]})
                await self.say(
                    f"{spoken_code(ticket['code'])}. {ticket['origin']['name']}. {ticket['description']}",
                    arm_idle=True,
                )
                return True
            if kind == "history":
                history = await self.tool("tickets.history.v1", {"ticket_id": ticket["id"]})
                event_names = {
                    "created": "Creado",
                    "updated": "Actualizado",
                    "edited": "Editado",
                    "status_changed": "Cambio de estado",
                    "archived": "Ocultado",
                    "restored": "Restaurado",
                }
                await self.say(
                    ". ".join(
                        event_names.get(e["event_type"], "Cambio registrado")
                        + ": "
                        + (e["note"] or "sin nota")
                        for e in history["items"][:5]
                    ),
                    arm_idle=True,
                )
                return True
            if self.draft and self.draft.owner == "agent" and not self.draft.transferred:
                self.db.save_draft(self.draft)
                self.publish(
                    "draft_saved", {"draft_id": self.draft.id, "reason": "new_resource_request"}
                )
            self.confirmation = None
            self.missing = None
            self.draft = Draft(
                self.user["id"],
                tool=f"tickets.{kind}.v1",
                resource=f"tickets/{ticket['id']}",
                payload={"version": ticket["version"]},
                display_code=ticket["code"],
            )
            if kind == "update":
                self.draft.change(
                    origin_unit_id=ticket["origin"]["id"],
                    destination_unit_id=ticket["destination"]["id"],
                    problem_type_id=ticket["problem_type"]["id"],
                    description=ticket["description"],
                    occurred_at=ticket.get("occurred_at"),
                )
            if kind == "status":
                self.status_context = {
                    "draft_id": self.draft.id,
                    "current": ticket["status"],
                    "code": code,
                }
                target = requested_status
                if not target:
                    await self.ask_missing("status")
                    return True
                self.draft.change(status=target)
                if prepared_text:
                    self.draft.change(note=prepared_text)
                    await self.review()
                    return True
                if target not in {"resolved", "cancelled"} and ticket["status"] not in {
                    "resolved",
                    "cancelled",
                }:
                    if review_only:
                        await self.review()
                        return True
                    # Explicit low-impact order authorizes its exact payload once.
                    self.confirmation = Confirmation.issue(
                        self.draft, self.clock, self.config.confirmation_seconds, self.session_id
                    )
                    await self.commit()
                    return True
            self.set_state(State.COLLECTING_DRAFT)
            if prepared_text:
                key = "reason" if kind in {"archive", "restore"} else "description"
                self.draft.change(**{key: prepared_text})
                await self.review()
                return True
            self.missing = (
                "note"
                if kind == "status"
                else "reason"
                if kind in {"archive", "restore"}
                else "description"
            )
            action = {
                "archive": "ocultar",
                "restore": "restaurar",
                "status": "cambiar el estado",
                "update": "editar",
            }[kind]
            if kind == "status" and self.draft.payload.get("status") == "resolved":
                action = "marcar como resuelto"
            await self.say(
                f"Preparé {action} el ticket {spoken_code(ticket['code'])}. Decime el motivo o la descripción nueva.",
                arm_idle=True,
            )
            return True
        except TicketError as exc:
            await self.report_failure(exc, generation=generation)
            return True

    async def close(self):
        self.cancel_idle()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.operations.close()
