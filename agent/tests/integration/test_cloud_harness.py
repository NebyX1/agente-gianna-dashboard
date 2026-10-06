"""Live DeepSeek multi-turn semantics against explicit read-only catalogue fixtures.

Real API/browser/audio trajectories live in test_harness_voice.py. These tests
exercise conversation context and tool selection, not a keyword classifier bank.
"""

from copy import deepcopy
import json
import os
import re

import httpx
import pytest
from gianna.config import ROOT
from gianna.dialogue.activation import normalize
from gianna.dialogue.state_machine import State
from gianna.models.cloud_interpreter import CloudInterpreter
from gianna.models.ollama_cloud import CloudChat
from tests.unit.test_conversation_agent import harness  # noqa: F401
from tests.unit.test_dialogue import supervisor  # noqa: F401

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("GIANNA_CLOUD_HARNESS") != "1", reason="Explicit live DeepSeek conversations"
    ),
]


@pytest.fixture
async def live(harness):  # noqa: F811 - imported pytest fixture
    s, agent, _ = harness
    async with httpx.AsyncClient() as client:
        agent.chat = CloudChat(s.config, client)
        s.interpreter = s.tev = CloudInterpreter(s.config, client)
        exchanges = []

        async def say(text):
            await s.submit(text)
            assert s.last_speech and "No pude completar esa consulta" not in s.last_speech["text"]
            assert not s.db.operations(), "No explicit confirmation was issued"
            exchanges.append(
                {"user": text, "answer": s.last_speech["text"], "draft": s.snapshot()["draft"]}
            )
            print("Harness live:", text, "->", s.last_speech["text"], flush=True)
            return normalize(s.last_speech["text"])

        yield s, say
        target = ROOT.parent / "artifacts/gianna-harness-repair-cloud.json"
        previous = json.loads(target.read_text(encoding="utf-8")) if target.exists() else []
        target.write_text(
            json.dumps(previous + exchanges, ensure_ascii=False, indent=2), encoding="utf-8"
        )


async def test_reported_creation_catalogues_followups_selection_and_correction(live):
    s, say = live
    await say(
        "Gianna, necesito que crees un nuevo ticket para mí, que es un pedido de la Secretaría General para cambiarle las hojas a todas las impresoras que se quedaron sin hojas en esa secretaría."
    )
    assert s.draft.payload["origin_unit_id"] == 7
    assert s.draft.payload["problem_type_id"] == 3
    original, revision = deepcopy(s.draft.payload), s.draft.revision
    assert (
        "para mí" not in original["description"]
        and "que es un pedido" not in original["description"]
    )
    reply = await say("¿Qué áreas registradas tenés?")
    assert all(normalize(r["name"]) in reply for r in s.catalogs["org_units"])
    assert s.draft.payload == original and s.draft.revision == revision
    assert any(r[1] == "/api/v1/catalogs" for r in s.test_requests)
    second = re.search(r"2[.)]\s*(?:\*\*)?([^\n]+)", s.last_speech["text"])
    assert second, "Catalogue choices must be numbered for follow-up selection"
    chosen = next(
        r["id"] for r in s.catalogs["org_units"] if normalize(r["name"]) in normalize(second[1])
    )
    await say("Elegí la segunda de las que me dijiste como origen")
    assert (
        s.draft.payload["origin_unit_id"] == chosen
        and s.draft.payload["description"] == original["description"]
    )
    reply = await say("¿Y qué tipos de problema hay?")
    assert "impresoras" in reply and s.draft.payload["description"] == original["description"]
    reply = await say("¿Qué te pedí registrar?")
    assert "impresoras" in reply and ("hojas" in reply or "papel" in reply)
    await say(
        "No, eso quedó mal. Lo que dije es que desde Secretaría General nos pidieron poner nuevas hojas a las impresoras"
    )
    assert s.draft.payload["origin_unit_id"] == 7
    assert {"poner", "nuevas", "hojas"} <= set(normalize(s.draft.payload["description"]).split())
    assert "eso quedó mal" not in s.draft.payload["description"]
    assert s.state == State.WAITING_CONFIRMATION


