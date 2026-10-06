"""Bounded local metrics and private storage; never records headers or audio implicitly."""

import asyncio
from contextvars import ContextVar
from collections import defaultdict, deque
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import subprocess
import sys
import time


def private_directory(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        subprocess.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"{os.environ['USERNAME']}:(OI)(CI)F",
            ],
            capture_output=True,
            check=True,
        )
    else:
        path.chmod(0o700)


def configure_logs(config):
    private_directory(config.data_dir / "logs")
    handler = RotatingFileHandler(
        config.data_dir / "logs/runtime.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    logger = logging.getLogger("gianna")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    from loguru import logger as native

    native.remove()
    native.add(
        sys.stderr,
        level="DEBUG" if config.diagnostics else "WARNING",
        filter=lambda record: (
            not any(
                phrase in record["message"]
                for phrase in ("Generating TTS", "Finished TTS", "not speaking [", "Transcription:")
            )
        ),
    )
    return handler


# Context is carried only by the accepted voice turn, then attached to its TTS frame.
# It is diagnostic timing, never authority, transcript or a persisted credential.
voice_response_clock = ContextVar("voice_response_clock", default=None)


class Metrics:
    def __init__(self):
        self.samples = defaultdict(lambda: deque(maxlen=512))
        self.load = deque(maxlen=128)
        self.started = time.perf_counter()

    def add(self, name, ms):
        self.samples[name].append(float(ms))

    async def watch_loop(self):
        while True:
            due = time.perf_counter() + 0.1
            await asyncio.sleep(0.1)
            self.add("event_loop_lag", max(0, (time.perf_counter() - due) * 1000))

    async def watch_load(self):
        def sample():
            import psutil

            value = {
                "uptime_seconds": time.perf_counter() - self.started,
                "system_cpu_percent": psutil.cpu_percent(),
                "system_ram_bytes": psutil.virtual_memory().used,
                "runtime_rss_bytes": psutil.Process().memory_info().rss,
            }
            try:
                process = subprocess.run(
                    [
                        "nvidia-smi",
                        "--query-gpu=memory.used,utilization.gpu",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                if process.returncode == 0:
                    value["gpus"] = [
                        dict(zip(("memory_MiB", "utilization_percent"), map(int, line.split(","))))
                        for line in process.stdout.strip().splitlines()
                    ]
            except (OSError, ValueError, subprocess.TimeoutExpired):
                value["gpu_sample"] = "unavailable"
            return value

        while True:
            self.load.append(await asyncio.to_thread(sample))
            await asyncio.sleep(5)

    def snapshot(self):
        import numpy as np

        return {
            name: {
                "count": len(values),
                "p50_ms": float(np.percentile(values, 50)),
                "p95_ms": float(np.percentile(values, 95)),
            }
            for name, values in self.samples.items()
            if values
        }


class InstanceLock:
    def __init__(self, path):
        self.file = open(path, "a+b")
        self.file.seek(0)
        self.file.write(b"0")
        self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("Gianna ya está usando este directorio de datos")

    def close(self):
        self.file.close()
