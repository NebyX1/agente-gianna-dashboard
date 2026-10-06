from pipecat.audio.filters.rnnoise_filter import RNNoiseFilter
from pipecat.frames.frames import StartFrame, InputAudioRawFrame, FilterControlFrame, ErrorFrame
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection


class RequiredRNNoiseFilter(RNNoiseFilter):
    """A fresh streaming RNNoise/resampler state is created for EVERY transport."""

    async def start(self, sample_rate):
        await super().start(sample_rate)
        if not self._rnnoise_ready:
            raise RuntimeError("RNNoise unavailable")
        await super().filter(bytes((sample_rate // 50) * 2))


class RecognitionPreservingDenoise(FrameProcessor):
    """Denoise for acoustic detectors without discarding Whisper's consonants.

    Streaming resampling can buffer several input chunks. Pair the emitted
    sample count with a FIFO of original PCM, rather than the current chunk.
    Both paths remain ephemeral; this does not record microphone audio.
    """

    def __init__(self, audio_filter=None):
        super().__init__()
        self.filter = audio_filter or RequiredRNNoiseFilter()
        self.original = bytearray()

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM:
            if isinstance(frame, StartFrame):
                await self.filter.start(16000)
            elif isinstance(frame, InputAudioRawFrame):
                self.original.extend(frame.audio)
                if len(self.original) > 16000 * 2 * 2:
                    self.original.clear()
                    await self.push_frame(ErrorFrame(error="stt_unavailable:audio_filter_backlog"))
                    return
                filtered = await self.filter.filter(frame.audio)
                if not filtered:
                    return
                count = len(filtered)
                if count > len(self.original):
                    # A warmup/resampler tail can precede live samples.
                    self.original[:0] = bytes(count - len(self.original))
                frame.gianna_recognition_audio = bytes(self.original[:count])
                del self.original[:count]
                frame.audio = filtered
            elif isinstance(frame, FilterControlFrame):
                await self.filter.process_frame(frame)
        await self.push_frame(frame, direction)

    async def cleanup(self):
        self.original.clear()
        await self.filter.stop()
        await super().cleanup()
