from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import select

from app.extensions import db
from app.models import OrgUnit, ProblemType, Ticket, TicketEvent, User, now
from app.schemas import (
    ACTIVE,
    STATUSES,
    OrgUnitCreate,
    ProblemTypeCreate,
    TicketArchive,
    TicketCreate,
    TicketRestore,
    TicketStatusChange,
    TicketUpdate,
    UserCreate,
    UserUpdate,
    load,
)
from app.services import agent_operations
from app.services.auth import authorize, hasher, user_read
from app.services.tickets import (
    archive_ticket,
    change_status,
    create_ticket,
    display_read,
    filtered,
    get_ticket,
    idempotent,
    paginate,
    restore_ticket,
    ticket_read,
    type_read,
    unit_read,
    update_ticket,
)
from app.utils.responses import APIError, iso, success

bp = Blueprint("domain", __name__, url_prefix="/api/v1")


def statuses():
    return [{"code": code, **value} for code, value in STATUSES.items()]


@bp.get("/catalogs")
@authorize("admin", "operator")
def catalogs():
    units = db.session.scalars(
        select(OrgUnit).where(OrgUnit.is_active.is_(True)).order_by(OrgUnit.name)
    ).all()
    types = db.session.scalars(
        select(ProblemType).where(ProblemType.is_active.is_(True)).order_by(ProblemType.name)
    ).all()
    default = next(
        (
            u.id
            for u in units
            if u.code == current_app.config["DEFAULT_DESTINATION_UNIT_CODE"]
            and u.can_receive_tickets
        ),
        None,
    )
    return success(
        {
            "org_units": [unit_read(u) for u in units],
            "problem_types": [type_read(t) for t in types],
            "statuses": statuses(),
            "default_destination_unit_id": default,
            "warnings": []
            if default
            else ["No hay destino predeterminado habilitado; seleccioná uno manualmente"],
        }
    )


@bp.get("/tickets")
@authorize("admin", "operator")
def tickets_list():
    return success(
        paginate(filtered(select(Ticket)).order_by(Ticket.created_at, Ticket.id), ticket_read)
    )


@bp.post("/tickets")
@authorize("admin", "operator")
def tickets_create():
    data = load(TicketCreate)
    result, status = (agent_operations.execute("tickets.create.v1", "tickets", data,
        lambda: create_ticket(data), 201) if agent_operations.delegated() else
        idempotent("tickets:create", data, lambda: create_ticket(data), 201))
    return success(result, status)


@bp.get("/tickets/<int:ticket_id>")
@authorize("admin", "operator")
def tickets_detail(ticket_id):
    return success(ticket_read(get_ticket(ticket_id)))


@bp.patch("/tickets/<int:ticket_id>")
@authorize("admin", "operator")
def tickets_edit(ticket_id):
    data = load(TicketUpdate)
    if agent_operations.delegated():
        result, status = agent_operations.execute("tickets.update.v1", f"tickets/{ticket_id}", data,
            lambda: update_ticket(ticket_id, dict(data), commit=False))
        return success(result, status)
    return success(update_ticket(ticket_id, data))


@bp.patch("/tickets/<int:ticket_id>/status")
@authorize("admin", "operator")
def tickets_status(ticket_id):
    data = load(TicketStatusChange)
    if agent_operations.delegated():
        result, status = agent_operations.execute("tickets.status.v1", f"tickets/{ticket_id}", data,
            lambda: change_status(ticket_id, data, commit=False))
        return success(result, status)
    return success(change_status(ticket_id, data))


@bp.post("/tickets/<int:ticket_id>/archive")
@authorize("admin", "operator")
def tickets_archive(ticket_id):
    data = load(TicketArchive)
    if agent_operations.delegated():
        result, status = agent_operations.execute("tickets.archive.v1", f"tickets/{ticket_id}", data,
            lambda: archive_ticket(ticket_id, data))
        return success(result, status)
    result, status = idempotent(
        f"tickets:{ticket_id}:archive", data, lambda: archive_ticket(ticket_id, data)
    )
    return success(result, status)


