import hashlib
import json
import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from flask import g, request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Idempotency, OrgUnit, ProblemType, Ticket, TicketEvent, now
from app.schemas import ACTIVE, STATUSES
from app.utils.responses import APIError, iso


def unit_read(unit):
    return {
        "id": unit.id,
        "code": unit.code,
        "name": unit.name,
        "kind": unit.kind,
        "is_active": unit.is_active,
        "can_receive_tickets": unit.can_receive_tickets,
        "parent_id": unit.parent_id,
    }


def type_read(kind):
    return {
        "id": kind.id,
        "code": kind.code,
        "name": kind.name,
        "description": kind.description,
        "is_active": kind.is_active,
    }


def ticket_read(ticket):
    return {
        "id": ticket.id,
        "code": ticket.code,
        "origin_unit_id": ticket.origin_unit_id,
        "destination_unit_id": ticket.destination_unit_id,
        "problem_type_id": ticket.problem_type_id,
        "origin": unit_read(ticket.origin),
        "destination": unit_read(ticket.destination),
        "problem_type": type_read(ticket.problem_type),
        "description": ticket.description,
        "status": ticket.status,
        "version": ticket.version,
        "created_by_user_id": ticket.created_by_user_id,
        **{
            key: iso(getattr(ticket, key))
            for key in [
                "created_at",
                "updated_at",
                "first_response_at",
                "resolved_at",
                "cancelled_at",
                "occurred_at",
                "archived_at",
            ]
        },
        "archived_by_user_id": ticket.archived_by_user_id,
        "archive_reason": ticket.archive_reason,
    }


def display_read(ticket):
    return {
        "id": ticket.id,
        "code": ticket.code,
        "status": ticket.status,
        "origin": {"id": ticket.origin.id, "name": ticket.origin.name},
        "destination": {"id": ticket.destination.id, "name": ticket.destination.name},
        "problem_type": {"id": ticket.problem_type.id, "name": ticket.problem_type.name},
        "created_at": iso(ticket.created_at),
        "updated_at": iso(ticket.updated_at),
        "description_preview": ticket.description[:400],
    }


def get_ticket(ticket_id, *, mutate=False, hidden=False):
    ticket = db.session.execute(
        select(Ticket).where(Ticket.id == ticket_id).with_for_update()
        if mutate
        else select(Ticket).where(Ticket.id == ticket_id)
    ).scalar_one_or_none()
    if not ticket or (ticket.archived_at and g.user.role != "admin"):
        raise APIError("not_found", "No se encontró el ticket", 404)
    if mutate and ticket.archived_at and not hidden:
        raise APIError("ticket_archived", "Restaurá el ticket antes de modificarlo", 409)
    return ticket


def check_version(ticket, version):
    if ticket.version != version:
        raise APIError(
            "version_conflict",
            "Otra persona cambió el ticket. Se cargará la versión vigente",
            409,
            details={"ticket_id": ticket.id, "current_version": ticket.version},
        )


def references(data):
    for key, model in [
        ("origin_unit_id", OrgUnit),
        ("destination_unit_id", OrgUnit),
        ("problem_type_id", ProblemType),
    ]:
        if key not in data:
            continue
        record = db.session.get(model, data[key])
        if (
            not record
            or not record.is_active
            or (key == "destination_unit_id" and not record.can_receive_tickets)
        ):
            raise APIError(
                "validation_error",
                "Seleccioná referencias activas y un destino habilitado",
                errors={key: ["No existe, está inactivo o no admite tickets"]},
            )


def audit(ticket, kind, before=None, note=None):
    db.session.flush()
    db.session.add(
        TicketEvent(
            ticket_id=ticket.id,
            actor_user_id=g.user.id,
            actor_name=g.user.name,
            event_type=kind,
            request_id=g.request_id,
            before=before,
            after=ticket_read(ticket),
            note=note,
            channel="voice_agent" if getattr(getattr(g, "auth_session", None), "client_id", None) == "gianna-agent" else "manual_ui",
        )
    )
    db.session.flush()


