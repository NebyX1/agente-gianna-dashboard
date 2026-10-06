"""A spoken turn must wait for every pause-separated segment before it is understood."""

import asyncio
import time

import pytest

from gianna.audio.pipeline import DialogueProcessor
from gianna.audio.stt_whisper_turbo import RejectedFrame, keep_segment
from gianna.audio.turn_boundary import TurnBoundary, guard_delay
from pipecat.frames.frames import (
    TranscriptionFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
    InputAudioRawFrame,
)
from pipecat.processors.frame_processor import FrameDirection


class Supervisor:
    def __init__(self):
        self.submitted, self.rejected, self.events = [], [], []

    async def submit(self, text, **kwargs):
        self.submitted.append(text)

    async def vad_started(self):
        pass

    async def vad_stopped(self):
        pass

    async def rejected_audio(self, evidence):
        self.rejected.append(evidence)

    def publish(self, kind, data):
        self.events.append(kind)


class Resident:
    last_evidence = None

    class config:
        stt_grace_seconds = 0.5
        turn_settle_seconds = 0.01
        turn_stop_seconds = 0.05


@pytest.fixture
async def processor():
    p = DialogueProcessor(Supervisor(), Resident())

    async def noop(*args, **kwargs):
        pass

    p.push_frame = noop
    yield p
    await p.cleanup()


def stopped():
    return VADUserStoppedSpeakingFrame(stop_secs=0.8, timestamp=time.time())


async def feed(p, frame):
    await p.process_frame(frame, FrameDirection.DOWNSTREAM)


async def wait_for(condition, timeout=2):
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.01)


async def test_sentence_split_by_a_pause_is_dispatched_whole(processor):
    p = processor
    first, second = (
        TranscriptionFrame("Necesito crear un ticket para", "u", "t"),
        TranscriptionFrame("la impresora de Tránsito.", "u", "t"),
    )
    await feed(p, VADUserStartedSpeakingFrame())
    await feed(p, stopped())
    await feed(p, first)
    await feed(p, VADUserStartedSpeakingFrame())
    await feed(p, stopped())
    # The detector closes the turn while the second segment is still being transcribed.
    await feed(p, UserStoppedSpeakingFrame())
    await asyncio.sleep(0.1)
    assert p.supervisor.submitted == []
    await feed(p, second)
    await wait_for(lambda: p.supervisor.submitted)
    assert p.supervisor.submitted == ["Necesito crear un ticket para la impresora de Tránsito."]


async def test_noise_segment_does_not_discard_the_real_one(processor):
    p = processor
    await feed(p, VADUserStartedSpeakingFrame())
    await feed(p, stopped())
    await feed(p, RejectedFrame({"reason": "impulse"}))
    await feed(p, VADUserStartedSpeakingFrame())
    await feed(p, stopped())
    await feed(p, UserStoppedSpeakingFrame())
    await feed(p, TranscriptionFrame("En Tránsito no anda internet.", "u", "t"))
    await wait_for(lambda: p.supervisor.submitted)
    assert p.supervisor.submitted == ["En Tránsito no anda internet."]


async def test_pure_noise_is_reported_once_and_not_dispatched(processor):
    p = processor
    await feed(p, VADUserStartedSpeakingFrame())
    await feed(p, stopped())
    await feed(p, RejectedFrame({"reason": "silence"}))
    await feed(p, UserStoppedSpeakingFrame())
    await asyncio.sleep(0.1)
    assert p.supervisor.submitted == [] and p.supervisor.rejected == [{"reason": "silence"}]


async def test_lost_transcript_does_not_freeze_the_turn(processor):
    p = processor
    await feed(p, VADUserStartedSpeakingFrame())
    await feed(p, stopped())
    await feed(p, TranscriptionFrame("Hola Gianna.", "u", "t"))
    await feed(p, VADUserStartedSpeakingFrame())
    await feed(p, stopped())  # this segment never produces anything
    await feed(p, UserStoppedSpeakingFrame())
    await wait_for(lambda: p.supervisor.submitted, timeout=3)
    assert p.supervisor.submitted == ["Hola Gianna."]
    assert "stt_timeout" in p.supervisor.events


async def test_speech_resuming_cancels_a_pending_dispatch(processor):
    p = processor
    await feed(p, VADUserStartedSpeakingFrame())
    await feed(p, stopped())
    await feed(p, TranscriptionFrame("Quiero registrar un pedido porque,", "u", "t"))
    p.settle_base = 5
    await feed(p, UserStoppedSpeakingFrame())
    await feed(p, VADUserStartedSpeakingFrame())
    await asyncio.sleep(0.1)
    assert p.supervisor.submitted == [] and p.settle is None


