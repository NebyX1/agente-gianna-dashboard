"""Everyday conversation at real dialogue boundaries, without ticket side effects."""

import asyncio
from dataclasses import asdict

import pytest

from gianna.dialogue.conversation import Intent, conversational_intent, terminal_ticket_request
from gianna.dialogue.state_machine import State
from tests.unit.test_dialogue import supervisor as supervisor_fixture
from tests.unit.test_core import Adapter

supervisor = supervisor_fixture


CASES = [
    ("¿Estás ahí?", Intent.PRESENCE),
    ("Hola, ¿estás ahí?", Intent.PRESENCE),
    ("¿Me escuchás?", Intent.PRESENCE),
    ("¿Seguís ahí?", Intent.PRESENCE),
    ("Che, ¿podés escucharme?", Intent.PRESENCE),
    ("¿Estás disponible?", Intent.PRESENCE),
    ("Hola", Intent.GREETING),
    ("Buenas tardes", Intent.GREETING),
    ("Buenos días", Intent.GREETING),
    ("¿Cómo andás?", Intent.WELLBEING),
    ("Hola, ¿todo bien?", Intent.WELLBEING),
    ("¿Qué podés hacer?", Intent.HELP),
    ("¿En qué me podés ayudar?", Intent.HELP),
    ("Explicame las opciones", Intent.HELP),
    ("¿Cómo hago para crear un ticket?", Intent.HELP),
    ("Necesito orientación", Intent.HELP),
    ("Muchas gracias", Intent.THANKS),
    ("Gracias por tu ayuda", Intent.THANKS),
    ("Perdón, me equivoqué", Intent.APOLOGY),
    ("No entendí", Intent.REPEAT),
    ("¿Podés repetirlo, por favor?", Intent.REPEAT),
    ("Hablame más despacio", Intent.SLOWER),
    ("¿Qué te falta?", Intent.NEXT),
    ("¿Qué sigue?", Intent.NEXT),
    ("¿Cómo seguimos?", Intent.NEXT),
    ("¿Ya lo guardaste?", Intent.PROGRESS),
    ("¿Qué estás haciendo?", Intent.PROGRESS),
    ("Esperame un minuto", Intent.PAUSE),
    ("Estoy al teléfono", Intent.PAUSE),
    ("Estoy el teléfono", Intent.PAUSE),
    ("Estoy hablando por teléfono", Intent.PAUSE),
    ("No lo envíes", Intent.PAUSE),
    ("Seguimos", Intent.RESUME),
    ("Ya volví", Intent.RESUME),
    ("Retomemos el borrador", Intent.RESUME),
    ("Gracias, hasta luego", Intent.END),
    ("Finalizá la conversación", Intent.END),
    ("Cerrá esta sesión", Intent.END),
    ("No necesito nada más", Intent.END),
    ("Terminamos por hoy", Intent.END),
    ("Listo", Intent.FINISH),
    ("Finalizá eso", Intent.FINISH),
    ("Repetí la pregunta, por favor", Intent.REPEAT),
    ("Repetí las preguntas por favor", Intent.REPEAT),
    ("¿Podés repetir la revisión?", Intent.REPEAT),
    ("Lo entendí", Intent.ACK),
    ("Perfecto", Intent.ACK),
    ("Dale", Intent.ACK),
]


@pytest.mark.parametrize("text,intent", CASES)
def test_everyday_intents(text, intent):
    assert conversational_intent(text) == intent


@pytest.mark.parametrize(
    "text",
    [
        'Descripción: "¿Estás ahí?" aparece en la pantalla',
        "En Tránsito la impresora dice gracias y no imprime",
        "La aplicación no permite finalizar la operación",
        "El teléfono no me escucha al hablar",
        "La oficina cerró y el pedido sigue pendiente",
        "Corregí la descripción: no necesito nada más",
        "Agregá que el sistema pide ayuda",
        "Motivo: ya está",
        "Nota: gracias por todo",
        "La usuaria dijo chau y se cortó el sistema",
        "Me equivoqué al imprimir y salió todo negro",
        "Finalizá el ticket número 10",
        "Cerrá los tickets 10 y 11",
    ],
)
def test_ticket_content_and_resource_commands_are_not_social(text):
    assert conversational_intent(text) is None


