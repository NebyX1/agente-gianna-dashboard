import asyncio
import httpx
from gianna.diagnostics import versions
from gianna.audio.model_manifest import verify
from gianna.profiles.loader import load_profile
from gianna.models.local_interpreter import LocalInterpreter
from gianna.models.cloud_interpreter import CloudInterpreter
from gianna.adapters.credentials import Credentials
from gianna.audio.stt_whisper_turbo import WhisperResident
from gianna.audio.tts_piper import PiperResident, SynthesisRequest


async def audio_probe(config):
    import io
    import wave
    from gianna.audio.denoise import RequiredRNNoiseFilter
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3

    stt, piper = WhisperResident(config), PiperResident(config)
    try:
        await piper.worker.run(piper.load)
        wav = await piper.worker.run(
            piper.synthesize,
            SynthesisRequest(
                text="Hola Gianna, necesito tu ayuda para registrar un pedido.",
                sample_rate=16000,
                speed=0.8,
            ),
        )
        with wave.open(io.BytesIO(wav), "rb") as w:
            pcm = w.readframes(w.getnframes())
            assert w.getframerate() == 16000 and w.getnchannels() == 1
        await stt.warmup()
        text, evidence = await stt.transcribe(pcm)
        if not text:
            raise RuntimeError("stt_no_speech_in_fixture")
        denoise = RequiredRNNoiseFilter()
        await denoise.start(16000)
        await denoise.filter(pcm)
        await denoise.stop()
        vad = SileroVADAnalyzer()
        vad.set_sample_rate(16000)
        await vad.analyze_audio(pcm[:1024])
        turn = LocalSmartTurnAnalyzerV3(
            smart_turn_model_path=str(config.models_dir / "smart-turn-v3.2-cpu.onnx"), cpu_count=1
        )
        turn.set_sample_rate(16000)
        turn.append_audio(pcm, True)
        await turn.analyze_end_of_turn()
        return {
            "device": config.stt_device,
            "compute_type": config.stt_compute_type,
            "transcript": text,
            "Piper": "Daniela 22050->16000 Hz",
            "RNNoise": "real PCM processed",
            "Silero": "processed",
            "SmartTurn": "v3.2 CPU processed",
            "microphone": "requires explicit browser permission",
        }
    finally:
        await stt.worker.close()
        await piper.worker.close()


async def browser_probe():
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content("<main><h1>Prueba local de Gianna</h1></main>")
            assert await page.get_by_role("heading", name="Prueba local de Gianna").count() == 1
            return {"browser": browser.version, "managed": True}
        finally:
            await browser.close()


async def doctor(config):
    result = {"ready": True, "versions": versions(), "checks": {}}
    async with httpx.AsyncClient() as client:
        checks = {
            "models": lambda: asyncio.to_thread(verify, config),
            "profile": lambda: asyncio.to_thread(load_profile),
            "interpreter": lambda: (
                CloudInterpreter if config.interpreter_backend == "cloud" else LocalInterpreter
            )(config, client).preflight(),
            "audio": lambda: audio_probe(config),
            "browser": browser_probe,
            "tickets": lambda: client.get(config.tickets_api + "/readyz", timeout=5),
            "contract": lambda: client.get(config.tickets_api + "/api/v1/openapi.json", timeout=5),
        }
        for name, call in checks.items():
            try:
                data = await call()
                if isinstance(data, httpx.Response):
                    data.raise_for_status()
                    data = data.json()
                if name == "contract" and not {
                    "/auth/agent-session",
                    "/agent/operations/{operation_id}",
                } <= set(data["paths"]):
                    raise RuntimeError("Tickets delegation/receipt contract missing")
                result["checks"][name] = {
                    "status": "ok",
                    "details": data if name in {"interpreter", "audio", "browser"} else "verified",
                }
            except Exception as exc:
                result["ready"] = False
                result["checks"][name] = {
                    "status": "failed",
                    "error": type(exc).__name__,
                    "detail": str(exc)[:250],
                }
    credentials = Credentials()
    result["credentials"] = {
        "backend": credentials.backend_name,
        "secure": credentials.secure,
        "storage": "os_keyring" if credentials.secure else "memory_only",
    }
    result["cloud"] = {
        "configured": bool(config.cloud_api_key),
        "model": config.cloud_model,
        "required_for_tickets": config.interpreter_backend == "cloud",
    }
    result["note"] = (
        "Doctor prueba dependencias reales en su proceso. run repite warmup en la instancia residente; el permiso y la prueba del micrófono/parlante físicos requieren al usuario."
    )
    return result
