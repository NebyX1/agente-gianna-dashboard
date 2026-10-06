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


def run(args):
    result = subprocess.run(compose + args, cwd=root)
    if result.returncode:
        raise SystemExit(
            "Falló la preparación E2E; revisá la salida del comando anterior"
        )


run(["config", "--quiet"])
run(["up", "-d", "--build", "--wait", "--wait-timeout", "180"])
# This fixed project has separate test volumes. Reset only this isolated schema.
run(["exec", "-T", "backend", "flask", "--app", "wsgi", "db", "downgrade", "base"])
run(["exec", "-T", "backend", "flask", "--app", "wsgi", "db", "upgrade"])
run(["exec", "-T", "backend", "flask", "--app", "wsgi", "seed-catalogs"])
run(["exec", "-T", "backend", "flask", "--app", "wsgi", "seed-test-users", "--reset"])
run(["cp", "backend:/home/appuser/.test-users.json", "e2e/.test-users.json"])
run(["exec", "-T", "backend", "flask", "--app", "wsgi", "seed-previous-day"])
print("E2E aislado listo: frontend 5373, pantalla 5374, API 5300, Mailpit 8026.")
