from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from flask_migrate import upgrade
from sqlalchemy import func, select
from test_auth import challenge
from test_domain import create

from app.commands import seed_catalogs
from app.extensions import db
from app.models import AuthSession, Ticket, TicketEvent


def parallel(function, count=2):
    barrier = Barrier(count)

    def run(index):
        barrier.wait(timeout=10)
        return function(index)

    with ThreadPoolExecutor(max_workers=count) as pool:
        return list(pool.map(run, range(count)))


@pytest.mark.integration
def test_mariadb_simultaneous_idempotency_version_and_archive(app, headers, payload):
    if not app.config["SQLALCHEMY_DATABASE_URI"].startswith("mariadb+"):
        pytest.skip("Requiere MariaDB real")
    key = str(uuid4())
    replies = parallel(lambda _: create(app, headers, payload, key))
    assert [r.status_code for r in replies] == [201, 201]
    assert replies[0].json["data"] == replies[1].json["data"]
    ticket = replies[0].json["data"]
    path = f"/api/v1/tickets/{ticket['id']}"
    updates = parallel(
        lambda i: app.test_client().patch(
            path,
            headers=headers["operator"],
            json={
                **payload,
                "version": ticket["version"],
                "description": f"Cambio simultáneo del operador número {i}",
            },
        )
    )
    assert sorted(r.status_code for r in updates) == [200, 409]
    current = app.test_client().get(path, headers=headers["operator"]).json["data"]
    archive_key = str(uuid4())
    archives = parallel(
        lambda _: app.test_client().post(
            path + "/archive",
            headers={**headers["operator"], "Idempotency-Key": archive_key},
            json={"version": current["version"], "reason": "Ocultación concurrente de prueba"},
        )
    )
    assert [r.status_code for r in archives] == [200, 200]
    assert archives[0].json["data"] == archives[1].json["data"]
    with app.app_context():
        assert db.session.scalar(select(func.count(Ticket.id))) == 1
        assert db.session.scalar(select(func.count(TicketEvent.id))) == 3


@pytest.mark.integration
def test_mariadb_otp_consumption_atomic(app):
    if not app.config["SQLALCHEMY_DATABASE_URI"].startswith("mariadb+"):
        pytest.skip("Requiere MariaDB real")
    pending, code = challenge(app)
    responses = parallel(
        lambda _: app.test_client().post(
            "/api/v1/auth/verify-2fa", json={"pending_token": pending, "code": code}
        )
    )
    assert sorted(r.status_code for r in responses) == [200, 401]
    with app.app_context():
        assert db.session.scalar(select(func.count(AuthSession.id))) == 1


@pytest.mark.integration
def test_mariadb_upgrade_seed_repeat_and_no_drift(app, headers, payload):
    if not app.config["SQLALCHEMY_DATABASE_URI"].startswith("mariadb+"):
        pytest.skip("Requiere MariaDB real")
    ticket = create(app, headers, payload).json["data"]
    with app.app_context():
        directory = str(Path(__file__).resolve().parents[1] / "migrations")
        upgrade(directory=directory)
        seed_catalogs()
        seed_catalogs()
        assert db.session.get(Ticket, ticket["id"]).code == ticket["code"]
    result = app.test_cli_runner().invoke(args=["db", "check"])
    assert result.exit_code == 0, result.output
