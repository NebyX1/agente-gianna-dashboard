from uuid import uuid4

from conftest import allow_resend, login
from sqlalchemy import select

from app.extensions import db
from app.models import AgentOperation, AgentOperationEvent, AuthSession, Ticket, TicketEvent, User


def delegate(client, parent):
    r = client.post("/api/v1/auth/agent-session", json={}, headers=parent)
    assert r.status_code == 200, r.json
    assert r.json["data"]["scope"] == ["tickets"]
    return {"Authorization": "Bearer " + r.json["data"]["access_token"]}


def operation(child):
    return {**child, "X-Agent-Operation-ID": str(uuid4()), "Idempotency-Key": str(uuid4())}


def test_delegation_scoped_and_revoked_with_parent(app, headers):
    c = app.test_client()
    child = delegate(c, headers["admin"])
    assert c.get("/api/v1/admin/users", headers=child).status_code == 403
    assert c.put("/api/v1/auth/change-password", json={}, headers=child).status_code == 403
    assert c.post("/api/v1/auth/agent-session", json={}, headers=child).status_code == 403
    assert c.post("/api/v1/auth/agent-session", json={"role": "admin"}, headers=headers["admin"]).status_code == 422
    assert c.post("/api/v1/auth/agent-session", json={}, headers=headers["viewer"]).status_code == 403
    with app.app_context():
        sessions = db.session.scalars(select(AuthSession)).all()
        delegated = next(s for s in sessions if s.parent_session_id)
        assert delegated.expires_at <= db.session.get(AuthSession, delegated.parent_session_id).expires_at
    c.post("/api/v1/auth/logout", headers=headers["admin"])
    assert c.get("/api/v1/catalogs", headers=child).status_code == 401


def test_receipt_replay_identity_survives_new_login_and_archive(app, headers, payload):
    c = app.test_client()
    child = delegate(c, headers["operator"])
    h = operation(child)
    first = c.post("/api/v1/tickets", json=payload, headers=h)
    assert first.status_code == 201, first.json
    receipt = first.json["data"]
    assert "description" not in receipt
    tid = receipt["ticket_id"]
    second = c.post("/api/v1/tickets", json=payload, headers=h)
    assert second.json["data"] == receipt
    assert c.post("/api/v1/tickets", json={**payload, "description": "Otros datos diferentes"}, headers=h).status_code == 409
    assert c.post("/api/v1/tickets", json=payload, headers={**h, "Idempotency-Key": str(uuid4())}).status_code == 409
    # Update/status are idempotent too, including their expected original version.
    sh = operation(child)
    body = {"version": receipt["version"], "status": "in_progress"}
    changed = c.patch(f"/api/v1/tickets/{tid}/status", json=body, headers=sh)
    assert changed.status_code == 200
    assert c.patch(f"/api/v1/tickets/{tid}/status", json=body, headers=sh).json["data"] == changed.json["data"]
    archived = c.post(f"/api/v1/tickets/{tid}/archive", json={"version": changed.json["data"]["version"], "reason": "Prueba de ocultación"}, headers=operation(child))
    assert archived.status_code == 200, archived.json
    assert c.get(f"/api/v1/tickets/{tid}", headers=child).status_code == 404
    assert c.get(f'/api/v1/agent/operations/{h["X-Agent-Operation-ID"]}', headers=child).json["data"] == receipt
    assert c.get(f'/api/v1/agent/operations/{h["X-Agent-Operation-ID"]}', headers=headers["admin"]).status_code == 404
    c.post("/api/v1/auth/logout", headers=headers["operator"])
    allow_resend(app)
    new_child = delegate(c, login(app))
    replay = c.post("/api/v1/tickets", json=payload, headers={**h, **new_child})
    assert replay.json["data"] == receipt
    assert replay.headers["X-Request-ID"] != first.headers["X-Request-ID"]
    with app.app_context():
        assert len(db.session.scalars(select(Ticket)).all()) == 1
        assert len(db.session.scalars(select(AgentOperation)).all()) == 3
        assert len(db.session.scalars(select(AgentOperationEvent)).all()) == 3
        assert {e.channel for e in db.session.scalars(select(TicketEvent)).all()} == {"voice_agent"}


def test_atomic_rollback_and_current_permissions(app, headers, payload):
    c = app.test_client()
    child = delegate(c, headers["operator"])
    h = operation(child)
    assert c.post("/api/v1/tickets", json={**payload, "origin_unit_id": 999999}, headers=h).status_code == 422
    with app.app_context():
        assert not db.session.scalars(select(AgentOperation)).all()
    assert c.post("/api/v1/tickets", json=payload, headers=child).status_code == 422
    assert c.post("/api/v1/tickets", json=payload, headers=h).status_code == 201
    with app.app_context():
        user = db.session.scalar(select(User).where(User.role == "operator"))
        user.auth_version += 1
        db.session.commit()
    assert c.post("/api/v1/tickets", json=payload, headers=h).status_code == 401
