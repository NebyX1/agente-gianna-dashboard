"""Regression of the updated direct-address criterion with the actual local Tev."""

import os

import httpx
import pytest

from gianna.config import Settings
from gianna.dialogue.activation import ACTIVATION_CRITERIA, candidate
from gianna.models.ollama_tev1 import TevDecision

pytestmark = [
    pytest.mark.models,
    pytest.mark.integration,
    pytest.mark.skipif(
        Settings().interpreter_backend != "local", reason="Historical local Tev regression"
    ),
    pytest.mark.skipif(os.getenv("GIANNA_REAL_E2E") != "1", reason="Real resident Tev required"),
]


@pytest.mark.parametrize(
    "text,direct",
    [
        ("Hola Gianna, ¿estás ahí?", True),
        ("Gianna, ¿me escuchás?", True),
        ("Hola Gianna, seguimos.", True),
        ("Hola Gianna, finalizá el ticket número 15.", True),
        ("Hola Gianna, necesito tu ayuda para registrar un pedido nuevo.", True),
        ("Ella se llama Gianna", False),
        ("Mañana hablamos con Gianna", False),
        ("Gianna? No sé...", False),
        ("Diana, ¿estás ahí?", False),
        ("¿Estás ahí?", False),
    ],
)
async def test_actual_direct_address(text, direct):
    if candidate(text) is None:
        assert not direct
        return
    async with httpx.AsyncClient() as client:
        tev = TevDecision(Settings(), client)
        decision = await tev.choose(text, ACTIVATION_CRITERIA)
        assert tev.last_error is None
        assert (decision == "invoke") is direct
