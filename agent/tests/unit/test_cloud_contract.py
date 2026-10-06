"""HTTP contract fixtures; no claim of a live authenticated cloud response."""

import json
import httpx
import pytest
from gianna.config import Settings
from gianna.models.ollama_cloud import CloudReasoner
from gianna.tools.registry import ToolRegistry
from gianna.tools.tickets import install_tools
from gianna.adapters.tickets_http import TicketsHTTP


async def test_no_key_or_no_explicit_request_performs_no_http():
    calls = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: calls.append(r))
    ) as client:
        reasoner = CloudReasoner(Settings(cloud_api_key=""), client)
        assert (await reasoner.preflight())["status"] == "disabled"
        with pytest.raises(RuntimeError):
            await reasoner.reason("mejorar", explicit=True)
        reasoner.available = True
        with pytest.raises(RuntimeError):
            await reasoner.reason("mejorar", explicit=False)
    assert not calls


async def test_direct_model_and_rewrite_rejects_number_changes():
    calls = []

    def respond(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"models": [{"name": "deepseek-v4.1-flash"}]})
        assert json.loads(request.content)["model"] == "deepseek-v4.1-flash"
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": json.dumps(
                        {
                            "kind": "rewrite",
                            "explanation": "Propuesta",
                            "description": "Hay 110 impresoras averiadas",
                            "steps": [],
                        }
                    )
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        reasoner = CloudReasoner(Settings(cloud_api_key="test-contract-only"), client)
        assert (await reasoner.preflight())["status"] == "ready"
        with pytest.raises(ValueError, match="rewrite_changed_number"):
            await reasoner.reason(
                "Mejorá la redacción", explicit=True, description="Hay 10 impresoras averiadas"
            )
    assert len(calls) == 2


async def test_plan_cannot_propose_two_writes():
    config = Settings(cloud_api_key="test-contract-only")
    registry = ToolRegistry()
    install_tools(registry, TicketsHTTP(config, None), None, None)
    payload = {
        "origin_unit_id": 1,
        "destination_unit_id": 1,
        "problem_type_id": 1,
        "description": "Datos de prueba",
    }
    proposal = {
        "kind": "plan",
        "explanation": "Plan",
        "steps": [
            {"tool_id": "tickets.create.v1", "resource": "tickets", "arguments": payload},
            {"tool_id": "tickets.create.v1", "resource": "tickets", "arguments": payload},
        ],
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"message": {"content": json.dumps(proposal)}})
        )
    ) as client:
        reasoner = CloudReasoner(config, client)
        reasoner.available = True
        with pytest.raises(ValueError, match="one_final_write"):
            await reasoner.reason("Planeá dos pedidos", explicit=True, registry=registry)
