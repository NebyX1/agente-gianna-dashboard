"""Real DeepSeek tools and MariaDB counts; fixtures only on the isolated 5400 stack.

No conversation/model/HTTP result is substituted. This tests text turns and
actual voice synthesis, not a physical microphone or the browser transport.
"""

import io
import json
import os
import re
import time
import wave
from uuid import uuid4

import httpx
import pytest

from gianna.adapters.tickets_http import TicketsHTTP
from gianna.audio.tts_piper import PiperResident, SynthesisRequest
from gianna.config import ROOT, Settings
from gianna.dialogue.activation import normalize
from gianna.models.cloud_interpreter import CloudInterpreter
from gianna.persistence.database import Database
from gianna.profiles.loader import load_profile
from gianna.runtime.conversation_agent import ConversationAgent
from gianna.runtime.event_bus import EventBus
from gianna.runtime.operation_manager import OperationManager
from gianna.runtime.supervisor import Supervisor
from gianna.tools.dispatcher import Dispatcher
from gianna.tools.registry import ToolRegistry
from gianna.tools.tickets import install_tools
from tests.integration.test_real_recovery import login

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("GIANNA_REAL_E2E") != "1", reason="Explicit isolated API/MariaDB and live Cloud"
    ),
]


class RecordedTickets(TicketsHTTP):
    def __init__(self, *args):
        super().__init__(*args)
        self.reads = []

    async def request(self, method, path, **kwargs):
        if method == "POST" and kwargs.get("token"):
            kwargs["headers"] = {"Idempotency-Key": str(uuid4())}
        self.reads.append({"method": method, "path": path, "query": kwargs.get("query", {})})
        return await super().request(method, path, **kwargs)


