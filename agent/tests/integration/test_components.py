"""Actual owned Piper stop/restart and unavailable network endpoints. No borrowed PID is killed."""

import asyncio
import io
import json
import os
import subprocess
import sys
import wave
import httpx
import pytest
from gianna.config import ROOT, Settings
from gianna.models.ollama_tev1 import TevDecision
from gianna.adapters.tickets_http import TicketsHTTP

pytestmark = [
    pytest.mark.integration,
    pytest.mark.models,
    pytest.mark.skipif(
        Settings().interpreter_backend != "local", reason="Historical local Tev recovery"
    ),
    pytest.mark.skipif(
        os.getenv("GIANNA_REAL_E2E") != "1", reason="Explicit owned local service test"
    ),
]


async def test_owned_piper_restart_and_differentiated_network_failures(tmp_path):
    base = Settings()
    env = os.environ.copy()
    env.update(
        GIANNA_PIPER_PORT="5003",
        GIANNA_DATA_DIR=str(tmp_path),
        GIANNA_MODEL_DIR=str(base.models_dir),
    )
    env.pop("GIANNA_CLOUD_API_KEY", None)
    env.pop("OLLAMA_API_KEY", None)
    process = None
    log = (tmp_path / "piper-test.log").open("wb")
    async with httpx.AsyncClient() as client:

        async def start():
            nonlocal process
            # Refuse to attach/replace someone else's service.
            import socket

            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 5003))
            process = subprocess.Popen(
                [sys.executable, "-m", "gianna", "piper"],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            for _ in range(100):
                assert process.poll() is None
                try:
                    response = await client.get("http://127.0.0.1:5003/health", timeout=1)
                    if response.is_success:
                        assert response.json()["voice"] == "es_AR-daniela-high"
                        return process.pid
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.1)
            raise AssertionError("Owned Piper failed to warm")

        try:
            first = await start()
            response = await client.post(
                "http://127.0.0.1:5003/",
                json={"text": "Cuando necesites algo, llamame.", "sample_rate": 24000},
                timeout=30,
            )
            response.raise_for_status()
            with wave.open(io.BytesIO(response.content), "rb") as wav:
                assert wav.getframerate() == 24000 and wav.getnframes() > 24000
            process.terminate()
            await asyncio.to_thread(process.wait, 10)
            with pytest.raises(httpx.TransportError):
                await client.post(
                    "http://127.0.0.1:5003/", json={"text": "No debe anunciar éxito"}, timeout=2
                )
            second = await start()
            response = await client.post(
                "http://127.0.0.1:5003/", json={"text": "Gianna está lista."}, timeout=30
            )
            response.raise_for_status()
            assert first != second and response.content.startswith(b"RIFF")
            unavailable = base.model_copy(
                update={"ollama_url": "http://127.0.0.1:1", "tickets_api": "http://127.0.0.1:1"}
            )
            assert (
                await TevDecision(unavailable, client).choose(
                    "Gianna registrá", {"invoke": "Pedido dirigido", "ignore": "Otro contenido"}
                )
                == "clarify"
            )
            with pytest.raises(httpx.ConnectError):
                await TicketsHTTP(unavailable, client).health()
            # Return to the same installed engines/API; no alternate provider.
            tev = await TevDecision(base, client).preflight()
            ready = await TicketsHTTP(
                base.model_copy(update={"tickets_api": "http://localhost:5400"}), client
            ).health()
            assert tev["digest"] and ready
            (ROOT.parent / "artifacts/gianna-components.json").write_text(
                json.dumps(
                    {
                        "owned_piper_restart": True,
                        "voice": "es_AR-daniela-high",
                        "piper_offline_connect_error": True,
                        "tev_offline_clarify": True,
                        "api_offline_connect_error": True,
                        "same_tev_digest_after_reconnect": tev["digest"],
                        "fallback_used": False,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        finally:
            if process and process.poll() is None:
                process.terminate()
                await asyncio.to_thread(process.wait, 10)
            log.close()
