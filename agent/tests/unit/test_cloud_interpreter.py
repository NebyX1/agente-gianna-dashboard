import json

import httpx
import pytest
from gianna.config import Settings
from gianna.models.cloud_interpreter import CloudInterpreter


async def test_cloud_routes_semantics_and_catalogue_without_local_requests():
    calls = []

    def respond(request):
        calls.append(request)
        assert request.url.host == "ollama.com" and request.url.scheme == "https"
        assert request.headers["Authorization"] == "Bearer contract-fixture"
        if request.method == "GET":
            return httpx.Response(200, json={"models": [{"name": "deepseek-v4.1-flash"}]})
        body = json.loads(request.content)
        assert body["model"] == "deepseek-v4.1-flash"
        assert "format" not in body and "keep_alive" not in body
        assert body["think"] is False and body["stream"] is False
        message = json.loads(body["messages"][1]["content"])
        answer = (
            {"choice": "printer", "confidence": 0.94}
            if "criteria" in message
            else {"intent": "presence", "content": "", "addressed": True}
        )
        return httpx.Response(200, json={"message": {"content": json.dumps(answer)}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        config = Settings(cloud_api_key="contract-fixture")
        assert "contract-fixture" not in repr(config)
        model = CloudInterpreter(config, client)
        assert (await model.preflight())["local"] is False
        assert (
            await model.choose("No imprime", {"printer": "Impresoras", "clarify": "Duda"})
            == "printer"
        )
    assert len(calls) == 3


@pytest.mark.parametrize(
    "content",
    [
        "not JSON",
        '{"intent":"invented"}',
        '{"intent":"presence","execute":true}',
    ],
)
async def test_invalid_cloud_result_never_becomes_data_or_local_fallback(content):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"message": {"content": content}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = CloudInterpreter(Settings(cloud_api_key="fixture"), client)
        result = await model.classify("Te dije a ver si me habías escuchado", has_draft=True)
        assert result.intent == "clarify" and model.last_error
    assert len(calls) == 1 and calls[0].url.host == "ollama.com"


@pytest.mark.parametrize(
    "answer",
    [
        {"choice": "unknown", "confidence": 0.95},
        {"choice": "printer", "confidence": 0.2},
        {"choice": "printer", "confidence": 4},
    ],
)
async def test_catalogue_requires_known_choice_and_confidence(answer):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"message": {"content": json.dumps(answer)}})
        )
    ) as client:
        model = CloudInterpreter(Settings(cloud_api_key="fixture"), client)
        assert await model.choose("No imprime", {"printer": "Impresoras"}) == "clarify"


async def test_no_cloud_key_fails_preflight_without_any_http():
    calls = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: calls.append(r))
    ) as client:
        model = CloudInterpreter(Settings(cloud_api_key=""), client)
        with pytest.raises(RuntimeError, match="OLLAMA_API_KEY"):
            await model.preflight()
        assert (await model.classify("¿Me escuchás?")).intent == "clarify"
    assert not calls


async def test_cloud_http_failure_does_not_try_local_ollama():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = CloudInterpreter(Settings(cloud_api_key="fixture"), client)
        assert (await model.classify("¿Me escuchás?")).intent == "clarify"
    assert len(calls) == 1 and calls[0].url.host == "ollama.com"


def test_requested_dotenv_names(monkeypatch, tmp_path):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    dotenv = tmp_path / ".env"
    dotenv.write_text("OLLAMA_API_KEY=fixture-env\nOLLAMA_MODEL=deepseek-v4.1-flash:cloud\n")
    config = Settings(_env_file=dotenv)
    assert config.cloud_api_key == "fixture-env"
    assert config.conversation_model == "deepseek-v4.1-flash:cloud"
    assert config.interpreter_backend == "cloud"


async def test_cloud_correction_receives_real_draft_and_pending_question():
    text = "desde Secretaría General nos pidieron poner nuevas hojas a las impresoras"
    payload = {"description": "Descripción equivocada", "origin_unit_id": 4}

    def respond(request):
        message = json.loads(json.loads(request.content)["messages"][1]["content"])
        assert message["borrador_actual"] == payload
        assert message["campo_pendiente"] == "problem_type_id"
        assert message["borrador_iniciado"] is True
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": json.dumps(
                        {"intent": "repair_request", "content": text, "addressed": True}
                    )
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = CloudInterpreter(Settings(cloud_api_key="fixture"), client)
        result = await model.classify(
            "No, lo que dije es que " + text, field="problem_type_id", has_draft=True, draft=payload
        )
        assert result.intent == "repair_request" and result.content == text


@pytest.mark.parametrize("origin,valid", [("Secretaría General", True), ("Sociales", False)])
async def test_incident_context_cannot_invent_or_reuse_an_office(origin, valid):
    answer = {"origin": origin, "destination": ""}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"message": {"content": json.dumps(answer)}})
        )
    ) as client:
        model = CloudInterpreter(Settings(cloud_api_key="fixture"), client)
        text = "desde Secretaría General nos pidieron poner nuevas hojas a las impresoras"
        if valid:
            assert (await model.incident_context(text)).origin == origin
        else:
            with pytest.raises(ValueError, match="not_literal"):
                await model.incident_context(text)
