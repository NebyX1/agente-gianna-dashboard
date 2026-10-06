"""Fault injection around REAL HTTP/MariaDB commits; not an audio test."""

import asyncio
import json
import os
import re
import time
import httpx
import pytest
from gianna.config import Settings, ROOT
from gianna.adapters.tickets_http import TicketsHTTP, TicketError
from gianna.dialogue.draft import Draft
from gianna.dialogue.confirmations import Confirmation
from gianna.persistence.database import Database
from gianna.runtime.operation_manager import OperationManager

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("GIANNA_REAL_E2E") != "1",
        reason="Explicit isolated MariaDB/API/SMTP services required",
    ),
]


async def login(client, credentials):
    response = await client.post("http://localhost:5400/api/v1/auth/login", json=credentials)
    if response.status_code == 429:
        # Exercise the normal resend cooldown; never disable auth limits in live fixtures.
        await asyncio.sleep(61)
        response = await client.post("http://localhost:5400/api/v1/auth/login", json=credentials)
    response.raise_for_status()
    pending = response.json()["data"]["pending_token"]
    code = None
    for _ in range(30):
        mails = (await client.get("http://localhost:8027/api/v1/messages")).json()["messages"]
        for mail in mails:
            body = (await client.get("http://localhost:8027/api/v1/message/" + mail["ID"])).json()
            if any(r["Address"] == credentials["email"] for r in body.get("To", [])):
                found = re.search(r"\b\d{6}\b", body.get("Text", ""))
                if found:
                    code = found[0]
                    break
        if code:
            break
        await asyncio.sleep(0.2)
    assert code
    response = await client.post(
        "http://localhost:5400/api/v1/auth/verify-2fa",
        json={"pending_token": pending, "code": code},
    )
    response.raise_for_status()
    return response.json()["data"]["access_token"]


class LoseCommittedResponse(httpx.AsyncBaseTransport):
    def __init__(self):
        self.network = httpx.AsyncHTTPTransport()
        self.lose = False

    async def handle_async_request(self, request):
        response = await self.network.handle_async_request(request)
        if self.lose and request.method == "POST" and "X-Agent-Operation-ID" in request.headers:
            self.lose = False
            await response.aread()
            await response.aclose()
            raise httpx.ReadTimeout("Test lost response AFTER real commit", request=request)
        return response

    async def aclose(self):
        await self.network.aclose()


