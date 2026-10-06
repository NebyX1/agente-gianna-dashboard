import asyncio
import threading
import time
from types import SimpleNamespace
import pytest
from pydantic import ValidationError
from gianna.dialogue.activation import candidate
from gianna.dialogue.draft import Draft
from gianna.dialogue.confirmations import Confirmation
from gianna.audio.turn_boundary import TurnBoundary
from gianna.models.decision_protocol import Choice, Noul
from gianna.runtime.cancellation import NativeWorker
from gianna.runtime.event_bus import EventBus
from gianna.runtime.operation_manager import OperationManager
from gianna.persistence.database import Database
from gianna.adapters.tickets_http import TicketError
from gianna.profiles.loader import load_profile, safe_reference
from gianna.tools.registry import ToolRegistry


@pytest.mark.parametrize(
    "text",
    ["mañana registro un ticket", "Diana, ayudame", "Ella se llama Gianna", "El nombre es Giana"],
)
def test_negative_activation(text):
    assert candidate(text) is None


@pytest.mark.parametrize("name", ["Gianna", "Giana", "Yianna", "Siana", "Iana"])
def test_wake_preserves_same_utterance(name):
    assert "impresora" in candidate(f"{name}, registrá un ticket de la impresora")


def test_confirmation_bound_to_actor_revision_payload_owner_expiry():
    d = Draft(1, payload={"description": "Literal original"})
    now = [10]

    def clock():
        return now[0]

    c = Confirmation.issue(d, clock, 120)
    assert c.valid(d, 1, clock)
    assert not c.valid(d, 2, clock)
    d.change(description="Corrección nueva")
    assert not c.valid(d, 1, clock)
    c = Confirmation.issue(d, clock, 120)
    d.owner = "human"
    assert not c.valid(d, 1, clock)
    d.owner = "agent"
    now[0] = 131
    assert not c.valid(d, 1, clock)


@pytest.mark.parametrize("order", [("complete", "transcript"), ("transcript", "complete")])
def test_turn_barrier_only_once_and_duplicate_segment(order):
    t = TurnBoundary()
    for action in order:
        if action == "complete":
            t.finish()
        else:
            t.transcript("segment1", "La impresora no imprime")
    t.transcript("segment1", "La impresora no imprime")
    assert t.consume() == "La impresora no imprime"
    assert t.consume() is None


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1, 1.1])
def test_tev_rejects_nonfinite_and_range(bad):
    with pytest.raises(ValidationError):
        Choice.model_validate(
            {
                "type": "choice",
                "choice": "a",
                "probabilities": {"a": bad, "b": 0},
                "confidence": 0.5,
            }
        )
    with pytest.raises(ValidationError):
        Noul.model_validate({"type": "noul", "noul": bad})


def test_tev_distribution_and_unknown_fields():
    with pytest.raises(ValidationError):
        Choice.model_validate(
            {"type": "choice", "choice": "x", "probabilities": {"a": 1}, "confidence": 0.5}
        )
    with pytest.raises(ValidationError):
        Choice.model_validate(
            {
                "type": "choice",
                "choice": "a",
                "probabilities": {"a": 0.1, "b": 0.2},
                "confidence": 0.5,
            }
        )
    with pytest.raises(ValidationError):
        Noul.model_validate({"type": "noul", "noul": 0.5, "execute": "shell"})


async def test_native_cancellation_keeps_physical_exclusion():
    worker = NativeWorker("test")
    started, release = threading.Event(), threading.Event()
    active = [0]

    def inference():
        active[0] += 1
        started.set()
        release.wait(3)
        active[0] -= 1

    task = asyncio.create_task(worker.run(inference))
    while not started.is_set():
        await asyncio.sleep(0.005)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert active[0] == 1
    with pytest.raises(RuntimeError, match="native_worker_busy"):
        await worker.run(lambda: None)
    release.set()
    await worker.close()
    assert active[0] == 0


def test_profile_rejects_escape_and_unknown_tools(tmp_path):
    with pytest.raises(ValueError):
        safe_reference(tmp_path, "../secret.json")
    with pytest.raises(ValueError):
        load_profile("../../secret")
    with pytest.raises(ValueError):
        load_profile(registry=ToolRegistry())


