"""Native Chromium microphone: first negation and full-sentence consent during TTS.

No getUserMedia, STT, transcript or autoplay override. Synthetic Daniela audio
uses Chromium's WAV capture device and writes only to the isolated test API.
"""

import asyncio
from dataclasses import asdict
import io
import json
import os
import re
import time
import wave

import httpx
import numpy as np
import pytest
import uvicorn
from playwright.async_api import expect
from scipy.signal import resample_poly

from gianna.config import ROOT, Settings
from gianna.dialogue.activation import normalize
from gianna.dialogue.draft import Draft
from gianna.dialogue.interpretation import Reply
from gianna.dialogue.state_machine import State
from gianna.server.app import create_app
from tests.e2e.test_voice_flow import login_browser, wait_until

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.models,
    pytest.mark.gpu,
    pytest.mark.skipif(
        os.getenv("GIANNA_REAL_E2E") != "1", reason="Explicit real native voice test"
    ),
]


async def test_first_interruption_and_natural_spoken_confirmation(tmp_path):
    base = Settings()
    config = Settings(
        data_dir=tmp_path,
        model_dir=base.models_dir,
        nltk_dir=base.data_dir / "nltk",
        tickets_api="http://localhost:5400",
        tickets_web="http://localhost:5473",
        port=7862,
        piper_port=5002,
        raw_audio=True,  # Synthetic test input only, retained for failed ASR diagnosis.
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
    console = None
    interruptions = []
    evidence = {
        "input": "synthetic Daniela via native Chromium WAV microphone",
        "microphone_override": False,
        "transcript_override": False,
        "autoplay_override": False,
        "interruptions": [],
        "short_speech": [],
    }
    try:
        await wait_until(lambda: server.started, 150)
        s = runtime.supervisor
        assert s.state != State.BLOCKED, runtime.diagnostics

        def rows(kind):
            return [
                json.loads(r[0])
                for r in runtime.db.connection.execute(
                    "SELECT data FROM events WHERE kind=? ORDER BY id", (kind,)
                )
            ]

        async with httpx.AsyncClient() as client:

            async def synth(text, speed=1):
                response = await client.post(
                    "http://127.0.0.1:5002/",
                    json={"text": text, "speed": speed, "sample_rate": 48000},
                    timeout=35,
                )
                response.raise_for_status()
                with wave.open(io.BytesIO(response.content)) as wav:
                    return np.frombuffer(wav.readframes(wav.getnframes()), np.int16).copy()

            # Check short, quiet answers and negations with the real resident decoder.
            reviewed = asdict(
                Draft(
                    1,
                    payload={
                        "origin_unit_id": 7,
                        "destination_unit_id": 1,
                        "problem_type_id": 2,
                        "description": "Secretaría General solicita hojas para las impresoras",
                    },
                )
            )
            for text in ["Confirmo", "Confirmado", "No confirmo", "No, todavía no"]:
                source = await synth(text, 1.15)
                for amplitude in (1, 0.18):
                    samples = resample_poly(source.astype(np.float32), 1, 3) * amplitude
                    pcm = np.concatenate([np.zeros(16000), samples, np.zeros(20800)]).astype(
                        np.int16
                    )
                    decoded, detail = await runtime.stt.transcribe(pcm.tobytes())
                    meaning, decision = await s.review_interpreter.interpret(
                        decoded, reviewed, source="voice"
                    )
                    evidence["short_speech"].append(
                        {
                            "said": text,
                            "amplitude": amplitude,
                            "heard": decoded,
                            "quality": detail,
                            "review_reply": meaning.kind,
                            "semantic_decision": decision.model_dump(),
                        }
                    )
                    plain = normalize(decoded)
                    if text.startswith("No"):
                        assert re.search(r"\bno\b", plain), (text, decoded)
                        assert meaning.kind != Reply.APPROVE
                    else:
                        assert meaning.kind == Reply.APPROVE, (text, decoded, decision)

            phrases = [
                (8, "No, no lo guardes todavía"),
                (23, "Hola Gianna, ahora quiero que sigamos con el pedido que estaba preparando"),
                (38, "Sí, Gianna, confirmado, podés guardar la operación que acabás de revisar"),
            ]
            samples = np.zeros(48000 * 80, np.int16)
            for offset, text in phrases:
                clip = await synth(text, 1.05)
                samples[offset * 48000 : offset * 48000 + len(clip)] = clip
            fixture = tmp_path / "native-interruptions.wav"
            with wave.open(str(fixture), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(48000)
                wav.writeframes(samples.tobytes())
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
            await console.get_by_label("Mensaje para Gianna").fill(
                "Creá un ticket. En Secretaría General necesitan cambiar las hojas de todas las impresoras. "
                "Son dos equipos, uno al lado de la ventana y otro junto a la puerta. "
                "Lo necesitan hoy antes de las tres de la tarde para imprimir los expedientes."
            )
            await console.get_by_role("button", name="Enviar a Gianna", exact=True).click()
            await wait_until(lambda: s.state == State.WAITING_CONFIRMATION, 45)
            payload = dict(s.draft.payload)
            assert not s.db.operations()
            interruptions = []
            publish = s.publish

            def observe(kind, data):
                if kind == "audio_interrupted":
                    interruptions.append(time.time() * 1000)
                publish(kind, data)

            s.publish = observe
            await console.get_by_role("button", name="Conectar micrófono", exact=True).click()
            await expect(
                console.get_by_role("button", name="Micrófono conectado", exact=True)
            ).to_be_visible(timeout=15000)
            # Observe received RTC samples; do not alter playback or the microphone.
            await console.evaluate("""async()=>{
                const audio=document.querySelector('audio');
                const ctx=new AudioContext();await ctx.resume();
                const source=ctx.createMediaStreamSource(audio.srcObject);
                const analyser=ctx.createAnalyser();analyser.fftSize=512;source.connect(analyser);
                const sink=ctx.createGain();sink.gain.value=0;analyser.connect(sink);sink.connect(ctx.destination);
                const values=new Float32Array(512);window.__rtcSamples=[];
                window.__rtcSampleTimer=setInterval(()=>{analyser.getFloatTimeDomainData(values);
                    const rms=Math.sqrt(values.reduce((sum,x)=>sum+x*x,0)/values.length);
                    window.__rtcSamples.push({at:Date.now(),rms,muted:audio.muted});},20);
            }""")
            await console.get_by_role("button", name="Repetir", exact=True).click()
            await wait_until(lambda: s.state == State.PAUSED, 18)
            assert len(rows("stt_final")) == 1, rows("stt_final")
            assert "no" in normalize(rows("stt_final")[0]["text"])
            assert s.draft.payload == payload and not s.db.operations()
            await wait_until(
                lambda: len(rows("stt_final")) >= 2 and s.state == State.WAITING_CONFIRMATION, 30
            )
            assert not s.db.operations()
            await wait_until(lambda: s.last_receipt is not None, 30)
            assert len(rows("stt_final")) == 3, rows("stt_final")
            assert "confirm" in normalize(rows("stt_final")[2]["text"])
            assert len(s.db.operations()) == 1 and s.db.operations()[0]["status"] == "succeeded"
            receipt = s.last_receipt
            ticket = await s.tickets.request("GET", f"/api/v1/tickets/{receipt['ticket_id']}")
            assert ticket["description"] == payload["description"]
            assert (await s.tickets.request("GET", "/api/v1/tickets"))["total"] == before + 1
            rtc = await console.evaluate("window.__rtcSamples")
            evidence.update(
                rtc_samples=rtc,
                acoustic_cuts=interruptions,
                metrics=runtime.supervisor.metrics.snapshot(),
            )
            assert len(interruptions) == 3, interruptions
            # First negation and final consent both interrupt actual playing speech.
            for cut in (interruptions[0], interruptions[2]):
                before_cut = [r for r in rtc if cut - 700 <= r["at"] < cut]
                assert any(r["rms"] > 0.003 for r in before_cut), "No actual TTS overlap"
                quiet = next(
                    (r for r in rtc if cut <= r["at"] <= cut + 500 and r["rms"] < 0.0003), None
                )
                assert quiet, "RTC output did not stop within 500 ms of acoustic interruption"
                after_cut = [r for r in rtc if cut + 500 <= r["at"] <= cut + 900]
                assert after_cut and max(r["rms"] for r in after_cut) < 0.0003, (
                    "Old speech resumed after the interruption"
                )
                evidence["interruptions"].append(
                    {"at": cut, "output_stopped_ms": quiet["at"] - cut}
                )
            assert not rows("audio_error"), rows("audio_error")
            assert not s.errors
            evidence.update(
                transcripts=rows("stt_final"),
                receipt=receipt,
                ticket=ticket,
                semantic_review=rows("review_interpreted"),
                operations=len(s.db.operations()),
            )
            await console.screenshot(
                path=str(ROOT.parent / "artifacts/gianna-native-barge-in.png"), full_page=True
            )
    finally:
        if console and not console.is_closed():
            evidence.setdefault("rtc_samples", await console.evaluate("window.__rtcSamples ?? []"))
        evidence.setdefault("acoustic_cuts", interruptions)
        if runtime.supervisor and hasattr(runtime.supervisor, "metrics"):
            evidence.setdefault("metrics", runtime.supervisor.metrics.snapshot())
        if runtime.db:
            evidence["events"] = [
                dict(r)
                for r in runtime.db.connection.execute("SELECT kind,data FROM events ORDER BY id")
            ]
        (ROOT.parent / "artifacts/gianna-native-barge-in.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if runtime.audio:
            await runtime.audio.close()
        if runtime.browser:
            await runtime.browser.close()
        server.should_exit = True
        await asyncio.wait_for(serving, 45)
