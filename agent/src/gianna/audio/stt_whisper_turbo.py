import re
from copy import copy
from dataclasses import asdict
from datetime import UTC, datetime
import numpy as np
from pipecat.services.whisper.stt import WhisperSTTService
from pipecat.transcriptions.language import Language
from pipecat.frames.frames import TranscriptionFrame, ErrorFrame, DataFrame
from gianna.runtime.cancellation import NativeWorker
from gianna.audio.quality_gate import measure


_HALLUCINATIONS = re.compile(
    r"amara\s*\.?\s*org|subtitulos? (?:realizados? )?por|gracias por (?:ver|mirar|su atencion)|"
    r"suscribete|no olvides suscribirte|^\W*(?:musica|aplausos|risas)\W*$|^\W*gracias\W*$",
)


def keep_segment(s):
    from gianna.dialogue.activation import normalize

    if _HALLUCINATIONS.search(normalize(s["text"]).strip()) and s["avg_logprob"] < -0.35:
        return False
    if s["no_speech_prob"] > 0.8 or s["avg_logprob"] < -2.0:
        return False
    return not (s["no_speech_prob"] > 0.6 and s["avg_logprob"] < -1.0)


def transcription_samples(pcm):
    """Bounded gain for a quiet accepted speech segment, never for rejected noise."""
    samples = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768
    rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0
    peak = float(np.max(np.abs(samples))) if samples.size else 0
    gain = min(6.0, 0.035 / rms, 0.9 / peak) if rms and peak else 1.0
    gain = max(1.0, gain)
    return samples * gain, gain


def speech_window(samples, sample_rate=16000):
    """Trim exterior silence only, preserving quiet phonemes and internal pauses."""
    step = sample_rate // 50
    rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0
    threshold = max(0.0015, rms * 0.12)
    active = [
        i
        for i in range(0, len(samples), step)
        if float(np.sqrt(np.mean(samples[i : i + step] ** 2))) >= threshold
    ]
    if not active:
        return samples, 0
    margin = int(sample_rate * 0.25)
    start = max(0, active[0] - margin)
    end = min(len(samples), active[-1] + step + margin)
    return samples[start:end], start / sample_rate


class RejectedFrame(DataFrame):
    def __init__(self, evidence):
        super().__init__()
        self.evidence = evidence


