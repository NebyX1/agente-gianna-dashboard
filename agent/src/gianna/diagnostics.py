from dataclasses import dataclass
import importlib.metadata
import platform


@dataclass
class Diagnostic:
    component: str
    status: str
    detail: str


def versions():
    packages = [
        "pipecat-ai",
        "faster-whisper",
        "ctranslate2",
        "piper-tts",
        "pyrnnoise",
        "audiolab",
        "av",
        "playwright",
    ]
    return {
        "os": platform.platform(),
        "python": platform.python_version(),
        "packages": {p: importlib.metadata.version(p) for p in packages},
    }
