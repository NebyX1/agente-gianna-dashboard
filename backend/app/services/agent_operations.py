import hashlib
import json
import re

from flask import g, request
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import AgentOperation, AgentOperationEvent, Ticket, TicketEvent
from app.utils.responses import APIError, iso


def delegated():
    return g.auth_session.client_id == "gianna-agent"


def execute(tool, resource, payload, operation, status=200):
    """Reserve both identities, mutate, link audit and persist receipt in ONE transaction."""
    op_id = request.headers.get("X-Agent-Operation-ID", "")
    key = request.headers.get("Idempotency-Key", "")
    if not all(re.fullmatch(r"[A-Za-z0-9_-]{16,64}", v) for v in (op_id, key)):
        raise APIError("validation_error", "Gianna requiere X-Agent-Operation-ID e Idempotency-Key")
    # Hash the validated wire payload, with canonical JSON ordering. Pydantic's
    # absent optional defaults must not alter the client's confirmation identity.
    digest = hashlib.sha256(json.dumps(request.get_json(), sort_keys=True, default=iso,
                         separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    query = select(AgentOperation).where(
        AgentOperation.actor_user_id == g.user.id, AgentOperation.client_id == "gianna-agent",
        or_(AgentOperation.operation_id == op_id, AgentOperation.key == key))

    def replay(records):
        if len(records) != 1 or any((r.operation_id, r.key, r.tool, r.resource, r.payload_hash)
                                  != (op_id, key, tool, resource, digest) for r in records):
            raise APIError("agent_operation_conflict", "La identidad ya está ligada a otra operación", 409)
        return records[0].receipt, records[0].status_code

    existing = db.session.scalars(query).all()
    if existing:
        return replay(existing)
    record = AgentOperation(actor_user_id=g.user.id, client_id="gianna-agent", operation_id=op_id,
        key=key, tool=tool, resource=resource, payload_hash=digest, status_code=status)
    db.session.add(record)
    try:
        db.session.flush()  # Unique constraints serialize concurrent requests across workers.
    except IntegrityError:
        db.session.rollback()
        existing = db.session.scalars(query).all()
        if not existing:
            raise
        return replay(existing)
    result = operation()
    ticket = db.session.get(Ticket, result.get("id", result.get("ticket_id")))
    events = db.session.scalars(select(TicketEvent).where(
        TicketEvent.ticket_id == ticket.id, TicketEvent.request_id == g.request_id,
        TicketEvent.actor_user_id == g.user.id)).all()
    if not events:
        raise RuntimeError("Agent write without audit event")
    record.ticket_id = ticket.id
    for event in events:
        db.session.add(AgentOperationEvent(operation_id=record.id, event_id=event.id))
    record.receipt = {
        "operation_id": op_id, "tool": tool, "payload_hash": digest, "ticket_id": ticket.id,
        "code": ticket.code, "version": ticket.version, "status": ticket.status,
        "event_ids": [e.id for e in events], "committed_at": iso(events[-1].timestamp),
        "server_request_id": g.request_id,
    }
    db.session.commit()
    return record.receipt, status


def receipt(op_id):
    # Minimal information only, even when an operator's ticket has since been archived.
    record = db.session.scalar(select(AgentOperation).where(
        AgentOperation.actor_user_id == g.user.id, AgentOperation.client_id == "gianna-agent",
        AgentOperation.operation_id == op_id))
    if not record or (record.tool == "tickets.restore.v1" and g.user.role != "admin"):
        raise APIError("not_found", "No hay recibo visible para esta operación", 404)
    return record.receipt
