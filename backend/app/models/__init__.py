from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.types import TypeDecorator

from app.extensions import db


def now():
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """MariaDB DATETIME(6): UTC at rest, always aware at the Python boundary."""

    impl = sa.DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(
            DATETIME(fsp=6) if dialect.name in {"mysql", "mariadb"} else sa.DateTime()
        )

    def process_bind_param(self, value, dialect):
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("Datetime requiere zona horaria")
            return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=UTC) if value is not None else None


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.Enum("admin", "operator", "viewer", name="role"), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    auth_version = db.Column(db.Integer, nullable=False, default=1)
    challenge_nonce = db.Column(db.String(36))
    last_otp_sent_at = db.Column(UTCDateTime())


class OrgUnit(db.Model):
    __tablename__ = "org_units"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True, nullable=False)
    name = db.Column(db.String(160), nullable=False)
    kind = db.Column(db.Enum("area", "office", "municipality", name="unit_kind"), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    can_receive_tickets = db.Column(db.Boolean, nullable=False, default=False)
    parent_id = db.Column(db.Integer, db.ForeignKey("org_units.id"))


class ProblemType(db.Model):
    __tablename__ = "problem_types"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True, nullable=False)
    name = db.Column(db.String(160), nullable=False)
    description = db.Column(db.String(400))
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class Ticket(db.Model):
    __tablename__ = "tickets"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    code = db.Column(db.String(64), unique=True)
    origin_unit_id = db.Column(
        db.Integer, db.ForeignKey("org_units.id"), nullable=False, index=True
    )
    destination_unit_id = db.Column(
        db.Integer, db.ForeignKey("org_units.id"), nullable=False, index=True
    )
    problem_type_id = db.Column(
        db.Integer, db.ForeignKey("problem_types.id"), nullable=False, index=True
    )
    description = db.Column(db.Text, nullable=False)
    status = db.Column(
        db.Enum("new", "in_progress", "waiting", "resolved", "cancelled", name="ticket_status"),
        nullable=False,
        default="new",
    )
    created_at = db.Column(UTCDateTime(), default=now, nullable=False, index=True)
    updated_at = db.Column(UTCDateTime(), default=now, nullable=False)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    version = db.Column(db.Integer, default=1, nullable=False)
    first_response_at = db.Column(UTCDateTime())
    resolved_at = db.Column(UTCDateTime())
    cancelled_at = db.Column(UTCDateTime())
    occurred_at = db.Column(UTCDateTime())
    archived_at = db.Column(UTCDateTime())
    archived_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    archive_reason = db.Column(db.String(1000))
    origin = db.relationship(OrgUnit, foreign_keys=[origin_unit_id], lazy="joined")
    destination = db.relationship(OrgUnit, foreign_keys=[destination_unit_id], lazy="joined")
    problem_type = db.relationship(ProblemType, lazy="joined")
    __mapper_args__ = {"version_id_col": version}
    __table_args__ = (
        db.Index("ix_tickets_operational", "archived_at", "status", "created_at", "id"),
    )


class TicketEvent(db.Model):
    __tablename__ = "ticket_events"
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False, index=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    event_type = db.Column(db.String(32), nullable=False)
    timestamp = db.Column(UTCDateTime(), default=now, nullable=False)
    request_id = db.Column(db.String(64), nullable=False)
    channel = db.Column(db.String(32), nullable=False, default="manual_ui")
    before = db.Column(db.JSON)
    after = db.Column(db.JSON, nullable=False)
    note = db.Column(db.String(1000))
    actor_name = db.Column(db.String(120), nullable=False)


class Challenge(db.Model):
    __tablename__ = "challenges"
    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    code_hash = db.Column(db.String(255), nullable=False)
    expires_at = db.Column(UTCDateTime(), nullable=False)
    consumed_at = db.Column(UTCDateTime())
    attempts = db.Column(db.Integer, default=0, nullable=False)


class AuthSession(db.Model):
    __tablename__ = "auth_sessions"
    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    auth_version = db.Column(db.Integer, nullable=False)
    expires_at = db.Column(UTCDateTime(), nullable=False)
    revoked_at = db.Column(UTCDateTime())
    parent_session_id = db.Column(db.String(36), db.ForeignKey("auth_sessions.id"), index=True)
    client_id = db.Column(db.String(32), nullable=False, default="manual-ui", server_default="manual-ui")


class AgentOperation(db.Model):
    """Identity and minimal receipt live as long as ticket history, independently of JWT/cache."""
    __tablename__ = "agent_operations"
    id = db.Column(db.Integer, primary_key=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    client_id = db.Column(db.String(32), nullable=False)
    operation_id = db.Column(db.String(64), nullable=False)
    key = db.Column(db.String(64), nullable=False)
    tool = db.Column(db.String(48), nullable=False)
    resource = db.Column(db.String(64), nullable=False)
    payload_hash = db.Column(db.String(64), nullable=False)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"))
    receipt = db.Column(db.JSON)
    status_code = db.Column(db.Integer, nullable=False)
    created_at = db.Column(UTCDateTime(), default=now, nullable=False)
    __table_args__ = (
        db.UniqueConstraint("actor_user_id", "client_id", "operation_id", name="uq_agent_operation"),
        db.UniqueConstraint("actor_user_id", "client_id", "key", name="uq_agent_key"),
    )


class AgentOperationEvent(db.Model):
    __tablename__ = "agent_operation_events"
    operation_id = db.Column(db.Integer, db.ForeignKey("agent_operations.id"), primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("ticket_events.id"), primary_key=True)


class Idempotency(db.Model):
    __tablename__ = "idempotency"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    scope = db.Column(db.String(100), nullable=False)
    key = db.Column(db.String(64), nullable=False)
    payload_hash = db.Column(db.String(64), nullable=False)
    result = db.Column(db.JSON)
    status_code = db.Column(db.Integer, nullable=False)
    created_at = db.Column(UTCDateTime(), default=now, nullable=False, index=True)
    __table_args__ = (db.UniqueConstraint("user_id", "scope", "key", name="uq_idempotency_scope"),)
