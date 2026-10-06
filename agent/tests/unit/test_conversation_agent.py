"""Harness boundaries and multi-turn state; model doubles do not test semantics."""

import asyncio
from copy import deepcopy
import json

import httpx
import pytest
from gianna.adapters.base import Capability
from gianna.dialogue.draft import Draft
from gianna.dialogue.state_machine import State
from gianna.models.ollama_cloud import CloudChat
from gianna.runtime.agent_tools import AgentTools
from gianna.runtime.conversation_agent import ConversationAgent
from gianna.tools.dispatcher import Dispatcher
from gianna.tools.registry import ToolRegistry
from gianna.tools.tickets import install_tools
from tests.unit.test_dialogue import supervisor  # noqa: F401


@pytest.fixture
def harness(supervisor):  # noqa: F811 - imported pytest fixture
    s, clock = supervisor
    s.catalogs["org_units"].append(
        {
            "id": 7,
            "name": "Secretaría General",
            "code": "SECRETARIA_GENERAL",
            "can_receive_tickets": False,
        }
    )
    s.catalogs["org_units"].append(
        {"id": 4, "name": "Sociales", "code": "SOCIALES", "can_receive_tickets": False}
    )
    for unit in s.catalogs["org_units"]:
        unit.update(kind="office" if unit["id"] == 7 else "area", is_active=True, parent_id=None)
    for problem in s.catalogs["problem_types"]:
        problem.update(description=None, is_active=True)
    s.catalogs["problem_types"].extend(
        {"id": id_, "name": name, "code": code, "description": None, "is_active": True}
        for id_, name, code in [
            (8, "Conectividad / Internet", "INTERNET"),
            (9, "Hardware", "HARDWARE"),
            (10, "Acceso a sistemas", "SISTEMAS"),
            (11, "Otros", "OTROS"),
        ]
    )
    s.catalogs.update(
        warnings=[],
        statuses=[
            {
                "code": "new",
                "label": "Nuevo",
                "transitions": ["in_progress", "waiting", "cancelled"],
            },
            {
                "code": "in_progress",
                "label": "En curso",
                "transitions": ["waiting", "resolved", "cancelled"],
            },
            {"code": "waiting", "label": "En espera", "transitions": ["in_progress", "cancelled"]},
            {"code": "resolved", "label": "Resuelto", "transitions": ["in_progress"]},
            {"code": "cancelled", "label": "Cancelado", "transitions": ["new"]},
        ],
    )
    ticket = {
        "id": 91,
        "code": "IDL-TI-000004",
        "status": "new",
        "version": 8,
        "description": "La impresora no imprime desde ayer",
        "origin": s.catalogs["org_units"][1],
        "destination": s.catalogs["org_units"][0],
        "problem_type": s.catalogs["problem_types"][0],
        "origin_unit_id": 2,
        "destination_unit_id": 1,
        "problem_type_id": 3,
        "created_by_user_id": 1,
        "created_at": "2026-10-05T12:00:00Z",
        "updated_at": "2026-10-05T12:00:00Z",
        **dict.fromkeys(
            [
                "first_response_at",
                "resolved_at",
                "cancelled_at",
                "occurred_at",
                "archived_at",
                "archived_by_user_id",
                "archive_reason",
            ]
        ),
    }
    s.test_requests = []

    async def request(method, path, **kwargs):
        s.test_requests.append((method, path, kwargs))
        assert method == "GET", "Conversation tool must not perform a remote write"
        if path == "/api/v1/catalogs":
            return deepcopy(s.catalogs)
        if path == "/api/v1/tickets":
            return {"items": [deepcopy(ticket)], "total": 1, "page": 1, "pages": 1, "per_page": 25}
        if path == "/api/v1/tickets/91":
            return deepcopy(ticket)
        raise AssertionError(path)

    s.tickets.request = request

    async def execute(*args, **kwargs):
        raise AssertionError("This fixture forbids all business writes")

    s.tickets.execute = execute
    s.tickets.discover = lambda: [Capability("idl_tickets_http_v1", "1", True, "")]
    registry = ToolRegistry()
    install_tools(registry, s.tickets, None, s)
    s.dispatcher = Dispatcher(registry)
    s.state = State.INVITING
    agent = ConversationAgent(s, None)
    s.conversation_agent = agent
    return s, agent, clock


def call(name, **arguments):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": name, "arguments": arguments}}],
    }


