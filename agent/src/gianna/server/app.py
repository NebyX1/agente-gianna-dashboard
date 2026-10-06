import asyncio
import json
from contextlib import asynccontextmanager
from typing import Literal
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from pipecat.transports.smallwebrtc.request_handler import (
    SmallWebRTCRequestHandler,
    SmallWebRTCRequest,
    ConnectionMode,
    SmallWebRTCPatchRequest,
    IceCandidate,
)
from gianna.bootstrap import Runtime
from gianna.config import ROOT
from gianna.server.local_auth import LocalAuthMiddleware
from gianna.dialogue.state_machine import State


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[
        "activate",
        "text",
        "pause",
        "stop_voice",
        "repeat",
        "open_board",
        "handoff",
        "reconcile",
        "logout",
        "return_to_task",
        "reset_conversation",
    ]
    text: str = Field(default="", max_length=4000)


class Playback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    utterance_id: str
    generation_id: str


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    speed: float = Field(ge=0.65, le=1.4)
    quiet: bool
    volume: float = Field(default=0.85, ge=0, le=1)
    text_size: int = Field(default=18, ge=16, le=28)
    high_contrast: bool = False
    echo_cancellation: bool = True
    noise_suppression: bool = False
    auto_gain_control: bool = False


def create_app(config, *, managed_browser=True):
    runtime = Runtime(config)

    @asynccontextmanager
    async def lifespan(app):
        try:
            await runtime.start(browser=managed_browser)
            yield
        finally:
            await rtc.close()
            await runtime.close()

    app = FastAPI(lifespan=lifespan)
    app.state.runtime = runtime
    app.add_middleware(LocalAuthMiddleware, config=config, secret=runtime.secret)
    rtc = SmallWebRTCRequestHandler(connection_mode=ConnectionMode.SINGLE, host="127.0.0.1")
    audio_connection_lock = asyncio.Lock()

    @app.get("/api/state")
    async def state():
        return {**runtime.supervisor.snapshot(), "diagnostics": runtime.diagnostics}

    @app.get("/api/metrics")
    async def metrics():
        return runtime.metrics.snapshot()

    @app.post("/api/shutdown")
    async def shutdown():
        if not getattr(runtime, "shutdown_callback", None):
            raise HTTPException(503, "Usá Ctrl+C en el launcher")

        async def stop():
            await asyncio.sleep(0.2)
            runtime.shutdown_callback()

        asyncio.create_task(stop())
        return {"closing": True}

    @app.get("/api/events")
    async def events():
        bus = runtime.supervisor.bus
        queue = bus.subscribe()

        async def stream():
            try:
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "schema_version": "1",
                            "event_id": str(__import__("uuid").uuid4()),
                            "kind": "state",
                            "session_id": runtime.supervisor.session_id,
                            "turn_id": runtime.supervisor.turn_id,
                            "generation_id": runtime.supervisor.generation_id,
                            "at": __import__("datetime")
                            .datetime.now(__import__("datetime").UTC)
                            .isoformat(),
                            "data": runtime.supervisor.snapshot(),
                        }
                    )
                    + "\n\n"
                )
                while True:
                    try:
                        value = await asyncio.wait_for(queue.get(), 15)
                        yield "data: " + json.dumps(value, ensure_ascii=False) + "\n\n"
                        if value["kind"] == "saturation":
                            return
                    except TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                bus.subscribers.discard(queue)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/api/command")
    async def command(cmd: Command):
        s = runtime.supervisor
        if cmd.action == "reset_conversation":
            async with audio_connection_lock:
                try:

                    async def close_audio():
                        await rtc.close()
                        if runtime.audio:
                            await runtime.audio.close()

                    await s.reset_conversation(close_audio)
                except ValueError as exc:
                    raise HTTPException(409, str(exc)) from exc
            return s.snapshot()
        if s.resetting:
            raise HTTPException(409, "La conversación se está limpiando. Esperá un momento.")
        if s.state == State.BLOCKED and cmd.action not in {"logout", "stop_voice"}:
            raise HTTPException(503, "Corrigí el diagnóstico y reiniciá el mismo componente")
        actions = {
            "activate": s.activate,
            "pause": s.pause,
            "repeat": s.repeat,
            "handoff": s.handoff,
            "reconcile": s.reconcile,
        }
        session = s.session_id
        try:
            if cmd.action in actions:
                await actions[cmd.action]()
            elif cmd.action == "text":
                await s.submit(cmd.text, source="text")
            elif cmd.action == "stop_voice":
                if s.stop_callback:
                    await s.stop_callback()
            elif cmd.action == "open_board":
                await runtime.browser.show()
            elif cmd.action == "logout":
                await runtime.broker.close()
            elif cmd.action == "return_to_task":
                if runtime.browser.human_control:
                    # Explicit button relinquishes human surface only; transferred draft stays transferred.
                    runtime.browser.human_control = False
                    s.draft = None
                await s.activate()
        except Exception as exc:
            if session == s.session_id:
                await s.report_failure(exc)
        return s.snapshot()

    @app.post("/api/playback-complete")
    async def playback(packet: Playback):
        await runtime.supervisor.playback_complete(packet.utterance_id, packet.generation_id)
        return {"accepted": True}

    @app.post("/api/preferences")
    async def preferences(body: Preferences):
        if not runtime.supervisor.user:
            raise HTTPException(401, "Iniciá sesión para guardar tus preferencias")
        data = {"schema_version": "1", **body.model_dump()}
        runtime.db.save_preferences(runtime.supervisor.user["id"], data)
        runtime.supervisor.voice_speed = body.speed
        runtime.supervisor.quiet = body.quiet
        runtime.supervisor.publish("preferences", data)
        return data

    @app.post("/api/audio-settings")
    async def audio_settings(body: dict):
        allowed = {
            "echoCancellation",
            "noiseSuppression",
            "autoGainControl",
            "sampleRate",
            "channelCount",
            "latency",
        }
        clean = {
            k: {name: value for name, value in body.get(k, {}).items() if name in allowed}
            for k in ("requested", "effective")
        }
        runtime.supervisor.publish("audio_settings", clean)
        return {"recorded": True}

    @app.post("/api/offer")
    async def offer(body: dict):
        if runtime.supervisor.state == State.BLOCKED:
            raise HTTPException(503, "Audio bloqueado")
        allowed = {"sdp", "type", "pc_id", "restart_pc", "request_data", "requestData"}
        if set(body) - allowed or len(body.get("sdp", "")) > 65536:
            raise HTTPException(422, "Oferta inválida")
        request = SmallWebRTCRequest.from_dict(body)
        async with audio_connection_lock:
            if not request.pc_id:
                # Explicitly connecting a microphone in another local console
                # transfers the single audio channel instead of returning 400.
                await rtc.close()
                await runtime.audio.close()
            return await rtc.handle_web_request(request, runtime.audio.connect)

    @app.patch("/api/offer")
    async def candidates(body: dict):
        if set(body) != {"pc_id", "candidates"} or len(body["candidates"]) > 32:
            raise HTTPException(422, "Candidatos inválidos")
        return await rtc.handle_patch_request(
            SmallWebRTCPatchRequest(
                pc_id=body["pc_id"], candidates=[IceCandidate(**c) for c in body["candidates"]]
            )
        )

    @app.get("/healthz")
    async def health():
        return {"alive": True}

    ui = ROOT / "ui/dist"
    if (ui / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=ui / "assets"), name="assets")

    @app.get("/")
    async def index():
        if not (ui / "index.html").exists():
            return JSONResponse(
                {"code": "console_build_missing", "action": "npm --prefix ui run build"}, 503
            )
        return FileResponse(ui / "index.html")

    return app
