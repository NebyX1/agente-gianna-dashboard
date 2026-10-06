from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class Evidence:
    duration_ms: float
    active_ms: float
    peak: float
    rms: float
    reason: str | None


def measure(pcm: bytes, sample_rate=16000):
    a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
    peak = float(np.max(np.abs(a))) if a.size else 0
    rms = float(np.sqrt(np.mean(a * a))) if a.size else 0
    step = sample_rate // 50
    active = (
        sum(float(np.sqrt(np.mean(a[i : i + step] ** 2))) >= 0.006 for i in range(0, a.size, step))
        * 20
    )
    duration = a.size * 1000 / sample_rate
    reason = "silence" if peak < 0.004 or rms < 0.001 else None
    if peak > 0.2 and active <= 80 and duration > 180:
        reason = "impulse"
    return Evidence(duration, active, peak, rms, reason)