async def test_area_counts_followups_pagination_short_lookup_and_spoken_output(tmp_path):
    config = Settings(
        data_dir=tmp_path,
        model_dir=Settings().models_dir,
        tickets_api="http://localhost:5400",
        tickets_web="http://localhost:5473",
    )
    # Fixed isolated target; this test must never follow the production .env API.
    assert config.tickets_api == "http://localhost:5400"
    evidence = {"provider": config.cloud_model, "input": "text", "turns": []}
    db = Database(tmp_path / "references.db")
    async with httpx.AsyncClient() as client:
        users = json.loads(
            (ROOT.parent / "artifacts/design-check-users.json").read_text(encoding="utf-8")
        )
        parent = await login(client, {k: users["operator"][k] for k in ("email", "password")})
        tickets = RecordedTickets(config, client)
        user = await tickets.delegate(parent)
        catalogs = await tickets.request("GET", "/api/v1/catalogs")
        ids = {u["name"]: u["id"] for u in catalogs["org_units"]}
        transit, social = ids["Tránsito"], ids["Sociales"]
        marker = "[REFERENCE REAL] " + str(uuid4())
        payload = {
            "origin_unit_id": transit,
            "destination_unit_id": catalogs["default_destination_unit_id"],
            "problem_type_id": catalogs["problem_types"][0]["id"],
            "description": marker + " La impresora de Tránsito no imprime.",
        }
        created = []
        for index in range(17):
            created.append(
                await tickets.request(
                    "POST",
                    "/api/v1/tickets",
                    token=parent,
                    payload={
                        **payload,
                        "description": payload["description"] + f" Puesto {index}.",
                    },
                )
            )
        for index, status in [
            (12, "in_progress"),
            (13, "in_progress"),
            (14, "cancelled"),
            (15, "in_progress"),
        ]:
            created[index] = await tickets.request(
                "PATCH",
                f"/api/v1/tickets/{created[index]['id']}/status",
                token=parent,
                payload={
                    "version": created[index]["version"],
                    "status": status,
                    "note": "Fixture de accesibilidad",
                },
            )
        for index, status in [(13, "waiting"), (15, "resolved")]:
            created[index] = await tickets.request(
                "PATCH",
                f"/api/v1/tickets/{created[index]['id']}/status",
                token=parent,
                payload={
                    "version": created[index]["version"],
                    "status": status,
                    "note": "Fixture de accesibilidad",
                },
            )
        await tickets.request(
            "POST",
            f"/api/v1/tickets/{created[16]['id']}/archive",
            token=parent,
            payload={"version": created[16]["version"], "reason": "Fixture oculto"},
        )
        await tickets.request(
            "POST", "/api/v1/tickets", token=parent, payload={**payload, "origin_unit_id": social}
        )
        expected = {}
        for area in (transit, social):
            expected[area] = (
                await tickets.request(
                    "GET",
                    "/api/v1/tickets",
                    query={"origin_unit_id": area, "status": "active", "per_page": 1},
                )
            )["total"]
        assert expected[transit] > 10
        control = await tickets.request(
            "GET",
            "/api/v1/tickets",
            query={"origin_unit_id": transit, "status": "active", "q": marker},
        )
        assert control["total"] == 14, (
            "Active counts include new/in_progress/waiting, never terminal or hidden"
        )
        all_before = (await tickets.request("GET", "/api/v1/tickets", query={"per_page": 1}))[
            "total"
        ]
        interpreter = CloudInterpreter(config, client)
        manager = OperationManager(db, tickets, config, time.monotonic)
        s = Supervisor(config, db, EventBus(), tickets, interpreter, manager, load_profile(), None)
        s.interpreter = interpreter
        registry = ToolRegistry()
        install_tools(registry, tickets, None, s)
        s.dispatcher = Dispatcher(registry)
        s.conversation_agent = ConversationAgent(s, client)
        await s.authenticated(user)
        try:

            async def say(text):
                start, read_start = time.monotonic(), len(tickets.reads)
                old = s.last_speech
                await s.submit(text)
                assert s.last_speech is not old and not s.errors
                reply = s.last_speech["text"]
                assert not s.draft and not db.operations(), (
                    "A query cannot prepare or send a change"
                )
                assert "IDL-TI-" not in reply and "0, 0" not in reply
                reads = tickets.reads[read_start:]
                assert all(r["method"] == "GET" for r in reads)
                evidence["turns"].append(
                    {
                        "user": text,
                        "answer": reply,
                        "reads": reads,
                        "elapsed_seconds": round(time.monotonic() - start, 3),
                    }
                )
                print("Real references:", text, "->", reply, flush=True)
                return normalize(reply), reads

            reply, reads = await say("Gianna, ¿cuántos tickets de Tránsito tengo activos?")
            assert re.search(rf"\b{expected[transit]}\b", reply) and "transito" in reply
            assert len(reply) < 300
            assert any(
                r["query"].get("origin_unit_id") == transit
                and r["query"].get("status") == "active"
                and r["query"].get("per_page") == 1
                and "q" not in r["query"]
                for r in reads
            )
            reply, reads = await say("¿Y de la dirección de Sociales?")
            assert re.search(rf"\b{expected[social]}\b", reply) and "sociales" in reply
            assert any(
                r["query"].get("origin_unit_id") == social and r["query"].get("status") == "active"
                for r in reads
            )
            reply, reads = await say("¿Y cuáles son los de Tránsito? Decime diez como máximo.")
            assert "numero" in reply
            assert any(
                r["query"].get("origin_unit_id") == transit and r["query"].get("status") == "active"
                for r in reads
            )
            reply, reads = await say("Seguí con los siguientes diez de esa lista")
            assert any(
                r["query"].get("page", 1) == 2
                and r["query"].get("origin_unit_id") == transit
                and r["query"].get("status") == "active"
                for r in reads
            )
            number = int(created[0]["code"].split("-")[-1])
            reply, reads = await say(f"¿Qué problema tiene el ticket terminación {number}?")
            assert "impresora" in reply and "puesto 0" in reply
            assert any(r["query"].get("q") == created[0]["code"] for r in reads)
            assert (await tickets.request("GET", "/api/v1/tickets", query={"per_page": 1}))[
                "total"
            ] == all_before
            # The real speaker synthesizes the exact shortened final answer.
            piper = PiperResident(config)
            try:
                await piper.worker.run(piper.load)
                wav = await piper.worker.run(
                    piper.synthesize, SynthesisRequest(text=s.last_speech["text"])
                )
                with wave.open(io.BytesIO(wav)) as audio:
                    assert audio.getnframes() > audio.getframerate()
                    evidence["tts"] = {
                        "text": s.last_speech["text"],
                        "seconds": audio.getnframes() / audio.getframerate(),
                    }
            finally:
                await piper.worker.close()
        finally:
            (ROOT.parent / "artifacts/gianna-ticket-accessibility-live.json").write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            await s.close()
            await tickets.close()
            db.close()