def test_turn_boundary_counts_segments():
    t = TurnBoundary()
    t.speech_started()
    t.speech_stopped()
    t.speech_started()
    t.speech_stopped()
    t.finish()
    t.transcript("a", "uno")
    assert not t.ready()
    t.transcript("b", "dos")
    assert t.consume() == "uno dos" and t.consume() is None


async def test_continuous_audio_does_not_reset_the_finished_phrase(processor):
    p = processor
    await feed(p, VADUserStartedSpeakingFrame())
    await feed(p, stopped())
    await feed(p, TranscriptionFrame("Gianna, ¿me escuchás?", "u", "t"))
    await feed(p, UserStoppedSpeakingFrame())
    for _ in range(30):
        await feed(p, InputAudioRawFrame(bytes(640), 16000, 1))
        await asyncio.sleep(0.005)
    assert p.supervisor.submitted == ["Gianna, ¿me escuchás?"]
    assert "stt_timeout" not in p.supervisor.events


async def test_incomplete_detector_verdict_has_a_silence_deadline(processor):
    p = processor
    await feed(p, VADUserStartedSpeakingFrame())
    await feed(p, stopped())
    await feed(p, TranscriptionFrame("Gianna, ¿estás ahí?", "u", "t"))
    # SmartTurn never sends a full turn verdict for this phrase.
    for _ in range(30):
        await feed(p, InputAudioRawFrame(bytes(640), 16000, 1))
        await asyncio.sleep(0.005)
    assert p.supervisor.submitted == ["Gianna, ¿estás ahí?"]


async def test_transcript_before_stop_does_not_leave_a_phantom_pending_segment(processor):
    p = processor
    await feed(p, VADUserStartedSpeakingFrame())
    await feed(p, TranscriptionFrame("Hola Gianna.", "u", "t"))
    await feed(p, stopped())
    await feed(p, UserStoppedSpeakingFrame())
    await wait_for(lambda: p.supervisor.submitted)
    assert p.turn.pending == 0 and "stt_timeout" not in p.supervisor.events


async def test_upstream_echo_does_not_add_another_speech_segment(processor):
    p = processor
    await feed(p, VADUserStartedSpeakingFrame())
    await feed(p, stopped())
    await p.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.UPSTREAM)
    await p.process_frame(stopped(), FrameDirection.UPSTREAM)
    await feed(p, TranscriptionFrame("Hola Gianna.", "u", "t"))
    await feed(p, UserStoppedSpeakingFrame())
    await wait_for(lambda: p.supervisor.submitted)
    assert p.supervisor.submitted == ["Hola Gianna."] and p.turn.pending == 0


def test_stale_end_of_turn_is_ignored_while_speaking():
    t = TurnBoundary()
    t.speech_started()
    t.finish()
    assert not t.complete


@pytest.mark.parametrize(
    "text,patient",
    [
        ("Necesito registrar un pedido para", True),
        ("La impresora de Tránsito no imprime porque,", True),
        ("La impresora no imprime…", True),
        ("Sí.", False),
        ("Confirmo.", False),
        ("En Tránsito la impresora no imprime desde ayer.", False),
        ("¿Estás ahí?", False),
    ],
)
def test_unfinished_clauses_wait_longer(text, patient):
    assert (guard_delay(text) > 1) is patient


@pytest.mark.parametrize(
    "segment,kept",
    [
        ({"text": "Necesito un ticket", "no_speech_prob": 0.05, "avg_logprob": -0.4}, True),
        ({"text": "Tránsito", "no_speech_prob": 0.3, "avg_logprob": -1.3}, True),
        (
            {
                "text": "Subtítulos por la comunidad de Amara.org",
                "no_speech_prob": 0.2,
                "avg_logprob": -0.9,
            },
            False,
        ),
        ({"text": "ruido", "no_speech_prob": 0.9, "avg_logprob": -0.5}, False),
        ({"text": "mmm", "no_speech_prob": 0.7, "avg_logprob": -1.4}, False),
        ({"text": "Gracias.", "no_speech_prob": 0.05, "avg_logprob": -0.2}, True),
    ],
)
def test_stt_filter_keeps_real_speech_and_drops_hallucinations(segment, kept):
    assert keep_segment(segment) is kept
