"""Pinned downloads; manifest records actual hashes, never machine-specific paths."""

import hashlib
import importlib.metadata
import json
from pathlib import Path
from huggingface_hub import HfApi, hf_hub_download, snapshot_download

WHISPER_REPO = "dropbox-dash/faster-whisper-large-v3-turbo"
WHISPER_REV = "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf"
VOICE_REPO = "rhasspy/piper-voices"
VOICE_REV = "c10ece1aade47bb51c153c893d14e5bf8e5b7117"
VOICE_PATH = "es/es_AR/daniela/high/es_AR-daniela-high"


def provenance(manifest):
    for name, entry in manifest["files"].items():
        if name.startswith("whisper-"):
            entry.update(
                source=f"https://huggingface.co/{WHISPER_REPO}/tree/{WHISPER_REV}",
                revision=WHISPER_REV,
                license="MIT (Whisper model/code; CT2 conversion)",
                license_source="https://github.com/openai/whisper/blob/main/LICENSE",
            )
        elif name.startswith("piper/"):
            entry.update(
                source=f"https://huggingface.co/{VOICE_REPO}/tree/{manifest['piper_revision']}/es/es_AR/daniela/high",
                revision=manifest["piper_revision"],
                license="Voice card: dataset CC-BY-SA-4.0; repository tag MIT is not a separate voice-weights grant",
                license_source=f"https://huggingface.co/{VOICE_REPO}/blob/{manifest['piper_revision']}/es/es_AR/daniela/high/MODEL_CARD",
            )
        else:
            entry.update(
                source="pipecat-ai==1.10.0 wheel",
                revision="1.10.0",
                license="BSD-2-Clause",
                license_source="https://huggingface.co/pipecat-ai/smart-turn-v3",
            )
    manifest["licenses"] = {
        "piper_runtime": "GPL-3.0-or-later (installed distribution metadata)",
        "pipecat_runtime": "BSD-2-Clause",
        "faster_whisper": "MIT",
        "ctranslate2": "MIT",
        "tev_code": "MIT",
        "tev_base": "Qwen3.5-0.8B Apache-2.0",
        "tev_weights": "Experimental release license being finalized in model card; do not infer from code/base",
        "hermes_patterns": "MIT; independent harness, no imported AIAgent internals",
    }
    return manifest


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(config):
    import nltk

    nltk.download(
        "punkt_tab", download_dir=str(config.data_dir / "nltk"), quiet=True, raise_on_error=True
    )
    root = config.models_dir
    root.mkdir(parents=True, exist_ok=True)
    api = HfApi()
    info = api.model_info(WHISPER_REPO, revision=WHISPER_REV)
    if info.sha != WHISPER_REV:
        raise RuntimeError("Whisper revision mismatch")
    snapshot_download(
        WHISPER_REPO,
        revision=WHISPER_REV,
        local_dir=root / "whisper-large-v3-turbo",
        allow_patterns=["*.json", "model.bin", "vocabulary.*", "README.md", "LICENSE*"],
    )
    # Resolve ONCE; following installs use manifest's immutable revision.
    old = (
        json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if (root / "manifest.json").exists()
        else {}
    )
    voice_rev = old.get("piper_revision") or VOICE_REV
    if voice_rev != VOICE_REV:
        raise RuntimeError("Configured voice revision differs from tested artifact")
    for ext in (".onnx", ".onnx.json"):
        source = Path(hf_hub_download(VOICE_REPO, VOICE_PATH + ext, revision=voice_rev))
        target = root / "piper" / source.name
        target.parent.mkdir(exist_ok=True)
        import shutil

        shutil.copyfile(source, target)
    card = Path(hf_hub_download(VOICE_REPO, "es/es_AR/daniela/high/MODEL_CARD", revision=voice_rev))
    (root / "piper/MODEL_CARD").write_bytes(card.read_bytes())
    from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3

    LocalSmartTurnAnalyzerV3()
    # The installed Pipecat distribution includes the pinned CPU artifact.
    import pipecat

    candidates = list(Path(pipecat.__file__).parent.rglob("smart-turn-v3.2-cpu.onnx"))
    if len(candidates) != 1:
        raise RuntimeError("Smart Turn v3.2 CPU artifact unavailable")
    import shutil

    shutil.copyfile(candidates[0], root / "smart-turn-v3.2-cpu.onnx")
    manifest = {
        "format_version": 1,
        "whisper_repo": info.id,
        "whisper_revision": info.sha,
        "piper_repo": VOICE_REPO,
        "piper_revision": voice_rev,
        "piper_runtime": importlib.metadata.version("piper-tts"),
        "pipecat_runtime": "1.10.0",
        "smart_turn_source": "pipecat-ai 1.10.0 distribution",
        "files": {},
    }
    for path in root.rglob("*"):
        if path.is_file() and path.name != "manifest.json" and ".cache" not in path.parts:
            manifest["files"][path.relative_to(root).as_posix()] = {
                "sha256": sha256(path),
                "size": path.stat().st_size,
            }
    provenance(manifest)
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    verify(config)
    return manifest


def verify(config):
    root = config.models_dir
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    from gianna.config import ROOT

    pinned = json.loads((ROOT / "contracts/model-manifest.lock.json").read_text(encoding="utf-8"))
    if (
        not set(pinned["files"]) <= set(manifest["files"])
        or manifest["piper_revision"] != VOICE_REV
    ):
        raise RuntimeError("Required pinned model files/revision missing")
    for name, entry in pinned["files"].items():
        if any(manifest["files"][name][field] != entry[field] for field in ("sha256", "size")):
            raise RuntimeError(f"Model differs from tested source: {name}")
    if manifest["whisper_revision"] != WHISPER_REV or manifest[
        "piper_runtime"
    ] != importlib.metadata.version("piper-tts"):
        raise RuntimeError("Model/runtime identity mismatch")
    for name, entry in manifest["files"].items():
        path = (root / name).resolve()
        if (
            not path.is_relative_to(root.resolve())
            or path.stat().st_size != entry["size"]
            or sha256(path) != entry["sha256"]
        ):
            raise RuntimeError(f"Corrupt model: {name}")
    voice = json.loads((root / "piper/es_AR-daniela-high.onnx.json").read_text(encoding="utf-8"))
    if voice["audio"]["sample_rate"] != 22050 or voice["dataset"] != "daniela":
        raise RuntimeError("Piper voice identity mismatch")
    return manifest
