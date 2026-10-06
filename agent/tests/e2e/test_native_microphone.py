"""Native browser capture, continuous real RTC audio, Whisper and DeepSeek Cloud.

Synthetic WAV fixture uses Chromium's native capture device; no getUserMedia or
WebAudio replacement and no autoplay-policy override. No business writes.
"""

import asyncio
import io
import json
import os
import wave

import httpx
import pytest
import uvicorn
from playwright.async_api import expect
from gianna.config import ROOT, Settings
from gianna.dialogue.state_machine import State
from gianna.server.app import create_app
from tests.e2e.test_voice_flow import login_browser, wait_until

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.models,
    pytest.mark.gpu,
    pytest.mark.skipif(os.getenv("GIANNA_REAL_E2E") != "1", reason="Real audio/cloud services"),
]


async def test_native_microphone_dispatches_each_phrase_with_continuous_pcm(tmp_path):
    base = Settings()
    config = Settings(
        data_dir=tmp_path,
        model_dir=base.models_dir,
        nltk_dir=base.data_dir / "nltk",
        tickets_api="http://localhost:5400",
        tickets_web="http://localhost:5473",
        port=7862,
        piper_port=5002,
    )
    assert config.interpreter_backend == "cloud"
    app = create_app(config, managed_browser=False)
    runtime = app.state.runtime
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=7862,
            access_log=False,
            log_level="warning",
            timeout_graceful_shutdown=5,
        )
    )
    serving = asyncio.create_task(server.serve())
    calls = []
    try:
        await wait_until(lambda: server.started, 120)
        assert runtime.supervisor.state != State.BLOCKED, runtime.diagnostics

        async def check_request(request):
            assert request.url.host in {"localhost", "127.0.0.1", "ollama.com"}
            assert request.url.port != 11434, "Cloud mode must never invoke a local LLM"
            calls.append(str(request.url))

        runtime.client.event_hooks["request"].append(check_request)
        async with httpx.AsyncClient() as client:
            fixture = tmp_path / "native-microphone.wav"
            phrases = ["Hola Gianna, ¿estás ahí?", "Te dije a ver si me habías escuchado"]
            pcm = bytes(48000 * 2 * 2)
            for text in phrases:
                response = await client.post(
                    "http://127.0.0.1:5002/",
                    json={"text": text, "speed": 0.9, "sample_rate": 48000},
                    timeout=30,
                )
                response.raise_for_status()
                with wave.open(io.BytesIO(response.content)) as wav:
                    assert wav.getframerate() == 48000 and wav.getnchannels() == 1
                    pcm += wav.readframes(wav.getnframes())
                pcm += bytes(48000 * 2 * 14)
            with wave.open(str(fixture), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(48000)
                wav.writeframes(pcm)
            await runtime.browser.start(runtime.broker, visible=False, audio_fixture=fixture)
            await runtime.browser.context.route("https://**/*", lambda route: route.abort())
            credentials = json.loads(
                (ROOT.parent / "artifacts/design-check-users.json").read_text()
            )["operator"]
            await login_browser(runtime.browser.page, client, credentials)
            await wait_until(lambda: runtime.supervisor.user is not None)
            console = next(
                p for p in runtime.browser.context.pages if p.url == config.console_origin + "/"
            )
            await console.bring_to_front()
            await console.get_by_role("button", name="Conectar micrófono", exact=True).click()
            await expect(
                console.get_by_role("button", name="Micrófono conectado", exact=True)
            ).to_be_visible(timeout=15000)
            await expect(
                console.get_by_role("meter", name="Nivel de audio recibido")
            ).to_be_visible()

            def rows(kind):
                return [
                    json.loads(r[0])
                    for r in runtime.db.connection.execute(
                        "SELECT data FROM events WHERE kind=? ORDER BY id", (kind,)
                    )
                ]

            await wait_until(lambda: len(rows("transcript")) >= 2 and len(rows("speech")) >= 2, 50)
            await wait_until(
                lambda: len(runtime.metrics.samples.get("vad_stop_to_turn_dispatch", [])) >= 2, 10
            )
            await wait_until(
                lambda: len(runtime.metrics.samples.get("tts_first_server_audio", [])) >= 2, 15
            )
            turns, replies = rows("transcript"), rows("speech")
            assert len(turns) == 2, turns
            assert all(
                "estás ahí" not in t["text"].lower() or t["text"].lower().count("estás ahí") == 1
                for t in turns
            )
            assert "ya estoy activada" in replies[0]["text"].lower(), replies
            assert "estoy acá" in replies[1]["text"].lower(), replies
            assert not runtime.supervisor.draft and not runtime.db.operations()
            assert runtime.audio.monitor.frames > 100 and runtime.audio.monitor.received_ms > 10000
            assert any(url == "https://ollama.com/api/chat" for url in calls)
            dispatch = runtime.metrics.samples["vad_stop_to_turn_dispatch"]
            assert max(dispatch) < 4000, dispatch
            evidence = {
                "input": "native Chromium WAV capture, synthetic Daniela",
                "autoplay_override": False,
                "getUserMedia_override": False,
                "interpreter": config.conversation_model,
                "local_llm_calls": 0,
                "transcripts": turns,
                "replies": replies,
                "received_frames": runtime.audio.monitor.frames,
                "metrics": runtime.metrics.snapshot(),
                "no_draft_or_business_write": True,
            }
            (ROOT.parent / "artifacts/gianna-native-microphone.json").write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            await console.screenshot(
                path=str(ROOT.parent / "artifacts/gianna-native-microphone.png"), full_page=True
            )
    finally:
        if runtime.db:
            events = [
                dict(r)
                for r in runtime.db.connection.execute("SELECT kind,data FROM events ORDER BY id")
            ]
            (ROOT.parent / "artifacts/gianna-native-events.json").write_text(
                json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        if runtime.audio:
            await runtime.audio.close()
        if runtime.browser:
            await runtime.browser.close()
        server.should_exit = True
        await asyncio.wait_for(serving, 45)
