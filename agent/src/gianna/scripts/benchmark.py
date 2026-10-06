import time
import httpx
import numpy as np
from gianna.audio.stt_whisper_turbo import WhisperResident
from gianna.models.ollama_tev1 import TevDecision
from gianna.diagnostics import versions


def percentiles(samples):
    return (
        {
            "count": len(samples),
            "p50_ms": float(np.percentile(samples, 50)),
            "p95_ms": float(np.percentile(samples, 95)),
        }
        if samples
        else {"count": 0}
    )


async def benchmark(config):
    result = {"hardware": versions(), "synthetic": True, "human_audio": False}
    resident = WhisperResident(config)
    start = time.perf_counter()
    await resident.warmup()
    result["resident_warmup_ms"] = (time.perf_counter() - start) * 1000
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"http://127.0.0.1:{config.piper_port}/",
            json={
                "text": "En Tránsito la impresora no imprime y muestra una luz roja.",
                "sample_rate": 16000,
            },
            timeout=30,
        )
        r.raise_for_status()
        import io
        import wave

        with wave.open(io.BytesIO(r.content), "rb") as w:
            pcm = w.readframes(w.getnframes())
        times = []
        transcripts = []
        for _ in range(10):
            start = time.perf_counter()
            text, evidence = await resident.transcribe(pcm)
            times.append((time.perf_counter() - start) * 1000)
            transcripts.append(text)
        result["stt_warm"] = percentiles(times)
        result["transcript"] = transcripts[-1]
        tev = TevDecision(config, client)
        result["tev_preflight"] = await tev.preflight()
        times = []
        for _ in range(10):
            start = time.perf_counter()
            choice = await tev.choose(
                "Gianna, registrá un ticket",
                {"create": "Orden de crear", "ignore": "No hay orden", "clarify": "Ambiguo"},
            )
            times.append((time.perf_counter() - start) * 1000)
        result["decision_warm"] = percentiles(times)
        result["last_decision"] = choice
    await resident.worker.close()
    return result
