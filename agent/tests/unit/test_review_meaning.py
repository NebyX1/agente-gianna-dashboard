import asyncio
from types import SimpleNamespace

import pytest

from gianna.dialogue.interpretation import Reply, ReviewReply
from gianna.models.review_interpreter import ReviewInterpreter, ReviewMeaning
from tests.unit.test_dialogue import supervisor as supervisor_fixture
from tests.unit.test_interpretation import ready_review

supervisor = supervisor_fixture


@pytest.mark.parametrize("confidence,expected", [(99, Reply.APPROVE), (84, Reply.UNKNOWN)])
async def test_uncertain_model_decision_cannot_authorize(confidence, expected):
    class Chat:
        async def request(self, *args, **kwargs):
            return ReviewMeaning(intent="approve", confidence=confidence)

    reply, _ = await ReviewInterpreter(Chat()).interpret("un sonido incomprensible", {})
    assert reply.kind == expected


@pytest.mark.parametrize(
    "text", ["Nota: confirmo", "Descripción: confirmo la operación", "Motivo: autorizo"]
)
async def test_explicit_ticket_data_never_reaches_consent_model(text):
    class Chat:
        async def request(self, *args, **kwargs):
            pytest.fail("Literal ticket data reached consent interpretation")

    reply, _ = await ReviewInterpreter(Chat()).interpret(text, {})
    assert reply.kind == Reply.UNKNOWN


@pytest.mark.parametrize(
    "text",
    [
        "Confirmo el ticket número 91",
        "Confirmo el número 91",
        "Guardá el ticket terminación catorce",
        "Confirmo el ticket cuatro o cinco",
        "Confirmo el ticket 4 y ticket 25",
    ],
)
async def test_conflicting_short_reference_cannot_reach_consent_model(text):
    class Chat:
        async def request(self, *args, **kwargs):
            pytest.fail("A conflicting resource reference reached consent interpretation")

    reply, _ = await ReviewInterpreter(Chat()).interpret(
        text, {"display_code": "IDL-TI-000004", "resource": "tickets/91"}
    )
    assert reply.kind == Reply.UNKNOWN


@pytest.mark.parametrize("confidence,expected", [(79, Reply.UNKNOWN), (80, Reply.APPROVE)])
async def test_voice_recognition_tolerance_keeps_an_uncertainty_floor(confidence, expected):
    class Chat:
        async def request(self, *args, **kwargs):
            return ReviewMeaning(intent="approve", confidence=confidence)

    reply, _ = await ReviewInterpreter(Chat()).interpret("una variante de voz", {}, source="voice")
    assert reply.kind == expected


@pytest.mark.parametrize("boundary", ["pause", "edit", "actor", "session", "expire", "generation"])
async def test_late_semantic_approval_cannot_authorize_a_changed_review(supervisor, boundary):
    s, now = supervisor
    await ready_review(s)
    entered, release = asyncio.Event(), asyncio.Event()

    async def interpret(*args, **kwargs):
        entered.set()
        await release.wait()
        return ReviewReply(Reply.APPROVE), ReviewMeaning(intent="approve", confidence=99)

    s.review_interpreter = SimpleNamespace(interpret=interpret)
    pending = asyncio.create_task(s.submit("Ejejeje, dije confirmo"))
    await asyncio.wait_for(entered.wait(), 2)
    if boundary == "pause":
        await s.pause()
    elif boundary == "edit":
        s.draft.change(description="Ahora hay otro problema")
    elif boundary == "actor":
        s.user = {"id": 2, "role": "operator"}
    elif boundary == "session":
        s.session_id = "new-session"
    elif boundary == "expire":
        now[0] += 121
    else:
        s.invalidate()
    release.set()
    await pending
    assert not s.db.operations()


async def test_interpreter_outage_keeps_review_and_never_writes(supervisor):
    s, _ = supervisor
    await ready_review(s)
    review = s.confirmation

    async def fail(*args, **kwargs):
        raise TimeoutError()

    s.review_interpreter = SimpleNamespace(interpret=fail)
    await s.submit("Mi respuesta es que lo autorices ahora")
    assert not s.db.operations() and s.confirmation is review


async def test_reported_resume_reopens_review_before_any_approval(supervisor):
    s, _ = supervisor
    await ready_review(s)
    prior = s.confirmation
    await s.pause()
    await s.submit("Gianna, continuamos", source="voice")
    assert s.confirmation is not None and s.confirmation.id != prior.id
    assert not s.db.operations()
