import asyncio
from dataclasses import asdict

import pytest
from gianna.dialogue.draft import Draft
from gianna.dialogue.state_machine import State
from gianna.persistence.database import Database
from tests.unit.test_context_repair import Interpretation
from tests.unit.test_dialogue import supervisor as supervisor_fixture

supervisor = supervisor_fixture


async def test_reset_starts_empty_and_removes_saved_chat_only_for_current_actor(supervisor):
    s, _ = supervisor
    other = Draft(actor_id=2, payload={"description": "Otro usuario"})
    s.db.save_draft(other)
    s.db.event("another-session", "g", "transcript", {"text": "Otro chat"}, actor_id=2)
    await s.start_request("En Tránsito la impresora no imprime")
    old = s.confirmation
    before_session, before_generation = s.session_id, s.generation_id
    queue = s.bus.subscribe()
    s.publish("transcript", {"text": "La conversación anterior"})
    s.errors.append({"message": "Error anterior"})
    s.pending_request = {"text": "Pedido anterior"}
    await s.reset_conversation()
    assert s.state == State.DORMANT and s.user["id"] == 1 and s.catalogs
    assert s.session_id != before_session and s.generation_id != before_generation
    assert s.draft is s.confirmation is s.last_speech is s.last_receipt is None
    assert not s.errors and not s.pending_request and not s.db.load_drafts(1)
    assert s.db.load_drafts(2)[0].id == other.id
    assert not old.valid(Draft(actor_id=1), 1, s.clock)
    kinds = []
    while not queue.empty():
        kinds.append(queue.get_nowait()["kind"])
    assert kinds == ["conversation_reset", "state"]
    assert (
        s.db.connection.execute(
            "SELECT COUNT(*) FROM events WHERE actor_id=1 AND kind='transcript'"
        ).fetchone()[0]
        == 0
    )
    assert (
        s.db.connection.execute("SELECT COUNT(*) FROM events WHERE actor_id=2").fetchone()[0] == 1
    )
    await s.submit("Nuevo ticket")
    assert s.draft is not None and not s.draft.payload.get("description")


async def test_reset_preserves_committed_operations_preferences_and_human_drafts(supervisor):
    from unittest.mock import AsyncMock

    s, _ = supervisor
    await s.start_request("En Tránsito la impresora no imprime")
    row = s.operations.prepare(s.session_id, s.draft, s.confirmation, s.profile)
    s.operations.set_status(row["operation_id"], "succeeded", receipt={"code": "IDL-TI-000001"})
    durable = s.db.operations()
    prefs = s.db.preferences(1)
    s.db.save_preferences(1, prefs)
    human = Draft(
        actor_id=1, owner="human", transferred=True, payload={"description": "Trabajo manual"}
    )
    s.db.save_draft(human)
    await s.reset_conversation()
    assert s.db.operations() == durable and s.db.preferences(1) == prefs
    assert human.id in {d.id for d in s.db.load_drafts(1)}
    assert not any(d.owner == "agent" and not d.transferred for d in s.db.load_drafts(1))
    assert not s.last_receipt and not s.db.operations(1, nonterminal=True)
    s.tickets.request = AsyncMock(return_value=s.catalogs)
    await s.authenticated(dict(s.user))
    assert not s.draft and not s.last_receipt, (
        "A restart/login must not restore cleared conversation context"
    )


@pytest.mark.parametrize("status", ["prepared", "dispatched", "outcome_unknown"])
async def test_pending_operation_refuses_reset_without_touching_chat_or_draft(supervisor, status):
    s, _ = supervisor
    await s.start_request("En Tránsito la impresora no imprime")
    row = s.operations.prepare(s.session_id, s.draft, s.confirmation, s.profile)
    s.operations.set_status(row["operation_id"], status)
    before = asdict(s.draft), s.generation_id, s.db.operations()
    with pytest.raises(ValueError, match="comprobarse"):
        await s.reset_conversation()
    assert (asdict(s.draft), s.generation_id, s.db.operations()) == before


@pytest.mark.parametrize("fails", [False, True])
async def test_late_model_reply_and_input_during_audio_shutdown_cannot_restore_chat(
    supervisor, fails
):
    s, _ = supervisor
    await s.start_request("En Tránsito la impresora no imprime")
    started, release = asyncio.Event(), asyncio.Event()
    model = Interpretation("repair_request", "En Informática la impresora falla")

    async def delayed(text):
        started.set()
        await release.wait()
        if fails:
            raise ValueError("Cloud no disponible")
        return type("Mention", (), {"origin": "Informática", "destination": ""})()

    model.incident_context = delayed
    s.interpreter = model
    work = asyncio.create_task(s.submit("Corregí: En Informática la impresora falla"))
    await asyncio.wait_for(started.wait(), 2)

    async def close_audio():
        await s.submit("Esto pertenece al micrófono viejo", source="voice")

    await s.reset_conversation(close_audio)
    release.set()
    await work
    assert not s.draft and not s.last_speech and s.state == State.DORMANT
    assert {r[0] for r in s.db.connection.execute("SELECT kind FROM events WHERE actor_id=1")} == {
        "conversation_reset",
        "state",
    }


def test_migration_scopes_existing_history_to_each_authenticated_actor(tmp_path):
    import json
    import sqlite3

    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.execute(
        "CREATE TABLE events(id INTEGER PRIMARY KEY,session_id TEXT,generation_id TEXT,kind TEXT,data TEXT,at TEXT)"
    )
    for actor in [1, 2]:
        c.execute(
            "INSERT INTO events(session_id,generation_id,kind,data,at) VALUES('same','g','state',?,'now')",
            (json.dumps({"user": {"id": actor}}),),
        )
        c.execute(
            "INSERT INTO events(session_id,generation_id,kind,data,at) VALUES('same','g','transcript',?,'now')",
            (json.dumps({"text": f"Chat {actor}"}),),
        )
    c.commit()
    c.close()
    db = Database(path)
    db.clear_conversation(1, "same")
    assert [r[0] for r in db.connection.execute("SELECT actor_id FROM events")] == [2, 2]
    db.close()


async def test_account_change_during_audio_shutdown_cannot_erase_another_actors_history(supervisor):
    s, _ = supervisor
    s.db.event("other", "g", "transcript", {"text": "Contenido de otra cuenta"}, actor_id=2)
    await s.start_request("En Tránsito la impresora no imprime")

    async def close_audio():
        s.user = {"id": 2, "role": "operator", "name": "Otro operador"}
        s.invalidate()

    with pytest.raises(ValueError, match="sesión cambió"):
        await s.reset_conversation(close_audio)
    assert s.db.load_drafts(1)
    assert (
        s.db.connection.execute("SELECT COUNT(*) FROM events WHERE actor_id=2").fetchone()[0] == 1
    )
    assert not s.resetting
