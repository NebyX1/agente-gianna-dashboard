"""Real browser, WebRTC, Whisper, configured interpreter, Piper and delegated writes.

Requires the isolated design-check stack, never the user demo database.
The audio is synthetic Daniela, not a claim about a human mic/headset.
"""

import asyncio
import json
import os
import re
import time
import wave
import httpx
import pytest
import uvicorn
from gianna.config import Settings, ROOT
from gianna.server.app import create_app
from gianna.dialogue.state_machine import State
from tests.e2e.audio_input import MICROPHONE, phrase, confirm_by_audio

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.models,
    pytest.mark.gpu,
    pytest.mark.skipif(
        os.getenv("GIANNA_REAL_E2E") != "1", reason="Explicit isolated real model/browser test"
    ),
]


async def wait_until(predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.1)
    raise AssertionError("Condition timed out")


async def login_browser(
    page, client, credentials, origin="http://localhost:5473", final="**/tickets"
):
    await page.goto(origin + "/login")
    await page.get_by_label("Correo electrónico", exact=True).fill(credentials["email"])
    await page.get_by_label("Contraseña", exact=True).fill(credentials["password"])
    await page.get_by_role("button", name="Continuar →", exact=True).click()
    from playwright.async_api import TimeoutError as BrowserTimeout

    try:
        await page.get_by_label("Código de verificación", exact=True).wait_for(timeout=3000)
    except BrowserTimeout:
        # Repeated isolated runs obey the real 60-second OTP cooldown.
        await asyncio.sleep(61)
        await page.get_by_role("button", name="Continuar →", exact=True).click()
    await page.get_by_label("Código de verificación", exact=True).wait_for()
    code = None
    for _ in range(30):
        mails = (await client.get("http://localhost:8027/api/v1/messages")).json()["messages"]
        for mail in mails:
            body = (await client.get("http://localhost:8027/api/v1/message/" + mail["ID"])).json()
            if any(
                recipient["Address"] == credentials["email"] for recipient in body.get("To", [])
            ):
                found = re.search(r"\b\d{6}\b", body.get("Text", ""))
                if found:
                    code = found[0]
                    break
        if code:
            break
        await asyncio.sleep(0.2)
    assert code, "Real SMTP OTP not received"
    await page.get_by_label("Código de verificación", exact=True).fill(code)
    await page.get_by_role("button", name="Verificar e ingresar", exact=True).click()
    await page.wait_for_url(final)