@pytest.mark.parametrize("text,intent", CASES)
async def test_initial_conversation_never_creates_a_ticket(supervisor, text, intent):
    s, _ = supervisor
    await s.submit("Gianna, " + text)
    assert s.draft is None and s.confirmation is None and not s.db.operations()
    assert s.last_speech and s.last_speech["text"]
    if intent == Intent.PRESENCE:
        assert s.last_speech["text"] == "Hola, soy Gianna y ya estoy activada."
    if intent == Intent.END or intent == Intent.FINISH:
        assert s.state == State.DORMANT


@pytest.mark.parametrize(
    "text",
    ["Gianna, ¿estás ahí?", "¿estás ahí?", "Me escuchás?", "Qué podés hacer?"],
)
async def test_direct_typed_console_does_not_require_repeated_wake(supervisor, text):
    s, _ = supervisor
    await s.submit(text, source="text")
    assert s.last_speech and s.draft is None


async def test_ambient_voice_still_requires_direct_wake(supervisor):
    s, _ = supervisor
    await s.submit("¿Estás ahí?", source="voice")
    assert s.state == State.DORMANT and s.last_speech is None
    await s.submit("Ella se llama Gianna", source="voice")
    assert s.last_speech is None
    await s.submit("Gianna, ¿estás ahí?", source="voice")
    assert "ya estoy activada" in s.last_speech["text"] and s.draft is None


NON_DESTRUCTIVE = [
    "¿Estás ahí?",
    "Hola",
    "Todo bien?",
    "Qué podés hacer?",
    "Gracias",
    "Perdón",
    "No entendí",
    "Más despacio",
    "Qué falta?",
    "Ya lo guardaste?",
    "Listo",
    "Finalizá eso",
]


@pytest.mark.parametrize("text", NON_DESTRUCTIVE)
@pytest.mark.parametrize("stage", ["missing", "confirmation"])
async def test_social_turns_preserve_payload_revision_and_pending_question(supervisor, text, stage):
    s, _ = supervisor
    await s.activate(initial="nuevo ticket")
    await s.submit(
        "La impresora no imprime" if stage == "missing" else "En Tránsito la impresora no imprime"
    )
    before = asdict(s.draft)
    confirmation, missing, state = s.confirmation, s.missing, s.state
    await s.submit(text)
    assert asdict(s.draft) == before
    assert (s.state, s.missing) == (state, missing)
    assert s.confirmation is confirmation
    assert not s.db.operations()
    assert (
        "sin enviar" in s.last_speech["text"]
        or "todavía no lo envié" in s.last_speech["text"]
        or "oficina" in s.last_speech["text"]
        or "Voy a registrar" in s.last_speech["text"]
    )


async def test_pause_end_and_resume_incomplete_draft_ask_actual_missing_field(supervisor):
    s, _ = supervisor
    await s.activate(initial="nuevo ticket")
    await s.submit("La impresora no imprime desde esta mañana")
    before = asdict(s.draft)
    await s.submit("Estoy en una llamada")
    assert s.state == State.PAUSED and asdict(s.draft) == before
    await s.submit("Gianna, seguimos")
    assert s.state == State.ASKING_MISSING_FIELD and s.missing == "origin_unit_id"
    assert s.confirmation is None
    await s.submit("Finalizá la conversación")
    assert s.state == State.DORMANT and asdict(s.draft) == before
    assert s.confirmation is None and s.idle_deadline is None
    await s.submit("Gianna, estás ahí?")
    assert s.state == State.ASKING_MISSING_FIELD
    await s.submit("Tránsito")
    assert s.state == State.WAITING_CONFIRMATION
    assert s.draft.payload["description"] == before["payload"]["description"]
    assert not s.db.operations()


async def test_end_invalidates_confirmation_and_resume_reviews_again(supervisor):
    s, _ = supervisor
    await s.activate(initial="nuevo ticket")
    await s.submit("En Tránsito la impresora no imprime")
    old = s.confirmation
    await s.submit("Gracias, hasta luego")
    assert s.state == State.DORMANT and s.confirmation is None
    await s.submit("Gianna, retomemos el borrador")
    assert s.state == State.WAITING_CONFIRMATION and s.confirmation.id != old.id
    assert not s.db.operations()


