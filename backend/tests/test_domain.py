from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.extensions import db
from app.models import OrgUnit, Ticket, TicketEvent, now
from app.utils.responses import APIError


def create(app, headers, payload, key=None):
    return app.test_client().post(
        "/api/v1/tickets",
        json=payload,
        headers={**headers["operator"], "Idempotency-Key": key or str(uuid4())},
    )


def test_create_history_utc_author_and_projection(app, headers, payload):
    payload["description"] = "  <script>alert('xss')</script> Impresora rota  "
    response = create(app, headers, payload)
    assert response.status_code == 201
    ticket = response.json["data"]
    assert ticket["created_at"].endswith("Z") and ticket["description"].startswith("<script>")
    assert ticket["code"].startswith("IDL-TI-")
    with app.app_context():
        assert (
            db.session.get(Ticket, ticket["id"]).created_by_user_id == ticket["created_by_user_id"]
        )
        assert db.session.scalar(select(func.count(TicketEvent.id))) == 1
    projection = (
        app.test_client().get("/api/v1/display/tickets", headers=headers["viewer"]).json["data"]
    )
    assert projection["total"] == 1
    assert not {"description", "email", "created_by_user_id", "version", "archive_reason"} & set(
        projection["items"][0]
    )
    assert projection["items"][0]["description_preview"] == ticket["description"]


@pytest.mark.parametrize(
    "change",
    [
        {"description": "corto"},
        {"description": " " * 30},
        {"description": "x" * 4001},
        {"origin_unit_id": 987654},
        {"problem_type_id": 987654},
        {"created_at": "2026-01-01T00:00:00Z"},
        {"created_by": 1},
        {"archived_at": None},
        {"source_channel": "gianna"},
        {"occurred_at": "2026-01-01T12:00:00"},
        {"occurred_at": "2999-01-01T12:00:00Z"},
        {"origin_unit_id": "1"},
    ],
)
def test_validation(app, headers, payload, change):
    assert create(app, headers, {**payload, **change}).status_code == 422


def test_missing_fields_and_disabled_references(app, headers, payload):
    assert create(app, headers, {}).status_code == 422
    payload["destination_unit_id"] = payload["origin_unit_id"]
    assert create(app, headers, payload).status_code == 422
    with app.app_context():
        unit = db.session.get(OrgUnit, payload["origin_unit_id"])
        unit.is_active = False
        db.session.commit()
    assert create(app, headers, payload).status_code == 422


def test_idempotency_conflict_and_lost_response(app, headers, payload):
    key = str(uuid4())
    first = create(app, headers, payload, key)
    second = create(app, headers, payload, key)
    assert first.json["data"] == second.json["data"]
    assert first.json["meta"]["request_id"] != second.json["meta"]["request_id"]
    assert (
        create(
            app, headers, {**payload, "description": "Una descripción distinta del incidente"}, key
        ).status_code
        == 409
    )
    with app.app_context():
        assert db.session.scalar(select(func.count(Ticket.id))) == 1
    no_key = app.test_client().post("/api/v1/tickets", headers=headers["operator"], json=payload)
    assert no_key.status_code == 422


def test_transitions_reopen_and_timestamps(app, headers, payload):
    client = app.test_client()
    ticket = create(app, headers, payload).json["data"]
    path = f"/api/v1/tickets/{ticket['id']}/status"

    def move(status, note=None):
        nonlocal ticket
        response = client.patch(
            path,
            headers=headers["operator"],
            json={
                "version": ticket["version"],
                "status": status,
                **({"note": note} if note else {}),
            },
        )
        if response.status_code == 200:
            ticket = response.json["data"]
        return response

    assert move("resolved", "Solución").status_code == 422
    assert move("in_progress").status_code == 200
    first_response = ticket["first_response_at"]
    assert move("waiting").status_code == 200
    assert move("resolved").status_code == 422
    assert move("resolved", "Se reparó la impresora").status_code == 200
    assert ticket["resolved_at"]
    assert move("in_progress").status_code == 422
    assert move("in_progress", "Volvió a ocurrir la falla").status_code == 200
    assert ticket["resolved_at"] is None and ticket["first_response_at"] == first_response
    assert move("cancelled", "No corresponde el pedido").status_code == 200
    assert move("new", "Pedido confirmado nuevamente").status_code == 200
    assert ticket["cancelled_at"] is None
    history = client.get(
        f"/api/v1/tickets/{ticket['id']}/history", headers=headers["operator"]
    ).json["data"]
    assert any(
        e["event_type"] == "reopened" and e["before"]["resolved_at"] for e in history["items"]
    )


