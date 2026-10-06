"""Composed responses and the actual review/operation ownership boundaries."""

import asyncio
from dataclasses import asdict

import pytest

from gianna.dialogue.draft import Draft
from gianna.dialogue.interpretation import Reply, creation_request, data_text, review_reply
from gianna.dialogue.state_machine import State
from tests.unit.test_core import Adapter
from tests.unit.test_dialogue import supervisor as supervisor_fixture

supervisor = supervisor_fixture

APPROVALS = [
    "Eso es todo, Gianna, registra",
    "Confirmo Gianna",
    "Gianna, confirmo",
    "Sí, Gianna, confirmo, por favor",
    "Eso es todo, registralo",
    "Sí, eso es todo, podés registrarlo",
    "Registrá el pedido, por favor",
    "Podés registrarlo, Gianna",
    "Te pido que registres el pedido",
    "Quiero que lo registres",
    "Eso era todo, enviá el ticket",
    "Listo, guardalo",
    "Perfecto, podés enviarlo",
    "Sí, está bien así, entonces guardalo",
    "Confirmo que todo está correcto",
    "Los datos están correctos",
    "Sí, confirmo el pedido",
    "Te confirmo esta operación",
    "Esto es todo",
    "Eso es todo",
    "Confirmar",
]

UNAUTHORIZED = [
    "Sí, pero todavía no",
    "Sí, pero no lo registres",
    "No, registralo mañana",
    "Confirmo si cambiás el origen",
    "Si está correcto, registralo",
    "Creo que sí",
    "Sí, supongo",
    "Tal vez podés registrarlo",
    "Sí, después",
    "Registralo cuando vuelva",
    "Confirmo y esperá",
    "Eso es todo, pero falta la oficina",
    "No es todo, registra",
    "El técnico dijo confirmo",
    "Eso era para la persona del teléfono",
    'El sistema muestra "confirmo"',
    '"Eso es todo, registralo"',
    "Descripción: eso es todo, registralo",
    "Nota: confirmo",
    "Motivo: registra",
    "El botón registra no funciona",
    "Confirmo el ticket número 99",
    "Confirmo Gianna y Diana",
    "Sí, eso restado",
    "Eso todo registra",
    "Confirmo y",
    "Dale",
    "Perfecto",
    "Listo",
    "Registralo y borrá el ticket 2",
    "Sí, pero agregá que hay papel atascado",
    "Confirmo, pero cambiá el origen a Informática",
    "No, todavía no",
    "No lo guardes",
    "Sí, no lo ocultes",
    "Confirmo, pero espera",
]


@pytest.mark.parametrize("text", APPROVALS)
def test_composed_approval(text):
    assert review_reply(text, tool="tickets.create.v1").kind == Reply.APPROVE


@pytest.mark.parametrize("text", UNAUTHORIZED)
def test_no_partial_approval(text):
    assert review_reply(text, tool="tickets.create.v1").kind != Reply.APPROVE


@pytest.mark.parametrize(
    "tool,status,text",
    [
        ("tickets.archive.v1", None, "Ocultalo, Gianna"),
        ("tickets.restore.v1", None, "Sí, restaurá el ticket"),
        ("tickets.update.v1", None, "Actualizalo, por favor"),
        ("tickets.status.v1", "resolved", "Sí, finalizalo"),
        ("tickets.status.v1", "cancelled", "Cancelalo, Gianna"),
    ],
)
def test_action_must_correspond_to_current_review(tool, status, text):
    assert review_reply(text, tool=tool, status=status).kind == Reply.APPROVE
    assert review_reply(text, tool="tickets.create.v1").kind != Reply.APPROVE


@pytest.mark.parametrize("tool", ["tickets.archive.v1", "tickets.restore.v1", "tickets.status.v1"])
def test_finished_dictation_alone_does_not_authorize_a_different_operation(tool):
    assert review_reply("Eso es todo", tool=tool).kind != Reply.APPROVE
    assert review_reply("Eso es todo, registra", tool=tool).kind != Reply.APPROVE


