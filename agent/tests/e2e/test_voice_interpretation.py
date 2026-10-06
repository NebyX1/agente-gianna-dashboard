"""The reported conversation through actual WAV/WebRTC/STT, API and MariaDB."""

import asyncio
from dataclasses import asdict
import json
import os
import wave

import httpx
import pytest
import uvicorn

from gianna.config import ROOT, Settings
from gianna.dialogue.interpretation import creation_request
from gianna.dialogue.state_machine import State
from gianna.server.app import create_app
from tests.e2e.audio_input import MICROPHONE, confirm_by_audio, phrase
from tests.e2e.test_voice_flow import login_browser, wait_until

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.models,
    pytest.mark.gpu,
    pytest.mark.skipif(
        os.getenv("GIANNA_REAL_E2E") != "1", reason="Explicit real isolated services"
    ),
]


async def test_reported_natural_instructions_by_real_voice(tmp_path):
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
            log_level="warning",
            access_log=False,
            timeout_graceful_shutdown=5,
        )
    )
    serving = asyncio.create_task(server.serve())
    steps = []

    def played():
        speech = runtime.supervisor.last_speech
        return not speech or any(
            json.loads(r[0])["utterance_id"] == speech["utterance_id"]
            for r in runtime.db.connection.execute(
                "SELECT data FROM events WHERE kind='playback_complete' ORDER BY id DESC LIMIT 5"
            )
        )

    async def say(console, client, text, predicate):
        await wait_until(played, 55)
        previous_speech = s.last_speech["utterance_id"] if s.last_speech else None
        await phrase(console, client, text)
        await wait_until(lambda: predicate() and s.last_speech and s.last_speech["utterance_id"] != previous_speech, 25)
        event = runtime.db.connection.execute(
            "SELECT kind,data FROM events WHERE kind IN ('stt_final','stt_rejected') ORDER BY id DESC LIMIT 1"
        ).fetchone()
        evidence = json.loads(event["data"])
        transcript = evidence.get("text") or " ".join(segment["text"] for segment in evidence.get("segments", []))
        steps.append(
            {
                "spoken": text,
                "recognized": transcript,
                "answer": runtime.supervisor.last_speech["text"],
                "accepted": event["kind"] == "stt_final",
            }
        )
        print(f"Natural voice: {transcript} -> {runtime.supervisor.state}", flush=True)
        return transcript

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
            credentials = json.loads(
                (ROOT.parent / "artifacts/design-check-users.json").read_text()
            )["operator"]
            await login_browser(runtime.browser.page, client, credentials)
            await wait_until(lambda: s.user is not None)
            console = next(
                p for p in runtime.browser.context.pages if p.url == config.console_origin + "/"
            )
            await console.add_init_script(MICROPHONE)
            await console.reload()
            await console.get_by_role("button", name="Conectar micrófono", exact=True).click()
            await wait_until(lambda: s.speak_callback is not None)
            await say(
                console,
                client,
                "Hola Gianna, ¿estás ahí?",
                lambda: s.state in {State.INVITING, State.WAITING_INITIAL_INPUT},
            )
            assert s.draft is None
            await say(
                console, client, "Te dije a ver si me habías escuchado.",
                lambda: s.draft is None and "Sí, estoy acá" in s.last_speech["text"],
            )
            assert s.pending_request is None and not runtime.db.operations()
            await say(
                console, client, "En Tránsito la impresora no imprime desde ayer.",
                lambda: s.pending_request is not None,
            )
            assert s.draft is None and not runtime.db.load_drafts(s.user["id"])
            await say(console, client, "Sí, registralo.", lambda: s.state == State.WAITING_CONFIRMATION)
            assert not runtime.db.operations()
            before_discard = asdict(s.draft)
            for discard in (
                "Quiero descartar el borrador de este pedido.",
                "Gianna, descartá el borrador, por favor.",
                "Podés eliminar el borrador de este pedido, por favor.",
            ):
                await say(console, client, discard, lambda: True)
                if s.draft is None:
                    break
                assert asdict(s.draft) == before_discard and not runtime.db.operations()
            assert s.draft is None
            assert not runtime.db.operations()
            await say(console, client, "Quiero registrar un nuevo ticket, por favor.", lambda: s.missing == "description")
            blank = asdict(s.draft)
            await say(
                console, client, "Quería saber si me estabas escuchando.",
                lambda: s.last_speech and "Sí, estoy acá" in s.last_speech["text"],
            )
            assert asdict(s.draft) == blank and s.missing == "description"
            actual = await say(
                console,
                client,
                "Necesito registrar un nuevo ticket. Desde la dirección de Tránsito nos piden arreglar una impresora que está rota. Se tranca la hoja y no permite seguir imprimiendo.",
                lambda: (
                    s.state == State.WAITING_CONFIRMATION
                    or (s.state == State.ASKING_MISSING_FIELD and s.missing == "problem_type_id")
                ),
            )
            request = creation_request(actual)
            assert request is not None and s.draft.payload["description"] == request.content
            assert "Necesito registrar" not in s.draft.payload["description"]
            if s.state == State.ASKING_MISSING_FIELD:
                # A genuine missing/uncertain catalogue classification is
                # answered by speech; the transcript is never repaired by us.
                await say(
                    console,
                    client,
                    "Es un problema de impresoras.",
                    lambda: s.state == State.WAITING_CONFIRMATION,
                )
                assert s.draft.payload["description"] == request.content
            draft, old_review = asdict(s.draft), s.confirmation
            await say(
                console,
                client,
                "Sí, pero el origen es Informática.",
                lambda: s.confirmation and s.confirmation.id != old_review.id,
            )
            assert s.draft.payload["origin_unit_id"] == 1
            assert s.draft.payload["description"] == draft["payload"]["description"]
            assert not old_review.valid(s.draft, 2, s.clock) and not runtime.db.operations()
            corrected = asdict(s.draft)
            await say(console, client, "No, todavía no.", lambda: s.state == State.COLLECTING_DRAFT)
            assert (
                asdict(s.draft) == corrected
                and s.confirmation is None
                and not runtime.db.operations()
            )
            await say(
                console,
                client,
                "Podemos seguir, por favor.",
                lambda: s.state == State.WAITING_CONFIRMATION,
            )
            assert asdict(s.draft) == corrected
            await confirm_by_audio(
                console,
                client,
                runtime,
                utterances=(
                    "Eso es todo, Gianna, registrá.",
                    "Eso es todo, registrá el pedido.",
                    "Confirmo, Gianna.",
                ),
            )
            receipt = s.last_receipt
            assert receipt["tool"] == "tickets.create.v1"
            assert (
                len(runtime.db.operations()) == 1
                and runtime.db.operations()[0]["status"] == "succeeded"
            )
            observed = await s.tickets.observe(f"tickets/{receipt['ticket_id']}")
            assert observed["description"] == corrected["payload"]["description"]
            assert observed["origin"]["id"] == 1
            assert (await s.tickets.verify({"operation_id": receipt["operation_id"]}))["event_ids"]
            await console.screenshot(
                path=str(ROOT.parent / "artifacts/gianna-interpretation.png"), full_page=True
            )
            (ROOT.parent / "artifacts/gianna-interpretation.json").write_text(
                json.dumps(
                    {
                        "real_engines": True,
                        "input": "Synthetic WAV via WebAudio/WebRTC",
                        "steps": steps,
                        "receipt": receipt,
                        "clean_description": True,
                        "correction_precedes_consent": True,
                        "negative_does_not_write": True,
                        "one_operation": True,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
    finally:
        if runtime.db:
            rows = [
                dict(r)
                for r in runtime.db.connection.execute("SELECT kind,data FROM events ORDER BY id")
            ]
            (ROOT.parent / "artifacts/gianna-interpretation-events.json").write_text(
                json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        if runtime.audio:
            await runtime.audio.close()
        if runtime.browser:
            await runtime.browser.close()
        server.should_exit = True
        await asyncio.wait_for(serving, 45)
