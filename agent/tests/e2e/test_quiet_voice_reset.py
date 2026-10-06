"""Quiet synthetic voice via native Chromium capture, Cloud correction and UI reset.

No transcript injection, microphone replacement or business writes. The WAV fixture
tests the audio chain; it does not establish accuracy for the user's physical mic.
"""

import asyncio
import io
import json
import os
import wave

import httpx
import numpy as np
import pytest
import uvicorn
from playwright.async_api import expect
from gianna.config import ROOT, Settings
from gianna.dialogue.activation import normalize
from gianna.dialogue.state_machine import State
from gianna.server.app import create_app
from tests.e2e.test_voice_flow import login_browser, wait_until

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.models,
    pytest.mark.gpu,
    pytest.mark.skipif(os.getenv("GIANNA_REAL_E2E") != "1", reason="Real audio/cloud services"),
]


async def test_quiet_full_correction_and_clean_reset_with_microphone_reconnection(tmp_path):
    ordinary = Settings()
    config = Settings(
        data_dir=tmp_path,
        model_dir=ordinary.models_dir,
        nltk_dir=ordinary.data_dir / "nltk",
        tickets_api="http://localhost:5400",
        tickets_web="http://localhost:5473",
        port=7862,
        piper_port=5002,
    )
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
    evidence = {
        "input": "quiet synthetic Daniela through native Chromium capture",
        "microphone_override": False,
        "autoplay_override": False,
    }
    try:
        await wait_until(lambda: server.started, 120)
        assert runtime.supervisor.state != State.BLOCKED, runtime.diagnostics

        async def cloud_only(request):
            assert request.url.port != 11434, "No local language model"
            assert request.url.host in {"localhost", "127.0.0.1", "ollama.com"}

        runtime.client.event_hooks["request"].append(cloud_only)
        async with httpx.AsyncClient() as client:
            phrase = "No, eso está mal. Lo que dije es que desde Secretaría General nos pidieron poner nuevas hojas a las impresoras."
            response = await client.post(
                "http://127.0.0.1:5002/",
                json={"text": phrase, "speed": 0.9, "sample_rate": 48000},
                timeout=30,
            )
            response.raise_for_status()
            with wave.open(io.BytesIO(response.content)) as wav:
                assert wav.getframerate() == 48000 and wav.getnchannels() == 1
                samples = np.frombuffer(wav.readframes(wav.getnframes()), np.int16).astype(
                    np.float32
                )
            # Match the quiet signal observed in the user's capture diagnostics.
            rms = float(np.sqrt(np.mean((samples / 32768) ** 2)))
            quiet = (samples * (0.005 / rms)).astype(np.int16).tobytes()
            fixture = tmp_path / "quiet-correction.wav"
            with wave.open(str(fixture), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(48000)
                wav.writeframes(bytes(48000 * 2 * 2) + quiet + bytes(48000 * 2 * 60))
            evidence["fixture_rms"] = 0.005
            await runtime.browser.start(runtime.broker, visible=False, audio_fixture=fixture)
            await runtime.browser.context.route("https://**/*", lambda route: route.abort())
            credentials = json.loads(
                (ROOT.parent / "artifacts/design-check-users.json").read_text()
            )["operator"]
            await login_browser(runtime.browser.page, client, credentials)
            await wait_until(
                lambda: (
                    runtime.supervisor.user is not None and runtime.supervisor.catalogs is not None
                )
            )
            s = runtime.supervisor
            actor = s.user["id"]
            # Only setup bypass: recreate the stale draft reported by the user.
            await s.start_request("Desde Sociales nos pidieron revisar una impresora.")
            assert s.draft_labels()["origin_unit_id"] == "Sociales"
            console = next(
                p for p in runtime.browser.context.pages if p.url == config.console_origin + "/"
            )
            await console.bring_to_front()
            await console.get_by_role("button", name="Conectar micrófono", exact=True).click()
            await expect(
                console.get_by_role("button", name="Micrófono conectado", exact=True)
            ).to_be_visible(timeout=15000)
            await wait_until(
                lambda: (
                    s.draft and "hojas" in s.draft.payload.get("description", "").lower()
                ),
                55,
            )
            description = normalize(s.draft.payload["description"])
            assert "secretaria general" in description and "impresoras" in description
            assert "sociales" not in description
            assert s.draft_labels()["origin_unit_id"] == "Secretaría General"
            assert s.missing is None and s.state == State.WAITING_CONFIRMATION
            assert (
                "Secretaría General" in s.last_speech["text"]
                and "Puedo registrar" not in s.last_speech["text"]
            )
            turns = [
                json.loads(r[0])
                for r in runtime.db.connection.execute(
                    "SELECT data FROM events WHERE kind='transcript' ORDER BY id"
                )
            ]
            assert len(turns) == 1, turns
            assert turns[0]["source"] == "voice"
            # Preserve the effective transcript: Whisper may render "nuevas"
            # differently at this low input level. Never inject/fix it in tests.
            assert description in normalize(turns[0]["text"])
            if "nuevas" in normalize(turns[0]["text"]):
                assert "nuevas" in description
            # Native browser AGC may already have raised the quiet input. The
            # segment normalizer adds gain only when it remains quiet afterward.
            assert turns[0]["evidence"]["applied_gain"] >= 1
            evidence.update(
                {
                    "transcripts": turns,
                    "corrected_draft": s.snapshot()["draft"],
                    "reply": s.last_speech["text"],
                }
            )
            await wait_until(lambda: runtime.metrics.samples.get("tts_first_server_audio"), 20)
            old_audio_task = runtime.audio.task
            old_session = s.session_id
            observer = await runtime.browser.context.new_page()
            await observer.goto(config.console_origin + "/")
            await observer.get_by_role("button", name="Borrar conversación", exact=True).wait_for()
            await console.get_by_label("Mensaje para Gianna").fill("Mensaje que no envié")
            await console.get_by_role("button", name="Borrar conversación", exact=True).click()
            await wait_until(lambda: s.session_id != old_session and not s.draft)
            await expect(console.get_by_label("Mensaje para Gianna")).to_have_value("")
            await expect(console.locator(".transcript")).to_be_empty()
            await expect(observer.locator(".transcript")).to_be_empty()
            await expect(
                console.get_by_role("button", name="Nuevo ticket", exact=True)
            ).to_be_enabled()
            await expect(
                console.get_by_role("button", name="Micrófono conectado", exact=True)
            ).to_be_visible(timeout=20000)
            assert runtime.audio.task is not old_audio_task and runtime.audio.monitor.frames > 0
            assert s.user["id"] == actor and s.state == State.DORMANT
            assert not s.last_speech and not s.last_receipt and not s.db.operations()
            assert not s.db.load_drafts(actor)
            assert (
                s.db.connection.execute(
                    "SELECT COUNT(*) FROM events WHERE actor_id=? AND kind IN ('transcript','speech')",
                    (actor,),
                ).fetchone()[0]
                == 0
            )
            evidence.update(
                {
                    "reset": "chat, unsent draft and pending text cleared in both consoles",
                    "authenticated_actor_preserved": actor,
                    "new_audio_channel_receiving": True,
                    "no_business_writes": True,
                    "metrics": runtime.metrics.snapshot(),
                }
            )
            await console.screenshot(
                path=str(ROOT.parent / "artifacts/gianna-quiet-reset.png"), full_page=True
            )
    finally:
        if runtime.db:
            evidence["final_events"] = [
                dict(r)
                for r in runtime.db.connection.execute("SELECT kind,data FROM events ORDER BY id")
            ]
        (ROOT.parent / "artifacts/gianna-quiet-reset.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if runtime.audio:
            await runtime.audio.close()
        if runtime.browser:
            await runtime.browser.close()
        server.should_exit = True
        await asyncio.wait_for(serving, 45)