async def test_full_voice_ticket_and_safe_preview(tmp_path):
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
    server_task = asyncio.create_task(server.serve())
    try:
        await wait_until(lambda: server.started, 120)
        assert runtime.supervisor.state != State.BLOCKED, runtime.diagnostics
        async with httpx.AsyncClient() as client:

            async def configured_http_only(request):
                allowed = {"localhost", "127.0.0.1"}
                if config.interpreter_backend == "cloud":
                    allowed.add("ollama.com")
                    assert request.url.port != 11434, "No local LLM request in Cloud mode"
                assert request.url.host in allowed, "Unexpected service in voice test"

            runtime.client.event_hooks["request"].append(configured_http_only)
            fixture = tmp_path / "voice-flow.wav"
            with wave.open(str(fixture), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(48000)
                wav.writeframes(bytes(96000))
            await runtime.browser.start(runtime.broker, visible=False, audio_fixture=fixture)
            await runtime.browser.context.route("https://**/*", lambda route: route.abort())
            page = runtime.browser.page
            errors = []
            runtime.browser.context.on(
                "page", lambda p: p.on("pageerror", lambda error: errors.append(str(error)))
            )
            credentials = json.loads(
                (ROOT.parent / "artifacts/design-check-users.json").read_text()
            )["operator"]
            await login_browser(page, client, credentials)
            await wait_until(lambda: runtime.supervisor.user is not None)
            before = await runtime.supervisor.tickets.request("GET", "/api/v1/tickets")
            console = next(
                p for p in runtime.browser.context.pages if p.url == config.console_origin + "/"
            )
            await console.add_init_script(MICROPHONE)
            await console.reload()
            await console.get_by_role("button", name="Conectar micrófono", exact=True).click()
            try:
                await wait_until(lambda: runtime.supervisor.speak_callback is not None, 30)
            except AssertionError:
                raise AssertionError(
                    "Microphone connect failed: " + await console.locator("main").inner_text()
                )
            await phrase(
                console, client, "Hola Gianna, necesito tu ayuda para registrar un pedido nuevo."
            )
            await wait_until(
                lambda: (
                    runtime.supervisor.state == State.ASKING_MISSING_FIELD
                    and runtime.supervisor.missing == "description"
                )
            )
            await phrase(
                console, client, "En Tránsito la impresora no imprime y muestra una luz roja."
            )
            await wait_until(lambda: runtime.supervisor.state == State.WAITING_CONFIRMATION)
            await phrase(
                console,
                client,
                "Corregí la descripción: La impresora tiene un atasco de papel y no imprime.",
            )
            await wait_until(
                lambda: (
                    runtime.supervisor.state == State.WAITING_CONFIRMATION
                    and "papel" in runtime.supervisor.draft.payload.get("description", "")
                ),
                45,
            )
            await wait_until(
                lambda: any(
                    json.loads(row[0]).get("revision") == runtime.supervisor.draft.revision
                    for row in runtime.db.connection.execute(
                        "SELECT data FROM events WHERE kind='browser_evidence'"
                    )
                )
            )
            preview = runtime.browser.page
            assert (
                await preview.get_by_test_id("gianna-preview").get_attribute("data-contract")
                == "idl.gianna.form.v1"
            )
            assert await preview.get_by_test_id("ticket-submit").is_disabled()
            # The handler must block scripted submit and Enter, not just a disabled button.
            await preview.get_by_test_id("ticket-form").evaluate(
                "form => form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))"
            )
            await preview.get_by_test_id("ticket-form").press("Enter")
            assert not runtime.db.operations()
            await confirm_by_audio(console, client, runtime)
            receipt = runtime.supervisor.last_receipt
            after = await runtime.supervisor.tickets.request("GET", "/api/v1/tickets")
            assert after["total"] == before["total"] + 1
            history = await runtime.supervisor.tickets.request(
                "GET", f"/api/v1/tickets/{receipt['ticket_id']}/history"
            )
            assert history["items"][0]["channel"] == "voice_agent"
            assert runtime.db.operations()[0]["status"] == "succeeded"
            await wait_until(lambda: runtime.supervisor.state == State.DORMANT, 30)
            assert runtime.supervisor.speak_callback is not None, "DORMANT must keep WebRTC alive"
            assert not errors, errors
            tv = await runtime.browser.context.new_page()
            users = json.loads((ROOT.parent / "artifacts/design-check-users.json").read_text())
            await login_browser(tv, client, users["viewer"], "http://localhost:5474", "**/pantalla")
            await tv.get_by_test_id("display-ticket").first.wait_for(timeout=15000)
            footer = await tv.get_by_text(re.compile(r"^Página \d+ de \d+$")).inner_text()
            pages = int(re.search(r"de (\d+)$", footer)[1])
            # The isolated stack rotates every 5 s. Its persistent fixtures can
            # span more than the three pages that a fixed 15 s wait would cover.
            await (
                tv.get_by_test_id("display-ticket")
                .filter(has_text=receipt["code"])
                .wait_for(timeout=5000 * (pages + 2))
            )
            assert runtime.supervisor.user["id"] == 2
            await console.get_by_role("button", name="Activar Gianna", exact=True).click()
            await wait_until(lambda: runtime.supervisor.state == State.WAITING_INITIAL_INPUT, 20)
            armed = runtime.supervisor.idle_deadline
            assert armed and 115 < armed - time.monotonic() <= 120
            await wait_until(lambda: runtime.supervisor.state == State.DORMANT, 130)
            goodbyes = [
                json.loads(row[0])
                for row in runtime.db.connection.execute(
                    "SELECT data FROM events WHERE kind='speech'"
                )
                if json.loads(row[0]).get("text") == "Cuando necesites algo, llamame."
            ]
            assert len(goodbyes) == 1
            await phrase(
                console, client, "Hola Gianna, necesito tu ayuda para registrar un pedido nuevo."
            )
            await wait_until(
                lambda: (
                    runtime.supervisor.state == State.ASKING_MISSING_FIELD
                    and runtime.supervisor.missing == "description"
                ),
                40,
            )
            assert len(runtime.db.operations()) == 1
            assert runtime.supervisor.speak_callback is not None
            evidence = {
                "metrics": runtime.metrics.snapshot(),
                "load_samples": list(runtime.metrics.load),
                "observation_seconds": time.perf_counter() - runtime.metrics.started,
                "voice_transport": "SmallWebRTC",
                "interpreter_backend": config.interpreter_backend,
                "interpreter_model": config.conversation_model,
                "input": "synthetic es_AR-daniela-high WAV",
                "receipt": receipt,
                "one_ticket": True,
                "preview_submit_blocked": True,
                "DORMANT_transport_connected": True,
                "voice_correction": True,
                "visualizer_projection": True,
                "idle_120_seconds_from_client_playback": True,
                "voice_reactivation_without_restart": True,
                "diagnostics": runtime.diagnostics,
            }
            (ROOT.parent / "artifacts/gianna-voice-e2e.json").write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            await console.screenshot(
                path=str(ROOT.parent / "artifacts/gianna-console-e2e.png"), full_page=True
            )
    finally:
        if runtime.db:
            events = [
                dict(r)
                for r in runtime.db.connection.execute("SELECT kind,data FROM events ORDER BY id")
            ]
            (ROOT.parent / "artifacts/gianna-e2e-events.json").write_text(
                json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        if runtime.audio:
            await runtime.audio.close()
        if runtime.browser:
            await runtime.browser.close()
        server.should_exit = True
        await asyncio.wait_for(server_task, 45)
