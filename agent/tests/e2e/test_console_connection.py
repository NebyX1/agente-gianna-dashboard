"""Small real WebRTC connection diagnostic, no business write or STT substitution."""

import asyncio
import os
import wave
import pytest
import uvicorn
from playwright.async_api import expect
from gianna.config import Settings
from gianna.server.app import create_app
from tests.e2e.test_voice_flow import wait_until

pytestmark = [
    pytest.mark.models,
    pytest.mark.gpu,
    pytest.mark.e2e,
    pytest.mark.skipif(os.getenv("GIANNA_REAL_E2E") != "1", reason="Owned models/browser services"),
]


async def test_console_real_webrtc_connection(tmp_path):
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
    running = asyncio.create_task(server.serve())
    try:
        await wait_until(lambda: server.started, 120)
        audio = tmp_path / "silence.wav"
        with wave.open(str(audio), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(48000)
            wav.writeframes(bytes(48000 * 2 * 60))
        await runtime.browser.start(runtime.broker, visible=False, audio_fixture=audio)
        console = next(
            p for p in runtime.browser.context.pages if p.url == config.console_origin + "/"
        )
        messages = []
        console.on("console", lambda m: messages.append(m.text[:200]))
        await runtime.browser.context.route("https://**/*", lambda route: route.abort())
        # A copied localhost link must work in a browser with no launcher cookie.
        await runtime.browser.context.clear_cookies()
        await console.reload()
        await expect(
            console.get_by_role("button", name="Activar Gianna", exact=True)
        ).to_be_enabled()
        cookies = await runtime.browser.context.cookies(config.console_origin)
        assert any(c["name"] == "gianna_pairing" and c["httpOnly"] for c in cookies)
        assert await console.evaluate("async () => (await fetch('/api/state')).status") == 200
        assert not await console.get_by_text(
            "Se perdió la conexión con Gianna.", exact=False
        ).count()

        # Recover the actual SSE connection after a browser network outage. No
        # command is replayed; the supervisor's draft and generation stay intact.
        before = runtime.supervisor.snapshot()
        await runtime.browser.context.set_offline(True)
        await expect(console.get_by_role("heading", name="Reconectando con Gianna")).to_be_visible(
            timeout=25000
        )
        await expect(
            console.get_by_role("button", name="Activar Gianna", exact=True)
        ).to_be_disabled()
        # Repair lost pairing from the loaded UI, without navigating again.
        await runtime.browser.context.clear_cookies()
        await runtime.browser.context.set_offline(False)
        await expect(
            console.get_by_role("button", name="Activar Gianna", exact=True)
        ).to_be_enabled(timeout=15000)
        after = runtime.supervisor.snapshot()
        assert (
            after["draft"] == before["draft"] and after["generation_id"] == before["generation_id"]
        )
        assert await console.evaluate("async () => (await fetch('/api/state')).status") == 200

        await console.get_by_role("button", name="Conectar micrófono", exact=True).click()
        try:
            await wait_until(lambda: runtime.supervisor.speak_callback is not None, 15)
        except AssertionError:
            raise AssertionError(str(messages) + await console.locator("main").inner_text())
        assert runtime.supervisor.speak_callback
        # A second unpaired browser can take the one audio channel explicitly.
        # Opening it alone does not disconnect the first microphone.
        other = await runtime.browser.context.browser.new_context(permissions=["microphone"])
        try:
            await other.route("https://**/*", lambda route: route.abort())
            second = await other.new_page()
            await second.goto(config.console_origin)
            await expect(
                second.get_by_role("button", name="Activar Gianna", exact=True)
            ).to_be_enabled()
            await expect(
                console.get_by_role("button", name="Micrófono conectado", exact=True)
            ).to_be_visible()
            await second.get_by_role("button", name="Conectar micrófono", exact=True).click()
            await expect(
                second.get_by_role("button", name="Micrófono conectado", exact=True)
            ).to_be_visible(timeout=20000)
            await expect(
                console.get_by_role("button", name="Conectar micrófono", exact=True)
            ).to_be_visible(timeout=10000)
            assert runtime.supervisor.speak_callback
        finally:
            await other.close()
    finally:
        await runtime.audio.close()
        await runtime.browser.close()
        server.should_exit = True
        await asyncio.wait_for(running, 45)
