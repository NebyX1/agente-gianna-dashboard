import asyncio
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from gianna.dialogue.interpretation import creation_request
from gianna.dialogue.state_machine import State
from gianna.models.local_interpreter import TurnMeaning
from tests.unit.test_dialogue import supervisor as supervisor_fixture

supervisor = supervisor_fixture


class Interpretation:
    last_error = None

    def __init__(self, intent, content="", origin=""):
        self.intent, self.content, self.origin = intent, content, origin
        self.inputs = []

    async def classify(self, text, **context):
        self.inputs.append((text, context))
        return TurnMeaning(intent=self.intent, content=self.content)

    async def incident_context(self, text):
        return SimpleNamespace(origin=self.origin, destination="")


@pytest.mark.parametrize(
    "prefix",
    [
        "Yo necesito que escribas un ticket por mí porque ",
        "Necesito que escribas un ticket por mí. ",
        "Quiero que me redactes un pedido: ",
    ],
)
def test_natural_create_instruction_does_not_become_description(prefix):
    text = "nos pidieron poner nuevas hojas a las impresoras"
    assert creation_request(prefix + text).content == text


async def test_long_narrative_while_asking_type_keeps_the_whole_incident(supervisor):
    s, _ = supervisor
    await s.start_request("En Tránsito nos solicitaron asistencia")
    assert s.missing == "problem_type_id"
    text = "Nos pidieron poner nuevas hojas a las impresoras porque se quedaron sin papel"
    s.interpreter = Interpretation("field_data")
    await s.submit(text)
    assert s.interpreter.inputs, "A category inside a sentence must not bypass interpretation"
    assert text in s.draft.payload["description"]
    assert s.draft.payload["problem_type_id"] == 3
    assert s.state == State.WAITING_CONFIRMATION and not s.db.operations()


async def test_complaint_that_mentions_printers_is_not_a_type_answer(supervisor):
    s, _ = supervisor
    await s.start_request("En Tránsito nos solicitaron asistencia")
    before = asdict(s.draft)
    s.interpreter = Interpretation("feedback")
    await s.submit("Estás entendiendo mal lo que te dije de las impresoras")
    assert asdict(s.draft) == before
    assert s.missing == "description" and s.confirmation is None
    assert "Puedo registrar" not in s.last_speech["text"]
    assert "reemplazarla" in s.last_speech["text"] and not s.db.operations()


async def test_complete_correction_replaces_stale_description_and_unknown_origin(supervisor):
    s, _ = supervisor
    await s.start_request("En Tránsito la impresora no imprime")
    old_review = s.confirmation
    text = "desde Secretaría General nos pidieron poner nuevas hojas a las impresoras"
    s.interpreter = Interpretation("repair_request", text, "Secretaría General")
    await s.submit("No, eso está mal. Lo que dije es que " + text)
    assert s.draft.payload["description"] == text
    assert "origin_unit_id" not in s.draft.payload
    assert s.confirmation is None and not old_review.valid(s.draft, 1, s.clock)
    assert s.missing == "origin_unit_id" and "Secretaría General" in s.last_speech["text"]
    assert "no figura en el catálogo" in s.last_speech["text"] and not s.db.operations()
    s.interpreter = None
    await s.submit("Tránsito")
    assert s.state == State.WAITING_CONFIRMATION
    assert s.draft.payload["description"] == text and s.draft.payload["origin_unit_id"] == 2


async def test_incomplete_correction_waits_for_full_details_before_replacing(supervisor):
    s, _ = supervisor
    await s.start_request("En Tránsito la impresora no imprime")
    before = dict(s.draft.payload)
    s.interpreter = Interpretation("repair_request")
    await s.submit(
        "Necesito que escribas algo coherente, te estoy diciendo que recién de la dirección..."
    )
    assert s.draft.payload == before and s.confirmation is None and s.missing == "description"
    s.interpreter = Interpretation("field_data", origin="Tránsito")
    text = "En Tránsito nos pidieron poner nuevas hojas a las impresoras"
    await s.submit(text)
    assert s.draft.payload["description"] == text and s.state == State.WAITING_CONFIRMATION
    assert not s.db.operations()


async def test_data_during_review_updates_draft_and_requires_a_new_review(supervisor):
    s, _ = supervisor
    await s.start_request("En Tránsito la impresora no imprime")
    old = s.confirmation
    text = "hay que poner nuevas hojas a las impresoras"
    s.interpreter = Interpretation("append_request", text)
    await s.submit("También " + text)
    assert "poner nuevas hojas" in s.draft.payload["description"]
    assert s.confirmation.id != old.id and not old.valid(s.draft, 1, s.clock)
    assert not s.db.operations()


async def test_unknown_question_is_never_written_as_a_description(supervisor):
    s, _ = supervisor
    await s.start_request()
    before = asdict(s.draft)
    s.interpreter = Interpretation("clarify")
    await s.submit("Qué tiempo va a hacer mañana")
    assert asdict(s.draft) == before and not s.db.operations()


async def test_late_context_extraction_cannot_change_draft_after_pause(supervisor):
    s, _ = supervisor
    await s.start_request("En Tránsito la impresora no imprime")
    before = asdict(s.draft)
    entered, release = asyncio.Event(), asyncio.Event()
    text = "En Informática nos pidieron poner nuevas hojas a las impresoras"
    model = Interpretation("repair_request", text)

    async def delayed(text):
        entered.set()
        await release.wait()
        return SimpleNamespace(origin="Informática", destination="")

    model.incident_context = delayed
    s.interpreter = model
    working = asyncio.create_task(s.submit("No, lo correcto es: " + text))
    await asyncio.wait_for(entered.wait(), 2)
    await s.pause()
    release.set()
    await working
    assert asdict(s.draft) == before and s.state == State.PAUSED and not s.db.operations()
