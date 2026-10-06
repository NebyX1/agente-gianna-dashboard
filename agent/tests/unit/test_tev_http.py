import httpx
import pytest
from gianna.config import Settings
from gianna.models.ollama_tev1 import TevDecision


async def test_http_protocol_and_closed_labels():
    requests = []

    def respond(request):
        import json

        body = json.loads(request.content)
        requests.append(body)
        assert request.url.path == "/v1/systemone"
        assert body["questions"]["choice"]["type"] == "choice"
        return httpx.Response(
            200,
            json={
                "answers": {
                    "choice": {
                        "type": "choice",
                        "choice": "create",
                        "probabilities": {"create": 0.9, "ignore": 0.1},
                        "confidence": 0.6,
                    }
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        tev = TevDecision(Settings(), client)
        assert (
            await tev.choose("registrá un ticket", {"create": "Crear", "ignore": "No es una orden"})
            == "create"
        )
        assert requests[0]["model"] == "tev1:0.8b"


@pytest.mark.parametrize(
    "response",
    [
        {"choice": "unknown", "probabilities": {"create": 1, "ignore": 0}},
        {"choice": "create", "probabilities": {"create": 0.5, "ignore": 0.5, "extra": 0}},
        {"choice": "create", "probabilities": {"create": 0.9, "ignore": 0.9}},
    ],
)
async def test_malformed_tev_clarifies_no_cloud_fallback(response):
    def respond(request):
        return httpx.Response(
            200, json={"answers": {"choice": {"type": "choice", "confidence": 0.5, **response}}}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        assert (
            await TevDecision(Settings(), client).choose(
                "algo", {"create": "Crear", "ignore": "Ajeno"}
            )
            == "clarify"
        )


async def test_timeout_clarifies_locally():
    def respond(request):
        raise httpx.ReadTimeout("timeout", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        assert (
            await TevDecision(Settings(), client).choose(
                "algo", {"create": "Crear", "ignore": "Ajeno"}
            )
            == "clarify"
        )