@pytest.mark.parametrize(
    "prefix",
    [
        "Necesito registrar un nuevo ticket. ",
        "Quiero crear un ticket: ",
        "Gianna, registrá un pedido. ",
        "Podés registrar un ticket, por favor. ",
        "Quisiera registrar un pedido nuevo. ",
        "Me gustaría crear un ticket. ",
        "¿Podrías registrar un ticket? ",
        "Preciso registrar una nueva solicitud. ",
        "Necesito tu ayuda para registrar un ticket. ",
        "Ayudame a crear una incidencia: ",
        "Necesito que crees un ticket. ",
        "Hola , necesito tu ayuda para registrar un pedido nuevo. ",
        "Buenas tardes, quisiera crear un ticket: ",
    ],
)
def test_creation_instruction_and_literal_data_are_separate(prefix):
    problem = 'En Tránsito Gianna ve "cancelar impresión" y la impresora no imprime.'
    parsed = creation_request(prefix + problem)
    assert parsed and parsed.content == problem


@pytest.mark.parametrize(
    "text",
    [
        "La aplicación no permite registrar un ticket",
        'Descripción: "Registrá un ticket" aparece en pantalla',
        "Nota: quiero crear un ticket",
        "No quiero registrar un ticket",
        "El técnico dijo que necesitaba registrar un ticket",
    ],
)
def test_creation_words_inside_dictation_are_content(text):
    assert creation_request(text) is None


def test_vocative_is_removed_from_data_only_at_explicit_leading_address():
    literal = 'La usuaria Gianna dijo "confirmo" y el sistema no respondió.'
    assert data_text(literal) == literal
    assert data_text("Gianna, " + literal) == literal
    assert data_text("La usuaria se llama Gianna") == "La usuaria se llama Gianna"


@pytest.mark.parametrize(
    "text",
    ["Buenas tardes", "Gianna, buenas tardes", "Buenas noches, Gianna", "Buenos días, Gianna"],
)
async def test_greeting_components_are_not_erased_by_command_normalization(supervisor, text):
    s, _ = supervisor
    await s.submit(text)
    assert s.last_speech["text"].startswith("Hola, soy Gianna")
    assert s.draft is None and not s.db.operations()


async def ready_review(s):
    await s.activate(initial="nuevo ticket")
    await s.submit("En Tránsito la impresora no imprime")
    assert s.state == State.WAITING_CONFIRMATION


@pytest.mark.parametrize("text", APPROVALS)
async def test_natural_approval_dispatches_one_bound_operation(supervisor, text):
    s, _ = supervisor
    adapter = Adapter()
    adapter.allow.clear()
    s.operations.adapter = adapter
    await ready_review(s)
    draft, confirmation = asdict(s.draft), s.confirmation
    await s.submit(text)
    await asyncio.sleep(0.01)
    (row,) = s.db.operations()
    assert row["draft_id"] == draft["id"] and row["confirmation_id"] == confirmation.id
    assert row["payload_hash"] == confirmation.digest and row["status"] == "dispatched"
    generation = s.generation_id
    await s.submit("Confirmo, Gianna")
    assert s.generation_id == generation and len(s.db.operations()) == 1
    adapter.allow.set()
    await asyncio.gather(*s.tasks)
    assert s.last_receipt and len(adapter.sent) == 1
    assert s.db.operations()[0]["status"] == "succeeded"
    await s.submit("Gianna, confirmo")
    assert len(adapter.sent) == 1 and s.draft is None
    assert "ya quedó guardada" in s.last_speech["text"]


@pytest.mark.parametrize("text", UNAUTHORIZED)
async def test_negative_uncertain_or_correction_reply_never_dispatches(supervisor, text):
    s, _ = supervisor
    await ready_review(s)
    await s.submit(text)
    assert not s.db.operations()


