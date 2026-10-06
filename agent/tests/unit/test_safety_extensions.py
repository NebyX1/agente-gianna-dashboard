import asyncio
import time
from types import SimpleNamespace
import pytest
from gianna.dialogue.confirmations import Confirmation
from gianna.dialogue.draft import Draft
from gianna.dialogue.numbers import ticket_number
from gianna.runtime.operation_manager import OperationManager
from gianna.persistence.database import Database
from gianna.audio.pipeline import DialogueProcessor
from tests.unit.test_core import Adapter
from gianna.config import Settings
from pydantic import ValidationError


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Mostrá ticket número cinco", 5),
        ("ticket cero cero cero cero dos tres", 23),
        ("ticket cuarenta y dos", 42),
        ("IDL-TI-000035", 35),
        ("ticket 4 o 5", None),
        ("ticket 4 y ticket 5", None),
        ("ticket cero", None),
        ("En Tránsito hay 5 impresoras", None),
    ],
)
def test_resource_number_must_be_unambiguous(text, expected):
    assert ticket_number(text) == expected


async def test_retry_keeps_identity_requires_new_session_confirmation(tmp_path):
    db = Database(tmp_path / "retry.db")
    manager = OperationManager(db, Adapter(), SimpleNamespace(), time.monotonic)
    d = Draft(1, payload={"description": "Datos exactos"})
    old = Confirmation.issue(d, time.monotonic, 120, "old-session")
    row = manager.prepare("old-session", d, old, {"profile_id": "idl.tickets", "version": "1.0.0"})
    manager.set_status(row["operation_id"], "outcome_unknown")
    row = db.operations()[0]
    with pytest.raises(RuntimeError, match="confirmation_invalid"):
        manager.prepare_retry("new-session", row, d, old)
    new = Confirmation.issue(d, time.monotonic, 120, "new-session")
    retry = manager.prepare_retry("new-session", row, d, new)
    assert (retry["operation_id"], retry["idempotency_key"], retry["payload_hash"]) == (
        row["operation_id"],
        row["idempotency_key"],
        row["payload_hash"],
    )
    assert db.operations()[0]["status"] == "outcome_unknown"
    await manager.dispatch(retry, d, new, lambda: True)
    manager.set_status(row["operation_id"], "outcome_unknown")
    assert db.operations()[0]["status"] == "succeeded"
    assert len(manager.adapter.sent) == 1
    db.close()


async def test_invalid_recovery_proof_remains_unknown(tmp_path):
    db = Database(tmp_path / "proof.db")
    adapter = Adapter()
    manager = OperationManager(db, adapter, SimpleNamespace(), time.monotonic)
    d = Draft(1, payload={"description": "Literal"})
    c = Confirmation.issue(d, time.monotonic, 120, "session")
    row = manager.prepare("session", d, c, {"profile_id": "idl.tickets", "version": "1.0.0"})
    manager.set_status(row["operation_id"], "outcome_unknown")
    adapter.receipts[row["operation_id"]] = {
        "operation_id": "other-operation",
        "payload_hash": d.digest,
        "event_ids": [1],
    }
    assert (await manager.recover(1))[0]["status"] == "outcome_unknown"
    assert not adapter.sent
    db.close()


async def test_accepted_stop_cancels_slow_semantics_not_native_or_http_effects():
    entered = asyncio.Event()
    stopped = asyncio.Event()
    calls = []

    class Supervisor:
        async def submit(self, text, **kwargs):
            calls.append(text)
            if text == "modelo lento":
                entered.set()
                await asyncio.sleep(10)
            stopped.set()

        def publish(self, *args):
            pass

    processor = DialogueProcessor(Supervisor(), None)
    processor.consumer = asyncio.create_task(processor.consume())
    processor.queue.put_nowait(("modelo lento", {}, None))
    await asyncio.wait_for(entered.wait(), 1)
    processor.queue.put_nowait(("pará", {}, None))
    await asyncio.wait_for(stopped.wait(), 1)
    assert calls == ["modelo lento", "pará"]
    await processor.cleanup()


def test_private_preferences_actor_isolation_and_retention(tmp_path):
    db = Database(tmp_path / "prefs.db")
    prefs = db.preferences(1)
    prefs["speed"] = 0.8
    db.save_preferences(1, prefs)
    assert db.preferences(1)["speed"] == 0.8 and db.preferences(2)["speed"] == 1
    with pytest.raises(Exception):
        db.save_preferences(1, {**prefs, "cloud_api_key": "not allowed"})
    db.close()


def test_engine_configuration_never_silently_changes_provider():
    with pytest.raises(ValidationError):
        Settings(stt_device="cpu", stt_compute_type="int8_float16")
    with pytest.raises(ValidationError):
        Settings(cloud_url="https://other.example")
    assert (
        Settings(stt_device="cpu", stt_compute_type="int8", stt_grace_seconds=45).stt_device
        == "cpu"
    )
