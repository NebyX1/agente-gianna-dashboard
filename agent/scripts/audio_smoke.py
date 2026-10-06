import asyncio
import json
import time
import wave
from pathlib import Path
from gianna.config import settings
from gianna.audio.stt_whisper_turbo import WhisperResident


async def main():
    stt = WhisperResident(settings())
    start = time.perf_counter()
    await stt.warmup()
    cold = time.perf_counter() - start
    with wave.open(
        str(Path(__file__).resolve().parents[2] / "artifacts/gianna-dictation.wav"), "rb"
    ) as w:
        assert w.getframerate() == 16000
        pcm = w.readframes(w.getnframes())
    start = time.perf_counter()
    text, evidence = await stt.transcribe(pcm)
    print(
        json.dumps(
            {
                "warmup_seconds": cold,
                "stt_seconds": time.perf_counter() - start,
                "text": text,
                "evidence": evidence,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    await stt.worker.close()


if __name__ == "__main__":
    asyncio.run(main())
