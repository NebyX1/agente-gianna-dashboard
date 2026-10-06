import os
import re
import secrets
from datetime import timedelta
from pathlib import Path

import pytest
from flask_migrate import downgrade, upgrade
from sqlalchemy import select

from app import create_app
from app.commands import seed_catalogs
from app.extensions import db
from app.models import User, now
from app.services.auth import hasher

PASSWORD = "test-only-passphrase-8842"


@pytest.fixture
def app(tmp_path):
    uri = os.getenv("TEST_DATABASE_URI", f"sqlite:///{tmp_path / 'unit.db'}")
    if not uri.startswith("sqlite:") and not uri.rsplit("/", 1)[-1].endswith("_test"):
        raise RuntimeError("TEST_DATABASE_URI debe apuntar a una base aislada terminada en _test")
    result = create_app(
        {
            "TESTING": True,
            "APP_ENV": "test",
            "SQLALCHEMY_DATABASE_URI": uri,
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "SECRET_KEY": secrets.token_hex(32),
            "JWT_SECRET_KEY": secrets.token_hex(32),
            "JWT_ACCESS_TOKEN_EXPIRES": timedelta(hours=14),
            "DISPLAY_JWT_ACCESS_HOURS": 14,
            "JWT_TOKEN_LOCATION": ["headers"],
            "CORS_ORIGINS": ["http://localhost:5173", "http://localhost:5174"],
            "RATELIMIT_STORAGE_URI": os.getenv("TEST_REDIS_URI", "memory://"),
            "RATELIMIT_KEY_PREFIX": secrets.token_hex(8),
            "RATELIMIT_ENABLED": True,
            "MAIL_DEFAULT_SENDER": "tickets@example.test",
            "MAIL_TIMEOUT": 1,
            "TEST_MAIL_OUTBOX": [],
            "DEFAULT_DESTINATION_UNIT_CODE": "TI",
            "MAX_CONTENT_LENGTH": 32768,
        }
    )
    migrations = str(Path(__file__).resolve().parents[1] / "migrations")
    with result.app_context():
        downgrade(directory=migrations, revision="base")
        upgrade(directory=migrations)
        seed_catalogs()
        for role in ("admin", "operator", "viewer"):
            db.session.add(
                User(
                    email=f"{role}@example.test",
                    name=role.title(),
                    role=role,
                    password_hash=hasher.hash(PASSWORD),
                )
            )
        db.session.commit()
    yield result
    with result.app_context():
        db.session.remove()
        db.engine.dispose()


def login(app, role="operator"):
    client = app.test_client()
    response = client.post(
        "/api/v1/auth/login", json={"email": f"{role}@example.test", "password": PASSWORD}
    )
    assert response.status_code == 200, response.json
    pending = response.json["data"]["pending_token"]
    message = app.config["TEST_MAIL_OUTBOX"][-1]
    code = re.search(r"\b\d{6}\b", message.body)[0]
    response = client.post("/api/v1/auth/verify-2fa", json={"pending_token": pending, "code": code})
    assert response.status_code == 200, response.json
    return {"Authorization": "Bearer " + response.json["data"]["access_token"]}


@pytest.fixture
def headers(app):
    return {role: login(app, role) for role in ("admin", "operator", "viewer")}


@pytest.fixture
def payload(app, headers):
    catalog = app.test_client().get("/api/v1/catalogs", headers=headers["operator"]).json["data"]
    return {
        "origin_unit_id": next(u["id"] for u in catalog["org_units"] if u["code"] == "TRANSITO"),
        "destination_unit_id": catalog["default_destination_unit_id"],
        "problem_type_id": catalog["problem_types"][0]["id"],
        "description": "La impresora no imprime y hace un ruido raro",
    }


def allow_resend(app, role="operator"):
    with app.app_context():
        user = db.session.scalar(select(User).where(User.email == f"{role}@example.test"))
        user.last_otp_sent_at = now() - timedelta(seconds=61)
        db.session.commit()
