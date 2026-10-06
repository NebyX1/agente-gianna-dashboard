"""Run critical tests in a fresh MariaDB 11.4 container, never the development DB."""

import secrets
import subprocess
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
suffix = secrets.token_hex(4)
network = "idl-tests-" + suffix
database = "idl-mariadb-test-" + suffix
password = secrets.token_hex(24)


def run(args, **kwargs):
    result = subprocess.run(args, cwd=root, **kwargs)
    if result.returncode:
        raise SystemExit(
            "Falló una verificación del backend; consultá la salida anterior"
        )


run(["docker", "build", "-t", "idl-tickets-backend", "./backend"])
run(
    [
        "docker",
        "build",
        "-f",
        "backend/Dockerfile.test",
        "-t",
        "idl-tickets-backend-tests",
        "./backend",
    ]
)
run(["docker", "network", "create", network], stdout=subprocess.DEVNULL)
try:
    run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            database,
            "--network",
            network,
            "--network-alias",
            "testdb",
            "-e",
            "MARIADB_DATABASE=idl_tickets_test",
            "-e",
            "MARIADB_USER=idl_test",
            "-e",
            f"MARIADB_PASSWORD={password}",
            "-e",
            f"MARIADB_ROOT_PASSWORD={password}",
            "mariadb:11.4.8",
        ],
        stdout=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        ready = subprocess.run(
            [
                "docker",
                "exec",
                database,
                "healthcheck.sh",
                "--connect",
                "--innodb_initialized",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if ready.returncode == 0:
            break
        time.sleep(2)
    else:
        raise SystemExit("MariaDB aislada no estuvo lista dentro de 90 segundos")
    run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            network,
            "-e",
            f"TEST_DATABASE_URI=mariadb+mariadbconnector://idl_test:{password}@testdb:3306/idl_tickets_test",
            "idl-tickets-backend-tests",
            "-q",
        ]
    )
finally:
    subprocess.run(["docker", "rm", "-f", database], stdout=subprocess.DEVNULL)
    subprocess.run(["docker", "network", "rm", network], stdout=subprocess.DEVNULL)