def script(agent, *answers):
    pending = iter(answers)
    recorded = []
    last = None

    async def turn(messages, tools):
        nonlocal last
        recorded.append(deepcopy(messages))
        try:
            last = next(pending)
        except StopIteration:
            if last is None or last.get("tool_calls"):
                raise AssertionError("Unexpected extra tool/model round") from None
        return last

    agent.chat.turn = turn
    return recorded


async def test_catalogue_question_during_review_uses_tool_and_keeps_confirmation(harness):
    s, agent, _ = harness
    await s.start_request("En Tránsito la impresora no imprime")
    previous, confirmation = deepcopy(s.draft.payload), s.confirmation
    history = script(
        agent,
        call("catalogues"),
        {"role": "assistant", "content": "1. Informática. 2. Tránsito. 3. Secretaría General."},
    )
    await s.submit("Gianna, ¿qué áreas registradas tenés?")
    assert s.draft.payload == previous and s.confirmation is confirmation
    assert s.test_requests[-1][1] == "/api/v1/catalogs"
    assert any(m["role"] == "tool" for m in history[-1])
    assert "Secretaría General" in s.last_speech["text"]
    assert not s.db.operations()
    texts = [m["content"] for m in history[0] if m["role"] == "user"]
    assert len(texts) == 1 and texts[0].count("áreas") == 1
    # Complete tool exchanges, as well as the preceding factual reply, survive.
    script(agent, {"role": "assistant", "content": "Te enumeré tres opciones."})
    messages = s.db.conversation_messages(1, s.session_id)
    assert any(m["role"] == "tool" for m in messages)
    await s.submit("¿Qué me acabás de enumerar?")
    assert s.draft.payload == previous


async def test_question_from_dormant_enters_native_harness(harness):
    s, agent, _ = harness
    s.state = State.DORMANT
    script(
        agent,
        call("catalogues"),
        {"role": "assistant", "content": "Secretaría General está registrada."},
    )
    await s.submit("¿Está registrada Secretaría General?")
    assert s.draft is None and not s.db.operations()
    assert s.test_requests[-1][1] == "/api/v1/catalogs"


async def test_selection_after_catalogue_preserves_description_and_reissues_review(harness):
    s, agent, _ = harness
    await s.start_request("En Tránsito la impresora no imprime")
    description, old = s.draft.payload["description"], s.confirmation
    script(agent, call("prepare_request", mode="select", origin_unit_id=7))
    await s.submit("Usá Secretaría General como origen")
    assert s.draft.payload["origin_unit_id"] == 7
    assert s.draft.payload["description"] == description
    assert not old.valid(s.draft, 1, s.clock, s.session_id)
    assert s.confirmation and not s.db.operations()


async def test_combined_description_and_fields_are_reviewed_once(harness):
    s, agent, _ = harness
    await s.start_request("En Tránsito la impresora no imprime")
    old = s.confirmation
    before = s.db.connection.execute("SELECT COUNT(*) FROM events WHERE kind='speech'").fetchone()[
        0
    ]
    script(
        agent,
        call(
            "prepare_request",
            mode="replace",
            text="desde Secretaría General pidieron nuevas hojas para todas las impresoras",
            origin_unit_id=7,
            problem_type_id=3,
        ),
    )
    await s.submit(
        "Lo que dije es que desde Secretaría General pidieron nuevas hojas para todas las impresoras"
    )
    assert s.draft.payload["origin_unit_id"] == 7
    assert (
        s.draft.payload["description"]
        == "desde Secretaría General pidieron nuevas hojas para todas las impresoras"
    )
    assert (
        s.db.connection.execute("SELECT COUNT(*) FROM events WHERE kind='speech'").fetchone()[0]
        == before + 1
    )
    assert s.confirmation.valid(s.draft, 1, s.clock, s.session_id)
    assert not old.valid(s.draft, 1, s.clock, s.session_id)
    assert not s.db.operations()


async def test_invalid_combined_field_rejects_entire_change_before_mutation(harness):
    s, agent, _ = harness
    await s.start_request("En Tránsito la impresora no imprime")
    previous, confirmation = deepcopy(s.draft.payload), s.confirmation
    with pytest.raises(ValueError, match="catálogo"):
        await agent.tools.call(
            "prepare_request",
            {
                "mode": "replace",
                "text": "Pidieron nuevas hojas para todas las impresoras",
                "origin_unit_id": 999,
            },
            "Pidieron nuevas hojas para todas las impresoras",
        )
    assert s.draft.payload == previous and s.confirmation is confirmation


