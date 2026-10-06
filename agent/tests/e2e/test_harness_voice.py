"""Reported incident + catalogue question via native RTC, then full UI confirmation.

Uses synthetic Daniela in Chromium's real WAV capture device, real Whisper,
DeepSeek tools, Piper, UI and isolated API/DB. No microphone/transcript override.
Only the design-check database receives one explicitly confirmed test ticket.
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
from gianna.dialogue.activation import normalize
from gianna.dialogue.state_machine import State
from gianna.dialogue.spoken_text import spoken_code
from gianna.server.app import create_app
from tests.e2e.test_voice_flow import login_browser, wait_until

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.models,
    pytest.mark.gpu,
    pytest.mark.skipif(
        os.getenv("GIANNA_REAL_E2E") != "1", reason="Explicit native voice/cloud/API test"
    ),
]


async def test_reported_incident_catalogue_followups_and_confirmed_creation(tmp_path):
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
        "input": "synthetic Daniela through native Chromium WAV capture",
        "microphone_override": False,
        "autoplay_override": False,
        "local_llm_calls": 0,
    }
    try:
        await wait_until(lambda: server.started, 150)
        s = runtime.supervisor
        assert s.state != State.BLOCKED, runtime.diagnostics
        assert runtime.diagnostics["conversation_agent"]["native_tools"]

        async def cloud_only(request):
            assert request.url.port != 11434 and request.url.host in {
                "localhost",
                "127.0.0.1",
                "ollama.com",
            }

        runtime.client.event_hooks["request"].append(cloud_only)
        async with httpx.AsyncClient() as client:
            fixture = tmp_path / "incident-and-catalogues.wav"
            pcm = bytes(48000 * 2 * 2)
            phrases = [
                "Gianna, necesito que crees un nuevo ticket para mí, que es un pedido de la Secretaría General para cambiarle las hojas a todas las impresoras que se quedaron sin hojas en esa secretaría.",
                "¿Qué áreas registradas tenés?",
            ]
            for text in phrases:
                response = await client.post(
                    "http://127.0.0.1:5002/",
                    json={"text": text, "speed": 0.95, "sample_rate": 48000},
                    timeout=30,
                )
                response.raise_for_status()
                with wave.open(io.BytesIO(response.content)) as wav:
                    pcm += wav.readframes(wav.getnframes())
                pcm += bytes(48000 * 2 * 42)
            with wave.open(str(fixture), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(48000)
                wav.writeframes(pcm)
            await runtime.browser.start(runtime.broker, visible=False, audio_fixture=fixture)
            await runtime.browser.context.route("https://**/*", lambda route: route.abort())
            credentials = json.loads(
                (ROOT.parent / "artifacts/design-check-users.json").read_text(encoding="utf-8")
            )["operator"]
            await login_browser(runtime.browser.page, client, credentials)
            await wait_until(lambda: s.user is not None and s.catalogs is not None)
            before = (await s.tickets.request("GET", "/api/v1/tickets"))["total"]
            console = next(
                p for p in runtime.browser.context.pages if p.url == config.console_origin + "/"
            )
            await console.bring_to_front()
            # Public activation is an explicit listening request. This trajectory
            # tests interpretation independently of the ASR wake-word spelling.
            await console.get_by_role("button", name="Activar Gianna", exact=True).click()
            await console.get_by_role("button", name="Conectar micrófono", exact=True).click()
            await expect(
                console.get_by_role("button", name="Micrófono conectado", exact=True)
            ).to_be_visible(timeout=15000)
            await wait_until(
                lambda: s.draft is not None and s.state == State.WAITING_CONFIRMATION, 60
            )
            original = dict(s.draft.payload)
            incident = normalize(original["description"])
            assert ("hojas" in incident or "papel" in incident) and "impresora" in incident
            assert "gomas" not in incident and "ocas" not in incident
            assert s.draft_labels()["origin_unit_id"] == "Secretaría General"
            assert s.draft_labels()["problem_type_id"] == "Impresoras"
            assert (
                "para mí" not in original["description"]
                and "que es un pedido" not in original["description"]
            )

            def rows(kind):
                return [
                    json.loads(r[0])
                    for r in runtime.db.connection.execute(
                        "SELECT data FROM events WHERE kind=? ORDER BY id", (kind,)
                    )
                ]

            await wait_until(
                lambda: (
                    len(rows("transcript")) >= 2
                    and any(
                        m["name"] == "catalogues" and m["ok"] for m in rows("agent_tool_completed")
                    )
                    and all(
                        normalize(r["name"]) in normalize(s.last_speech["text"])
                        for r in s.catalogs["org_units"]
                    )
                ),
                80,
            )
            answer = normalize(s.last_speech["text"])
            assert all(normalize(r["name"]) in answer for r in s.catalogs["org_units"]), answer
            assert s.draft.payload == original and not s.db.operations()
            turns = rows("transcript")
            assert len(turns) == 2 and all(t["source"] == "voice" for t in turns)
            assert "secretaria general" in normalize(
                turns[0]["text"]
            ) and "areas registradas" in normalize(turns[1]["text"])
            evidence.update(
                transcripts=turns,
                catalogue_answer=s.last_speech["text"],
                draft_before_followups=s.snapshot()["draft"],
            )
            await console.get_by_role("button", name="Apagar micrófono", exact=True).click()
            await console.get_by_role("button", name="Detener voz", exact=True).click()

            async def send(text):
                before_speech = s.last_speech["utterance_id"]
                await console.get_by_label("Mensaje para Gianna").fill(text)
                await console.get_by_role("button", name="Enviar a Gianna", exact=True).click()
                await wait_until(
                    lambda: s.last_speech and s.last_speech["utterance_id"] != before_speech, 35
                )

            await send("¿Y qué tipos de problemas hay?")
            assert all(
                normalize(r["name"]) in normalize(s.last_speech["text"])
                for r in s.catalogs["problem_types"]
            )
            assert s.draft.payload == original
            await send("Usá Tránsito como origen")
            assert (
                s.draft_labels()["origin_unit_id"] == "Tránsito"
                and s.draft.payload["description"] == original["description"]
            )
            await send("Perdón, el origen correcto es Secretaría General")
            assert s.draft_labels()["origin_unit_id"] == "Secretaría General"
            assert (
                s.draft.payload["description"] == original["description"] and not s.db.operations()
            )
            await send("Confirmo Gianna, registrá ese ticket")
            await wait_until(lambda: s.last_receipt is not None and len(s.db.operations()) == 1, 35)
            receipt = s.last_receipt
            ticket = await s.tickets.request("GET", f"/api/v1/tickets/{receipt['ticket_id']}")
            assert (
                ticket["origin"]["name"] == "Secretaría General"
                and ticket["problem_type"]["name"] == "Impresoras"
            )
            assert ticket["description"] == original["description"]
            after = (await s.tickets.request("GET", "/api/v1/tickets"))["total"]
            assert after == before + 1
            await send("¿Qué número quedó registrado?")
            assert (
                receipt["code"] in s.last_speech["text"]
                or receipt["code"].removeprefix("IDL-TI-").lstrip("0") in s.last_speech["text"]
                or spoken_code(receipt["code"]) in s.last_speech["text"]
            )
            assert len(s.db.operations()) == 1
            evidence.update(
                receipt=receipt,
                verified_ticket=ticket,
                tickets_before=before,
                tickets_after=after,
                speech=rows("speech"),
                tools=rows("agent_tool_completed"),
                native_audio_frames=runtime.audio.monitor.frames if runtime.audio.monitor else None,
            )
            await console.screenshot(
                path=str(ROOT.parent / "artifacts/gianna-harness-voice.png"), full_page=True
            )
    finally:
        if runtime.db:
            evidence["events"] = [
                dict(r)
                for r in runtime.db.connection.execute("SELECT kind,data FROM events ORDER BY id")
            ]
        (ROOT.parent / "artifacts/gianna-harness-voice.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if runtime.audio:
            await runtime.audio.close()
        if runtime.browser:
            await runtime.browser.close()
        server.should_exit = True
        await asyncio.wait_for(serving, 45)
