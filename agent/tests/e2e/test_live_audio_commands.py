"""Dynamic WAV microphone through WebAudio -> WebRTC -> real pipeline.

Only this test replaces getUserMedia with a controlled audio stream. Business
commands never enter through the text endpoint. No physical echo/headset claim.
"""

import asyncio
import json
import os
import wave
import httpx
import pytest
import uvicorn
from gianna.config import Settings, ROOT
from gianna.server.app import create_app
from gianna.dialogue.state_machine import State
from tests.e2e.test_voice_flow import wait_until, login_browser
from tests.e2e.audio_input import MICROPHONE, phrase, confirm_by_audio

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.models,
    pytest.mark.gpu,
    pytest.mark.skipif(
        os.getenv("GIANNA_REAL_E2E") != "1", reason="Isolated real model/browser services"
    ),
]


async def test_read_filter_archive_and_handoff_by_real_audio(tmp_path):
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
            log_level="warning",
            access_log=False,
            timeout_graceful_shutdown=5,
        )
    )
    running = asyncio.create_task(server.serve())
    try:
        await wait_until(lambda: server.started, 120)
        assert runtime.supervisor.state != State.BLOCKED, runtime.diagnostics
        fixture = tmp_path / "silence.wav"
        with wave.open(str(fixture), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(48000)
            wav.writeframes(bytes(96000))
        await runtime.browser.start(runtime.broker, visible=False, audio_fixture=fixture)
        async with httpx.AsyncClient() as client:
            users = json.loads((ROOT.parent / "artifacts/design-check-users.json").read_text())
            await login_browser(runtime.browser.page, client, users["operator"])
            await wait_until(lambda: runtime.supervisor.user is not None)
            rows = (await runtime.supervisor.tickets.request("GET", "/api/v1/tickets"))["items"]
            target = next(row for row in reversed(rows) if row["created_by_user_id"] == 2)
            number = int(target["code"][-6:])
            console = next(
                p for p in runtime.browser.context.pages if p.url == config.console_origin + "/"
            )
            await console.add_init_script(MICROPHONE)
            await console.reload()
            await console.get_by_role("button", name="Conectar micrófono", exact=True).click()
            await wait_until(lambda: runtime.supervisor.speak_callback is not None)
            await phrase(
                console, client, "Hola Gianna, necesito tu ayuda para registrar un pedido nuevo."
            )
            await wait_until(
                lambda: runtime.supervisor.state in {State.INVITING, State.WAITING_INITIAL_INPUT}
            )
            await phrase(console, client, f"Por favor mostrame el ticket número {number}.")
            await runtime.browser.page.wait_for_url(f"**/tickets/{target['id']}", timeout=15000)
            assert await runtime.browser.page.get_by_role(
                "heading", name=target["code"], exact=True
            ).is_visible()
            await phrase(console, client, "Buscá tickets que contengan la palabra impresora.")
            assert (
                await runtime.browser.page.get_by_role(
                    "textbox", name="Buscar tickets por código o descripción", exact=True
                ).input_value()
                == "impresora"
            )
            await phrase(console, client, f"Ocultá el ticket número {number}.")
            await wait_until(
                lambda: (
                    runtime.supervisor.draft
                    and runtime.supervisor.draft.tool == "tickets.archive.v1"
                )
            )
            await phrase(
                console, client, "Lo pidieron porque este pedido era una prueba de integración."
            )
            await wait_until(lambda: runtime.supervisor.state == State.WAITING_CONFIRMATION)
            await confirm_by_audio(console, client, runtime)
            receipt = runtime.supervisor.last_receipt
            assert receipt["ticket_id"] == target["id"] and receipt["tool"] == "tickets.archive.v1"
            from gianna.adapters.tickets_http import TicketError

            with pytest.raises(TicketError):
                await runtime.supervisor.tickets.observe(f"tickets/{target['id']}")
            assert (
                await runtime.supervisor.tickets.verify({"operation_id": receipt["operation_id"]})
            )["event_ids"]
            await wait_until(lambda: runtime.supervisor.state == State.DORMANT)
            await phrase(
                console, client, "Hola Gianna, necesito tu ayuda para registrar un pedido nuevo."
            )
            await wait_until(
                lambda: runtime.supervisor.state in {State.INVITING, State.WAITING_INITIAL_INPUT}
            )
            await phrase(
                console, client, "En Tránsito la impresora no imprime y tiene papel atascado."
            )
            # The genuine STT may spell a catalogue name incorrectly. Respond by voice
            # to its actual missing-field question, rather than force an inferred ID.
            for _ in range(4):
                await wait_until(
                    lambda: (
                        runtime.supervisor.state
                        in {State.WAITING_CONFIRMATION, State.ASKING_MISSING_FIELD}
                    )
                )
                if runtime.supervisor.state == State.WAITING_CONFIRMATION:
                    break
                answers = {
                    "origin_unit_id": "El origen del pedido es Tránsito.",
                    "destination_unit_id": "El destino del pedido es Informática.",
                    "problem_type_id": "El tipo de problema es impresoras.",
                    "description": "La impresora no imprime y tiene papel atascado.",
                }
                await phrase(console, client, answers[runtime.supervisor.missing])
            await wait_until(lambda: runtime.supervisor.state == State.WAITING_CONFIRMATION)
            old = runtime.supervisor.draft
            await console.get_by_role("button", name="Tomar el control manual", exact=True).click()
            await runtime.browser.page.get_by_test_id("gianna-manual").wait_for()
            assert not await runtime.browser.page.get_by_test_id("ticket-submit").is_disabled()
            assert old.transferred and old.owner == "human"
            assert len(runtime.db.operations()) == 1
            # Deliberately close ONLY this owned surface: no success from stale page handles.
            await runtime.browser.close()
            from gianna.adapters.playwright_browser import BrowserContractError

            with pytest.raises(BrowserContractError):
                await runtime.browser.show()
            result = {
                "metrics": runtime.metrics.snapshot(),
                "load_samples": list(runtime.metrics.load),
                "microphone": "Test-only WebAudio PCM -> WebRTC",
                "real_engines": True,
                "voice_read": True,
                "voice_filter": True,
                "voice_archive": receipt,
                "manual_handoff": True,
                "API_UI_duplicate": False,
                "owned_browser_failure_detected": True,
            }
            (ROOT.parent / "artifacts/gianna-live-commands.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    finally:
        if runtime.db:
            events = [
                dict(row)
                for row in runtime.db.connection.execute("SELECT kind,data FROM events ORDER BY id")
            ]
            (ROOT.parent / "artifacts/gianna-live-events.json").write_text(
                json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        if runtime.audio:
            await runtime.audio.close()
        if runtime.browser:
            await runtime.browser.close()
        server.should_exit = True
        await asyncio.wait_for(running, 45)