async def test_social_reply_cannot_extend_expired_write_permission(supervisor):
    s, now = supervisor
    await s.activate(initial="nuevo ticket")
    await s.submit("En Tránsito la impresora no imprime")
    old = s.confirmation
    now[0] = old.expires + 1
    await s.submit("Gianna, estás ahí?")
    assert s.confirmation is old and not old.valid(s.draft, 1, s.clock)
    await s.submit("Confirmo")
    assert not s.db.operations()
    assert s.confirmation is not old


async def test_help_is_local_and_role_aware(supervisor):
    s, _ = supervisor
    s.user["role"] = "viewer"
    await s.submit("Explicame las opciones")
    assert "buscar y leer" in s.last_speech["text"]
    assert "Puedo registrar" not in s.last_speech["text"]
    assert "Podés registrar" not in s.last_speech["text"]
    assert s.cloud is None and not s.db.operations()


async def test_repeat_after_presence_reads_actual_review_not_social_reply(supervisor):
    s, _ = supervisor
    await s.activate(initial="nuevo ticket")
    await s.submit("En Tránsito la impresora no imprime")
    question = s.last_speech["text"]
    await s.submit("¿Estás ahí?")
    await s.submit("No entendí")
    assert s.last_speech["text"] == question


async def test_resume_respects_manual_owner(supervisor):
    s, _ = supervisor
    await s.activate(initial="nuevo ticket")
    await s.submit("En Tránsito la impresora no imprime")
    s.draft.owner, s.draft.transferred = "human", True
    s.state = State.PAUSED
    old = asdict(s.draft)
    await s.submit("Gianna, seguimos")
    assert asdict(s.draft) == old and "control manual" in s.last_speech["text"]
    assert not s.db.operations()


@pytest.mark.parametrize(
    "text",
    [
        "Finalizá el ticket número 10",
        "Cerrá el ticket 10",
        "Resolvé el ticket diez",
        "Marcá el ticket 10 como resuelto",
        "Cancelá el ticket 10",
    ],
)
async def test_terminal_requests_prepare_note_and_confirmation_without_write(supervisor, text):
    s, _ = supervisor
    s.catalogs["statuses"] = [
        {"code": "resolved", "label": "Resuelto"},
        {"code": "cancelled", "label": "Cancelado"},
    ]
    calls = []

    async def tool(name, args):
        calls.append(name)
        return {
            "items": [{"id": 10, "code": "IDL-TI-000010", "version": 4, "status": "in_progress"}]
        }

    s.tool = tool
    await s.submit("Gianna, " + text)
    assert calls == ["tickets.search.v1"]
    expected = "cancelled" if "Cancelá" in text else "resolved"
    assert s.draft.tool == "tickets.status.v1"
    assert s.draft.resource == "tickets/10"
    assert s.draft.payload == {"version": 4, "status": expected}
    assert s.missing == "note" and s.confirmation is None and not s.db.operations()
    await s.submit("El equipo confirmó que la intervención terminó correctamente")
    assert s.state == State.WAITING_CONFIRMATION
    assert s.confirmation.resource == "tickets/10" and not s.db.operations()


@pytest.mark.parametrize(
    "text", ["Finalizá el ticket", "Resolvé el ticket 10 o 11", "Cerrá el ticket 10 y ticket 11"]
)
async def test_closure_requires_one_identified_ticket(supervisor, text):
    s, _ = supervisor
    await s.submit("Gianna, " + text)
    assert "Necesito el código" in s.last_speech["text"]
    assert s.draft is None and not s.db.operations()


async def test_presence_during_reserved_http_keeps_receipt_and_single_operation(supervisor):
    s, _ = supervisor
    entered, release = asyncio.Event(), asyncio.Event()
    adapter = Adapter()
    adapter.token = "test"
    original = adapter.execute

    async def execute(row):
        entered.set()
        await release.wait()
        return await original(row)

    adapter.execute = execute
    s.operations.adapter = adapter
    await s.activate(initial="nuevo ticket")
    await s.submit("En Tránsito la impresora no imprime")
    await s.submit("Confirmo")
    await asyncio.wait_for(entered.wait(), 2)
    generation = s.generation_id
    await s.submit("Gianna, estás ahí?")
    assert s.generation_id == generation and s.state == State.EXECUTING
    assert "procesando" in s.last_speech["text"] and "Guardé" not in s.last_speech["text"]
    release.set()
    await asyncio.gather(*s.tasks)
    assert len(adapter.sent) == 1 and len(s.db.operations()) == 1
    assert s.db.operations()[0]["status"] == "succeeded"
    assert s.last_receipt and s.state == State.CLOSING


