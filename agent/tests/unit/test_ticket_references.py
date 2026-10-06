"""Accessible public references must retain the canonical resource and exact totals."""

from copy import deepcopy

import pytest

from gianna.dialogue.numbers import ticket_number
from gianna.dialogue.spoken_text import accessible_ticket_text, code_number, spoken_code
from gianna.runtime.conversation_agent import ConversationAgent
from tests.unit.test_conversation_agent import harness  # noqa: F401
from tests.unit.test_dialogue import supervisor  # noqa: F401


@pytest.mark.parametrize(
    "text,number",
    [
        ("Leeme el ticket terminación 25", 25),
        ("ticket con terminación veinticinco", 25),
        ("terminación ciento veintitrés", 123),
        ("ticket número ciento uno", 101),
        ("ticket cien", 100),
        ("ticket doscientos treinta y cinco", 235),
        ("ticket mil veintitrés", 1023),
        ("ticket quince mil doscientos cuatro", 15204),
        ("ticket 1000001", 1000001),
        ("ticket terminación cuatro o cinco", None),
        ("ticket terminación 4 y ticket 25", None),
        ("ticket cuatro y cinco", None),
        ("ticket 4 y cinco", None),
        ("ticket IDL-TI-000004 y ticket ciento uno", None),
        ("ticket ciento", None),
        ("ticket cien cinco", None),
        ("ticket cero", None),
        ("Hay ciento veintitrés impresoras", None),
    ],
)
def test_short_reference_and_spoken_hundreds_are_unambiguous(text, number):
    assert ticket_number(text) == number


def test_speech_removes_only_padding_and_keeps_the_whole_number():
    text = "Tenés el ticket IDL-TI-000001, el IDL-TI-000025 y el IDL-TI-000123."
    assert accessible_ticket_text(text) == "Tenés el ticket número 1, el número 25 y el número 123."
    assert spoken_code("IDL-TI-1000001") == "número 1000001"
    assert code_number("IDL-TI-000101") == 101
    assert code_number("otro-código") is None
    assert (
        accessible_ticket_text("Hay 000025 hojas. IDL-TI-000000.")
        == "Hay 000025 hojas. IDL-TI-000000."
    )


async def test_generated_speech_is_short_but_receipt_is_unchanged(supervisor):  # noqa: F811
    s, _ = supervisor
    s.last_receipt = {"code": "IDL-TI-000025", "ticket_id": 91}
    original = deepcopy(s.last_receipt)
    heard = []

    async def speak(message):
        heard.append(message["text"])

    s.speak_callback = speak
    await s.say("Guardé el ticket IDL-TI-000025.")
    assert s.last_speech["text"] == heard[-1] == "Guardé el ticket número 25."
    assert s.last_receipt == original


async def test_counts_preserve_filters_and_total_without_returning_a_page(harness):  # noqa: F811
    s, agent, _ = harness
    previous = s.tickets.request

    async def request(method, path, **kwargs):
        result = await previous(method, path, **kwargs)
        return {**result, "total": 123, "pages": 123}

    s.tickets.request = request
    result, spoken = await agent.tools.call("count_tickets", {"origin_unit_id": 2}, "cuántos")
    assert result == {"total": 123, "filters": {"origin_unit_id": 2, "status": "active"}}
    assert s.test_requests[-1][2]["query"] == {
        "origin_unit_id": 2,
        "status": "active",
        "per_page": 1,
    }
    assert not spoken and not s.draft and not s.db.operations()
    result, _ = await agent.tools.call(
        "count_tickets", {"status": "resolved", "destination_unit_id": 1}, "resueltos"
    )
    assert result["filters"] == {"status": "resolved", "destination_unit_id": 1}


async def test_search_pages_and_context_keep_public_number_separate_from_id(harness):  # noqa: F811
    s, agent, _ = harness
    previous = s.tickets.request

    async def request(method, path, **kwargs):
        result = await previous(method, path, **kwargs)
        query = kwargs["query"]
        start = (query.get("page", 1) - 1) * query["per_page"]
        return {
            "items": [
                dict(result["items"][0], id=900 + n, code=f"IDL-TI-{n:06d}")
                for n in range(start + 1, min(start + query["per_page"], 25) + 1)
            ],
            "total": 25,
            "pages": 3,
            "page": query.get("page", 1),
            "per_page": query["per_page"],
        }

    s.tickets.request = request
    all_numbers = []
    for page in (1, 2, 3):
        result, _ = await agent.tools.call(
            "search_tickets", {"status": "active", "origin_unit_id": 2, "page": page}, "seguir"
        )
        projected = ConversationAgent.project("search_tickets", result)
        assert projected["total"] == 25 and projected["has_more"] == (page < 3)
        for row in projected["items"]:
            assert row["id"] == 900 + row["number"]
            assert row["spoken_reference"] == f"ticket número {row['number']}"
            all_numbers.append(row["number"])
    assert all_numbers == list(range(1, 26))
    assert not s.db.operations()


async def test_short_reference_reviews_the_real_id_not_a_partial_code(harness):  # noqa: F811
    s, _, _ = harness
    previous = s.tickets.request

    async def request(method, path, **kwargs):
        result = await previous(method, path, **kwargs)
        ticket = result["items"][0]
        return {**result, "items": [dict(ticket, id=104, code="IDL-TI-000104"), ticket]}

    s.tickets.request = request
    await s.resource_command("Pasá el ticket terminación cuatro a En curso", review_only=True)
    assert s.draft.resource == "tickets/91"
    assert s.draft.display_code == "IDL-TI-000004"
    assert "ticket número 4" in s.last_speech["text"]
    assert "000004" not in s.last_speech["text"] and not s.db.operations()