@pytest.mark.parametrize(
    "text",
    [
        "Sí, pero cambiá el origen a Informática",
        "Confirmo, pero cambiá el origen a Informática",
        "Gianna, no, cambiá el origen a Informática",
        "Antes, cambiá el origen a Informática",
    ],
)
async def test_correction_wins_over_consent_and_requires_new_review(supervisor, text):
    s, _ = supervisor
    await ready_review(s)
    old, description = s.confirmation, s.draft.payload["description"]
    await s.submit(text)
    assert s.state == State.WAITING_CONFIRMATION
    assert s.draft.payload["origin_unit_id"] == 1
    assert s.draft.payload["description"] == description
    assert s.confirmation.id != old.id and not old.valid(s.draft, 1, s.clock)
    assert not s.db.operations()


@pytest.mark.parametrize(
    "text",
    [
        "No, el origen es Informática",
        "En realidad, el origen debe ser Informática",
        "Sí, pero el origen tiene que ser Informática",
    ],
)
async def test_declarative_field_correction(supervisor, text):
    s, _ = supervisor
    await ready_review(s)
    original = s.draft.payload["description"]
    await s.submit(text)
    assert s.draft.payload["origin_unit_id"] == 1
    assert s.draft.payload["description"] == original and not s.db.operations()


@pytest.mark.parametrize("text", ["No", "No, todavía no", "No lo guardes", "Confirmo, pero espera"])
async def test_control_reply_to_a_missing_field_is_not_dictation(supervisor, text):
    s, _ = supervisor
    await s.activate(initial="nuevo ticket")
    await s.submit("La impresora no imprime desde ayer")
    original = asdict(s.draft)
    await s.submit(text)
    assert asdict(s.draft) == original and not s.db.operations()


async def test_correction_can_target_a_field_other_than_the_pending_question(supervisor):
    s, _ = supervisor
    await s.activate(initial="nuevo ticket")
    await s.submit("La impresora no imprime desde ayer")
    assert s.missing == "origin_unit_id"
    await s.submit("Cambiá el destino a Informática")
    assert s.draft.payload["destination_unit_id"] == 1 and s.missing == "origin_unit_id"
    assert s.draft.payload["description"] == "La impresora no imprime desde ayer"


async def test_unclear_reply_preserves_review_identity_and_expiry(supervisor):
    s, now = supervisor
    await ready_review(s)
    old, data = s.confirmation, asdict(s.draft)
    now[0] += 110
    await s.submit("Sí, eso restado")
    assert s.confirmation is old and asdict(s.draft) == data
    now[0] += 11
    await s.submit("Eso es todo, Gianna, registra")
    assert not s.db.operations() and s.confirmation.id != old.id
    assert s.state == State.WAITING_CONFIRMATION


@pytest.mark.parametrize(
    "text",
    [
        "Sí, pero falta la oficina",
        "Sí, pero todavía no",
        "Sí, pero no está bien así",
        "En realidad, falta un dato",
    ],
)
async def test_uninterpreted_qualification_keeps_payload_and_review(supervisor, text):
    s, _ = supervisor
    await ready_review(s)
    draft, confirmation = asdict(s.draft), s.confirmation
    await s.submit(text)
    assert asdict(s.draft) == draft and s.confirmation is confirmation
    assert not s.db.operations()


@pytest.mark.parametrize(
    "text", ["Corregí", "Corregí la descripción", "Cambiá el origen a", "Agregá que"]
)
async def test_incomplete_correction_asks_for_data_without_storing_the_command(supervisor, text):
    s, _ = supervisor
    await ready_review(s)
    draft = asdict(s.draft)
    await s.submit(text)
    assert asdict(s.draft) == draft and s.confirmation is None
    assert s.state == State.COLLECTING_DRAFT and not s.db.operations()


