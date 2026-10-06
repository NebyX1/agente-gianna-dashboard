from types import SimpleNamespace

import pytest
from pipecat.frames.frames import ErrorFrame, InterruptionFrame, VADUserStartedSpeakingFrame
from pipecat.processors.frame_processor import FrameDirection

from gianna.audio.pipeline import AcousticInterruptionProcessor, GuardedPiper, DialogueProcessor


class Supervisor:
    generation_id = "generation"
    voice_speed = 1

    def __init__(self):
        self.errors = []
        self.events = []
        self.stops = 0

    def publish(self, kind, data):
        self.events.append((kind, data))

    def snapshot(self):
        return {"errors": self.errors}

    async def vad_started(self):
        self.stops += 1


async def test_acoustic_cut_preserves_start_frame_and_does_not_reset_capture():
    s = Supervisor()
    p = AcousticInterruptionProcessor(s)
    downstream = []

    async def push(frame, direction):
        downstream.append(frame)

    p.push_frame = push
    start = VADUserStartedSpeakingFrame()
    await p.process_frame(start, FrameDirection.DOWNSTREAM)
    assert s.stops == 1 and downstream == [start]
    assert not any(isinstance(frame, InterruptionFrame) for frame in downstream)


@pytest.mark.parametrize(
    "error",
    [
        "tts_unavailable:http_503",
        "TTS context 123 completed with no audio",
        "3 consecutive TTS contexts completed with no audio",
    ],
)
async def test_synthesis_fault_does_not_report_microphone_failure(error):
    s = Supervisor()
    p = DialogueProcessor(s, SimpleNamespace())
    await p.audio_error(ErrorFrame(error=error))
    assert s.errors[-1]["code"] == "tts_unavailable"
    assert "micrófono" not in s.errors[-1]["message"]


async def test_cancelled_silent_context_does_not_count_as_provider_failure():
    s = Supervisor()
    tts = GuardedPiper(s, base_url="http://127.0.0.1:5002", aiohttp_session=None)
    tts.context_generations["old"] = (s.generation_id, tts.output_epoch)
    tts.output_epoch += 1
    await tts._record_context_audio_outcome("old", False)
    assert tts._consecutive_zero_audio_contexts == 0
    assert s.events[-1][0] == "tts_cancelled"


async def test_actual_silent_provider_is_reported_and_success_clears_voice_error():
    s = Supervisor()
    tts = GuardedPiper(s, base_url="http://127.0.0.1:5002", aiohttp_session=None)
    failures = []

    async def fail(error_msg, **kwargs):
        failures.append(error_msg)

    tts.push_error = fail
    await tts._record_context_audio_outcome("failed", False)
    assert tts._consecutive_zero_audio_contexts == 1 and failures
    s.errors = [{"code": "tts_unavailable"}, {"code": "permission_denied"}]
    await tts._record_context_audio_outcome("healthy", True)
    assert s.errors == [{"code": "permission_denied"}]
    assert tts._consecutive_zero_audio_contexts == 0
    assert any(kind == "audio_recovered" for kind, _ in s.events)
