"""Unedited reported utterances through the real UI, model, API and durable writes.

The only business writes target idl-tickets-design-check (5400), after explicit
confirmation in the UI. No model/tool/HTTP/ASR response is replaced or retried.
"""

from copy import deepcopy
import asyncio
import json
import os
import time

import httpx
import pytest
import uvicorn
from gianna.config import ROOT, Settings
from gianna.dialogue.activation import normalize
from gianna.dialogue.state_machine import State
from gianna.dialogue.spoken_text import spoken_code
from gianna.server.app import create_app
from tests.e2e.test_voice_flow import login_browser, wait_until

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.models,
    pytest.mark.gpu,
    pytest.mark.skipif(os.getenv("GIANNA_REAL_E2E") != "1", reason="Explicit real UI/cloud/API"),
]


async def test_reported_conversation_then_ticket_lifecycle_through_ui(tmp_path):
    base = Settings()
    config = Settings(
        data_dir=tmp_path,
        model_dir=base.models_dir,
        nltk_dir=base.data_dir / "nltk",
        tickets_api="http://localhost:5400",
        tickets_web="http://localhost:5473",
        port=7862,
        piper_port=5002,
    )
    app = create_app(config, managed_browser=False)
    runtime = app.state.runtime
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=7862,
            access_log=False,
            log_level="warning",
            timeout_graceful_shutdown=5,
        )
    )
    serving = asyncio.create_task(server.serve())
    evidence = {"input": "reported human transcripts typed through public UI", "turns": []}
    try:
        await wait_until(lambda: server.started or serving.done(), 150)
        assert server.started and runtime.supervisor.state != State.BLOCKED, runtime.diagnostics
        s = runtime.supervisor
        await runtime.browser.start(runtime.broker, visible=False)
        async with httpx.AsyncClient() as client:
            credentials = json.loads(
                (ROOT.parent / "artifacts/design-check-users.json").read_text(encoding="utf-8")
            )["operator"]
            await login_browser(runtime.browser.page, client, credentials)
            await wait_until(lambda: s.user is not None and s.catalogs is not None)
            console = next(
                p for p in runtime.browser.context.pages if p.url == config.console_origin + "/"
            )
            await console.bring_to_front()
            before = (await s.tickets.request("GET", "/api/v1/tickets"))["total"]

            async def send(text):
                utterance = s.last_speech["utterance_id"] if s.last_speech else None
                started = time.monotonic()
                await console.get_by_label("Mensaje para Gianna").fill(text)
                await console.get_by_role("button", name="Enviar a Gianna", exact=True).click()
                await wait_until(
                    lambda: s.last_speech and s.last_speech["utterance_id"] != utterance,
                    95,
                )
                response = s.last_speech["text"]
                evidence["turns"].append(
                    {
                        "user": text,
                        "answer": response,
                        "draft": deepcopy(s.snapshot()["draft"]),
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                    }
                )
                print("Real UI:", text, "->", response, flush=True)
                assert "No pude completar esa consulta" not in response
                assert "cita literal" not in response
                return normalize(response)

            await send("Gianna, estás ahí?")
            await send(
                "¿Sabes qué es lo que quiero? Registrar un ticket nuevo y lo que registres es un ticket "
                "a la dirección de sociales que nos pidieron recién hace un ratito cambiar las hojas "
                "de las impresoras. ¿Podés anotar eso?"
            )
            assert s.state == State.WAITING_CONFIRMATION
            assert s.draft_labels()["origin_unit_id"] == "Sociales"
            assert s.draft_labels()["problem_type_id"] == "Impresoras"
            description = s.draft.payload["description"]
            await send("Te acabo de decir la oficina de servicios sociales")
            assert s.draft.payload["description"] == description
            assert s.draft_labels()["origin_unit_id"] == "Sociales"
            await send("¿Por qué no pudiste completar el pedido?")
            assert s.draft.payload["description"] == description
            assert not s.db.operations()

            payload, revision = deepcopy(s.draft.payload), s.draft.revision
            await send("¿Y a qué equipo va? ¿Ya está registrado?")
            assert s.draft.payload == payload and s.draft.revision == revision
            assert not s.db.operations()
            await send("Sí, pero agregá que son dos impresoras y lo necesitan antes de las tres")
            assert (
                "dos" in normalize(s.draft.payload["description"])
                or "2" in s.draft.payload["description"]
            )
            assert (
                "tres" in normalize(s.draft.payload["description"])
                or "15" in s.draft.payload["description"]
            )
            assert s.state == State.WAITING_CONFIRMATION and not s.db.operations()
            await send("No modifiques nada todavía")
            assert s.state == State.PAUSED and not s.db.operations()
            await send("Gianna, seguimos")
            assert s.state == State.WAITING_CONFIRMATION
            expected = deepcopy(s.draft.payload)
            await send("Confirmo, registrá ese ticket")
            await wait_until(lambda: len(s.db.operations()) == 1 and s.last_receipt is not None, 30)
            receipt = deepcopy(s.last_receipt)
            ticket = await s.tickets.request("GET", f"/api/v1/tickets/{receipt['ticket_id']}")
            assert ticket["description"] == expected["description"]
            assert ticket["origin"]["name"] == "Sociales"
            assert ticket["problem_type"]["name"] == "Impresoras"
            assert (await s.tickets.request("GET", "/api/v1/tickets"))["total"] == before + 1
            await send("Confirmo, registrá ese ticket")
            assert len(s.db.operations()) == 1
            reply = await send("¿Qué número quedó y qué te pedí registrar?")
            number = int(receipt["code"].split("-")[-1])
            assert (
                str(number) in reply or normalize(spoken_code(receipt["code"])) in reply
            ) and "impresora" in reply

            await send(f"Poné el ticket número {number} en curso")
            assert (
                s.draft.tool == "tickets.status.v1" and s.draft.payload["status"] == "in_progress"
            )
            assert len(s.db.operations()) == 1
            assert (await s.tickets.request("GET", f"/api/v1/tickets/{ticket['id']}"))[
                "status"
            ] == "new"
            await send("Confirmo el cambio")
            await wait_until(lambda: len(s.db.operations()) == 2 and s.draft is None, 30)
            await send(
                f"Resolvé el ticket {number}, ya se repuso el papel en las dos impresoras y probamos que imprimen"
            )
            assert s.state == State.WAITING_CONFIRMATION, "Do not ask again for the supplied reason"
            assert s.draft.payload["status"] == "resolved" and "papel" in s.draft.payload["note"]
            assert (await s.tickets.request("GET", f"/api/v1/tickets/{ticket['id']}"))[
                "status"
            ] == "in_progress"
            await send("Confirmo, marcalo como resuelto")
            await wait_until(lambda: len(s.db.operations()) == 3 and s.draft is None, 30)
            finished = await s.tickets.request("GET", f"/api/v1/tickets/{ticket['id']}")
            assert finished["status"] == "resolved"
            history = await s.tickets.request("GET", f"/api/v1/tickets/{ticket['id']}/history")
            assert any("papel" in (r.get("note") or "") for r in history["items"])
            assert not s.db.connection.execute(
                "SELECT 1 FROM events WHERE kind='agent_turn_failed'"
            ).fetchone()
            evidence.update(
                ticket=finished, receipt=receipt, history=history, operations=len(s.db.operations())
            )
            await console.screenshot(
                path=str(ROOT.parent / "artifacts/gianna-conversation-repair-ui.png"),
                full_page=True,
            )
    finally:
        if runtime.db:
            evidence["events"] = [
                dict(r)
                for r in runtime.db.connection.execute("SELECT kind,data FROM events ORDER BY id")
            ]
        (ROOT.parent / "artifacts/gianna-conversation-repair-ui.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if runtime.audio:
            await runtime.audio.close()
        if runtime.browser:
            await runtime.browser.close()
        server.should_exit = True
        await asyncio.wait_for(serving, 45)