@pytest.mark.parametrize(
    "text",
    [
        "Quiero crear un ticket",
        "Necesito registrar un pedido",
        "Nuevo ticket",
        "Hola, creá un ticket",
    ],
)
async def test_explicit_new_request_asks_for_real_description(supervisor, text):
    s, _ = supervisor
    await s.submit(text)
    assert s.draft.payload == {"destination_unit_id": 1}
    assert s.state == State.ASKING_MISSING_FIELD and s.missing == "description"
    await s.submit("En Tránsito la impresora no imprime")
    assert s.state == State.WAITING_CONFIRMATION
    assert text not in s.draft.payload["description"] and not s.db.operations()


async def test_direct_voice_activation_needs_no_model(supervisor):
    s, _ = supervisor
    s.interpreter = None
    await s.submit("Hola Gianna, estás ahí?", source="voice")
    assert s.draft is None and s.state == State.INVITING
    assert s.last_speech["text"] == "Hola, soy Gianna y ya estoy activada."


@pytest.mark.parametrize("name", ["Gianna", "Giana", "Yana", "Yanna", "Jiana", "Iana"])
async def test_wake_name_variants_activate_with_a_simple_welcome(supervisor, name):
    s, _ = supervisor
    await s.submit(f"Hola {name}", source="voice")
    assert s.last_speech["text"] == "Hola, soy Gianna y ya estoy activada."
    assert s.state == State.INVITING and s.draft is None


@pytest.mark.parametrize("text", ["Diana, ¿estás ahí?", "Mañana vamos a la oficina", "Ganá tiempo y llamá"])
async def test_other_words_do_not_wake(supervisor, text):
    s, _ = supervisor
    await s.submit(text, source="voice")
    assert s.state == State.DORMANT and s.last_speech is None


async def test_activation_button_only_welcomes(supervisor):
    s, _ = supervisor
    await s.activate()
    assert s.last_speech["text"] == "Hola, soy Gianna y ya estoy activada."
    assert s.state == State.INVITING and s.draft is None

async def test_textual_presence_does_not_depend_on_intent_inference(supervisor):
    s, _ = supervisor

    async def choose(*args, **kwargs):
        raise AssertionError("A direct console question needs no wake inference")

    s.tev.choose = choose
    await s.submit("Gianna, estás ahí?", source="text")
    assert "ya estoy activada" in s.last_speech["text"] and s.draft is None


async def test_board_and_manual_control_before_any_draft(supervisor):
    s, _ = supervisor
    calls = []

    async def tool(name, args):
        calls.append((name, args))
        return {"shown": True}

    s.tool = tool
    await s.submit("Gianna, abrí el tablero")
    assert calls == [("browser.open.v1", {})] and s.draft is None
    await s.submit("Tomar el control manual")
    assert "Todavía no hay un borrador" in s.last_speech["text"]
    assert s.draft is None and not s.db.operations()


async def test_old_receipt_cannot_claim_success_for_new_pending_request(supervisor):
    s, _ = supervisor
    await s.activate(initial="nuevo ticket")
    await s.submit("En Tránsito la impresora no imprime")
    old = asdict(s.draft)
    s.last_receipt = {"code": "IDL-TI-000001", "operation_id": "older"}
    s.state = State.RECONCILING
    await s.submit("¿Ya lo guardaste?")
    assert asdict(s.draft) == old and s.draft.owner == "agent"
    assert "No tengo un comprobante de éxito para este pedido" in s.last_speech["text"]
    assert not s.db.operations()


