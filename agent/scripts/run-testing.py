"""Explicit local demo launcher: create a testing admin and authenticate all owned tabs.

Uses normal login + Mailpit OTP + delegation. No authentication bypass is installed
in the server or SPAs. Credentials live only in the current user's private data dir.
"""

import asyncio
import json
import re
import secrets
import socket
import subprocess

import httpx
import uvicorn
from gianna.config import ROOT, settings
from gianna.dialogue.state_machine import State
from gianna.runtime.observability import private_directory
from gianna.server.app import create_app

API = "http://localhost:5300"
WEB = "http://localhost:5373"
TV = "http://localhost:5374"
MAIL = "http://localhost:8026"
CONTAINER = "idl-tickets-e2e-backend-1"
EMAIL = "testing.admin@example.test"
NAME = "Administrador de pruebas"

CREATE_ADMIN = """
import json, sys
from sqlalchemy import select
from app import create_app
from app.extensions import db
from app.models import User
from app.services.auth import hasher
app = create_app()
with app.app_context():
    assert app.config['APP_ENV'] in {'development', 'test'}, 'Only development/test'
    data = json.load(sys.stdin)
    assert data['email'] == 'testing.admin@example.test'
    assert data['name'] == 'Administrador de pruebas'
    assert len(data['password']) >= 24
    user = db.session.scalar(select(User).where(User.email == data['email']))
    created = user is None
    if created:
        user = User(email=data['email'], name=data['name'], role='admin',
                    password_hash=hasher.hash(data['password']))
        db.session.add(user)
        db.session.commit()
    else:
        assert user.role == 'admin' and user.is_active and user.name == data['name']
        assert hasher.verify(user.password_hash, data['password']), 'Credential mismatch'
    print(json.dumps({'id': user.id, 'role': user.role, 'created': created}))
"""


def ensure_admin(config):
    inspected = subprocess.run(
        ["docker", "inspect", CONTAINER], capture_output=True, text=True, check=True
    )
    info = json.loads(inspected.stdout)[0]
    assert info["Config"]["Labels"]["com.docker.compose.project"] == "idl-tickets-e2e"
    assert info["State"]["Running"]
    private_directory(config.data_dir / "testing")
    credential_file = config.data_dir / "testing/admin.json"
    if not credential_file.exists():
        credential_file.write_text(
            json.dumps({"email": EMAIL, "name": NAME, "password": secrets.token_urlsafe(32)}),
            encoding="utf-8",
        )
        if __import__("os").name != "nt":
            credential_file.chmod(0o600)
    credentials = json.loads(credential_file.read_text(encoding="utf-8"))
    assert credentials["email"] == EMAIL and credentials["name"] == NAME
    created = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "python", "-c", CREATE_ADMIN],
        input=json.dumps(credentials),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if created.returncode:
        raise RuntimeError("No se pudo preparar el admin de pruebas; no se restableció otra cuenta")
    user = json.loads(created.stdout.strip().splitlines()[-1])
    print("Cuenta administradora de pruebas preparada.", flush=True)
    return credentials, user


async def login(client, credentials):
    messages = (await client.get(MAIL + "/api/v1/messages")).json()["messages"]
    previous = {m["ID"] for m in messages}
    for _ in range(3):
        response = await client.post(
            API + "/api/v1/auth/login",
            json={"email": credentials["email"], "password": credentials["password"]},
        )
        if response.status_code != 429:
            break
        print("Esperando el plazo normal de reingreso de la cuenta de pruebas…", flush=True)
        await asyncio.sleep(min(60, max(1, int(response.headers.get("Retry-After", "60")))))
    response.raise_for_status()
    pending = response.json()["data"]["pending_token"]
    for _ in range(60):
        messages = (await client.get(MAIL + "/api/v1/messages")).json()["messages"]
        for message in messages:
            if message["ID"] in previous:
                continue
            body = (await client.get(MAIL + "/api/v1/message/" + message["ID"])).json()
            if not any(x["Address"] == EMAIL for x in body.get("To", [])):
                continue
            code = re.search(r"\b\d{6}\b", body.get("Text", ""))
            if code:
                response = await client.post(
                    API + "/api/v1/auth/verify-2fa",
                    json={"pending_token": pending, "code": code[0]},
                )
                response.raise_for_status()
                session = response.json()["data"]
                assert session["user"]["role"] == "admin" and session["user"]["email"] == EMAIL
                return session
        await asyncio.sleep(0.5)
    raise RuntimeError("No llegó el código de la cuenta de pruebas a Mailpit")


async def wait_until(predicate, timeout=60):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.1)