async def test_natural_resume_reopens_real_review(live):
    s, say = live
    await say("Creá un ticket: en Sociales necesitan hojas para las impresoras")
    original, old_review = deepcopy(s.draft.payload), s.confirmation
    await s.pause()
    await say("Gianna, ya estoy de vuelta. Sigamos con lo que habíamos dejado pendiente")
    assert s.state == State.WAITING_CONFIRMATION
    assert s.draft.payload == original and s.confirmation.id != old_review.id


async def test_unknown_office_query_and_known_alternative_never_pollute_description(live):
    s, say = live
    incident = "Creá un ticket: desde la Oficina Atlántida piden hojas para las impresoras"
    reply = await say(incident)
    assert "atlantida" in reply and ("no figura" in reply or "no existe" in reply or "no esta" in reply)
    assert not s.draft or not s.draft.payload.get("origin_unit_id")
    # An unknown office may be clarified before opening the draft. The product
    # requirement is retaining the incident and completing it from that history,
    # not the exact point at which a local Draft object is allocated.
    assert any(m.get("content") == incident for m in s.db.conversation_messages(1, s.session_id))
    description = s.draft.payload["description"] if s.draft else None
    reply = await say("¿Qué oficinas o áreas puedo usar entonces?")
    assert "transito" in reply and "secretaria general" in reply
    if description is not None:
        assert s.draft.payload["description"] == description
    await say("Usá Tránsito como origen de este pedido")
    assert s.draft.payload["origin_unit_id"] == 2
    if description is not None:
        assert s.draft.payload["description"] == description
    else:
        description = s.draft.payload["description"]
        assert "impresora" in normalize(description)
        assert "hojas" in normalize(description) or "papel" in normalize(description)
    assert s.draft.payload["problem_type_id"] == 3
    assert s.state == State.WAITING_CONFIRMATION
    reply = await say("No lo envíes todavía, ¿qué destino tiene?")
    assert "informatica" in reply and not s.db.operations()


async def test_complete_incident_with_noisy_preamble_updates_all_facts(live):
    s, say = live
    await say("Creá un ticket: desde Tránsito nos pidieron revisar una impresora")
    await say(
        "Dijeres que desde Secretaría General nos pidieron poner nuevas hojas a las impresoras"
    )
    assert s.draft.payload["origin_unit_id"] == 7
    assert {"poner", "nuevas", "hojas"} <= set(normalize(s.draft.payload["description"]).split())
    assert "Tránsito" not in s.draft.payload["description"]
    assert s.state == State.WAITING_CONFIRMATION


async def test_existing_ticket_read_then_status_and_note_without_generated_write(live):
    s, say = live
    reply = await say("¿Qué problema tiene el ticket IDL-TI-000004?")
    assert "imprime" in reply and "ayer" in reply
    assert any(r[1] == "/api/v1/tickets" for r in s.test_requests)
    await say("Me gustaría poner el cuatro en curso")
    assert s.draft.tool == "tickets.status.v1" and s.draft.resource == "tickets/91"
    assert s.draft.payload["status"] == "in_progress" and s.confirmation
    reply = await say("¿Ya lo guardaste?")
    assert "no " in reply or "todavia" in reply or "sin enviar" in reply
    # After an explicit new request, terminal transitions still need a reason.
    # The read fixture starts at Nuevo, so resolving is correctly rejected.
    reply = await say("Me gustaría resolver el ticket cuatro")
    assert "no puede pasar directamente" in reply and "curso" in reply
    assert s.draft.payload["status"] == "in_progress" and not s.db.operations()


@pytest.mark.parametrize(
    "question,need",
    [
        ("¿Secretaría General existe en el catálogo?", "secretaria general"),
        ("¿Qué tipos de problemas se pueden registrar?", "impresoras"),
        ("¿Qué destinos pueden recibir los tickets?", "informatica"),
        ("¿Qué oficinas tenés disponibles?", "secretaria general"),
        ("¿Tenés tickets relacionados con impresoras?", "idl-ti-000004"),
    ],
)
async def test_daily_queries_answer_the_requested_fact(live, question, need):
    s, say = live
    reply = await say(question)
    assert need in reply and s.draft is None