@pytest.mark.parametrize(
    "name,args",
    [
        ("tickets.create.v1", {"description": "Inventado por el modelo"}),
        ("prepare_request", {"mode": "select", "origin_unit_id": 999}),
        ("prepare_request", {"mode": "select", "origin_unit_id": True}),
        ("prepare_request", {"mode": "replace", "text": "Una descripción que nadie dijo"}),
        ("catalogues", {"unexpected": True}),
    ],
)
async def test_uninstalled_invalid_or_invented_model_actions_do_not_mutate(harness, name, args):
    s, agent, _ = harness
    await s.start_request("En Tránsito la impresora no imprime")
    original = deepcopy(s.draft.payload)
    script(
        agent, call(name, **args), {"role": "assistant", "content": "Necesito que aclares el dato."}
    )
    await s.submit("No modifiques nada todavía")
    assert s.draft.payload == original and not s.db.operations()
    assert not s.errors


async def test_synthetic_status_command_only_prepares_never_authorizes_write(harness):
    s, agent, _ = harness
    script(agent, call("prepare_existing_ticket", action="status", number=4, status="in_progress"))
    await s.submit("Me gustaría poner el cuatro en curso")
    assert s.draft.tool == "tickets.status.v1"
    assert s.draft.resource == "tickets/91" and s.draft.payload["version"] == 8
    assert s.state == State.WAITING_CONFIRMATION and not s.db.operations()


async def test_native_note_completion_goes_to_review_with_user_facts(harness):
    s, agent, _ = harness
    s.draft = Draft(
        1,
        tool="tickets.status.v1",
        resource="tickets/91",
        payload={"version": 8, "status": "resolved"},
    )
    await s.ask_missing("note")
    script(
        agent,
        call("supply_draft_text", field="note", text="Se repuso el papel y se probó la impresión"),
    )
    await s.submit("Se repuso el papel y se probó la impresión")
    assert s.draft.payload["note"] == "Se repuso el papel y se probó la impresión"
    assert s.state == State.WAITING_CONFIRMATION and not s.db.operations()
    with pytest.raises(ValueError, match="campo"):
        await agent.tools.call(
            "prepare_request", {"mode": "select", "origin_unit_id": 7}, "Secretaría General"
        )


async def test_actor_history_isolation_and_completed_exchange_reset(harness):
    s, _, _ = harness
    for actor, session, text in [
        (1, s.session_id, "Mi pedido"),
        (2, s.session_id, "Otro actor"),
        (1, "otro-chat", "Otra sesión"),
    ]:
        s.db.event(session, s.generation_id, "transcript", {"text": text}, actor_id=actor)
    assert s.db.conversation_messages(1, s.session_id) == [{"role": "user", "content": "Mi pedido"}]
    s.publish(
        "agent_exchange",
        {
            "messages": [
                call("catalogues"),
                {"role": "tool", "tool_name": "catalogues", "content": "{}"},
            ]
        },
    )
    s.db.clear_conversation(1, s.session_id)
    assert s.db.conversation_messages(1, s.session_id) == []
    assert s.db.conversation_messages(2, s.session_id)


async def test_late_model_answer_after_generation_change_has_no_effect(harness):
    s, agent, _ = harness
    entered, release = asyncio.Event(), asyncio.Event()

    async def late(messages, tools):
        entered.set()
        await release.wait()
        return call("prepare_request", mode="create", text="En Tránsito la impresora no imprime")

    agent.chat.turn = late
    task = asyncio.create_task(s.submit("Quiero registrar: En Tránsito la impresora no imprime"))
    await entered.wait()
    s.invalidate()
    release.set()
    await task
    assert s.draft is None and not s.db.operations()


async def test_repeated_model_tool_calls_stop_at_bounded_budget(harness):
    s, agent, _ = harness
    script(agent, call("catalogues"), call("catalogues"), call("catalogues"))
    await s.submit("¿Qué oficinas hay?")
    assert len(s.test_requests) == 2 and "No pude completar" in s.last_speech["text"]
    failure = s.db.connection.execute(
        "SELECT data FROM events WHERE kind='agent_turn_failed'"
    ).fetchone()
    assert json.loads(failure[0])["detail"] == "agent_tool_budget_exhausted"
    assert not s.db.operations()