async def run():
    config = settings()
    if config.tickets_api != API or config.tickets_web != WEB or config.host != "127.0.0.1":
        raise RuntimeError("Este launcher sólo sirve para la demo local 5300/5373/5374")
    with socket.socket() as probe:
        probe.bind((config.host, config.port))
    credentials, user = await asyncio.to_thread(ensure_admin, config)
    app = create_app(config, managed_browser=False)
    runtime = app.state.runtime
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=config.host,
            port=config.port,
            access_log=False,
            log_level="warning",
            timeout_graceful_shutdown=5,
        )
    )
    runtime.shutdown_callback = lambda: setattr(server, "should_exit", True)
    serving = asyncio.create_task(server.serve())
    try:
        await wait_until(lambda: server.started or serving.done(), timeout=150)
        if serving.done() or runtime.supervisor.state == State.BLOCKED:
            raise RuntimeError("Gianna no completó el inicio; revisá su diagnóstico")
        async with httpx.AsyncClient(timeout=15) as client:
            session = await login(client, credentials)
        await runtime.browser.start(runtime.broker)
        context = runtime.browser.context
        auth_state = {
            "state": {
                "token": session["access_token"],
                "user": session["user"],
                "expiresAt": session["expires_at"],
            },
            "version": 0,
        }
        bundle = json.dumps({WEB: "idl-frontend-session", TV: "idl-visualizer-session"})
        # Writes only the documented stores of the owned demo tabs, once per tab.
        await context.add_init_script(
            "(() => {const stores=" + bundle + ";const key=stores[location.origin];"
            "if(key&&!sessionStorage.getItem('gianna-testing-bootstrapped')){"
            "localStorage.setItem(key,JSON.stringify(" + json.dumps(auth_state) + "));"
            "sessionStorage.setItem('gianna-testing-bootstrapped','1');}})();"
        )
        await runtime.browser.page.goto(WEB + "/tickets")
        await runtime.browser.unique(runtime.browser.locator("board"))
        await wait_until(
            lambda: runtime.supervisor.user and runtime.supervisor.user["id"] == user["id"]
        )
        assert runtime.supervisor.user["role"] == "admin"
        tv = await context.new_page()
        await tv.goto(TV + "/pantalla")
        await tv.get_by_role("heading", name="Tickets activos · IDL", exact=True).wait_for()
        console = next(p for p in context.pages if p.url == config.console_origin + "/")
        await console.reload()
        await context.grant_permissions(["microphone"], origin=config.console_origin)
        try:
            await console.get_by_role("button", name="Conectar micrófono", exact=True).click()
            await wait_until(
                lambda: (
                    runtime.supervisor.speak_callback is not None
                    and runtime.audio.monitor
                    and runtime.audio.monitor.frames > 0
                ),
                timeout=20,
            )
            mic_connected = True
        except Exception:
            mic_connected = False
            print(
                "Admin conectado. Conectá el micrófono desde la consola si hace falta.", flush=True
            )
        await console.bring_to_front()
        # The explicitly requested testing launcher starts an active conversation;
        # regular daily startup retains the ambient wake-name gate.
        await console.get_by_role("button", name="Activar Gianna", exact=True).click()
        report = {
            "account": {"id": user["id"], "name": NAME, "email": EMAIL, "role": "admin"},
            "tickets": WEB + "/tickets",
            "visualizer": TV + "/pantalla",
            "gianna": config.console_origin,
            "all_authenticated": True,
            "conversation_activated": runtime.supervisor.state
            in {
                State.INVITING,
                State.WAITING_INITIAL_INPUT,
                State.ASKING_MISSING_FIELD,
                State.WAITING_CONFIRMATION,
            },
            "gianna_delegated_admin": True,
            "microphone_connected": mic_connected,
            "microphone_receiving_audio": bool(
                runtime.audio.monitor and runtime.audio.monitor.frames > 0
            ),
            "session_expires_at": session["expires_at"],
            "pid": __import__("os").getpid(),
            "conversation_policy_sha256": __import__("hashlib")
            .sha256((ROOT / "src/gianna/dialogue/conversation.py").read_bytes())
            .hexdigest(),
            "interpretation_policy_sha256": __import__("hashlib")
            .sha256((ROOT / "src/gianna/dialogue/interpretation.py").read_bytes())
            .hexdigest(),
            "slot_policy_sha256": __import__("hashlib")
            .sha256((ROOT / "src/gianna/dialogue/slots.py").read_bytes())
            .hexdigest(),
            "supervisor_sha256": __import__("hashlib")
            .sha256((ROOT / "src/gianna/runtime/supervisor.py").read_bytes())
            .hexdigest(),
            "interpreter_sha256": __import__("hashlib")
            .sha256(
                (
                    ROOT
                    / (
                        "src/gianna/models/cloud_interpreter.py"
                        if config.interpreter_backend == "cloud"
                        else "src/gianna/models/local_interpreter.py"
                    )
                ).read_bytes()
            )
            .hexdigest(),
            "interpreter_model": config.conversation_model,
            "interpreter_backend": config.interpreter_backend,
            "conversation_harness": runtime.diagnostics.get("conversation_agent"),
            "conversation_harness_sha256": __import__("hashlib")
            .sha256((ROOT / "src/gianna/runtime/conversation_agent.py").read_bytes())
            .hexdigest(),
            "conversation_agent_policy_sha256": __import__("hashlib")
            .sha256((ROOT / "src/gianna/runtime/conversation_policy.py").read_bytes())
            .hexdigest(),
            "native_agent_tools_sha256": __import__("hashlib")
            .sha256((ROOT / "src/gianna/runtime/agent_tools.py").read_bytes())
            .hexdigest(),
            "spoken_review_sha256": __import__("hashlib")
            .sha256((ROOT / "src/gianna/dialogue/spoken_text.py").read_bytes())
            .hexdigest(),
            "agent_tools_sha256": __import__("hashlib")
            .sha256((ROOT / "src/gianna/runtime/agent_tools.py").read_bytes())
            .hexdigest(),
            "cloud_http_sha256": __import__("hashlib")
            .sha256((ROOT / "src/gianna/models/ollama_cloud.py").read_bytes())
            .hexdigest(),
            "audio_pipeline_sha256": __import__("hashlib")
            .sha256((ROOT / "src/gianna/audio/pipeline.py").read_bytes())
            .hexdigest(),
            "semantic_review_sha256": __import__("hashlib")
            .sha256((ROOT / "src/gianna/models/review_interpreter.py").read_bytes())
            .hexdigest(),
            "whisper_stt_sha256": __import__("hashlib")
            .sha256((ROOT / "src/gianna/audio/stt_whisper_turbo.py").read_bytes())
            .hexdigest(),
            "denoise_sha256": __import__("hashlib")
            .sha256((ROOT / "src/gianna/audio/denoise.py").read_bytes())
            .hexdigest(),
            "turn_boundary_sha256": __import__("hashlib")
            .sha256((ROOT / "src/gianna/audio/turn_boundary.py").read_bytes())
            .hexdigest(),
            "console_app_sha256": __import__("hashlib")
            .sha256((ROOT / "ui/src/App.tsx").read_bytes())
            .hexdigest(),
            "console_media_sha256": __import__("hashlib")
            .sha256((ROOT / "ui/src/LocalMediaManager.ts").read_bytes())
            .hexdigest(),
            "local_auth_sha256": __import__("hashlib")
            .sha256((ROOT / "src/gianna/server/local_auth.py").read_bytes())
            .hexdigest(),
            "console_connection_sha256": __import__("hashlib")
            .sha256((ROOT / "ui/src/useRuntimeConnection.ts").read_bytes())
            .hexdigest(),
            "console_index_sha256": __import__("hashlib")
            .sha256((ROOT / "ui/dist/index.html").read_bytes())
            .hexdigest(),
            "browser_adapter_sha256": __import__("hashlib")
            .sha256((ROOT / "src/gianna/adapters/playwright_browser.py").read_bytes())
            .hexdigest(),
            "window_layout": {
                name: await page.evaluate(
                    """() => ({windowWidth: innerWidth, windowHeight: innerHeight,
                    documentWidth: document.documentElement.clientWidth,
                    rootWidth: document.querySelector('#root').getBoundingClientRect().width,
                    mainWidth: document.querySelector('main').getBoundingClientRect().width,
                    mainRight: document.querySelector('main').getBoundingClientRect().right})"""
                )
                for name, page in {
                    "tickets": runtime.browser.page, "console": console, "visualizer": tv
                }.items()
            },
        }
        report["window_layout"]["fixed_viewport"] = context.pages[0].viewport_size
        (ROOT.parent / "artifacts").mkdir(exist_ok=True)
        for name, page in {
            "tickets": runtime.browser.page, "console": console, "visualizer": tv
        }.items():
            await page.screenshot(path=str(ROOT.parent / "artifacts" / f"gianna-full-width-{name}.png"))
        (ROOT.parent / "artifacts").mkdir(exist_ok=True)
        (ROOT.parent / "artifacts/testing-ready.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            "LISTO: tickets, visualizador y Gianna autenticados como Administrador de pruebas.",
            flush=True,
        )
        print(
            "Micrófono conectado." if mic_connected else "Micrófono pendiente de conexión.",
            flush=True,
        )
        await serving
    finally:
        server.should_exit = True
        if not serving.done():
            await serving


if __name__ == "__main__":
    asyncio.run(run())
