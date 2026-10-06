from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import pytest

from gianna.config import Settings
from gianna.dialogue.state_machine import State
from gianna.server import app as server


@pytest.fixture
def console_audio(monkeypatch):
    calls = []
    runtime = SimpleNamespace(
        secret="local-console",
        start=AsyncMock(),
        close=AsyncMock(),
        supervisor=SimpleNamespace(state=State.DORMANT),
        audio=SimpleNamespace(
            close=AsyncMock(side_effect=lambda: calls.append("audio.close")), connect=AsyncMock()
        ),
    )

    async def handle(request, callback):
        calls.append(("offer", request.pc_id))
        return {"sdp": "answer", "type": "answer", "pc_id": "new"}

    rtc = SimpleNamespace(
        close=AsyncMock(side_effect=lambda: calls.append("rtc.close")),
        handle_web_request=AsyncMock(side_effect=handle),
    )
    monkeypatch.setattr(server, "Runtime", lambda config: runtime)
    monkeypatch.setattr(server, "SmallWebRTCRequestHandler", lambda **kwargs: rtc)
    with TestClient(server.create_app(Settings()), base_url="http://127.0.0.1:7860") as client:
        client.cookies.set("gianna_pairing", runtime.secret)
        client.headers["Origin"] = "http://127.0.0.1:7860"
        yield client, runtime, calls


def test_explicit_new_microphone_releases_the_previous_channel(console_audio):
    client, _, calls = console_audio
    response = client.post("/api/offer", json={"sdp": "offer", "type": "offer"})
    assert response.status_code == 200
    assert calls == ["rtc.close", "audio.close", ("offer", None)]


def test_renegotiation_keeps_its_existing_audio_channel(console_audio):
    client, _, calls = console_audio
    response = client.post("/api/offer", json={"sdp": "offer", "type": "offer", "pc_id": "same"})
    assert response.status_code == 200
    assert calls == [("offer", "same")]


@pytest.mark.parametrize("blocked", [False, True])
def test_rejected_offer_does_not_disconnect_a_working_microphone(console_audio, blocked):
    client, runtime, calls = console_audio
    body = {"sdp": "offer", "type": "offer"}
    if blocked:
        runtime.supervisor.state = State.BLOCKED
    else:
        body["unexpected"] = True
    assert client.post("/api/offer", json=body).status_code == (503 if blocked else 422)
    assert calls == []


@pytest.mark.parametrize("audio_missing", [False, True])
def test_reset_closes_the_old_microphone_before_starting_a_clean_conversation(
    console_audio, audio_missing
):
    client, runtime, calls = console_audio
    if audio_missing:
        runtime.audio = None

    async def reset(close_audio):
        calls.append("invalidate")
        await close_audio()
        calls.append("reset")

    runtime.supervisor.reset_conversation = AsyncMock(side_effect=reset)
    runtime.supervisor.snapshot = lambda: {"draft": None, "state": "DORMANT"}
    result = client.post("/api/command", json={"action": "reset_conversation"})
    assert result.status_code == 200 and result.json()["draft"] is None
    assert calls == (
        ["invalidate", "rtc.close", "reset"]
        if audio_missing
        else ["invalidate", "rtc.close", "audio.close", "reset"]
    )


def test_reset_rejected_during_pending_write_keeps_existing_audio(console_audio):
    client, runtime, calls = console_audio
    runtime.supervisor.reset_conversation = AsyncMock(side_effect=ValueError("Operación pendiente"))
    result = client.post("/api/command", json={"action": "reset_conversation"})
    assert result.status_code == 409 and calls == []
