import asyncio
import secrets
import socket
import subprocess
import sys
import httpx
from gianna.config import ROOT
from gianna.persistence.database import Database
from gianna.runtime.event_bus import EventBus
from gianna.runtime.operation_manager import OperationManager
from gianna.runtime.supervisor import Supervisor
from gianna.tools.registry import ToolRegistry
from gianna.tools.tickets import install_tools
from gianna.profiles.loader import load_profile
from gianna.models.ollama_tev1 import TevDecision
from gianna.models.local_interpreter import LocalInterpreter
from gianna.models.cloud_interpreter import CloudInterpreter
from gianna.models.ollama_cloud import CloudReasoner
from gianna.adapters.tickets_http import TicketsHTTP
from gianna.adapters.playwright_browser import PlaywrightBrowser
from gianna.adapters.browser_session import BrowserSessionBroker
from gianna.audio.stt_whisper_turbo import WhisperResident
from gianna.audio.pipeline import AudioPipeline
from gianna.audio.model_manifest import verify
from gianna.audio.denoise import RequiredRNNoiseFilter
from gianna.dialogue.state_machine import State
import time
import json
import logging
from gianna.runtime.observability import Metrics, private_directory, configure_logs, InstanceLock


class Runtime:
    def __init__(self, config):
        self.config = config
        self.secret = secrets.token_urlsafe(48)
        self.client = None
        self.piper_process = None
        self.browser = self.audio = self.broker = self.stt = self.db = None
        self.diagnostics = {}
        self.supervisor = None

    async def start(self, *, browser=True):
        c = self.config
        private_directory(c.data_dir)
        self.instance_lock = InstanceLock(c.data_dir / "runtime.lock")
        self.log_handler = configure_logs(c)
        metrics = self.metrics = Metrics()
        self.loop_watch = asyncio.create_task(metrics.watch_loop())
        self.load_watch = asyncio.create_task(metrics.watch_load())
        self.db = Database(c.data_dir / "gianna.db")
        self.db.prune()
        self.client = httpx.AsyncClient(follow_redirects=False)
        bus = EventBus(c.max_events)
        tickets = TicketsHTTP(c, self.client)
        tickets.metrics = metrics
        interpreter = (CloudInterpreter if c.interpreter_backend == "cloud" else LocalInterpreter)(
            c, self.client
        )
        tev = interpreter if c.interpreter_backend == "cloud" else TevDecision(c, self.client)
        cloud = CloudReasoner(c, self.client)
        profile = load_profile(c.profile)
        operations = OperationManager(self.db, tickets, c, time.monotonic)
        self.supervisor = Supervisor(c, self.db, bus, tickets, tev, operations, profile, cloud)
        self.supervisor.interpreter = interpreter
        self.supervisor.metrics = metrics
        self.browser = PlaywrightBrowser(c, profile, self.secret)
        self.supervisor.browser = self.browser
        self.broker = BrowserSessionBroker(
            c, tickets, self.supervisor.authenticated, self.supervisor.auth_invalidated, self.db
        )
        self.diagnostics["credential_store"] = (
            "OS keyring"
            if self.broker.credentials.secure
            else "MEMORY ONLY: remote revocation cannot survive process loss"
        )
        registry = ToolRegistry()
        install_tools(registry, tickets, self.browser, self.supervisor)
        load_profile(c.profile, registry=registry)
        operations.registry = registry
        self.registry = registry
        from gianna.tools.dispatcher import Dispatcher

        self.supervisor.dispatcher = Dispatcher(registry, c.max_tool_calls)
        if c.interpreter_backend == "cloud":
            from gianna.runtime.conversation_agent import ConversationAgent

            self.supervisor.conversation_agent = ConversationAgent(self.supervisor, self.client)
            from gianna.models.review_interpreter import ReviewInterpreter

            self.supervisor.review_interpreter = ReviewInterpreter(
                self.supervisor.conversation_agent.chat
            )
        self.stt = WhisperResident(c)
        self.stt.metrics = metrics
        self.audio = AudioPipeline(c, self.supervisor, self.stt)
        try:
            from gianna.audio.text_runtime import prepare

            prepare(c)
            await asyncio.to_thread(verify, c)
            self.diagnostics["models"] = "verified"
            self.diagnostics["required_warmup_started_seconds"] = (
                time.perf_counter() - metrics.started
            )
            await self.start_piper()
            await self.stt.warmup()
            self.diagnostics["stt"] = {
                "device": c.stt_device,
                "compute_type": c.stt_compute_type,
                "resident": True,
            }
            denoise = RequiredRNNoiseFilter()
            await denoise.start(16000)
            await denoise.stop()
            self.diagnostics["rnnoise"] = "warmed"
            from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3

            turn = LocalSmartTurnAnalyzerV3(
                smart_turn_model_path=str(c.models_dir / "smart-turn-v3.2-cpu.onnx")
            )
            turn.set_sample_rate(16000)
            turn.append_audio(bytes(32000), True)
            await turn.analyze_end_of_turn()
            self.diagnostics["smart_turn"] = "v3.2-cpu warmed"
            try:
                self.diagnostics["interpreter"] = await interpreter.preflight()
                if hasattr(self.supervisor, "conversation_agent"):
                    self.diagnostics[
                        "conversation_agent"
                    ] = await self.supervisor.conversation_agent.preflight()
            except Exception as exc:
                if c.interpreter_backend == "cloud":
                    raise RuntimeError(
                        "No se pudo conectar DeepSeek Cloud; no se usará un modelo local"
                    ) from exc
                # Gianna still understands commands and catalogue answers without it.
                self.diagnostics["interpreter"] = {"status": "degraded", "error": str(exc)[:200]}
                logging.getLogger("gianna").warning("Interpreter degraded: %s", exc)
            # Catalogue matching remains optional: missing Tev asks for a category.
            try:
                self.diagnostics["catalogue_decision"] = (
                    self.diagnostics["interpreter"]
                    if c.interpreter_backend == "cloud"
                    else await tev.preflight()
                )
            except Exception as exc:
                self.diagnostics["catalogue_decision"] = {
                    "status": "disabled",
                    "error": type(exc).__name__,
                }
            self.diagnostics["tickets"] = await tickets.health()
            contract = await self.client.get(c.tickets_api + "/api/v1/openapi.json", timeout=5)
            contract.raise_for_status()
            if not {"/auth/agent-session", "/agent/operations/{operation_id}"} <= set(
                contract.json()["paths"]
            ):
                raise RuntimeError("Tickets agent contract missing")
            self.diagnostics["contracts"] = "delegation and receipts available"
            self.diagnostics["required_ready_seconds"] = time.perf_counter() - metrics.started
            try:
                self.diagnostics["cloud"] = await cloud.preflight()
            except Exception as exc:
                self.diagnostics["cloud"] = {"status": "disabled", "error": type(exc).__name__}
            self.supervisor.set_state(State.AUTH_REQUIRED)
        except Exception as exc:
            self.diagnostics["blocked"] = {
                "component_error": type(exc).__name__,
                "message": str(exc)[:300],
            }
            self.supervisor.errors.append(self.diagnostics["blocked"])
            self.supervisor.set_state(State.BLOCKED)
            logging.getLogger("gianna").error(
                "Preflight blocked: %s: %s", type(exc).__name__, str(exc)[:300]
            )
        (c.data_dir / "runtime-health.json").write_text(
            json.dumps(
                {
                    "pid": __import__("os").getpid(),
                    "piper_pid": self.piper_process.pid if self.piper_process else None,
                    "state": self.supervisor.state,
                    "diagnostics": self.diagnostics,
                    "metrics": metrics.snapshot(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        if browser:
            # Listener is already bound by Uvicorn; UI navigation scheduled after lifespan startup.
            self.browser_task = asyncio.create_task(self.open_browser())

    async def open_browser(self):
        await asyncio.sleep(0.5)
        try:
            await self.browser.start(self.broker)
            self.diagnostics["browser"] = await self.browser.health()
            self.supervisor.publish("diagnostics", self.diagnostics)
        except Exception as exc:
            self.diagnostics["browser"] = {"error": type(exc).__name__, "message": str(exc)[:150]}
            self.supervisor.set_state(State.BLOCKED)

    async def start_piper(self):
        c = self.config
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", c.piper_port))
            except OSError as exc:
                raise RuntimeError("Piper port occupied; no attach to unknown process") from exc
        logs = c.data_dir / "logs"
        logs.mkdir(exist_ok=True)
        log = logs / "piper.log"
        if log.exists() and log.stat().st_size > 2_000_000:
            for i in range(2, 0, -1):
                previous = logs / f"piper.log.{i}"
                if previous.exists():
                    previous.replace(logs / f"piper.log.{i + 1}")
            log.replace(logs / "piper.log.1")
        self.piper_log = (logs / "piper.log").open("a", encoding="utf-8")
        process_env = __import__("os").environ.copy()
        process_env.update(
            GIANNA_PIPER_PORT=str(c.piper_port),
            GIANNA_DATA_DIR=str(c.data_dir),
            GIANNA_MODEL_DIR=str(c.models_dir),
        )
        process_env.pop("GIANNA_CLOUD_API_KEY", None)
        process_env.pop("OLLAMA_API_KEY", None)
        self.piper_process = subprocess.Popen(
            [sys.executable, "-m", "gianna", "piper"],
            cwd=ROOT,
            env=process_env,
            stdout=self.piper_log,
            stderr=self.piper_log,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        for _ in range(120):
            if self.piper_process.poll() is not None:
                raise RuntimeError("Piper failed; inspect its own log")
            try:
                r = await self.client.get(f"http://127.0.0.1:{c.piper_port}/health", timeout=1)
                r.raise_for_status()
                self.diagnostics["piper"] = r.json()
                return
            except httpx.HTTPError:
                await asyncio.sleep(0.5)
        raise RuntimeError("Piper warmup deadline exceeded")

    async def close(self):
        if self.audio:
            await self.audio.close()
        if hasattr(self, "browser_task"):
            await asyncio.gather(self.browser_task, return_exceptions=True)
        if self.supervisor:
            await self.supervisor.close()
        if self.broker:
            await self.broker.close()
        if self.browser:
            await self.browser.close()
        if self.stt:
            await self.stt.worker.close()
        if self.client:
            await self.client.aclose()
        if self.db:
            self.db.close()
        if self.piper_process and self.piper_process.poll() is None:
            self.piper_process.terminate()
            await asyncio.to_thread(self.piper_process.wait, 10)
        if hasattr(self, "piper_log"):
            self.piper_log.close()
        if hasattr(self, "loop_watch"):
            self.loop_watch.cancel()
            await asyncio.gather(self.loop_watch, return_exceptions=True)
        if hasattr(self, "load_watch"):
            self.load_watch.cancel()
            await asyncio.gather(self.load_watch, return_exceptions=True)
        if hasattr(self, "log_handler"):
            logging.getLogger("gianna").removeHandler(self.log_handler)
            self.log_handler.close()
        if hasattr(self, "instance_lock"):
            self.instance_lock.close()