def event_read(event):
    return {
        "id": event.id,
        "ticket_id": event.ticket_id,
        "actor_user_id": event.actor_user_id,
        "actor_name": event.actor_name,
        "event_type": event.event_type,
        "timestamp": iso(event.timestamp),
        "request_id": event.request_id,
        "channel": event.channel,
        "before": event.before,
        "after": event.after,
        "note": event.note,
    }


@bp.get("/tickets/<int:ticket_id>/history")
@authorize("admin", "operator")
def tickets_history(ticket_id):
    get_ticket(ticket_id)
    return success(
        paginate(
            select(TicketEvent)
            .where(TicketEvent.ticket_id == ticket_id)
            .order_by(TicketEvent.timestamp.desc(), TicketEvent.id.desc()),
            event_read,
        )
    )


@bp.get("/admin/tickets/archived")
@authorize("admin")
def archived_list():
    return success(
        paginate(
            filtered(select(Ticket), operational=False)
            .where(Ticket.archived_at.is_not(None))
            .order_by(Ticket.created_at, Ticket.id),
            ticket_read,
        )
    )


@bp.post("/admin/tickets/<int:ticket_id>/restore")
@authorize("admin")
def tickets_restore(ticket_id):
    data = load(TicketRestore)
    if agent_operations.delegated():
        result, status = agent_operations.execute("tickets.restore.v1", f"tickets/{ticket_id}", data,
            lambda: restore_ticket(ticket_id, data, commit=False))
        return success(result, status)
    return success(restore_ticket(ticket_id, data))


@bp.get("/agent/operations/<string:operation_id>")
@authorize("admin", "operator")
def agent_receipt(operation_id):
    return success(agent_operations.receipt(operation_id))


@bp.get("/display/config")
@authorize("admin", "operator", "viewer")
def display_config():
    units = db.session.scalars(
        select(OrgUnit)
        .where(OrgUnit.is_active.is_(True), OrgUnit.can_receive_tickets.is_(True))
        .order_by(OrgUnit.name)
    ).all()
    return success(
        {
            "statuses": statuses(),
            "destinations": [{"id": u.id, "name": u.name} for u in units],
            "timezone": "America/Montevideo",
        }
    )


@bp.get("/display/tickets")
@authorize("admin", "operator", "viewer")
def display_tickets():
    if set(request.args) - {"destination_unit_id"}:
        raise APIError("validation_error", "La pantalla sólo admite filtro por destino")
    query = (
        filtered(select(Ticket))
        .where(Ticket.status.in_(ACTIVE))
        .order_by(Ticket.created_at, Ticket.id)
    )
    items = [display_read(t) for t in db.session.scalars(query).all()]
    return success({"items": items, "total": len(items), "generated_at": iso(now())})


def cohort():
    return db.session.scalars(filtered(select(Ticket), operational=False)).all()


def group(rows, field, label):
    counts = Counter(getattr(t, field) for t in rows)
    labels = {getattr(t, field): getattr(t, label).name for t in rows}
    return [
        {"id": id_, "name": labels[id_], "count": count}
        for id_, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    ]


@bp.get("/statistics/summary")
@authorize("admin", "operator")
def summary():
    rows = cohort()
    resolved = [t for t in rows if t.status == "resolved" and t.resolved_at]
    times = [(t.resolved_at - t.created_at).total_seconds() for t in resolved]
    daily = Counter(
        t.created_at.astimezone(ZoneInfo("America/Montevideo")).date().isoformat() for t in rows
    )
    active_counts = dict(
        Counter(
            t.status
            for t in db.session.scalars(
                select(Ticket).where(Ticket.archived_at.is_(None), Ticket.status.in_(ACTIVE))
            )
        )
    )
    return success(
        {
            "created": len(rows),
            "resolved": len(resolved),
            "cancelled": sum(t.status == "cancelled" for t in rows),
            "archived": sum(t.archived_at is not None for t in rows),
            "average_resolution_seconds": sum(times) / len(times) if times else None,
            "active_by_status": {s: active_counts.get(s, 0) for s in ACTIVE},
            "daily": [{"date": d, "count": n} for d, n in sorted(daily.items())],
            "origins": group(rows, "origin_unit_id", "origin"),
            "destinations": group(rows, "destination_unit_id", "destination"),
            "definition": "Cohorte por fecha de creación, días de Montevideo. Incluye ocultos y cancelados. Promedio desde creación hasta cierre vigente de actualmente resueltos; excluye cancelados. Activos actuales excluyen ocultos y son independientes del período.",
        }
    )


