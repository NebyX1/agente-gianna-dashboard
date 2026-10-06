from datetime import timedelta

from sqlalchemy import select
from test_domain import create

from app.extensions import db
from app.models import AuthSession, Ticket, User, now


def test_catalog_cycles_immutable_code_default_and_historical_edit(app, headers, payload):
    client = app.test_client()
    ticket = create(app, headers, payload).json["data"]
    admin = headers["admin"]
    origin, destination = payload["origin_unit_id"], payload["destination_unit_id"]
    assert (
        client.patch(
            f"/api/v1/admin/org-units/{origin}", headers=admin, json={"parent_id": destination}
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/v1/admin/org-units/{destination}", headers=admin, json={"parent_id": origin}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/v1/admin/org-units/{origin}", headers=admin, json={"code": "CHANGED"}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/v1/admin/org-units/{destination}",
            headers=admin,
            json={"can_receive_tickets": False},
        ).status_code
        == 200
    )
    assert (
        client.get("/api/v1/catalogs", headers=headers["operator"]).json["data"][
            "default_destination_unit_id"
        ]
        is None
    )
    assert (
        client.patch(
            f"/api/v1/admin/org-units/{origin}",
            headers=admin,
            json={"is_active": False, "name": "Nombre actualizado"},
        ).status_code
        == 200
    )
    changed = client.patch(
        f"/api/v1/tickets/{ticket['id']}",
        headers=headers["operator"],
        json={
            **payload,
            "version": ticket["version"],
            "description": "Cambio de texto conservando referencias históricas",
        },
    )
    assert changed.status_code == 200
    history = client.get(
        f"/api/v1/tickets/{ticket['id']}/history", headers=headers["operator"]
    ).json["data"]["items"]
    assert history[-1]["after"]["origin"]["name"] == "Tránsito"
    assert changed.json["data"]["origin"]["name"] == "Nombre actualizado"


def test_statistics_known_cohort_archives_cancelled_and_reopen(app, headers, payload):
    client = app.test_client()
    tickets = [create(app, headers, payload).json["data"] for _ in range(4)]
    with app.app_context():
        for index, value in enumerate(tickets):
            ticket = db.session.get(Ticket, value["id"])
            ticket.created_at = now() - timedelta(hours=2)
            if index == 0:
                ticket.status = "resolved"
                ticket.resolved_at = ticket.created_at + timedelta(hours=1)
            if index == 1:
                ticket.status = "cancelled"
                ticket.cancelled_at = now()
            if index == 2:
                ticket.archived_at = now()
        db.session.commit()
    summary = client.get("/api/v1/statistics/summary", headers=headers["operator"]).json["data"]
    assert (summary["created"], summary["resolved"], summary["cancelled"], summary["archived"]) == (
        4,
        1,
        1,
        1,
    )
    assert summary["average_resolution_seconds"] == 3600
    assert summary["active_by_status"]["new"] == 1
    problems = client.get("/api/v1/statistics/problems", headers=headers["operator"]).json["data"][
        "items"
    ]
    assert problems[0]["count"] == 4
    current = client.get(f"/api/v1/tickets/{tickets[0]['id']}", headers=headers["operator"]).json[
        "data"
    ]
    assert (
        client.patch(
            f"/api/v1/tickets/{current['id']}/status",
            headers=headers["operator"],
            json={
                "status": "in_progress",
                "version": current["version"],
                "note": "Problema reapareció",
            },
        ).status_code
        == 200
    )
    assert (
        client.get("/api/v1/statistics/summary", headers=headers["operator"]).json["data"][
            "average_resolution_seconds"
        ]
        is None
    )


def test_expired_session_and_inactive_user(app, headers):
    client = app.test_client()
    with app.app_context():
        viewer = db.session.scalar(select(User).where(User.role == "viewer"))
        session = db.session.scalar(select(AuthSession).where(AuthSession.user_id == viewer.id))
        session.expires_at = now() - timedelta(seconds=1)
        operator = db.session.scalar(select(User).where(User.role == "operator"))
        operator.is_active = False
        db.session.commit()
    assert client.get("/api/v1/display/tickets", headers=headers["viewer"]).status_code == 401
    assert client.get("/api/v1/tickets", headers=headers["operator"]).status_code == 401
