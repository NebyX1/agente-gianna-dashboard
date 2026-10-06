import asyncio
import time
import aiohttp
import numpy as np
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.frames.frames import (
    TranscriptionFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
    InterruptionFrame,
    TTSSpeakFrame,
    ErrorFrame,
    MetricsFrame,
    InputAudioRawFrame,
)
from pipecat.metrics.metrics import TurnMetricsData
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.pipeline.runner import PipelineRunner
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frameworks.rtvi.processor import RTVIProcessor
from pipecat.processors.frameworks.rtvi.frames import RTVIServerMessageFrame
from pipecat.services.piper.tts import PiperHttpTTSService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.turns.user_turn_processor import UserTurnProcessor
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.turns.user_start.vad_user_turn_start_strategy import VADUserTurnStartStrategy
from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import (
    TurnAnalyzerUserTurnStopStrategy,
)
from gianna.audio.stt_whisper_turbo import LocalWhisperService, RejectedFrame
from gianna.audio.denoise import RecognitionPreservingDenoise
from gianna.audio.turn_boundary import TurnBoundary, guard_delay
from gianna.dialogue.state_machine import State
from gianna.runtime.observability import voice_response_clock


class DialogueProcessor(FrameProcessor):
    def __init__(self, supervisor, resident, *, interruption_upstream=False):
        super().__init__()
        self.supervisor, self.resident = supervisor, resident
        config = getattr(resident, "config", None)
        self.stt_wait = config.stt_grace_seconds if config else 15
        self.settle_base = config.turn_settle_seconds if config else 0.4
        self.silence_limit = config.turn_stop_seconds if config else 2.0
        self.turn = TurnBoundary()
        self.queue = asyncio.Queue(maxsize=8)
        self.consumer = None
        self.current_input = None
        self.settle = None
        self.vad_clock = None
        self.interruption_upstream = interruption_upstream

    async def consume(self):
        while True:
            text, evidence, response_clock = await self.queue.get()
            if self.current_input and not self.current_input.done():
                self.current_input.cancel()
                await asyncio.gather(self.current_input, return_exceptions=True)
                self.supervisor.publish("semantic_work_interrupted", {})

            async def handle(text=text, evidence=evidence, response_clock=response_clock):
                timing_token = voice_response_clock.set(response_clock)
                try:
                    await self.supervisor.submit(text, source="voice", evidence=evidence)
                except Exception as exc:
                    if str(exc) == "stale_generation":
                        return
                    await self.supervisor.report_failure(exc)
                finally:
                    voice_response_clock.reset(timing_token)

            self.current_input = asyncio.create_task(handle())
            self.queue.task_done()

    def cancel_settle(self):
        if self.settle and not self.settle.done() and self.settle is not asyncio.current_task():
            self.settle.cancel()
        self.settle = None

    def arbitrate(self):
        """Dispatch only once the detector, every STT segment and a short silence agree."""
        turn = self.turn
        self.cancel_settle()
        if turn.dispatched or turn.speaking:
            return
        if not turn.complete:
            # An incomplete SmartTurn verdict must not keep several independent
            # repetitions in one turn indefinitely. Speech resuming cancels this.
            if self.vad_clock and (turn.pending or turn.segments):
                delay = max(
                    0, self.silence_limit - (time.perf_counter() - self.vad_clock["stopped_at"])
                )
                self.settle = asyncio.create_task(self.finish_after_silence(turn, delay))
            return
        if turn.pending:
            delay = self.stt_wait  # Watchdog: a segment whose transcript never arrives.
        elif turn.segments:
            delay = guard_delay(turn.text, self.settle_base)
        else:
            return
        self.settle = asyncio.create_task(self.settle_turn(turn, delay))

    async def finish_after_silence(self, turn, delay):
        await asyncio.sleep(delay)
        if self.turn is turn and not turn.dispatched and not turn.speaking:
            turn.finish()
            self.supervisor.publish("turn_silence_limit", {"segments": len(turn.segments)})
            self.arbitrate()

    async def settle_turn(self, turn, delay):
        await asyncio.sleep(delay)
        if self.turn is not turn or turn.dispatched or turn.speaking:
            return
        if turn.pending:
            turn.pending = 0
            self.supervisor.publish("stt_timeout", {"segments": len(turn.segments)})
        text = turn.consume()
        if text:
            self.dispatch(text)
        else:
            turn.dispatched = True
            await self.supervisor.rejected_audio(turn.rejection or {"reason": "no_transcript"})

    def dispatch(self, text):
        if self.queue.full():
            self.supervisor.publish(
                "saturation",
                {"component": "accepted_turns", "message": "Pausá la captura y reconectá"},
            )
            self.supervisor.set_state(State.BLOCKED)
            return
        if self.vad_clock and hasattr(self.supervisor, "metrics"):
            self.supervisor.metrics.add(
                "vad_stop_to_turn_dispatch",
                (time.perf_counter() - self.vad_clock["stopped_at"]) * 1000,
            )
        last = (
            next(iter(self.turn.evidence.values()))
            if len(self.turn.evidence) == 1
            else {"parts": list(self.turn.evidence.values())}
            if self.turn.evidence
            else getattr(self.resident, "last_evidence", None)
        )
        self.queue.put_nowait((text, last, self.vad_clock))

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if direction != FrameDirection.DOWNSTREAM:
            if isinstance(frame, ErrorFrame):
                await self.audio_error(frame)
            await self.push_frame(frame, direction)
            return
        if self.consumer is None:
            self.consumer = asyncio.create_task(self.consume())
        boundary_changed = True
        if isinstance(frame, VADUserStartedSpeakingFrame):
            self.cancel_settle()
            self.vad_clock = None
            if self.turn.dispatched:
                self.turn = TurnBoundary()
            self.turn.speech_started()
            if not self.interruption_upstream:
                await self.supervisor.vad_started()
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            # Frame timestamp comes from the detector, before STT/queue processing.
            self.vad_clock = {
                "stopped_at": time.perf_counter() - max(0, time.time() - frame.timestamp),
                "silence_seconds": frame.stop_secs,
                "recorded": False,
            }
            self.turn.speech_stopped()
            if hasattr(self.supervisor, "metrics"):
                self.supervisor.metrics.add("vad_reported_silence", frame.stop_secs * 1000)
            await self.supervisor.vad_stopped()
        elif isinstance(frame, MetricsFrame) and hasattr(self.supervisor, "metrics"):
            for metric in frame.data:
                if isinstance(metric, TurnMetricsData):
                    self.supervisor.metrics.add(
                        "smart_turn_inference", metric.e2e_processing_time_ms
                    )
        elif isinstance(frame, TranscriptionFrame) and direction == FrameDirection.DOWNSTREAM:
            self.turn.transcript(frame.id, frame.text, getattr(frame, "gianna_evidence", None))
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self.turn.finish()
        elif isinstance(frame, RejectedFrame):
            self.turn.reject(frame.evidence)
            if not self.turn.segments and self.turn.settled():
                # Pure noise: let the supervisor restore what the noise interrupted.
                await self.supervisor.rejected_audio(frame.evidence)
        elif isinstance(frame, ErrorFrame):
            await self.audio_error(frame)
        else:
            boundary_changed = False
        # Continuous PCM and status packets do not move the silence deadline.
        # Otherwise a healthy live microphone postpones dispatch forever.
        if boundary_changed:
            self.arbitrate()
        await self.push_frame(frame, direction)

    async def audio_error(self, frame):
        """Audio faults are reported but never brick the session."""
        from gianna.runtime.errors import ErrorCode, MESSAGES

        error = str(frame.error)
        stt = error.startswith(("STT:", "stt_unavailable"))
        code = (
            ErrorCode.STT
            if stt
            else ErrorCode.TTS
            if error.startswith("tts_unavailable") or "TTS context" in error
            else ErrorCode.AUDIO
        )
        if stt and self.turn.pending:
            self.turn.reject({"reason": error})
        self.supervisor.errors.append(
            {"component": "audio", "code": code, "message": MESSAGES[code]}
        )
        self.supervisor.publish("audio_error", {"code": code, "detail": error[:120]})
        self.supervisor.publish("state", self.supervisor.snapshot())

    async def cleanup(self):
        self.cancel_settle()
        if self.current_input:
            self.current_input.cancel()
            await asyncio.gather(self.current_input, return_exceptions=True)
        if self.consumer:
            self.consumer.cancel()
            await asyncio.gather(self.consumer, return_exceptions=True)
        await super().cleanup()