async def test_ending_conversation_during_http_keeps_committed_proof(supervisor):
    s, _ = supervisor
    adapter = Adapter()
    adapter.token = "test"
    adapter.allow.clear()
    s.operations.adapter = adapter
    await s.activate(initial="nuevo ticket")
    await s.submit("En Tránsito la impresora no imprime")
    await s.submit("Confirmo")
    for _ in range(50):
        if adapter.sent:
            break
        await asyncio.sleep(0.01)
    assert len(adapter.sent) == 1
    await s.submit("Finalizá la conversación")
    assert s.state == State.RECONCILING
    assert "se comprobará" in s.last_speech["text"]
    adapter.allow.set()
    await asyncio.gather(*s.tasks)
    await s.submit("¿Ya lo guardaste?")
    assert s.last_receipt and s.draft is None
    assert len(adapter.sent) == 1 and s.db.operations()[0]["status"] == "succeeded"


async def test_late_reconciliation_does_not_leak_old_actor_receipt(supervisor):
    s, _ = supervisor
    entered, release = asyncio.Event(), asyncio.Event()

    async def recover(actor):
        entered.set()
        await release.wait()
        return [{"code": "IDL-TI-000001", "operation_id": "old-actor"}]

    s.operations.recover = recover
    s.state = State.RECONCILING
    task = asyncio.create_task(s.submit("¿Ya lo guardaste?"))
    await entered.wait()
    await s.auth_invalidated()
    release.set()
    await task
    assert s.state == State.AUTH_REQUIRED and s.last_receipt is None
    assert s.last_speech is None


@pytest.mark.parametrize(
    "text",
    [
        "Finalizá el ticket número 10",
        "¿Podés cerrar el ticket diez?",
        "Resolvé el ticket IDL-TI-000010",
        "Marcá el ticket 10 como resuelto",
        "Cancelá el ticket 10",
    ],
)
async def test_terminal_instruction_switches_from_pending_review_without_losing_it(
    supervisor, text
):
    s, _ = supervisor
    await s.activate(initial="nuevo ticket")
    await s.submit("En Tránsito la impresora no imprime")
    old, confirmation = asdict(s.draft), s.confirmation
    s.catalogs["statuses"] = [
        {"code": "resolved", "label": "Resuelto"},
        {"code": "cancelled", "label": "Cancelado"},
    ]

    async def tool(name, args):
        return {
            "items": [{"id": 10, "code": "IDL-TI-000010", "version": 4, "status": "in_progress"}]
        }

    s.tool = tool
    await s.submit(text)
    assert s.draft.tool == "tickets.status.v1" and s.draft.resource == "tickets/10"
    assert s.confirmation is None and not confirmation.valid(s.draft, 1, s.clock)
    assert asdict(next(d for d in s.db.load_drafts(1) if d.id == old["id"])) == old
    assert not s.db.operations()


async def test_missing_resource_cannot_leave_previous_confirmation_armed(supervisor):
    s, _ = supervisor
    await s.activate(initial="nuevo ticket")
    await s.submit("En Tránsito la impresora no imprime")
    old = asdict(s.draft)
    await s.submit("Finalizá el ticket")
    assert s.confirmation is None and s.draft is None
    await s.submit("Confirmo")
    assert not s.db.operations() and s.draft is None
    await s.submit("Retomemos el borrador")
    assert asdict(s.draft) == old and s.state == State.WAITING_CONFIRMATION


@pytest.mark.parametrize(
    "text",
    [
        "Descripción: finalizá el ticket 10",
        'El sistema dice "cerrá el ticket 10"',
        "Finalizar la impresión del ticket 10 falla",
        "Cerrá el ticket 10 porque su pantalla dice gracias",
        "Cancelá la impresión del ticket 10",
    ],
)
def test_terminal_words_inside_dictation_cannot_switch_requests(text):
    assert not terminal_ticket_request(text)


@pytest.mark.parametrize("current,phrase", [("new", "primero"), ("resolved", "ya está")])
async def test_completion_explains_current_state_instead_of_sending_invalid_transition(
    supervisor, current, phrase
):
    s, _ = supervisor
    s.catalogs["statuses"] = [
        {"code": "new", "label": "Nuevo", "transitions": ["in_progress", "cancelled"]},
        {"code": "in_progress", "label": "En curso", "transitions": ["resolved", "cancelled"]},
        {"code": "resolved", "label": "Resuelto", "transitions": ["in_progress"]},
        {"code": "cancelled", "label": "Cancelado", "transitions": ["new"]},
    ]

    async def tool(name, args):
        return {"items": [{"id": 10, "code": "IDL-TI-000010", "version": 4, "status": current}]}

    s.tool = tool
    await s.submit("Gianna, finalizá el ticket 10")
    assert phrase in s.last_speech["text"]
    assert s.draft is None and s.confirmation is None and not s.db.operations()


