import re
from datetime import timedelta

from conftest import PASSWORD, allow_resend
from sqlalchemy import select

from app.extensions import db, limiter
from app.models import Challenge, User, now


def challenge(app):
    client = app.test_client()
    response = client.post(
        "/api/v1/auth/login", json={"email": "operator@example.test", "password": PASSWORD}
    )
    assert response.status_code == 200
    return response.json["data"]["pending_token"], re.search(
        r"\b\d{6}\b", app.config["TEST_MAIL_OUTBOX"][-1].body
    )[0]


def test_otp_single_use_expiration_cooldown_pending_scope(app):
    client = app.test_client()
    pending, code = challenge(app)
    assert (
        client.get(
            "/api/v1/display/tickets", headers={"Authorization": "Bearer " + pending}
        ).status_code
        == 401
    )
    assert (
        client.post("/api/v1/auth/resend-2fa", json={"pending_token": pending}).status_code == 429
    )
    response = client.post("/api/v1/auth/verify-2fa", json={"pending_token": pending, "code": code})
    assert response.status_code == 200
    assert (
        client.post(
            "/api/v1/auth/verify-2fa", json={"pending_token": pending, "code": code}
        ).status_code
        == 401
    )
    token = response.json["data"]["access_token"]
    headers = {"Authorization": "Bearer " + token}
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    allow_resend(app)
    pending, code = challenge(app)
    with app.app_context():
        row = db.session.scalar(select(Challenge).where(Challenge.consumed_at.is_(None)))
        row.expires_at = now() - timedelta(seconds=1)
        db.session.commit()
    assert (
        client.post(
            "/api/v1/auth/verify-2fa", json={"pending_token": pending, "code": code}
        ).status_code
        == 401
    )


def test_attempts_persist_and_resend_invalidates(app):
    pending, code = challenge(app)
    client = app.test_client()
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert (
            client.post(
                "/api/v1/auth/verify-2fa", json={"pending_token": pending, "code": wrong}
            ).status_code
            == 422
        )
    assert (
        client.post(
            "/api/v1/auth/verify-2fa", json={"pending_token": pending, "code": code}
        ).status_code
        == 429
    )
    allow_resend(app)
    assert (
        client.post("/api/v1/auth/resend-2fa", json={"pending_token": pending}).status_code == 200
    )
    assert (
        client.post(
            "/api/v1/auth/verify-2fa", json={"pending_token": pending, "code": code}
        ).status_code
        == 401
    )


def test_account_quota_across_rotations_and_ips(app):
    pending, _ = challenge(app)
    client = app.test_client()
    for index in range(39):
        response = client.post(
            "/api/v1/auth/verify-2fa",
            json={"pending_token": pending, "code": "000001"},
            environ_overrides={"REMOTE_ADDR": f"10.0.0.{index + 1}"},
        )
        assert response.status_code in {422, 429}
    allow_resend(app)
    response = client.post(
        "/api/v1/auth/resend-2fa",
        json={"pending_token": pending},
        environ_overrides={"REMOTE_ADDR": "10.0.1.1"},
    )
    assert response.status_code == 429
    assert response.json["error"]["code"] == "rate_limited"
    assert response.headers["Retry-After"]


def test_role_disable_password_revoke_and_last_admin(app, headers):
    client = app.test_client()
    with app.app_context():
        operator = db.session.scalar(select(User).where(User.role == "operator"))
        operator_id = operator.id
    assert (
        client.patch(
            f"/api/v1/admin/users/{operator_id}", headers=headers["admin"], json={"role": "viewer"}
        ).status_code
        == 200
    )
    assert client.get("/api/v1/auth/me", headers=headers["operator"]).status_code == 401
    response = client.put(
        "/api/v1/auth/change-password",
        headers=headers["viewer"],
        json={"current_password": PASSWORD, "new_password": "changed-test-password-782"},
    )
    assert response.status_code == 200
    assert client.get("/api/v1/auth/me", headers=headers["viewer"]).status_code == 401
    with app.app_context():
        admin_id = db.session.scalar(select(User.id).where(User.role == "admin"))
    assert (
        client.patch(
            f"/api/v1/admin/users/{admin_id}", headers=headers["admin"], json={"is_active": False}
        ).status_code
        == 409
    )


def test_cors_errors_readiness(app, headers, monkeypatch):
    client = app.test_client()
    positive = client.options(
        "/api/v1/tickets",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization,Idempotency-Key,Content-Type",
        },
    )
    assert (
        positive.status_code == 200
        and positive.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    )
    negative = client.options(
        "/api/v1/tickets",
        headers={"Origin": "https://untrusted.example", "Access-Control-Request-Method": "POST"},
    )
    assert "Access-Control-Allow-Origin" not in negative.headers
    error = client.get("/api/v1/missing")
    assert error.status_code == 404 and error.json["ok"] is False
    assert error.headers["X-Request-ID"] == error.json["meta"]["request_id"]
    with app.app_context():
        monkeypatch.setattr(limiter.storage, "check", lambda: False)
        assert client.get("/readyz").status_code == 503