def test_event_saturation_is_explicit():
    bus = EventBus(2)
    q = bus.subscribe()
    bus.publish({"kind": "one"})
    bus.publish({"kind": "two"})
    bus.publish({"kind": "three"})
    assert q.get_nowait()["kind"] == "saturation"


class Adapter:
    def __init__(self):
        self.sent = []
        self.receipts = {}
        self.user = {"role": "operator"}
        self.allow = asyncio.Event()
        self.allow.set()

    async def revalidate(self, actor):
        assert actor == 1

    async def execute(self, row):
        self.sent.append(row)
        await self.allow.wait()
        receipt = {
            "operation_id": row["operation_id"],
            "payload_hash": row["payload_hash"],
            "event_ids": [1],
            "code": "IDL-TI-000001",
        }
        self.receipts[row["operation_id"]] = receipt
        return receipt

    async def verify(self, row):
        if row["operation_id"] not in self.receipts:
            raise TicketError("not_found", 404)
        return self.receipts[row["operation_id"]]


@pytest.fixture
def manager(tmp_path):
    db = Database(tmp_path / "agent.db")
    adapter = Adapter()
    m = OperationManager(db, adapter, SimpleNamespace(), time.monotonic)
    yield m
    db.close()


def prepared(m):
    draft = Draft(1, payload={"description": "Literal"})
    confirm = Confirmation.issue(draft, time.monotonic, 120, "session")
    row = m.prepare("session", draft, confirm, {"profile_id": "idl.tickets", "version": "1.0.0"})
    return row, draft, confirm


async def test_handoff_wins_before_dispatch(manager):
    row, draft, confirmation = prepared(manager)
    assert (await manager.handoff(draft))["transferred"]
    with pytest.raises(RuntimeError, match="cancelled_before_dispatch"):
        await manager.dispatch(row, draft, confirmation, lambda: True)
    assert not manager.adapter.sent
    assert manager.db.operations()[0]["status"] == "cancelled_before_dispatch"
    assert manager.db.load_drafts(1)[0].transferred


async def test_dispatch_wins_handoff_must_reconcile(manager):
    row, draft, confirmation = prepared(manager)
    manager.adapter.allow.clear()
    task = asyncio.create_task(manager.dispatch(row, draft, confirmation, lambda: True))
    while not manager.adapter.sent:
        await asyncio.sleep(0.001)
    with pytest.raises(RuntimeError, match="handoff_requires_reconciliation"):
        await manager.handoff(draft)
    manager.adapter.allow.set()
    await task
    assert (await manager.handoff(draft))["committed"]["code"] == "IDL-TI-000001"


async def test_crash_prepared_never_auto_dispatch(manager):
    row, _, _ = prepared(manager)
    await manager.recover(1)
    assert not manager.adapter.sent
    assert manager.db.operations()[0]["status"] == "cancelled_before_dispatch"


async def test_absent_receipt_still_unknown_blocks_new_write(manager):
    row, draft, confirmation = prepared(manager)
    manager.set_status(row["operation_id"], "outcome_unknown")
    result = await manager.recover(1)
    assert result[0]["status"] == "outcome_unknown"
    with pytest.raises(RuntimeError, match="reconciliation_required"):
        prepared(manager)
    assert not manager.adapter.sent


async def test_cancelled_waiter_late_receipt_is_durable(manager):
    row, draft, confirmation = prepared(manager)
    manager.adapter.allow.clear()
    task = asyncio.create_task(manager.dispatch(row, draft, confirmation, lambda: True))
    while not manager.adapter.sent:
        await asyncio.sleep(0.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert manager.db.operations()[0]["status"] == "outcome_unknown"
    manager.adapter.allow.set()
    await manager.close()
    assert manager.db.operations()[0]["status"] == "succeeded"
    assert len(manager.adapter.sent) == 1


async def test_generation_rejected_before_final_dispatch(manager):
    row, draft, confirmation = prepared(manager)
    with pytest.raises(RuntimeError, match="cancelled_before_dispatch"):
        await manager.dispatch(row, draft, confirmation, lambda: False)
    assert not manager.adapter.sent
