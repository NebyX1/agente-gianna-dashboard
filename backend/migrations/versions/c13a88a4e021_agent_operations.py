"""Delegated sessions and durable agent receipts (no expiry/cleanup of operation identities)."""
import sqlalchemy as sa
from alembic import op

from app.models import UTCDateTime

revision = "c13a88a4e021"
down_revision = "b02f44c77b22"
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table("auth_sessions") as batch:
        batch.add_column(sa.Column("parent_session_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("client_id", sa.String(32), server_default="manual-ui", nullable=False))
        batch.create_foreign_key("fk_auth_parent", "auth_sessions", ["parent_session_id"], ["id"])
        batch.create_index("ix_auth_sessions_parent_session_id", ["parent_session_id"])
    op.create_table("agent_operations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_id", sa.String(32), nullable=False),
        sa.Column("operation_id", sa.String(64), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("tool", sa.String(48), nullable=False),
        sa.Column("resource", sa.String(64), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id")),
        sa.Column("receipt", sa.JSON()), sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("actor_user_id", "client_id", "operation_id", name="uq_agent_operation"),
        sa.UniqueConstraint("actor_user_id", "client_id", "key", name="uq_agent_key"))
    op.create_table("agent_operation_events",
        sa.Column("operation_id", sa.Integer(), sa.ForeignKey("agent_operations.id"), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("ticket_events.id"), primary_key=True))


def downgrade():
    op.drop_table("agent_operation_events")
    op.drop_table("agent_operations")
    with op.batch_alter_table("auth_sessions") as batch:
        batch.drop_constraint("fk_auth_parent", type_="foreignkey")
        batch.drop_index("ix_auth_sessions_parent_session_id")
        batch.drop_column("parent_session_id")
        batch.drop_column("client_id")