def idempotent(scope, payload, operation, status=200):
    key = request.headers.get("Idempotency-Key", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", key):
        raise APIError(
            "validation_error",
            "Idempotency-Key es obligatorio (16 a 64 caracteres seguros)",
            errors={"Idempotency-Key": ["Clave inválida"]},
        )
    digest = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, default=iso, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()

    def replay(record):
        if record.payload_hash != digest:
            raise APIError("idempotency_conflict", "Esta clave ya se utilizó con otros datos", 409)
        return record.result, record.status_code

    query = select(Idempotency).where(
        Idempotency.user_id == g.user.id, Idempotency.scope == scope, Idempotency.key == key
    )
    existing = db.session.execute(query).scalar_one_or_none()
    if existing:
        return replay(existing)
    record = Idempotency(
        user_id=g.user.id, scope=scope, key=key, payload_hash=digest, status_code=status
    )
    db.session.add(record)
    try:
        db.session.flush()  # Unique reservation waits for concurrent commit/rollback.
    except IntegrityError:
        db.session.rollback()
        existing = db.session.execute(query).scalar_one_or_none()
        if existing is None:
            raise
        return replay(existing)
    result = operation()
    record.result = result
    db.session.commit()
    return result, status


def create_ticket(data):
    references(data)
    ticket = Ticket(**data, created_by_user_id=g.user.id, status="new")
    db.session.add(ticket)
    db.session.flush()
    ticket.code = f"IDL-TI-{ticket.id:06d}"  # DB auto-increment, safe across workers.
    audit(ticket, "created")
    return ticket_read(ticket)


def update_ticket(ticket_id, data, *, commit=True):
    ticket = get_ticket(ticket_id, mutate=True)
    check_version(ticket, data.pop("version"))
    before = ticket_read(ticket)
    references(
        {
            key: value
            for key, value in data.items()
            if key.endswith("_id") and getattr(ticket, key) != value
        }
    )
    for key, value in data.items():
        setattr(ticket, key, value)
    ticket.updated_at = now()
    db.session.flush()
    db.session.expire(ticket, ["origin", "destination", "problem_type"])
    audit(ticket, "edited", before)
    if commit:
        db.session.commit()
    return ticket_read(ticket)


def change_status(ticket_id, data, *, commit=True):
    ticket = get_ticket(ticket_id, mutate=True)
    check_version(ticket, data["version"])
    target, previous = data["status"], ticket.status
    if target not in STATUSES[previous]["transitions"]:
        raise APIError("invalid_transition", "Ese cambio de estado no está permitido", 422)
    reopening = previous in {"resolved", "cancelled"}
    if (target in {"resolved", "cancelled"} or reopening) and not data.get("note"):
        raise APIError(
            "validation_error",
            "Ingresá la solución o el motivo",
            errors={"note": ["Campo obligatorio"]},
        )
    before = ticket_read(ticket)
    ticket.status, ticket.updated_at = target, now()
    if target == "in_progress" and ticket.first_response_at is None:
        ticket.first_response_at = now()
    ticket.resolved_at = now() if target == "resolved" else None
    ticket.cancelled_at = now() if target == "cancelled" else None
    audit(ticket, "reopened" if reopening else "status_changed", before, data.get("note"))
    if commit:
        db.session.commit()
    return ticket_read(ticket)


def archive_ticket(ticket_id, data):
    ticket = get_ticket(ticket_id, mutate=True)
    check_version(ticket, data["version"])
    before = ticket_read(ticket)
    ticket.archived_at, ticket.archived_by_user_id, ticket.archive_reason = (
        now(),
        g.user.id,
        data["reason"],
    )
    ticket.updated_at = now()
    audit(ticket, "archived", before, data["reason"])
    return {
        "ticket_id": ticket.id,
        "operation": "archive",
        "archived_at": iso(ticket.archived_at),
        "version": ticket.version,
    }


def restore_ticket(ticket_id, data, *, commit=True):
    ticket = get_ticket(ticket_id, mutate=True, hidden=True)
    check_version(ticket, data["version"])
    if not ticket.archived_at:
        raise APIError("not_archived", "El ticket ya está visible", 409)
    before = ticket_read(ticket)
    ticket.archived_at = ticket.archived_by_user_id = ticket.archive_reason = None
    ticket.updated_at = now()
    audit(ticket, "restored", before, data["reason"])
    if commit:
        db.session.commit()
    return ticket_read(ticket)


def period(value, end=False):
    try:
        day = date.fromisoformat(value)
        if end:
            day += timedelta(days=1)
        return datetime.combine(day, time.min, ZoneInfo("America/Montevideo")).astimezone(UTC)
    except ValueError as exc:
        raise APIError("validation_error", "Usá fechas YYYY-MM-DD para el período") from exc


def filtered(query, *, operational=True):
    args = request.args
    allowed = {
        "q",
        "origin_unit_id",
        "destination_unit_id",
        "problem_type_id",
        "status",
        "from",
        "to",
        "page",
        "per_page",
    }
    if set(args) - allowed:
        raise APIError("validation_error", "Hay filtros desconocidos")
    if operational:
        query = query.where(Ticket.archived_at.is_(None))
    for field in ("origin_unit_id", "destination_unit_id", "problem_type_id"):
        if args.get(field):
            try:
                value = int(args[field])
                if value < 1:
                    raise ValueError()
            except ValueError as exc:
                raise APIError(
                    "validation_error", "El filtro de catálogo debe ser un ID positivo"
                ) from exc
            query = query.where(getattr(Ticket, field) == value)
    if args.get("status"):
        states = ACTIVE if args["status"] == "active" else args["status"].split(",")
        if set(states) - set(STATUSES):
            raise APIError("validation_error", "Estado desconocido")
        query = query.where(Ticket.status.in_(states))
    if args.get("q"):
        if len(args["q"]) > 160:
            raise APIError("validation_error", "La búsqueda admite hasta 160 caracteres")
        term = "%" + args["q"].replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.where(
            (Ticket.code.like(term, escape="\\")) | (Ticket.description.like(term, escape="\\"))
        )
    if args.get("from"):
        query = query.where(Ticket.created_at >= period(args["from"]))
    if args.get("to"):
        query = query.where(Ticket.created_at < period(args["to"], True))
    if args.get("from") and args.get("to") and args["from"] > args["to"]:
        raise APIError("validation_error", "El inicio del período debe preceder al final")
    return query


def paginate(query, serializer):
    try:
        page, per_page = int(request.args.get("page", 1)), int(request.args.get("per_page", 30))
        if page < 1 or not 1 <= per_page <= 100:
            raise ValueError()
    except ValueError as exc:
        raise APIError(
            "validation_error", "page debe ser positivo y per_page estar entre 1 y 100"
        ) from exc
    pagination = db.paginate(query, page=page, per_page=per_page, error_out=False)
    return {
        "items": [serializer(item) for item in pagination.items],
        "page": page,
        "per_page": per_page,
        "total": pagination.total,
        "pages": pagination.pages,
    }
