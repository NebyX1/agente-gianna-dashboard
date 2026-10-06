from pathlib import Path
from types import SimpleNamespace

from pipecat.frames.frames import InputAudioRawFrame
from pipecat.processors.frame_processor import FrameDirection

from gianna.audio.denoise import RecognitionPreservingDenoise
from gianna.audio.stt_whisper_turbo import LocalWhisperService


async def test_resampler_buffering_pairs_original_pcm_without_losing_chunks():
    class Filter:
        calls = 0

        async def filter(self, audio):
            self.calls += 1
            return b"" if self.calls == 1 else bytes(8)

        async def stop(self):
            pass

    p = RecognitionPreservingDenoise(Filter())
    output = []

    async def push(frame, direction):
        output.append(frame)

    p.push_frame = push
    await p.process_frame(InputAudioRawFrame(b"1234", 16000, 1), FrameDirection.DOWNSTREAM)
    assert not output
    await p.process_frame(InputAudioRawFrame(b"5678", 16000, 1), FrameDirection.DOWNSTREAM)
    assert len(output) == 1 and output[0].audio == bytes(8)
    assert output[0].gianna_recognition_audio == b"12345678"
    assert not p.original
    await p.cleanup()


async def test_whisper_buffers_original_and_leaves_detector_frame_cleaned():
    resident = SimpleNamespace(
        model=None,
        config=SimpleNamespace(
            models_dir=Path("models"),
            stt_device="cpu",
            stt_compute_type="int8",
            max_turn_seconds=90,
        ),
    )
    p = LocalWhisperService(resident, sample_rate=16000)
    p._user_speaking = True
    frame = InputAudioRawFrame(bytes(8), 16000, 1)
    frame.gianna_recognition_audio = b"12345678"
    await p.process_audio_frame(frame, FrameDirection.DOWNSTREAM)
    assert p._audio_buffer == b"12345678"
    assert frame.audio == bytes(8)
