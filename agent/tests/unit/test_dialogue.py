import pytest
from gianna.runtime.supervisor import Supervisor
from gianna.runtime.event_bus import EventBus
from gianna.runtime.operation_manager import OperationManager
from gianna.persistence.database import Database
from gianna.config import Settings
from gianna.dialogue.state_machine import State
from gianna.profiles.loader import load_profile


class Tev:
    async def choose(self, text, criteria, context=""):
        return "invoke" if "invoke" in criteria else "clarify"


class DataInterpreter:
    """Unit transport double: tests supply ticket data; semantic accuracy is tested on Ollama."""
    last_error = None

    async def classify(self, text, *, has_draft=False, **kwargs):
        from gianna.models.local_interpreter import TurnMeaning
        return TurnMeaning(intent="field_data" if has_draft else "clarify", content=text)


class Tickets:
    user = {"id": 1, "role": "operator"}
    token = "test"


@pytest.fixture
def supervisor(tmp_path):
    db = Database(tmp_path / "agent.db")
    config = Settings()
    now = [100]

    def clock():
        return now[0]

    tickets = Tickets()
    manager = OperationManager(db, tickets, config, clock)
    s = Supervisor(
        config, db, EventBus(), tickets, Tev(), manager, load_profile(), None, clock=clock
    )
    s.interpreter = DataInterpreter()
    s.user = {"id": 1, "role": "operator", "name": "Operador"}
    s.catalogs = {
        "default_destination_unit_id": 1,
        "org_units": [
            {"id": 1, "name": "Informática", "code": "TI", "can_receive_tickets": True},
            {"id": 2, "name": "Tránsito", "code": "TRANSITO", "can_receive_tickets": False},
        ],
        "problem_types": [{"id": 3, "name": "Impresoras", "code": "IMPRESORA"}],
        "statuses": [],
    }
    s.state = State.DORMANT
    yield s, now
    s.cancel_idle()
    db.close()


async def test_same_wake_utterance_and_literal_description(supervisor):
    s, now = supervisor
    await s.submit(
        "Gianna, registrá un ticket. En Tránsito la impresora no imprime y dice cancelar impresión"
    )
    assert s.state == State.WAITING_CONFIRMATION
    assert s.draft.payload["origin_unit_id"] == 2
    assert s.draft.payload["problem_type_id"] == 3
    assert "cancelar impresión" in s.draft.payload["description"]
    assert not s.db.operations()


async def test_idle_only_armed_by_current_client_playback(supervisor):
    s, now = supervisor
    await s.activate()
    assert s.idle_deadline is None
    m = s.last_speech
    await s.playback_complete("old", m["generation_id"])
    assert s.idle_deadline is None
    await s.playback_complete(m["utterance_id"], m["generation_id"])
    assert s.idle_deadline == 220
    assert s.state == State.WAITING_INITIAL_INPUT


async def test_candidate_at_119_seconds_and_rejected_noise_does_not_reset(supervisor):
    s, now = supervisor
    await s.activate()
    m = s.last_speech
    await s.playback_complete(m["utterance_id"], m["generation_id"])
    original = s.idle_deadline
    now[0] = 219.9
    await s.vad_started()
    assert s.candidate_grace_deadline > original
    assert s.speech_candidate_at < original
    await s.rejected_audio({"reason": "impulse"})
    assert s.idle_deadline == original
    now[0] = 221
    await s.expire_idle(s.idle_version)
    assert s.state == State.DORMANT
    assert not s.db.operations()


async def test_stale_timeout_after_valid_turn_does_nothing(supervisor):
    s, now = supervisor
    await s.activate(initial="nuevo ticket")
    m = s.last_speech
    await s.playback_complete(m["utterance_id"], m["generation_id"])
    old = s.idle_version
    await s.submit("En Tránsito la impresora no imprime desde esta mañana")
    assert s.state == State.WAITING_CONFIRMATION
    await s.expire_idle(old)
    assert s.state == State.WAITING_CONFIRMATION
    assert s.confirmation


async def test_correction_invalidates_previous_confirmation_and_pause_keeps_draft(supervisor):
    s, now = supervisor
    await s.activate(initial="nuevo ticket")
    await s.submit("En Tránsito la impresora no imprime")
    c = s.confirmation
    await s.submit("Corregí la descripción: La impresora muestra error de papel")
    assert not c.valid(s.draft, 1, s.clock)
    await s.pause()
    assert s.state == State.PAUSED and s.draft
    assert s.confirmation is None
    assert not s.db.operations()