async def test_unknown_target_status_is_checked_against_catalogue_before_review(supervisor):
    s, _ = supervisor
    s.catalogs["statuses"] = [
        {"code": "new", "label": "Nuevo", "transitions": ["in_progress", "cancelled"]},
        {"code": "in_progress", "label": "En curso", "transitions": ["resolved"]},
        {"code": "resolved", "label": "Resuelto", "transitions": ["in_progress"]},
        {"code": "cancelled", "label": "Cancelado", "transitions": ["new"]},
    ]

    async def tool(name, args):
        return {"items": [{"id": 10, "code": "IDL-TI-000010", "version": 4, "status": "new"}]}

    s.tool = tool
    await s.submit("Gianna, cambiá el estado del ticket 10")
    assert s.missing == "status"
    await s.submit("Resuelto")
    assert "no puede pasar directamente" in s.last_speech["text"]
    assert s.missing == "status" and "status" not in s.draft.payload
    assert s.confirmation is None and not s.db.operations()


async def test_another_ticket_saves_first_draft_and_can_resume_it(supervisor):
    s, _ = supervisor
    await s.activate(initial="nuevo ticket")
    await s.submit("En Tránsito la impresora no imprime")
    old, confirmation = asdict(s.draft), s.confirmation
    await s.submit("Otro ticket")
    new = asdict(s.draft)
    assert new["id"] != old["id"] and new["payload"] == {"destination_unit_id": 1}
    assert s.missing == "description" and s.confirmation is None
    assert not confirmation.valid(s.draft, 1, s.clock)
    await s.submit("Retomemos el borrador anterior")
    assert asdict(s.draft) == old and s.state == State.WAITING_CONFIRMATION
    assert s.confirmation.id != confirmation.id and not s.db.operations()
    assert asdict(next(d for d in s.db.load_drafts(1) if d.id == new["id"])) == new


async def test_previous_draft_is_actor_scoped(supervisor):
    from gianna.dialogue.draft import Draft

    s, _ = supervisor
    s.db.save_draft(Draft(2, payload={"description": "Información de otro usuario"}))
    await s.submit("Retomemos el pedido anterior")
    assert "No hay otro borrador" in s.last_speech["text"]
    assert s.draft is None and not s.db.operations()


async def test_rejected_speech_requests_repetition_without_guessing_or_rearming_idle(supervisor):
    s, _ = supervisor
    await s.activate(initial="nuevo ticket")
    await s.submit("En Tránsito la impresora no imprime")
    message = s.last_speech
    await s.playback_complete(message["utterance_id"], message["generation_id"])
    draft, confirmation, deadline, generation = (
        asdict(s.draft),
        s.confirmation,
        s.idle_deadline,
        s.generation_id,
    )
    evidence = {
        "reason": "no_accepted_segments",
        "active_ms": 900,
        "segments": [{"text": "y el teléfono", "avg_logprob": -1.1}],
    }
    await s.rejected_audio(evidence)
    assert s.last_speech["text"] == "No te escuché bien. ¿Podés repetirlo?"
    assert not s.last_speech["arm_idle"]
    assert s.state == State.WAITING_CONFIRMATION and asdict(s.draft) == draft
    assert s.confirmation is confirmation and (s.idle_deadline, s.generation_id) == (
        deadline,
        generation,
    )
    assert not s.db.operations()
    await s.rejected_audio(evidence)
    assert s.last_speech["text"].count("No te escuché bien") == 1


async def test_noise_that_cuts_speech_makes_gianna_say_it_again(supervisor):
    s, _ = supervisor
    spoken = []

    async def speak(message):
        spoken.append(message["text"])

    async def stop():
        pass

    s.speak_callback, s.stop_callback = speak, stop
    await s.activate(initial="nuevo ticket")
    question = s.last_speech["text"]
    await s.vad_started()
    await s.rejected_audio({"reason": "impulse", "active_ms": 100})
    assert spoken == [question, question]
    await s.rejected_audio({"reason": "impulse", "active_ms": 100})
    assert spoken == [question, question]