class WhisperResident:
    def __init__(self, config):
        self.config = config
        self.worker = NativeWorker("whisper")
        self.model = None
        self.last_evidence = None

    def load(self):
        import ctranslate2
        from faster_whisper import WhisperModel

        c = self.config
        if c.stt_device == "cuda":
            if not ctranslate2.get_cuda_device_count() or c.stt_compute_type != "int8_float16":
                raise RuntimeError("Whisper requires CUDA/int8_float16; no automatic CPU fallback")
        elif c.stt_device != "cpu" or c.stt_compute_type != "int8":
            raise RuntimeError("Only explicit CPU/int8 or CUDA/int8_float16 profiles are supported")
        self.model = WhisperModel(
            str(c.models_dir / "whisper-large-v3-turbo"),
            device=c.stt_device,
            compute_type=c.stt_compute_type,
            cpu_threads=1,
            num_workers=1,
        )
        segments, _ = self.model.transcribe(
            np.zeros(16000, dtype=np.float32),
            language="es",
            task="transcribe",
            beam_size=1,
            vad_filter=False,
        )
        list(segments)  # Warmup physical native inference, same process and instance.

    async def warmup(self):
        await self.worker.run(self.load)

    def transcribe_sync(self, pcm):
        if self.config.raw_audio:
            import wave
            from uuid import uuid4

            root = self.config.data_dir / "audio-diagnostics"
            root.mkdir(exist_ok=True)
            # Opt-in bounded ring of 20 utterances, not a continuous microphone recording.
            for old in sorted(root.glob("*.wav"), key=lambda p: p.stat().st_mtime)[:-19]:
                old.unlink()
            with wave.open(str(root / (str(uuid4()) + ".wav")), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(pcm)
        evidence = asdict(measure(pcm))
        if evidence["reason"]:
            return "", {**evidence, "segments": []}
        samples, gain = transcription_samples(pcm)
        samples, offset = speech_window(samples)
        segments, info = self.model.transcribe(
            samples,
            language="es",
            task="transcribe",
            beam_size=5,
            temperature=0,
            condition_on_previous_text=False,
            initial_prompt=(
                "Conversación en español rioplatense con Gianna sobre tickets de Lavalleja. "
                "La persona puede confirmar, negar, corregir o consultar: confirmo, confirmado, "
                "no confirmo, no todavía, esperá, corregí, continuamos. "
                "Vocabulario del sistema: áreas registradas, orígenes, oficinas, municipios, "
                "destinos habilitados, tipos de problema, descripción, estado del ticket. "
                "Informática, Tránsito, Sociales, Secretaría General. "
                "Ticket número uno, terminación veinticinco, ticket ciento veintitrés."
            ),
            # Already segmented by the streaming VAD. A second VAD pass can
            # remove quiet words from a real microphone's accepted segment.
            vad_filter=False,
            hotwords="Gianna Lavalleja Informática Tránsito Sociales Secretaría General áreas registradas oficinas municipios destinos tipos de problema impresoras hojas ticket confirmo confirmado confirmar confirmamos correcto no todavía esperá",
            log_prob_threshold=-1,
            no_speech_threshold=0.6,
        )
        rows = [
            dict(
                text=s.text.strip(),
                start=s.start + offset,
                end=s.end + offset,
                no_speech_prob=s.no_speech_prob,
                avg_logprob=s.avg_logprob,
            )
            for s in segments
        ]
        # Dropping a real segment silently cuts the sentence, so only clear non-speech
        # and known Whisper hallucinations are rejected.
        accepted = [s["text"] for s in rows if s["text"] and keep_segment(s)]
        return " ".join(accepted), {
            **evidence,
            "segments": rows,
            "applied_gain": gain,
            "transcribed_ms": len(samples) * 1000 / 16000,
            "trimmed_start_ms": offset * 1000,
            "reason": None if accepted else "no_accepted_segments",
            "language": info.language,
        }

    async def transcribe(self, pcm):
        import time

        start = time.perf_counter()
        text, evidence = await self.worker.run(self.transcribe_sync, pcm)
        if hasattr(self, "metrics"):
            self.metrics.add("stt", (time.perf_counter() - start) * 1000)
        self.last_evidence = evidence
        return text, evidence


class LocalWhisperService(WhisperSTTService):
    def __init__(self, resident, **kwargs):
        self.resident = resident
        super().__init__(
            model=str(resident.config.models_dir / "whisper-large-v3-turbo"),
            device=resident.config.stt_device,
            compute_type=resident.config.stt_compute_type,
            settings=self.Settings(language=Language.ES),
            **kwargs,
        )
        import asyncio

        self._segment_queue = asyncio.Queue(maxsize=4)
        self._overflow = False

    async def process_audio_frame(self, frame, direction):
        # VAD/SmartTurn keep the cleaned signal. Recognition uses the original
        # matching PCM: RNNoise can suppress quiet unvoiced consonants as noise.
        if hasattr(frame, "gianna_recognition_audio"):
            frame = copy(frame)
            frame.audio = frame.gianna_recognition_audio
        if (
            len(self._audio_buffer) + len(frame.audio)
            > self.resident.config.max_turn_seconds * 16000 * 2
        ):
            self._overflow = True
            self._audio_buffer.clear()
            await self.push_frame(ErrorFrame(error="audio_turn_budget_exceeded"))
            return
        if not self._overflow:
            await super().process_audio_frame(frame, direction)

    async def _handle_user_stopped_speaking(self, frame):
        if self._overflow or self._segment_queue.full():
            self._audio_buffer.clear()
            self._overflow = False
            await self.push_frame(RejectedFrame({"reason": "audio_queue_saturated"}))
            return
        await super()._handle_user_stopped_speaking(frame)

    def _load(self):
        self._model = self.resident.model

    async def run_stt(self, audio):
        try:
            text, evidence = await self.resident.transcribe(audio)
            if text:
                frame = TranscriptionFrame(
                    text, self._user_id, datetime.now(UTC).isoformat(), Language.ES
                )
                frame.gianna_evidence = evidence
                yield frame
            else:
                yield RejectedFrame(evidence)
        except Exception as exc:
            yield RejectedFrame({"reason": "stt_error", "error": type(exc).__name__})