@pytest.mark.parametrize(
    "incident",
    [
        "¿Sabes qué es lo que quiero? Registrar un ticket nuevo y lo que registres es un ticket a la dirección de sociales que nos pidieron recién hace un ratito cambiar las hojas de las impresoras. ¿Podés anotar eso?",
        "Anotame lo que acaba de llamar Servicios Sociales: necesitan que cambiemos las hojas de todas las impresoras. Abrí un pedido con eso, por favor.",
        "Me llamaron de Sociales hace un rato por las impresoras, se quedaron sin papel. Necesito registrarlo.",
        "Hacé un ticket para el área social, pidieron reponer papel de las impresoras.",
    ],
)
async def test_reported_sociales_incident_and_paraphrases_prepare_without_reasking(live, incident):
    s, say = live
    await say(incident)
    assert s.draft is not None, "An explicit registration request must prepare a draft"
    assert s.draft.payload["origin_unit_id"] == 4
    assert s.draft.payload["problem_type_id"] == 3
    assert s.draft.payload["destination_unit_id"] == 1
    assert s.state == State.WAITING_CONFIRMATION
    description = s.draft.payload["description"]
    assert "impresora" in normalize(description)
    await say("Te acabo de decir la oficina de servicios sociales")
    assert s.draft.payload["origin_unit_id"] == 4
    assert s.draft.payload["description"] == description
    reply = await say("¿Por qué no pudiste completar el pedido?")
    assert "cita literal" not in reply and "no se que" not in reply
    assert s.draft.payload["description"] == description


async def test_prior_incident_followed_by_registration_and_office_clarification(live):
    s, say = live
    await say("Quiero que registres un ticket: nos pidieron cambiar las hojas de las impresoras")
    assert s.draft and s.missing == "origin_unit_id"
    description = s.draft.payload["description"]
    await say("Te acabo de decir la oficina de servicios sociales")
    assert s.draft.payload["origin_unit_id"] == 4
    assert s.draft.payload["description"] == description
    assert s.state == State.WAITING_CONFIRMATION


async def test_semantic_correction_queries_and_no_change_request(live):
    s, say = live
    await say("Registrá un ticket: Tránsito dice que la impresora no imprime")
    await say("No, entendiste mal: en Servicios Sociales sí imprimen, pidieron más hojas")
    assert s.draft.payload["origin_unit_id"] == 4
    assert "no imprime" not in normalize(s.draft.payload["description"])
    payload, revision = deepcopy(s.draft.payload), s.draft.revision
    await say("¿A quién se lo estamos enviando?")
    assert s.draft.payload == payload and s.draft.revision == revision
    await say("No modifiques nada todavía")
    assert s.draft.payload == payload and not s.db.operations()


@pytest.mark.parametrize(
    "incident,origin,problem",
    [
        (
            "Abrí un pedido por favor: desde Urbanismo no logran cargar ninguna página de Internet",
            None,
            8,
        ),
        ("Registrá que en Tránsito todos los equipos perdieron acceso a internet desde hoy", 2, 8),
        ("Haceme un ticket para Secretaría General: una computadora no enciende", 7, 9),
        (
            "Hay que dejar asentado el pedido de Sociales por el usuario del sistema de expedientes: al entrar le rechaza la contraseña",
            4,
            10,
        ),
        ("Creá un ticket porque en Secretaría General se rompió el teclado de una PC", 7, 9),
        (
            "Anotá como solicitud que Sociales no puede iniciar sesión en el sistema de recaudación",
            4,
            10,
        ),
        (
            "Tránsito llamó por papel atascado y una luz roja en la impresora. Quiero abrir el ticket con esos dos detalles",
            2,
            3,
        ),
    ],
)
async def test_additional_incidents_across_problem_types(live, incident, origin, problem):
    s, say = live
    await say(incident)
    assert s.draft is not None
    assert s.draft.payload["problem_type_id"] == problem
    if origin is None:
        assert not s.draft.payload.get("origin_unit_id") and s.missing == "origin_unit_id"
    else:
        assert s.draft.payload["origin_unit_id"] == origin
        assert s.state == State.WAITING_CONFIRMATION
    assert not s.db.operations()
