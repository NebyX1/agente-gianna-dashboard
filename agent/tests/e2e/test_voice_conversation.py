"""Conversation + ticket completion through genuine WAV/WebRTC/STT/TTS and API.

Audio is synthetic, injected only by the test microphone. No text commands or
forced transcripts substitute for business utterances. Uses the isolated stack.
"""

import asyncio
from dataclasses import asdict
import json
import os
import wave

import httpx
import pytest
import uvicorn

from gianna.config import ROOT, Settings
from gianna.dialogue.state_machine import State
from gianna.server.app import create_app
from tests.e2e.audio_input import MICROPHONE, confirm_by_audio, phrase
from tests.e2e.test_voice_flow import login_browser, wait_until

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.models,
    pytest.mark.gpu,
    pytest.mark.skipif(os.getenv("GIANNA_REAL_E2E") != "1", reason="Real isolated models/services"),
]


async def test_everyday_conversation_and_resolve_by_real_voice(tmp_path):
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
    s = None  # Runtime constructs its supervisor during startup.
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
    steps = []

    def played():
        if not s.last_speech:
            return True
        rows = runtime.db.connection.execute(
            "SELECT data FROM events WHERE kind='playback_complete' ORDER BY id DESC LIMIT 5"
        )
        return any(json.loads(r[0])["utterance_id"] == s.last_speech["utterance_id"] for r in rows)

    async def say(console, client, text, predicate, *, alternatives=()):
        # Wait for genuine client completion; a long help response must not race
        # the next fixture. Retries speak again, never reinterpret the transcript.
        for utterance in (text, *alternatives):
            await wait_until(played, 55)
            original_draft = asdict(s.draft) if s.draft else None
            original_operations = {r["operation_id"] for r in runtime.db.operations()}
            await phrase(console, client, utterance)
            try:
                await wait_until(predicate, 15)
            except AssertionError:
                # A rejected clip can be repeated by speaking another explicit
                # request. Never repeat an uncertain write or silently replace
                # a transcript that changed the user's draft.
                assert {r["operation_id"] for r in runtime.db.operations()} == original_operations
                assert (asdict(s.draft) if s.draft else None) == original_draft
                steps.append({"utterance": utterance, "accepted": False, "state": s.state})
                continue
            print(f"Voice conversation: {utterance} -> {s.state}", flush=True)
            steps.append(
                {
                    "utterance": utterance,
                    "accepted": True,
                    "state": s.state,
                    "answer": s.last_speech["text"],
                }
            )
            return
        raise AssertionError(f"Genuine voice requests did not reach expected state: {text}")

    def intent_seen(intent, after):
        rows = runtime.db.connection.execute(
            "SELECT data FROM events WHERE kind='conversation_intent' AND id>?", (after,)
        )
        return any(json.loads(r[0])["intent"] == intent for r in rows)

    def event_id():
        return runtime.db.connection.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]

    try:
        await wait_until(lambda: server.started, 150)
        s = runtime.supervisor
        assert s.state != State.BLOCKED, runtime.diagnostics
        fixture = tmp_path / "silence.wav"
        with wave.open(str(fixture), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(48000)
            wav.writeframes(bytes(96000))
        await runtime.browser.start(runtime.broker, visible=False, audio_fixture=fixture)
        async with httpx.AsyncClient(timeout=20) as client:
            users = json.loads((ROOT.parent / "artifacts/design-check-users.json").read_text())
            await login_browser(runtime.browser.page, client, users["operator"])
            await wait_until(lambda: s.user is not None)
            rows = (await s.tickets.request("GET", "/api/v1/tickets"))["items"]
            target = next(
                r
                for r in rows
                if r["created_by_user_id"] == 2 and r["status"] not in {"resolved", "cancelled"}
            )
            number = int(target["code"][-6:])
            console = next(
                p for p in runtime.browser.context.pages if p.url == config.console_origin + "/"
            )
            await console.add_init_script(MICROPHONE)
            await console.reload()
            await console.get_by_role("button", name="Conectar micrófono", exact=True).click()
            await wait_until(lambda: s.speak_callback is not None)
            before = event_id()
            await say(
                console, client, "Hola Gianna, ¿estás ahí?", lambda: intent_seen("presence", before)
            )
            assert "Sí, estoy acá" in s.last_speech["text"] and s.draft is None
            before = event_id()
            await say(console, client, "¿Qué podés hacer?", lambda: intent_seen("help", before))
            assert s.draft is None and not runtime.db.operations()
            await say(
                console,
                client,
                "La impresora no imprime desde esta mañana.",
                lambda: s.state == State.ASKING_MISSING_FIELD,
            )
            assert s.missing == "origin_unit_id"
            saved = asdict(s.draft)
            for text, intent in [
                ("¿Me escuchás?", "presence"),
                ("Muchas gracias.", "thanks"),
                ("¿Qué te falta?", "next"),
                ("Repetí la pregunta, por favor.", "repeat"),
            ]:
                before = event_id()
                await say(console, client, text, lambda: intent_seen(intent, before))
                assert asdict(s.draft) == saved and s.missing == "origin_unit_id"
                assert not runtime.db.operations()
            await say(
                console,
                client,
                "Estoy al teléfono.",
                lambda: s.state == State.PAUSED,
                alternatives=("Esperame un minuto, por favor.",),
            )
            await say(
                console,
                client,
                "Hola Gianna, seguimos.",
                lambda: s.state == State.ASKING_MISSING_FIELD,
                alternatives=("Hola Gianna, retomemos el borrador.",),
            )
            assert asdict(s.draft) == saved and s.confirmation is None
            await say(
                console,
                client,
                "Finalizá la conversación.",
                lambda: s.state == State.DORMANT,
                alternatives=("Gracias, terminamos por hoy.",),
            )
            assert asdict(s.draft) == saved and not runtime.db.operations()
            assert s.confirmation is None
            initial_operations = 0
            if target["status"] == "new":
                await say(
                    console,
                    client,
                    f"Hola Gianna, pasá el ticket número {number} a En curso.",
                    lambda: s.last_receipt is not None,
                )
                await wait_until(lambda: s.state == State.DORMANT, 40)
                target = await s.tickets.observe(f"tickets/{target['id']}")
                assert target["status"] == "in_progress"
                initial_operations = 1
            await say(
                console,
                client,
                f"Hola Gianna, finalizá el ticket número {number}.",
                lambda: s.draft and s.draft.tool == "tickets.status.v1",
            )
            assert s.draft.payload == {"version": target["version"], "status": "resolved"}
            assert (
                s.missing == "note"
                and s.confirmation is None
                and len(runtime.db.operations()) == initial_operations
            )
            await say(
                console,
                client,
                "El equipo confirmó que la intervención terminó correctamente.",
                lambda: s.state == State.WAITING_CONFIRMATION,
            )
            terminal_draft = asdict(s.draft)
            before = event_id()
            await say(console, client, "Gracias.", lambda: intent_seen("thanks", before))
            assert (
                asdict(s.draft) == terminal_draft
                and len(runtime.db.operations()) == initial_operations
            )
            await confirm_by_audio(console, client, runtime)
            receipt = s.last_receipt
            assert receipt["tool"] == "tickets.status.v1" and receipt["ticket_id"] == target["id"]
            observed = await s.tickets.observe(f"tickets/{target['id']}")
            assert observed["status"] == "resolved" and observed["version"] == target["version"] + 1
            assert len(runtime.db.operations()) == initial_operations + 1
            assert (await s.tickets.verify({"operation_id": receipt["operation_id"]}))["event_ids"]
            await wait_until(lambda: s.state == State.DORMANT, 40)
            # Address the assistant explicitly again, then recover the saved
            # request. Both are genuine speech; the dormant wake gate stays on.
            before = event_id()
            await say(
                console,
                client,
                "Hola Gianna, necesito tu ayuda.",
                lambda: intent_seen("help", before),
            )
            assert s.draft is None
            await say(
                console,
                client,
                "Podemos seguir, por favor.",
                lambda: (
                    s.state == State.ASKING_MISSING_FIELD
                    and s.draft is not None
                    and s.draft.id == saved["id"]
                ),
                alternatives=("Seguimos, por favor.",),
            )
            assert asdict(s.draft) == saved and s.missing == "origin_unit_id"
            await console.screenshot(
                path=str(ROOT.parent / "artifacts/gianna-conversation.png"), full_page=True
            )
            (ROOT.parent / "artifacts/gianna-conversation.json").write_text(
                json.dumps(
                    {
                        "real_engines": True,
                        "microphone": "Test-only WAV -> WebAudio -> WebRTC",
                        "steps": steps,
                        "resolved": receipt,
                        "one_terminal_operation": True,
                        "initial_operations": initial_operations,
                        "draft_preserved_and_resumed": True,
                        "metrics": runtime.metrics.snapshot(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
    finally:
        if runtime.db:
            events = [
                dict(r)
                for r in runtime.db.connection.execute("SELECT kind,data FROM events ORDER BY id")
            ]
            (ROOT.parent / "artifacts/gianna-conversation-events.json").write_text(
                json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        if runtime.audio:
            await runtime.audio.close()
        if runtime.browser:
            await runtime.browser.close()
        server.should_exit = True
        await asyncio.wait_for(running, 45)
