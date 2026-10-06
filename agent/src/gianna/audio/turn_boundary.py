import re
from dataclasses import dataclass, field
from uuid import uuid4

from gianna.dialogue.activation import normalize

# A clause that ends on one of these is almost certainly unfinished: the person is thinking.
# Whisper adds a final period even to unfinished clauses, so the dot proves nothing.
_OPEN_ENDING = re.compile(
    r"(?:\b(?:y|o|pero|porque|que|como|cuando|donde|aunque|entonces|ademas|tambien|"
    r"de|del|en|con|sin|para|por|al|la|el|los|las|un|una|unos|unas|mi|mis|su|sus)|[,;:])$"
)


def guard_delay(text: str, base: float = 0.4, patient: float = 1.6) -> float:
    """Extra silence to wait after the last transcript before treating the turn as finished."""
    plain = " ".join(normalize(text).split())
    if plain.endswith(("?", "!")) or len(plain.split()) <= 2:
        return base
    if plain.endswith(("...", "…")) or _OPEN_ENDING.search(plain.rstrip(". ")):
        return patient
    return base if plain.endswith(".") else base + 0.3


@dataclass
class TurnBoundary:
    """One spoken turn: it is dispatched only when nothing else can still arrive.

    A turn can hold several VAD segments (the person pauses mid-sentence). Each
    segment is transcribed separately, so the turn stays open until the detector
    reports its end AND every queued segment produced a transcript or a rejection.
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    complete: bool = False
    dispatched: bool = False
    speaking: bool = False
    pending: int = 0
    segments: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)
    rejection: dict | None = None

    def speech_started(self):
        if not self.speaking:
            # Reserve before STT starts: its result can precede the stop frame.
            self.pending += 1
        self.speaking = True
        self.complete = False

    def speech_stopped(self):
        self.speaking = False

    def transcript(self, segment_id, text, evidence=None):
        if self.dispatched or not text.strip() or segment_id in self.segments:
            return
        self.segments[segment_id] = text.strip()
        if evidence is not None:
            self.evidence[segment_id] = evidence
        self.pending = max(0, self.pending - 1)

    def reject(self, evidence=None):
        self.pending = max(0, self.pending - 1)
        self.rejection = evidence or {}

    def finish(self):
        # A late end-of-turn verdict about earlier speech is stale if they are talking again.
        if not self.speaking:
            self.complete = True

    @property
    def text(self):
        return " ".join(self.segments.values())

    def settled(self):
        return not self.dispatched and not self.speaking and self.pending == 0

    def ready(self):
        return self.complete and bool(self.segments) and self.settled()

    def consume(self):
        if not self.ready():
            return None
        self.dispatched = True
        return self.text