async def test_no_review_cannot_turn_a_yes_into_description(supervisor):
    s, _ = supervisor
    await s.submit("Confirmo, Gianna")
    assert s.draft is None and not s.db.operations()
    assert "no hay una revisión" in s.last_speech["text"]


async def test_screenshot_creation_in_active_conversation_has_clean_description(supervisor):
    s, _ = supervisor
    await s.submit("Hola Gianna, ¿estás ahí?")
    problem = "Desde Tránsito nos piden arreglar una impresora que se tranca al pasar la hoja."
    await s.submit("Necesito registrar un nuevo ticket. " + problem)
    assert s.state == State.WAITING_CONFIRMATION
    assert s.draft.payload["description"] == problem
    assert s.draft.payload["origin_unit_id"] == 2 and s.draft.payload["problem_type_id"] == 3
    assert not s.db.operations()


async def test_dictated_name_is_not_deleted_from_description(supervisor):
    s, _ = supervisor
    await s.activate(initial="nuevo ticket")
    literal = "En Tránsito la impresora de Gianna no imprime."
    await s.submit(literal)
    assert s.draft.payload["description"] == literal


async def test_type_can_be_classified_from_incident_without_rewriting_literal_data(supervisor):
    s, _ = supervisor
    calls = []

    async def choose(text, criteria, context=""):
        calls.append((text, criteria))
        return "id_3"

    s.tev.choose = choose
    await s.activate(initial="nuevo ticket")
    literal = "En Tránsito la inpesora se tranca con papel y no permite imprimir"
    await s.submit(literal)
    assert s.state == State.WAITING_CONFIRMATION and s.draft.payload["problem_type_id"] == 3
    assert s.draft.payload["description"] == literal
    assert calls[0][0] == literal and set(calls[0][1]) == {"id_3", "clarify", "ignore"}
    assert not s.db.operations()


async def test_uncertain_type_is_requested_without_assuming_a_category(supervisor):
    s, _ = supervisor
    await s.activate(initial="nuevo ticket")
    await s.submit("En Tránsito hay un problema sin categoría identificable")
    assert s.missing == "problem_type_id" and not s.draft.payload.get("problem_type_id")
    assert s.confirmation is None and not s.db.operations()


async def test_late_type_decision_cannot_modify_a_paused_draft(supervisor):
    s, _ = supervisor
    entered, release = asyncio.Event(), asyncio.Event()

    async def choose(*args):
        entered.set()
        await release.wait()
        return "id_3"

    s.tev.choose = choose
    await s.activate(initial="nuevo ticket")
    collect = asyncio.create_task(s.submit("En Tránsito la inpesora detiene todas las impresiones"))
    await asyncio.wait_for(entered.wait(), 2)
    await s.pause()
    saved = asdict(s.draft)
    release.set()
    await collect
    assert s.state == State.PAUSED and asdict(s.draft) == saved
    assert not s.draft.payload.get("problem_type_id") and not s.db.operations()


@pytest.mark.parametrize("boundary", ["session", "revision", "owner", "actor"])
async def test_natural_language_cannot_bypass_review_binding(supervisor, boundary):
    s, _ = supervisor
    await ready_review(s)
    if boundary == "session":
        s.session_id = "another-session"
    elif boundary == "revision":
        s.draft.change(description="Una descripción modificada sin revisar")
    elif boundary == "owner":
        s.draft.owner = "human"
    else:
        s.user = {"id": 2, "role": "operator"}
    await s.submit("Eso es todo, Gianna, registra")
    assert not s.db.operations()


async def test_description_completion_in_a_status_review_does_not_close_ticket(supervisor):
    s, _ = supervisor
    s.draft = Draft(
        1,
        tool="tickets.status.v1",
        resource="tickets/1",
        payload={"version": 1, "status": "resolved", "note": "Trabajo terminado"},
    )
    await s.review()
    await s.submit("Eso es todo")
    assert not s.db.operations()