async def test_unavailable_surfaces_and_business_writes_are_not_offered(harness):
    s, agent, _ = harness
    names = {d["function"]["name"] for d in agent.tools.definitions()}
    assert "catalogues" in names and "open_board" not in names
    assert not any("create.v1" in name or "execute" in name or "confirm" in name for name in names)
    s.tickets.token = None
    s.tickets.discover = lambda: [Capability("idl_tickets_http_v1", "1", False, "")]
    assert "catalogues" not in {d["function"]["name"] for d in agent.tools.definitions()}


@pytest.mark.parametrize("ownership", ["human", "other_actor"])
async def test_native_local_actions_cannot_edit_a_transferred_or_other_actor_draft(
    harness, ownership
):
    s, agent, _ = harness
    await s.start_request("En Tránsito la impresora no imprime")
    if ownership == "human":
        s.draft.owner = "human"
        s.draft.transferred = True
    else:
        s.draft.actor_id = 2
    original = deepcopy(s.draft.payload)
    with pytest.raises(ValueError, match="propio"):
        await agent.tools.call(
            "prepare_request", {"mode": "select", "origin_unit_id": 7}, "Secretaría General"
        )
    assert s.draft.payload == original


@pytest.mark.parametrize(
    "message",
    [
        None,
        [],
        {"role": "tool"},
        {"content": 42},
        {"tool_calls": [None]},
        {"tool_calls": [{"function": []}]},
        {"tool_calls": [{"function": {"name": "catalogues", "arguments": []}}]},
    ],
)
async def test_malformed_native_cloud_response_is_rejected(message):
    from gianna.config import Settings

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"message": message}))
    ) as client:
        with pytest.raises(ValueError):
            await CloudChat(Settings(cloud_api_key="contract-fixture"), client).turn([], [])


