"""Intent boundaries, independent of model accuracy and all remote writes."""
import asyncio
from dataclasses import asdict

import httpx
import pytest

from gianna.config import Settings
from gianna.models.local_interpreter import LocalInterpreter, TurnMeaning
from gianna.dialogue.state_machine import State
from tests.unit.test_dialogue import supervisor as supervisor_fixture

supervisor = supervisor_fixture


class Interpreter:
    last_error = None
    def __init__(self, intent):
        self.intent = intent
    async def classify(self, text, **kwargs):
        return TurnMeaning(intent=self.intent, content=text if self.intent == "incident" else "")


@pytest.mark.parametrize("text", [
    "Te dije a ver si me habías escuchado", "No sé qué querés que diga",
    "El clima está raro", "Me estás entendiendo mal", "Quería preguntarte otra cosa",
])
async def test_unknown_without_interpreter_cannot_open_draft(supervisor, text):
    s, _ = supervisor
    s.interpreter = None
    await s.activate()
    await s.submit(text)
    assert s.draft is None and s.confirmation is None and s.pending_request is None
    assert not s.db.operations() and not s.db.load_drafts(1)


@pytest.mark.parametrize("stage", ["empty", "description", "origin", "review", "paused"])
async def test_semantic_presence_is_conversation_at_every_stage(supervisor, stage):
    s, _ = supervisor
    if stage != "empty":
        await s.start_request("En Tránsito la impresora no imprime" if stage == "review" else "")
        if stage == "origin":
            await s.submit("La impresora no imprime desde esta mañana")
    else:
        await s.activate()
    if stage == "paused":
        await s.pause()
    before = asdict(s.draft) if s.draft else None
    old_review, field = s.confirmation, s.missing
    s.interpreter = Interpreter("presence")
    await s.submit("Te dije a ver si me habías escuchado")
    assert (asdict(s.draft) if s.draft else None) == before
    assert s.confirmation is old_review and s.missing == field
    assert "Sí, estoy acá y te escucho" in s.last_speech["text"]
    if stage == "description":
        assert "Contame qué pasó" in s.last_speech["text"]
        assert "¿De qué oficina" not in s.last_speech["text"]
    assert not s.db.operations()


async def test_unsolicited_incident_requires_start_consent_then_separate_write_consent(supervisor):
    s, _ = supervisor
    s.interpreter = Interpreter("incident")
    await s.submit("En Tránsito la impresora no imprime")
    assert s.draft is None and s.pending_request and not s.db.load_drafts(1)
    await s.submit("Sí, registralo")
    assert s.state == State.WAITING_CONFIRMATION
    assert s.draft.payload["description"] == "En Tránsito la impresora no imprime"
    assert s.pending_request is None and not s.db.operations()


@pytest.mark.parametrize("change", ["expired", "intervening_question", "logout"])
async def test_offer_cannot_outlive_its_question_or_session(supervisor, change):
    s, now = supervisor
    s.interpreter = Interpreter("incident")
    await s.submit("En Tránsito la impresora no imprime")
    if change == "expired":
        now[0] += 121
    elif change == "intervening_question":
        await s.submit("¿Me escuchás?")
    else:
        await s.auth_invalidated()
        assert s.snapshot()["pending_request"] is None
        return
    await s.submit("Sí, registralo")
    assert s.draft is None and not s.db.operations()


async def test_late_interpretation_cannot_resume_or_pollute_paused_draft(supervisor):
    s, _ = supervisor
    await s.start_request()
    before = asdict(s.draft)
    entered, release = asyncio.Event(), asyncio.Event()
    class Delayed:
        async def classify(self, text, **kwargs):
            entered.set()
            await release.wait()
            return TurnMeaning(intent="field_data", content=text)
    s.interpreter = Delayed()
    pending = asyncio.create_task(s.submit("La impresora muestra un error"))
    await asyncio.wait_for(entered.wait(), 2)
    await s.pause()
    release.set()
    await pending
    assert asdict(s.draft) == before and s.state == State.PAUSED
    assert not s.db.operations()


@pytest.mark.parametrize("instruction", ["Descartar borrador", "Quiero descartar el borrador de este pedido", "Gianna, descartá este borrador", "Podés borrar el borrador"])
async def test_discard_is_local_and_cannot_be_recovered_as_active(supervisor, instruction):
    s, _ = supervisor
    await s.start_request("En Tránsito la impresora no imprime")
    old_id = s.draft.id
    await s.submit(instruction)
    assert s.draft is None and s.confirmation is None and s.missing is None
    assert next(d for d in s.db.load_drafts(1) if d.id == old_id).owner == "discarded"
    await s.submit("Retomar")
    assert s.draft is None and not s.db.operations()


async def test_ambient_discard_still_requires_voice_activation(supervisor):
    s, _ = supervisor
    await s.start_request("En Tránsito la impresora no imprime")
    before = asdict(s.draft)
    await s.pause()
    await s.submit("Quiero descartar el borrador de este pedido", source="voice")
    assert asdict(s.draft) == before and not s.db.operations()


async def test_interpreter_outage_does_not_affect_direct_wake(supervisor):
    s, _ = supervisor
    s.interpreter = Interpreter("clarify")
    s.interpreter.last_error = "interpreter_unavailable"
    await s.submit("Gianna, me escuchás?", source="voice")
    assert s.last_speech and s.state == State.INVITING
    assert s.draft is None and not s.db.operations()


@pytest.mark.parametrize("phase", ["missing", "review"])
async def test_model_hypothesis_cannot_replace_current_request(supervisor, phase):
    s, _ = supervisor
    await s.start_request("En Tránsito la impresora no imprime" if phase == "review" else "")
    before, binding, field = asdict(s.draft), s.confirmation, s.missing
    s.interpreter = Interpreter("start_request")
    await s.submit("Eso es todo Gianna de Gistrá")
    assert asdict(s.draft) == before and s.confirmation is binding and s.missing == field
    assert not s.db.operations()


@pytest.mark.parametrize("hypothesis", ["end_conversation", "pause", "resume", "manual_control"])
async def test_unclear_review_cannot_change_flow_based_on_model_alone(supervisor, hypothesis):
    s, _ = supervisor
    await s.start_request("En Tránsito la impresora no imprime")
    before, binding, state = asdict(s.draft), s.confirmation, s.state
    s.interpreter = Interpreter(hypothesis)
    await s.submit("Eso es todo Gianna de Gistrá")
    assert asdict(s.draft) == before and s.confirmation is binding and s.state == state
    assert not s.db.operations()


@pytest.mark.parametrize("response", [
    {"message": {"content": '{"intent":"commit"}'}},
    {"message": {"content": '{"intent":"field_data","operation":"delete"}'}},
    {"message": {"content": 'not json'}},
    {},
])
async def test_invalid_model_output_is_clarification(response):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=response)
    )) as client:
        model = LocalInterpreter(Settings(), client)
        result = await model.classify("una frase cualquiera", has_draft=True)
        assert result.intent == "clarify" and model.last_error
