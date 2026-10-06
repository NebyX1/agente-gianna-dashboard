"""Real fixed-engine regression and measurements; synthesized speech is labelled explicitly."""

import asyncio
import io
import json
import time
import wave
import numpy as np
from gianna.config import Settings, ROOT
from gianna.audio.tts_piper import PiperResident, SynthesisRequest
from gianna.audio.stt_whisper_turbo import WhisperResident
from gianna.audio.denoise import RequiredRNNoiseFilter
from gianna.dialogue.activation import normalize


async def main():
    config = Settings()
    piper = PiperResident(config)
    stt = WhisperResident(config)
    folder = ROOT.parent / "artifacts/audio-regression"
    folder.mkdir(exist_ok=True)
    rows = []
    try:
        await piper.worker.run(piper.load)
        await stt.warmup()
        rng = np.random.default_rng(20261004)
        silence = np.zeros(32000, dtype=np.int16)
        impulse = silence.copy()
        impulse[16000:16010] = 30000
        keyboard = silence.copy()
        for start in [4000, 8000, 14000, 22000]:
            keyboard[start : start + 80] = rng.integers(-12000, 12000, 80, dtype=np.int16)
        noise = rng.normal(0, 1000, 32000).astype(np.int16)
        inputs = [
            ("silence", silence.tobytes(), None),
            ("impulse", impulse.tobytes(), None),
            ("keyboard", keyboard.tobytes(), None),
            ("noise", noise.tobytes(), None),
        ]
        for name, text in [
            ("wake", "Hola Gianna, necesito tu ayuda para registrar un pedido nuevo."),
            ("dictation", "En Tránsito la impresora no imprime y tiene un atasco de papel."),
            ("yes", "Sí."),
            ("no", "No."),
            ("stop", "Pará."),
            ("confirm", "Sí, eso es todo."),
        ]:
            started = time.perf_counter()
            wav = await piper.worker.run(
                piper.synthesize, SynthesisRequest(text=text, speed=0.8, sample_rate=16000)
            )
            with wave.open(io.BytesIO(wav), "rb") as w:
                pcm = w.readframes(w.getnframes())
            inputs.append((name, pcm, text))
            rows.append({"kind": "tts", "name": name, "seconds": time.perf_counter() - started})
        for name, pcm, expected in inputs:
            with wave.open(str(folder / (name + ".wav")), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(pcm)
            denoise = RequiredRNNoiseFilter()
            await denoise.start(16000)
            clean = await denoise.filter(pcm)
            await denoise.stop()
            started = time.perf_counter()
            text, evidence = await stt.transcribe(clean)
            rows.append(
                {
                    "kind": "stt",
                    "name": name,
                    "expected": expected,
                    "actual": text,
                    "exact_normalized_match": normalize(text).strip(" .,")
                    == normalize(expected or "").strip(" .,"),
                    "seconds": time.perf_counter() - started,
                    "evidence": evidence,
                }
            )
            if expected is None:
                assert not text, f"Noise yielded accepted text: {name}: {text}"
        assert any(row.get("actual") for row in rows if row.get("name") in {"yes", "no", "stop"}), (
            "All short controls rejected"
        )
        result = {
            "input": "Synthetic es_AR-daniela-high and generated control noise",
            "human_audio": False,
            "device": config.stt_device,
            "compute_type": config.stt_compute_type,
            "rows": rows,
        }
        (ROOT.parent / f"artifacts/gianna-audio-regression-{config.stt_device}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=True, indent=2))
    finally:
        await stt.worker.close()
        await piper.worker.close()


if __name__ == "__main__":
    asyncio.run(main())
