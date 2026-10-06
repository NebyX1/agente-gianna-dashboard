"""Configured catalogue interpreter for incident context, without transcript edits."""

import os

import httpx
import pytest

from gianna.config import Settings
from gianna.dialogue.slots import resolve
from gianna.models.ollama_tev1 import TevDecision
from gianna.models.cloud_interpreter import CloudInterpreter
from gianna.profiles.loader import load_profile

pytestmark = [
    pytest.mark.models,
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("GIANNA_REAL_E2E") != "1", reason="Actual configured model required"
    ),
]

ROWS = [
    {"id": 101, "code": "IMPRESORA", "name": "Impresoras"},
    {"id": 102, "code": "INTERNET", "name": "Conectividad / Internet"},
    {"id": 103, "code": "HARDWARE", "name": "Hardware"},
    {"id": 104, "code": "SISTEMAS", "name": "Acceso a sistemas"},
    {"id": 105, "code": "OTROS", "name": "Otros"},
]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("La inpesora se tranca con la hoja y no permite seguir imprimiendo", 101),
        ("La impesora deja todas las hojas atascadas y no sale la impresión", 101),
        ("No podemos navegar en la web ni conectarnos a la red desde la oficina", 102),
        ("No hay información para identificar una categoría de problema", None),
    ],
)
async def test_contextual_catalogue_with_configured_model(text, expected):
    async with httpx.AsyncClient() as client:
        config = Settings()
        tev = (CloudInterpreter if config.interpreter_backend == "cloud" else TevDecision)(
            config, client
        )
        selected = await resolve(
            text, ROWS, load_profile()["aliases_data"]["problem_type_id"], tev, "problem_type_id"
        )
        assert tev.last_error is None
        assert selected == expected