class AcousticInterruptionProcessor(FrameProcessor):
    """Cut output at acoustic onset, before transcription/semantic turn handling."""

    def __init__(self, supervisor):
        super().__init__()
        self.supervisor = supervisor

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if (
            isinstance(frame, VADUserStartedSpeakingFrame)
            and direction == FrameDirection.DOWNSTREAM
        ):
            await self.supervisor.vad_started()
        await self.push_frame(frame, direction)


class AudioInputMonitor(FrameProcessor):
    """Checks actual received PCM, independently of the WebRTC data channel.

    Sends bounded level/counter updates to this audio client. No audio is retained.
    """

    def __init__(self):
        super().__init__()
        self.received_ms = 0.0
        self.frames = 0
        self.last_received = None
        self.last_report = 0.0
        self.level = 0.0

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame) and direction == FrameDirection.DOWNSTREAM:
            self.last_received = time.perf_counter()
            self.frames += 1
            self.received_ms += (
                len(frame.audio) * 1000 / (2 * frame.sample_rate * frame.num_channels)
            )
            samples = np.frombuffer(frame.audio, dtype=np.int16).astype(np.float32) / 32768
            self.level = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0
            if self.last_received - self.last_report >= 0.5:
                self.last_report = self.last_received
                await self.push_frame(
                    RTVIServerMessageFrame(
                        data={
                            "kind": "audio_input",
                            "received_ms": self.received_ms,
                            "frames": self.frames,
                            "level": self.level,
                        }
                    )
                )
        await self.push_frame(frame, direction)