async def test_real_lost_response_restart_archive_restore_and_conflict(tmp_path):
    config = Settings(tickets_api="http://localhost:5400", tickets_web="http://localhost:5473")
    transport = LoseCommittedResponse()
    async with httpx.AsyncClient(transport=transport) as client:
        users = json.loads(
            (ROOT.parent / "artifacts/design-check-users.json").read_text(encoding="utf-8")
        )
        parent = await login(client, {k: users["operator"][k] for k in ("email", "password")})
        adapter = TicketsHTTP(config, client)
        user = await adapter.delegate(parent)
        db = Database(tmp_path / "recovery.db")
        manager = OperationManager(db, adapter, config, time.monotonic)
        catalogs = await adapter.request("GET", "/api/v1/catalogs")
        origin = next(x["id"] for x in catalogs["org_units"] if x["code"] == "TRANSITO")
        destination = catalogs["default_destination_unit_id"]
        problem = next(x["id"] for x in catalogs["problem_types"] if x["code"] == "IMPRESORA")
        profile = {"profile_id": "idl.tickets", "version": "1.0.0"}

        def prepare(tool, resource, payload, session="session-a"):
            d = Draft(user["id"], tool=tool, resource=resource, payload=payload)
            c = Confirmation.issue(d, time.monotonic, 120, session)
            return manager.prepare(session, d, c, profile), d, c

        from uuid import uuid4

        payload = {
            "origin_unit_id": origin,
            "destination_unit_id": destination,
            "problem_type_id": problem,
            "description": "[RECOVERY REAL] Impresora de integración con respuesta perdida "
            + str(uuid4()),
        }
        row, d, confirmation = prepare("tickets.create.v1", "tickets", payload)
        transport.lose = True
        with pytest.raises(RuntimeError, match="outcome_unknown"):
            await manager.dispatch(row, d, confirmation, lambda: True)
        assert db.operations()[0]["status"] == "outcome_unknown"
        db.close()
        # New local instance and new delegated session of SAME actor; NEVER another create POST.
        await adapter.delegate(parent)
        db = Database(tmp_path / "recovery.db")
        manager = OperationManager(db, adapter, config, time.monotonic)
        receipt = (await manager.recover(user["id"]))[0]
        assert (
            receipt["operation_id"] == row["operation_id"] and receipt["payload_hash"] == d.digest
        )
        found = await adapter.request("GET", "/api/v1/tickets", query={"q": payload["description"]})
        assert found["total"] == 1
        resource = f"tickets/{receipt['ticket_id']}"
        # Real concurrent edit produces 409; manager does not bump version or retry.
        stale, sd, sc = prepare(
            "tickets.update.v1",
            resource,
            {
                **payload,
                "version": receipt["version"],
                "description": "Cambio propuesto por Gianna",
            },
        )
        await adapter.request(
            "PATCH",
            "/api/v1/" + resource,
            payload={
                **payload,
                "version": receipt["version"],
                "description": "Cambio humano concurrente",
            },
            token=parent,
        )
        with pytest.raises(TicketError) as error:
            await manager.dispatch(stale, sd, sc, lambda: True)
        assert error.value.status == 409
        assert (
            db.operations()[1]["status"] == "failed_known"
            and sd.payload["version"] == receipt["version"]
        )
        current = await adapter.observe(resource)
        edited_row, edited_draft, edited_confirmation = prepare(
            "tickets.update.v1",
            resource,
            {
                **payload,
                "version": current["version"],
                "description": "Edición confirmada por Gianna después de revisar la versión actual",
            },
        )
        edited = await manager.dispatch(edited_row, edited_draft, edited_confirmation, lambda: True)
        assert (await adapter.observe(resource))["description"] == edited_draft.payload[
            "description"
        ]
        status, sd, sc = prepare(
            "tickets.status.v1", resource, {"version": edited["version"], "status": "in_progress"}
        )
        changed = await manager.dispatch(status, sd, sc, lambda: True)
        archived, ad, ac = prepare(
            "tickets.archive.v1",
            resource,
            {"version": changed["version"], "reason": "Ocultación de prueba con respuesta perdida"},
        )
        transport.lose = True
        with pytest.raises(RuntimeError, match="outcome_unknown"):
            await manager.dispatch(archived, ad, ac, lambda: True)
        with pytest.raises(TicketError) as invisible:
            await adapter.observe(resource)
        assert invisible.value.status == 404
        recovered = (await manager.recover(user["id"]))[0]
        assert recovered["tool"] == "tickets.archive.v1" and recovered["event_ids"]
        assert "description" not in recovered
        admin_parent = await login(client, {k: users["admin"][k] for k in ("email", "password")})
        admin = TicketsHTTP(config, client)
        admin_user = await admin.delegate(admin_parent)
        admin_manager = OperationManager(db, admin, config, time.monotonic)
        restored_draft = Draft(
            admin_user["id"],
            tool="tickets.restore.v1",
            resource=resource,
            payload={"version": recovered["version"], "reason": "Restauración real de integración"},
        )
        restored_confirmation = Confirmation.issue(
            restored_draft, time.monotonic, 120, "admin-session"
        )
        restored = admin_manager.prepare(
            "admin-session", restored_draft, restored_confirmation, profile
        )
        result = await admin_manager.dispatch(
            restored, restored_draft, restored_confirmation, lambda: True
        )
        history = await admin.request("GET", "/api/v1/" + resource + "/history")
        assert {"created", "edited", "status_changed", "archived", "restored"} <= {
            e["event_type"] for e in history["items"]
        }
        await adapter.request("POST", "/api/v1/auth/logout", token=parent)
        with pytest.raises(TicketError) as revoked:
            await adapter.revalidate(user["id"])
        assert revoked.value.status == 401
        evidence = {
            "actual_services": "Flask/MariaDB/Redis/SMTP",
            "synthetic_network_fault": "Lost actual committed HTTP response",
            "created": receipt,
            "edited": edited,
            "archive": recovered,
            "restore": result,
            "concurrent_409": True,
            "parent_revocation": True,
            "history_events": len(history["items"]),
        }
        (ROOT.parent / "artifacts/gianna-real-recovery.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        await admin.close()
        db.close()
