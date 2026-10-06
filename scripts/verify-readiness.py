"""Verify real dependency outages on the fixed isolated E2E project only."""

import json
import subprocess
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

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
    subprocess.run(compose + args, cwd=root, check=True)


def readiness():
    try:
        with urlopen("http://localhost:5300/readyz", timeout=15) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


assert readiness()[0] == 200, "El entorno E2E debe estar listo antes de esta prueba"
for service in ("redis", "mariadb"):
    try:
        run(["stop", service])
        status, body = readiness()
        assert status == 503 and body["error"]["code"] == "not_ready"
        assert body["meta"]["request_id"]
        print(f"Readiness sin {service}: 503 not_ready", flush=True)
    finally:
        run(["up", "-d", "--wait", "--wait-timeout", "180", service])
    assert readiness()[0] == 200, f"Readiness no se recuperó al iniciar {service}"
    print(f"Readiness recuperada con {service}: 200", flush=True)