class GuardedPiper(PiperHttpTTSService):
    def __init__(self, supervisor, **kwargs):
        self.supervisor = supervisor
        self.packet = None
        self.response_clock = None
        self.output_epoch = 0
        self.context_generations = {}
        super().__init__(**kwargs)

    async def process_frame(self, frame, direction):
        if isinstance(frame, InterruptionFrame):
            self.output_epoch += 1
        if isinstance(frame, TTSSpeakFrame):
            packet = getattr(frame, "gianna_packet", None)
            if not packet or packet["generation_id"] != self.supervisor.generation_id:
                return
            self.packet = packet
            self.response_clock = getattr(frame, "gianna_response_clock", None)
        await super().process_frame(frame, direction)

    async def _record_context_audio_outcome(self, context_id, received_audio):
        binding = self.context_generations.pop(context_id, None)
        if binding and binding != (self.supervisor.generation_id, self.output_epoch):
            self.supervisor.publish("tts_cancelled", {"context_id": context_id})
            return  # Intentional cancellation is not a silent provider response.
        await super()._record_context_audio_outcome(context_id, received_audio)
        if received_audio:
            remaining = [e for e in self.supervisor.errors if e.get("code") != "tts_unavailable"]
            if remaining != self.supervisor.errors:
                self.supervisor.errors = remaining
                self.supervisor.publish("audio_recovered", {"component": "tts"})
                self.supervisor.publish("state", self.supervisor.snapshot())

    async def run_tts(self, text, context_id):
        generation = self.packet["generation_id"] if self.packet else None
        epoch = self.output_epoch
        self.context_generations[context_id] = (generation, epoch)
        while len(self.context_generations) > 64:
            self.context_generations.pop(next(iter(self.context_generations)))
        response_clock = self.response_clock
        start = time.perf_counter()
        first = True
        try:
            async with self._session.post(
                self._base_url,
                json={
                    "text": text,
                    "voice": "es_AR-daniela-high",
                    "sample_rate": self.sample_rate,
                    "speed": self.supervisor.voice_speed,
                },
            ) as response:
                if response.status != 200:
                    if (generation, epoch) == (self.supervisor.generation_id, self.output_epoch):
                        yield ErrorFrame(error=f"tts_unavailable:http_{response.status}")
                    return
                async for frame in self._stream_audio_frames_from_iterator(
                    response.content.iter_chunked(self.chunk_size),
                    strip_wav_header=True,
                    context_id=context_id,
                ):
                    if (generation, epoch) != (self.supervisor.generation_id, self.output_epoch):
                        return
                    if first and hasattr(self.supervisor, "metrics"):
                        first = False
                        self.supervisor.metrics.add(
                            "tts_first_server_audio", (time.perf_counter() - start) * 1000
                        )
                        if response_clock and not response_clock["recorded"]:
                            response_clock["recorded"] = True
                            elapsed = time.perf_counter() - response_clock["stopped_at"]
                            self.supervisor.metrics.add(
                                "vad_stop_to_first_server_response_audio", elapsed * 1000
                            )
                            self.supervisor.metrics.add(
                                "estimated_speech_end_to_first_server_response_audio",
                                (elapsed + response_clock["silence_seconds"]) * 1000,
                            )
                    yield frame
        except Exception as exc:
            if (generation, epoch) == (self.supervisor.generation_id, self.output_epoch):
                yield ErrorFrame(error=f"tts_unavailable:{type(exc).__name__}")
        finally:
            # HTTP TTS contexts are closed by Pipecat after the final text frame.
            # Yielding a stop from a cancelled generator races that lifecycle.
            await self.stop_ttfb_metrics()


