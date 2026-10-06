"""Synthetic Daniela -> real Whisper -> public reference. No physical mic claim."""

import io
import os
import wave

import pytest

from gianna.audio.stt_whisper_turbo import WhisperResident
from gianna.audio.tts_piper import PiperResident, SynthesisRequest
from gianna.config import Settings
from gianna.dialogue.numbers import ticket_number

pytestmark = [
    pytest.mark.integration,
    pytest.mark.models,
    pytest.mark.gpu,
    pytest.mark.skipif(os.getenv("GIANNA_REAL_E2E") != "1", reason="Explicit native audio models"),
]


async def test_whisper_understands_short_numbers_and_termination(tmp_path):
    config = Settings(data_dir=tmp_path, model_dir=Settings().models_dir)
    piper, stt = PiperResident(config), WhisperResident(config)
    try:
        await piper.worker.run(piper.load)
        await stt.warmup()
        for phrase, number in [
            ("Leeme el ticket número uno.", 1),
            ("Leeme el ticket terminación veinticinco.", 25),
            ("Leeme el ticket número ciento veintitrés.", 123),
        ]:
            wav = await piper.worker.run(
                piper.synthesize, SynthesisRequest(text=phrase, sample_rate=16000, speed=0.85)
            )
            with wave.open(io.BytesIO(wav)) as audio:
                pcm = audio.readframes(audio.getnframes())
            transcript, evidence = await stt.transcribe(pcm)
            print("Native reference:", phrase, "->", transcript, flush=True)
            assert not evidence["reason"]
            assert ticket_number(transcript) == number
    finally:
        await stt.worker.close()
        await piper.worker.close()