async def test_field_correction_does_not_pollute_literal_description(supervisor):
    s, _ = supervisor
    await s.activate(initial="nuevo ticket")
    await s.submit("En Tránsito la impresora no imprime")
    original = s.draft.payload["description"]
    await s.submit("Cambiá el origen a Informática")
    assert s.draft.payload["origin_unit_id"] == 1
    assert s.draft.payload["description"] == original


async def test_yes_but_is_correction_not_a_write(supervisor):
    s, _ = supervisor
    await s.activate(initial="nuevo ticket")
    await s.submit("En Tránsito la impresora no imprime")
    old = s.confirmation
    await s.submit("Sí, pero agregá que tiene papel atascado")
    assert "tiene papel atascado" in s.draft.payload["description"]
    assert not old.valid(s.draft, 1, s.clock)
    assert not s.db.operations()


async def test_auth_switch_hides_previous_actor_data(supervisor):
    s, _ = supervisor
    await s.activate(initial="nuevo ticket")
    await s.submit("En Tránsito la impresora no imprime")
    old_id = s.draft.id
    await s.auth_invalidated()
    assert s.snapshot()["draft"] is None
    assert s.last_speech is None
    assert s.db.load_drafts(1)[0].id == old_id
    assert s.db.load_drafts(2) == []


async def test_late_authentication_cannot_restore_logged_out_user(supervisor):
    import asyncio

    s, _ = supervisor
    entered, release = asyncio.Event(), asyncio.Event()

    async def request(*args):
        entered.set()
        await release.wait()
        return {"old": True}

    s.tickets.request = request
    task = asyncio.create_task(s.authenticated({"id": 2, "role": "operator", "name": "Otro"}))
    await entered.wait()
    await s.auth_invalidated()
    release.set()
    await task
    assert s.user is None and s.catalogs is None and s.state == State.AUTH_REQUIRED


async def test_incident_date_is_reviewed_only_after_required_fields(supervisor):
    s, _ = supervisor
    await s.activate(initial="nuevo ticket")
    await s.submit("Fecha del incidente: 2026-10-03T14:30:00-03:00")
    assert s.state == State.ASKING_MISSING_FIELD and s.confirmation is None
    await s.submit("Tránsito")
    await s.submit("Impresoras")
    await s.submit("La impresora no imprime desde ayer")
    assert s.state == State.WAITING_CONFIRMATION
    assert "3/10/2026" in s.last_speech["text"] and "14:30" in s.last_speech["text"]


@pytest.mark.parametrize("verb", ["mostrame", "muéstrame", "mostrá", "muestra", "leeme"])
async def test_read_synonyms_remain_read_only(supervisor, verb):
    s, _ = supervisor
    calls = []

    async def tool(name, args):
        calls.append(name)
        if name == "tickets.search.v1":
            return {
                "items": [
                    {
                        "id": 10,
                        "code": "IDL-TI-000010",
                        "origin": {"name": "Tránsito"},
                        "description": "No imprime",
                    }
                ]
            }
        return {"shown": True, "url": "http://localhost/tickets/10"}

    s.tool = tool
    await s.activate(initial=f"por favor {verb} el ticket número 10")
    assert calls == ["tickets.search.v1", "browser.show.v1"]
    assert s.draft is None and not s.db.operations()


async def test_repeat_question_keeps_current_draft_even_after_an_older_receipt(supervisor):
    s, _ = supervisor
    s.last_receipt = {"code": "IDL-TI-000001"}
    await s.activate(initial="nuevo ticket")
    await s.submit("En Tránsito la impresora no imprime")
    question = s.last_speech["text"]
    await s.repeat()
    assert s.last_speech["text"] == question
    await s.repeat(code_only=True)
    assert "0, 0, 0, 0, 0, 1" in s.last_speech["text"]


async def test_unclear_yes_does_not_replace_archive_reason_or_write(supervisor):
    from gianna.dialogue.draft import Draft

    s, _ = supervisor
    s.draft = Draft(
        1,
        tool="tickets.archive.v1",
        resource="tickets/1",
        payload={"version": 1, "reason": "Es una prueba"},
    )
    await s.review()
    old = s.confirmation
    await s.submit("Sí, eso restado")
    assert s.draft.payload["reason"] == "Es una prueba"
    assert s.confirmation is old and not s.db.operations()
    assert "El borrador sigue igual y no lo envié" in s.last_speech["text"]