class AudioPipeline:
    def __init__(self, config, supervisor, resident):
        self.config, self.supervisor, self.resident = config, supervisor, resident
        self.task = self.transport = self.session = None
        self.running = None
        self.monitor = None

    async def connect(self, connection):
        if self.task:
            raise RuntimeError("audio_session_already_active")
        c, s = self.config, self.supervisor
        self.monitor = AudioInputMonitor()
        self.transport = SmallWebRTCTransport(
            connection,
            TransportParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                audio_in_sample_rate=16000,
                audio_out_sample_rate=c.transport_sample_rate,
                audio_out_channels=1,
            ),
        )
        vad = VADProcessor(
            vad_analyzer=SileroVADAnalyzer(
                params=VADParams(
                    confidence=c.vad_confidence,
                    start_secs=c.vad_start_seconds,
                    stop_secs=c.vad_stop_seconds,
                    min_volume=c.vad_min_volume,
                )
            )
        )
        stt = LocalWhisperService(self.resident, sample_rate=16000)
        turn = LocalSmartTurnAnalyzerV3(
            smart_turn_model_path=str(c.models_dir / "smart-turn-v3.2-cpu.onnx"),
            cpu_count=1,
            params=SmartTurnParams(stop_secs=c.turn_stop_seconds, pre_speech_ms=500),
        )
        turn_manager = UserTurnProcessor(
            user_turn_strategies=UserTurnStrategies(
                start=[VADUserTurnStartStrategy(enable_interruptions=False)],
                stop=[
                    TurnAnalyzerUserTurnStopStrategy(turn_analyzer=turn, wait_for_transcript=False)
                ],
            ),
            user_idle_timeout=0,
            user_turn_stop_timeout=c.turn_stop_seconds + 2,
        )
        dialogue = DialogueProcessor(s, self.resident, interruption_upstream=True)
        rtvi = RTVIProcessor()
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=35, connect=3, sock_read=32)
        )
        tts = GuardedPiper(
            s,
            base_url=f"http://127.0.0.1:{c.piper_port}",
            aiohttp_session=self.session,
            sample_rate=c.transport_sample_rate,
            # Piper returns a complete WAV. Long help/review synthesis can take
            # more than Pipecat's default 3 s; retain its audio context through
            # the bounded HTTP synthesis deadline instead of discarding speech.
            stop_frame_timeout_s=35,
            settings=GuardedPiper.Settings(voice="es_AR-daniela-high"),
        )
        pipeline = Pipeline(
            [
                self.transport.input(),
                self.monitor,
                rtvi,
                RecognitionPreservingDenoise(),
                vad,
                AcousticInterruptionProcessor(s),
                stt,
                turn_manager,
                dialogue,
                tts,
                self.transport.output(),
            ]
        )
        self.task = PipelineTask(
            pipeline,
            idle_timeout_secs=None,
            params=PipelineParams(
                allow_interruptions=True,
                audio_in_sample_rate=16000,
                audio_out_sample_rate=c.transport_sample_rate,
            ),
            observers=[rtvi.create_rtvi_observer()],
        )
        task, session = self.task, self.session

        @rtvi.event_handler("on_client_ready")
        async def ready(processor):
            await processor.set_bot_ready()
            s.publish(
                "audio_ready",
                {"input_sample_rate": 16000, "output_sample_rate": c.transport_sample_rate},
            )

        @self.transport.event_handler("on_client_disconnected")
        async def disconnected(transport, client):
            if self.task is task:
                s.speak_callback = s.stop_callback = None
                s.confirmation = None
            await task.cancel()

        async def speak(message):
            await task.queue_frame(RTVIServerMessageFrame(data={"kind": "speech", **message}))
            frame = TTSSpeakFrame(text=message["text"], append_to_context=False)
            frame.gianna_packet = message
            frame.gianna_response_clock = voice_response_clock.get()
            await task.queue_frame(frame)

        async def stop():
            start = time.perf_counter()
            # Never reset capture, VAD, STT or the accepted-turn queue for barge-in.
            # The priority system frame cancels synthesis and flushes output only.
            await tts.queue_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
            if hasattr(s, "metrics"):
                s.metrics.add("stop_frame_enqueue", (time.perf_counter() - start) * 1000)

        s.speak_callback, s.stop_callback = speak, stop

        async def run():
            try:
                await PipelineRunner(handle_sigint=False).run(task)
            finally:
                await session.close()
                if self.task is task:
                    s.speak_callback = s.stop_callback = None
                    self.task = None

        self.running = asyncio.create_task(run())

    async def close(self):
        if self.task:
            await self.task.cancel()
        if self.running:
            await asyncio.gather(self.running, return_exceptions=True)
