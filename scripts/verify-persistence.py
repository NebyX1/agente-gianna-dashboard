"""Check down/up preserves rows on the isolated E2E Compose project."""

import json
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
compose = [
    "docker",
    "compose",
    "-p",
    "idl-tickets-e2e",
    "-f",
    "compose.yaml",
    "-f",
    "compose.e2e.yaml",
    "--profile",
    "development",
]
code = "from app import create_app; from app.extensions import db; from app.models import Ticket, TicketEvent; from sqlalchemy import select,func; import json; app=create_app(); ctx=app.app_context(); ctx.push(); print(json.dumps({'tickets':db.session.scalar(select(func.count(Ticket.id))),'events':db.session.scalar(select(func.count(TicketEvent.id)))}))"


def count():
    output = subprocess.check_output(
        compose + ["exec", "-T", "backend", "python", "-c", code], cwd=root, text=True
    )
    return json.loads(output)


before = count()
assert before["tickets"] > 0, "Debe haber tickets antes de probar persistencia"
subprocess.run(compose + ["down"], cwd=root, check=True)
subprocess.run(
    compose + ["up", "-d", "--wait", "--wait-timeout", "180"], cwd=root, check=True
)
after = count()
assert before == after, f"Cambió el conteo: {before} -> {after}"
print(f"Persistencia confirmada tras down/up: {after}")