@pytest.mark.parametrize("arguments", [{}, "{}"])
async def test_native_cloud_http_protocol_and_argument_variants(arguments):
    from gianna.config import Settings

    seen = []

    def respond(request):
        body = json.loads(request.content)
        assert request.url.host == "ollama.com" and request.url.scheme == "https"
        assert body["tools"] and body["model"] == "deepseek-v4.1-flash"
        assert "format" not in body and body["think"] is False
        seen.extend(body["messages"])
        return httpx.Response(
            200,
            json={
                "message": call("catalogues", **{})
                | {"tool_calls": [{"function": {"name": "catalogues", "arguments": arguments}}]}
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        from gianna.tools.tickets import schema

        result = await CloudChat(Settings(cloud_api_key="contract-fixture"), client).turn(
            [{"role": "user", "content": "¿Qué áreas tenés?"}],
            [AgentTools.definition("catalogues", "Catálogos", schema({}))],
        )
        assert result["tool_calls"][0]["function"]["arguments"] == {}
    assert seen == [{"role": "user", "content": "¿Qué áreas tenés?"}]


async def test_creation_from_prior_narrative_and_current_clarification_accepts_catalogue_ids(
    harness,
):
    s, agent, _ = harness
    s.publish("transcript", {"text": "Me pidieron recién cambiar las hojas de las impresoras"})
    script(
        agent,
        call(
            "prepare_request",
            mode="create",
            text="Servicios Sociales solicitó cambiar las hojas de las impresoras.",
            origin_unit_id=4,
            destination_unit_id=1,
            problem_type_id=3,
        ),
    )
    await s.submit("Te acabo de decir la oficina de servicios sociales")
    assert s.draft.payload["origin_unit_id"] == 4
    assert s.state == State.WAITING_CONFIRMATION and not s.db.operations()
    messages = s.db.conversation_messages(1, s.session_id)
    assert any(m.get("tool_name") == "prepare_request" for m in messages)
    assert messages[-1]["content"] == s.last_speech["text"]
    assert sum(m.get("content") == s.last_speech["text"] for m in messages) == 1


async def test_native_creation_does_not_reinterpret_fields_with_legacy_classifier(harness):
    s, agent, _ = harness

    async def forbidden(*args, **kwargs):
        raise AssertionError("Native structured preparation must not reinterpret the same facts")

    s.interpreter.incident_context = forbidden
    s.tev.choose = forbidden
    script(
        agent,
        call(
            "prepare_request",
            mode="create",
            text="En Sociales necesitan papel para imprimir",
            origin_unit_id=4,
            problem_type_id=3,
        ),
    )
    await s.submit("Creá un ticket: en Sociales necesitan papel para imprimir")
    assert s.draft.payload["origin_unit_id"] == 4
    assert s.draft.payload["problem_type_id"] == 3
    assert s.confirmation and not s.db.operations()


async def test_native_empty_creation_keeps_draft_and_requests_only_missing_data(harness):
    s, agent, _ = harness
    script(agent, call("prepare_request", mode="create"))
    await s.submit("Quiero abrir un ticket nuevo")
    assert s.draft and s.missing == "origin_unit_id"
    original = s.draft.id
    script(agent, call("prepare_request", mode="select", origin_unit_id=4))
    await s.submit("Viene de Sociales")
    assert s.draft.id == original and s.missing == "problem_type_id"
    assert not s.db.operations()


async def test_native_correction_replaces_without_legacy_reclassification(harness):
    s, agent, _ = harness
    await s.start_request("En Tránsito la impresora no imprime")
    old = s.confirmation
    script(
        agent,
        call(
            "prepare_request",
            mode="replace",
            text="La impresora imprime, pero necesitan reponer papel.",
            origin_unit_id=4,
            problem_type_id=3,
        ),
    )
    await s.submit("Sí, pero corregí: sí imprime, lo que necesitan en Sociales es más papel")
    assert s.draft.payload["origin_unit_id"] == 4
    assert "no imprime" not in s.draft.payload["description"]
    assert not old.valid(s.draft, 1, s.clock, s.session_id)
    assert s.confirmation and not s.db.operations()


async def test_reselecting_same_origin_keeps_revision_and_confirmation(harness):
    s, agent, _ = harness
    await s.start_request("En Tránsito la impresora no imprime")
    revision, confirmation = s.draft.revision, s.confirmation
    result, spoken = await agent.tools.call(
        "prepare_request", {"mode": "select", "origin_unit_id": 2}, "Te dije Tránsito"
    )
    assert result["changed"] is False and not spoken
    assert s.draft.revision == revision and s.confirmation is confirmation


async def test_multi_call_batch_cannot_edit_a_review_after_speaking_it(harness):
    s, agent, _ = harness
    first = call(
        "prepare_request",
        mode="create",
        text="En Sociales la impresora no imprime",
        origin_unit_id=4,
        problem_type_id=3,
    )
    first["tool_calls"].extend(
        call("prepare_request", mode="select", origin_unit_id=2)["tool_calls"]
    )
    script(agent, first)
    await s.submit("Registrá el problema de la impresora en Sociales")
    assert s.draft.payload["origin_unit_id"] == 4 and s.confirmation
    messages = s.db.conversation_messages(1, s.session_id)
    assert sum(m["role"] == "tool" for m in messages) == 2
    assert any('"skipped": true' in m["content"] for m in messages if m["role"] == "tool")


@pytest.mark.parametrize(
    "status,label",
    [
        ("resolved", "resuelto"),
        ("cancelled", "cancelado"),
        ("in_progress", "en curso"),
    ],
)
async def test_confirmation_mark_as_matches_only_reviewed_status(status, label):
    from gianna.dialogue.interpretation import Reply, review_reply

    assert (
        review_reply(
            f"Confirmo, marcalo como {label}", tool="tickets.status.v1", status=status
        ).kind
        == Reply.APPROVE
    )
    assert (
        review_reply(f"No, marcalo como {label}", tool="tickets.status.v1", status=status).kind
        != Reply.APPROVE
    )
    assert (
        review_reply("Confirmo, marcalo como nuevo", tool="tickets.status.v1", status=status).kind
        != Reply.APPROVE
    )


async def test_previous_receipt_does_not_accredit_pending_change(harness):
    s, agent, _ = harness
    s.last_receipt = {"tool": "tickets.status.v1", "status": "in_progress", "ticket_id": 91}
    await s.start_request("En Tránsito la impresora no imprime")
    assert agent.context()["receipt"] is None
    assert agent.context()["previous_receipt"] == s.last_receipt


async def test_unknown_origin_correction_removes_old_area_but_preserves_other_facts(harness):
    s, agent, _ = harness
    await s.start_request("En Tránsito la impresora no imprime")
    description = s.draft.payload["description"]
    await agent.tools.call(
        "prepare_request",
        {"mode": "select", "unknown_origin": "Oficina Atlántida"},
        "El origen es Atlántida",
    )
    assert not s.draft.payload.get("origin_unit_id")
    assert s.draft.payload["description"] == description
    assert s.missing == "origin_unit_id" and not s.confirmation
