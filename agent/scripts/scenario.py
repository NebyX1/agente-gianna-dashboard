"""Conversación completa con el Supervisor real, Qwen local y un doble de tickets.

Uso: python scripts/scenario.py guion.txt (una transcripción de voz por línea, UTF-8).
"""

import asyncio
import sys
import tempfile
import time
from pathlib import Path

import httpx

from gianna.config import Settings
from gianna.dialogue.state_machine import State
from gianna.models.local_interpreter import LocalInterpreter
from gianna.persistence.database import Database
from gianna.profiles.loader import load_profile
from gianna.runtime.event_bus import EventBus
from gianna.runtime.operation_manager import OperationManager
from gianna.runtime.supervisor import Supervisor


class Tev:
    async def choose(self, text, criteria, context=""):
        return "clarify"


class Tickets:
    user = {"id": 1, "role": "operator"}
    token = "t"

    def __init__(self):
        self.sent = []
        self.receipts = {}

    async def revalidate(self, actor):
        return None

    async def execute(self, row):
        self.sent.append(row)
        receipt = {
            "operation_id": row["operation_id"],
            "payload_hash": row["payload_hash"],
            "event_ids": [1],
            "code": "IDL-TI-000001",
        }
        self.receipts[row["operation_id"]] = receipt
        return receipt

    async def verify(self, row):
        return self.receipts[row["operation_id"]]


async def main(lines):
    config = Settings(tickets_api="http://localhost:5300", tickets_web="http://localhost:5373")
    db = Database(Path(tempfile.mkdtemp()) / "agent.db")
    tickets = Tickets()
    s = Supervisor(
        config, db, EventBus(), tickets, Tev(), OperationManager(db, tickets, config, time.monotonic),
        load_profile(), None,
    )
    s.interpreter = LocalInterpreter(config, httpx.AsyncClient())
    s.user = {"id": 1, "role": "operator", "name": "Operador"}
    s.catalogs = {
        "default_destination_unit_id": 1,
        "org_units": [
            {"id": 1, "name": "Informática", "code": "TI", "can_receive_tickets": True},
            {"id": 2, "name": "Tránsito", "code": "TRANSITO", "can_receive_tickets": False},
            {"id": 3, "name": "Urbanismo", "code": "URBANISMO", "can_receive_tickets": False},
            {"id": 4, "name": "Sociales", "code": "SOCIALES", "can_receive_tickets": False},
            {"id": 5, "name": "Oficina de ejemplo (editable)", "code": "OFICINA_EJEMPLO", "can_receive_tickets": False},
        ],
        "problem_types": [
            {"id": 1, "name": "Conectividad / Internet", "code": "INTERNET"},
            {"id": 2, "name": "Impresoras", "code": "IMPRESORA"},
            {"id": 3, "name": "Acceso a sistemas", "code": "SISTEMAS"},
            {"id": 4, "name": "Hardware", "code": "HARDWARE"},
            {"id": 5, "name": "Otros", "code": "OTROS"},
        ],
        "statuses": [],
    }
    s.state = State.DORMANT
    spoken = []

    async def speak(message):
        spoken.append(message["text"])
        asyncio.create_task(s.playback_complete(message["utterance_id"], message["generation_id"]))

    s.speak_callback = speak
    for line in lines:
        spoken.clear()
        start = time.perf_counter()
        await s.submit(line, source="voice")
        await asyncio.sleep(0.2)
        print(f"\n> {line}")
        for text in spoken:
            print(f"  GIANNA: {text}")
        print(f"  [{s.state}] {time.perf_counter() - start:.1f}s draft={s.draft.payload if s.draft else None}")
    s.cancel_idle()
    db.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 1 and args[0].endswith(".txt"):
        args = [x for x in Path(args[0]).read_text(encoding="utf-8").splitlines() if x.strip()]
    asyncio.run(main(args))
