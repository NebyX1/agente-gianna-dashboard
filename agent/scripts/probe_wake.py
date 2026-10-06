"""Measure synthetic Daniela phrases through the real resident Whisper engine."""

import asyncio
import io
import json
import wave
import httpx
from gianna.config import Settings, ROOT
from gianna.audio.stt_whisper_turbo import WhisperResident


async def main():
    stt = WhisperResident(Settings())
    await stt.warmup()
    results = []
    async with httpx.AsyncClient() as client:
        for text in [
            "Hola Gianna, necesito tu ayuda para registrar un pedido nuevo.",
            "Gianna, por favor ayudame a registrar un ticket.",
            "Gianna, registra un ticket para la oficina de Tránsito.",
            "Giana, necesito registrar un pedido nuevo.",
            "Hola, Iana, quiero registrar un pedido.",
            "Sí, es todo.",
            "Sí.",
            "No.",
            "Pará.",
        ]:
            for speed in [1, 0.8]:
                response = await client.post(
                    "http://127.0.0.1:5001/",
                    json={"text": text, "speed": speed, "sample_rate": 16000},
                    timeout=30,
                )
                response.raise_for_status()
                with wave.open(io.BytesIO(response.content), "rb") as w:
                    pcm = w.readframes(w.getnframes())
                actual, evidence = await stt.transcribe(pcm)
                results.append(
                    {"input": text, "speed": speed, "actual": actual, "evidence": evidence}
                )
                print(json.dumps(results[-1], ensure_ascii=True), flush=True)
    (ROOT.parent / "artifacts/gianna-synthetic-phrases.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    await stt.worker.close()


asyncio.run(main())