@bp.get("/statistics/problems")
@authorize("admin", "operator")
def problems():
    return success({"items": group(cohort(), "problem_type_id", "problem_type")})


def admin_catalog(model, schema, serializer, item_id=None):
    if request.method == "GET":
        return success(
            {
                "items": [
                    serializer(row)
                    for row in db.session.scalars(select(model).order_by(model.name))
                ]
            }
        )
    data = load(schema, partial=item_id is not None, excluded=("code",) if item_id else ())
    # Serialize catalog changes to make parent-cycle validation safe under concurrent edits.
    rows = db.session.scalars(select(model).order_by(model.id).with_for_update()).all()
    row = next((r for r in rows if r.id == item_id), None) if item_id else model()
    if row is None:
        raise APIError("not_found", "No se encontró el registro", 404)
    if model is OrgUnit and data.get("parent_id") is not None:
        ancestors, parent = set(), data["parent_id"]
        by_id = {r.id: r for r in rows}
        while parent is not None:
            if parent == item_id or parent in ancestors:
                raise APIError("validation_error", "La relación entre unidades formaría un ciclo")
            ancestors.add(parent)
            if parent not in by_id or not by_id[parent].is_active:
                raise APIError("validation_error", "Seleccioná una unidad padre activa")
            parent = by_id[parent].parent_id
    for key, value in data.items():
        setattr(row, key, value)
    db.session.add(row)
    db.session.commit()
    return success(serializer(row), 200 if item_id else 201)


@bp.route("/admin/org-units", methods=["GET", "POST"])
@bp.patch("/admin/org-units/<int:item_id>")
@authorize("admin")
def admin_units(item_id=None):
    return admin_catalog(OrgUnit, OrgUnitCreate, unit_read, item_id)


@bp.route("/admin/problem-types", methods=["GET", "POST"])
@bp.patch("/admin/problem-types/<int:item_id>")
@authorize("admin")
def admin_types(item_id=None):
    return admin_catalog(ProblemType, ProblemTypeCreate, type_read, item_id)


@bp.route("/admin/users", methods=["GET", "POST"])
@bp.patch("/admin/users/<int:item_id>")
@authorize("admin")
def admin_users(item_id=None):
    if request.method == "GET":
        return success(
            {"items": [user_read(u) for u in db.session.scalars(select(User).order_by(User.name))]}
        )
    data = load(UserUpdate if item_id else UserCreate)
    # Lock all users in stable order; prevents two admins disabling each other concurrently.
    users = db.session.scalars(select(User).order_by(User.id).with_for_update()).all()
    if item_id:
        user = next((u for u in users if u.id == item_id), None)
        if not user:
            raise APIError("not_found", "Usuario inexistente", 404)
        if (
            user.role == "admin"
            and user.is_active
            and (
                data.get("role", user.role) != "admin" or not data.get("is_active", user.is_active)
            )
        ):
            if sum(u.role == "admin" and u.is_active for u in users) <= 1:
                raise APIError("last_admin", "Debe quedar al menos un administrador activo", 409)
        if (
            data.get("role", user.role) != user.role
            or data.get("is_active", user.is_active) != user.is_active
        ):
            user.auth_version += 1
            user.challenge_nonce = None
    else:
        password = data.pop("password")
        data["email"] = data["email"].lower()
        user = User(password_hash=hasher.hash(password))
    for key, value in data.items():
        setattr(user, key, value)
    db.session.add(user)
    db.session.commit()
    return success(user_read(user), 200 if item_id else 201)


@bp.get("/openapi.json")
def openapi():
    return jsonify(
        __import__("json").loads(
            (Path(current_app.root_path).parent / "contracts/openapi.json").read_text(
                encoding="utf-8"
            )
        )
    )
