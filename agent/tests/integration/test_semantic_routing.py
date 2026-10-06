"""Paraphrases through the configured interpreter, not mocked interpretation."""

import os
import httpx
import pytest
from gianna.config import Settings
from gianna.models.local_interpreter import LocalInterpreter
from gianna.models.cloud_interpreter import CloudInterpreter

pytestmark = [
    pytest.mark.models,
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("GIANNA_REAL_E2E") != "1", reason="Real configured model"),
]


def interpreter(client):
    config = Settings()
    factory = CloudInterpreter if config.interpreter_backend == "cloud" else LocalInterpreter
    return factory(config, client)


CASES = [
    ("Te dije a ver si me habías escuchado", "presence"),
    ("Parece que no me estás escuchando", "presence"),
    ("Te llegó lo que acabo de decir?", "presence"),
    ("Quería saber si seguías ahí conmigo", "presence"),
    ("Lo que te pregunté era si me estabas oyendo", "presence"),
    ("A ver, me oíste o no?", "presence"),
    ("Te estaba hablando a vos, ¿entendiste?", "presence"),
    ("No oí lo último que dijiste", "repeat"),
    ("Me repetís la última pregunta que hiciste?", "repeat"),
    ("No entendí lo que me acabás de preguntar", "repeat"),
    ("La impresora de Tránsito se tranca con el papel", "data"),
    ("El micrófono del teléfono no me escucha", "data"),
    ('La aplicación muestra "¿estás ahí?" y se congela', "data"),
    ("La computadora no responde y no puedo trabajar", "data"),
    ("No podemos navegar ni entrar a la red desde ayer", "data"),
    ("No sé qué querés que diga", "social"),
    ("Esto es bastante confuso, explicame cómo se usa", "social"),
    ("Tenés que dejar de interpretar todo como un ticket", "social"),
    ("Qué tiempo va a hacer mañana?", "social"),
    ("Me pasás una receta de torta?", "social"),
]


@pytest.mark.parametrize("field", [None, "description", "origin_unit_id"])
@pytest.mark.parametrize("text,expected", CASES)
async def test_real_semantic_boundary(text, expected, field):
    async with httpx.AsyncClient() as client:
        model = interpreter(client)
        result = await model.classify(text, field=field, has_draft=field is not None)
        assert not model.last_error
        print(text, field, result.intent)
        if expected == "data":
            assert result.intent in {"incident", "field_data"}
        elif expected == "social":
            assert result.intent not in {"incident", "field_data", "start_request"}
        else:
            assert result.intent == expected


@pytest.mark.parametrize(
    "text,field",
    [
        ("Tránsito", "origin_unit_id"),
        ("Informática", "destination_unit_id"),
        ("Impresoras", "problem_type_id"),
        ("El técnico cambió el rodillo roto", "note"),
    ],
)
async def test_real_answer_to_concrete_field(text, field):
    async with httpx.AsyncClient() as client:
        result = await interpreter(client).classify(text, field=field, has_draft=True)
        assert result.intent == "field_data"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Hola Gianna, ¿estás ahí?", True),
        ("Gianna, registrá un ticket", True),
        ("Decile a Gianna que venga", False),
        ("Estaba hablando con Gianna", False),
        ("La usuaria Gianna no puede imprimir", False),
    ],
)
async def test_actual_wake_address(text, expected):
    async with httpx.AsyncClient() as client:
        assert await interpreter(client).addressed(text) == expected


@pytest.mark.parametrize(
    "text,expected,content",
    [
        (
            "Necesito que escribas algo coherente, te estoy diciendo que recién de la dirección...",
            "repair_request",
            "",
        ),
        ("Estás entendiendo mal lo que te dije de las impresoras", "feedback", ""),
        (
            "No, eso está mal. Lo que dije es que desde Secretaría General nos pidieron poner nuevas hojas a las impresoras",
            "repair_request",
            "desde Secretaría General nos pidieron poner nuevas hojas a las impresoras",
        ),
        (
            "También hay que poner nuevas hojas a las impresoras",
            "append_request",
            "hay que poner nuevas hojas a las impresoras",
        ),
        (
            "Que desde secretaría general nos pidieron poner nuevas hojas a las impresoras",
            "repair_request",
            "desde secretaría general nos pidieron poner nuevas hojas a las impresoras",
        ),
    ],
)
async def test_real_correction_uses_context_without_becoming_generic_help(text, expected, content):
    async with httpx.AsyncClient() as client:
        model = interpreter(client)
        result = await model.classify(
            text,
            has_draft=True,
            field="description" if text.startswith("Que ") else "problem_type_id",
            draft={
                "origin_unit_id": 4,
                "description": "para mí que me dijeron recién de la dirección de sociales.",
            },
        )
        assert result.intent == expected, result
        if expected == "append_request":
            assert result.content in {content, text}, result
        else:
            assert result.content == content, result
        assert not model.last_error


async def test_real_context_reads_exact_unknown_origin_without_inventing_destination():
    async with httpx.AsyncClient() as client:
        model = interpreter(client)
        result = await model.incident_context(
            "Que desde secretaría general nos pidieron poner nuevas hojas a las impresoras"
        )
        assert result.origin == "secretaría general" and not result.destination
