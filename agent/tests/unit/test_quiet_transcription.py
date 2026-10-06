from types import SimpleNamespace

import numpy as np
import pytest
from gianna.audio.stt_whisper_turbo import WhisperResident, transcription_samples, speech_window


def pcm(scale):
    samples = np.sin(np.arange(16000) * 2 * np.pi * 220 / 16000) * scale
    return (samples * 32767).astype(np.int16).tobytes()


def test_quiet_gain_is_bounded_and_normal_level_is_unchanged():
    samples, gain = transcription_samples(pcm(0.006))
    assert gain == 6 and max(np.abs(samples)) < 0.04
    normal, gain = transcription_samples(pcm(0.2))
    assert gain == 1 and max(np.abs(normal)) < 0.21


def test_gain_does_not_clip_an_isolated_peak():
    samples = np.zeros(16000, np.int16)
    samples[100:500] = 32000
    samples[1000:] = np.frombuffer(pcm(0.005), np.int16)[:15000]
    result, gain = transcription_samples(samples.tobytes())
    assert gain == 1 and max(np.abs(result)) < 1


def test_silence_is_rejected_before_any_gain_or_model_request():
    resident = WhisperResident(SimpleNamespace(raw_audio=False))
    resident.model = SimpleNamespace(transcribe=lambda *a, **k: pytest.fail("Silence reached STT"))
    text, evidence = resident.transcribe_sync(bytes(32000))
    assert not text and evidence["reason"] == "silence"


def test_short_speech_window_preserves_quiet_edges_and_internal_pause():
    speech = np.frombuffer(pcm(0.006), np.int16).astype(np.float32) / 32768
    original = np.concatenate([np.zeros(16000), speech, np.zeros(16000), speech, np.zeros(24000)])
    cropped, offset = speech_window(original)
    assert offset == pytest.approx(0.75)
    assert len(cropped) == 56000
    assert np.array_equal(cropped[4000:20000], speech)
    assert np.count_nonzero(cropped[20000:36000]) == 0


def test_accepted_quiet_segment_is_not_filtered_by_a_second_vad():
    captured = {}

    def transcribe(samples, **options):
        captured.update(options)
        captured["rms"] = float(np.sqrt(np.mean(samples * samples)))
        return [
            SimpleNamespace(
                text="Secretaría General pidió hojas",
                start=0,
                end=1,
                no_speech_prob=0,
                avg_logprob=-0.2,
            )
        ], SimpleNamespace(language="es")

    resident = WhisperResident(SimpleNamespace(raw_audio=False))
    resident.model = SimpleNamespace(transcribe=transcribe)
    text, evidence = resident.transcribe_sync(pcm(0.006))
    assert text == "Secretaría General pidió hojas" and evidence["applied_gain"] == 6
    assert captured["beam_size"] == 5 and captured["vad_filter"] is False
    assert captured["rms"] > 0.02