def test_archive_replay_restricted_history_and_restore(app, headers, payload):
    client = app.test_client()
    ticket = create(app, headers, payload).json["data"]
    path = f"/api/v1/tickets/{ticket['id']}"
    body = {"version": ticket["version"], "reason": "Pedido duplicado por teléfono"}
    archive_headers = {**headers["operator"], "Idempotency-Key": str(uuid4())}
    first = client.post(path + "/archive", json=body, headers=archive_headers)
    second = client.post(path + "/archive", json=body, headers=archive_headers)
    assert first.status_code == second.status_code == 200
    assert first.json["data"] == second.json["data"]
    assert "description" not in second.json["data"]
    assert client.get(path, headers=headers["operator"]).status_code == 404
    assert client.get(path + "/history", headers=headers["operator"]).status_code == 404
    assert client.get("/api/v1/tickets", headers=headers["admin"]).json["data"]["total"] == 0
    assert (
        client.get("/api/v1/display/tickets", headers=headers["viewer"]).json["data"]["total"] == 0
    )
    assert (
        client.get("/api/v1/statistics/summary", headers=headers["operator"]).json["data"][
            "created"
        ]
        == 1
    )
    hidden = client.get(path, headers=headers["admin"]).json["data"]
    assert (
        client.patch(
            path, json={**payload, "version": hidden["version"]}, headers=headers["admin"]
        ).status_code
        == 409
    )
    response = client.post(
        f"/api/v1/admin/tickets/{ticket['id']}/restore",
        json={"version": hidden["version"], "reason": "Restauración autorizada"},
        headers=headers["admin"],
    )
    assert response.status_code == 200 and response.json["data"]["status"] == "new"
    assert (
        client.get("/api/v1/display/tickets", headers=headers["viewer"]).json["data"]["total"] == 1
    )
    with app.app_context():
        assert db.session.scalar(select(func.count(Ticket.id))) == 1
        assert db.session.scalar(select(func.count(TicketEvent.id))) == 3


def test_version_conflict_and_audit_rollback(app, headers, payload, monkeypatch):
    ticket = create(app, headers, payload).json["data"]
    body = {
        **payload,
        "version": ticket["version"],
        "description": "Cambio de descripción confirmado",
    }
    path = f"/api/v1/tickets/{ticket['id']}"
    assert app.test_client().patch(path, headers=headers["operator"], json=body).status_code == 200
    assert app.test_client().patch(path, headers=headers["operator"], json=body).status_code == 409

    def fail(*args, **kwargs):
        raise APIError("induced_failure", "Fallo inducido de auditoría", 500)

    monkeypatch.setattr("app.services.tickets.audit", fail)
    failed = create(app, headers, payload)
    assert failed.status_code == 500
    with app.app_context():
        assert db.session.scalar(select(func.count(Ticket.id))) == 1
        assert db.session.scalar(select(func.count(TicketEvent.id))) == 2


def test_montevideo_period_statistics_and_previous_day(app, headers, payload):
    first = create(app, headers, payload).json["data"]
    with app.app_context():
        row = db.session.get(Ticket, first["id"])
        from datetime import datetime

        row.created_at = datetime.fromisoformat("2026-10-04T02:30:00+00:00")
        db.session.commit()
    client = app.test_client()
    assert (
        client.get(
            "/api/v1/tickets?from=2026-10-03&to=2026-10-03", headers=headers["operator"]
        ).json["data"]["total"]
        == 1
    )
    assert (
        client.get("/api/v1/tickets?from=2026-10-04", headers=headers["operator"]).json["data"][
            "total"
        ]
        == 0
    )
    with app.app_context():
        row = db.session.get(Ticket, first["id"])
        row.created_at = now() - timedelta(days=1)
        db.session.commit()
    assert (
        client.get("/api/v1/display/tickets", headers=headers["viewer"]).json["data"]["total"] == 1
    )
    summary = client.get("/api/v1/statistics/summary", headers=headers["operator"]).json["data"]
    assert summary["created"] == 1 and summary["average_resolution_seconds"] is None


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/tickets"),
        ("get", "/catalogs"),
        ("get", "/tickets/1"),
        ("get", "/tickets/1/history"),
        ("post", "/tickets"),
        ("patch", "/tickets/1"),
        ("patch", "/tickets/1/status"),
        ("post", "/tickets/1/archive"),
        ("post", "/admin/tickets/1/restore"),
        ("get", "/admin/tickets/archived"),
        ("get", "/admin/users"),
        ("post", "/admin/users"),
        ("patch", "/admin/users/1"),
        ("get", "/admin/org-units"),
        ("post", "/admin/org-units"),
        ("patch", "/admin/org-units/1"),
        ("get", "/admin/problem-types"),
        ("post", "/admin/problem-types"),
        ("patch", "/admin/problem-types/1"),
        ("get", "/statistics/summary"),
        ("get", "/statistics/problems"),
    ],
)
def test_viewer_permissions_http(app, headers, method, path):
    assert (
        getattr(app.test_client(), method)("/api/v1" + path, headers=headers["viewer"]).status_code
        == 403
    )
