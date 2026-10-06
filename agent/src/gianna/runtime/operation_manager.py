import asyncio
import json
from uuid import uuid4
from gianna.persistence.database import utc
from gianna.adapters.tickets_http import TicketError
import httpx


class OperationManager:
    def __init__(self, database, adapter, config, clock):
        self.db, self.adapter, self.config, self.clock = database, adapter, config, clock
        self.ownership = asyncio.Lock()
        self.pending = None

    def prepare(self, session, draft, confirmation, profile):
        import re

        if (draft.tool == "tickets.create.v1" and draft.resource != "tickets") or (
            draft.tool != "tickets.create.v1"
            and not re.fullmatch(r"tickets/[1-9][0-9]*", draft.resource)
        ):
            raise RuntimeError("resource_identity_invalid")
        if hasattr(self, "registry"):
            tool = self.registry.validate(draft.tool, draft.payload)
            if self.adapter.user["role"] not in tool.roles or draft.tool not in profile["tools"]:
                raise RuntimeError("permission_denied")
        if not confirmation.valid(draft, draft.actor_id, self.clock, session):
            raise RuntimeError("confirmation_invalid")
        if self.db.operations(draft.actor_id, nonterminal=True):
            raise RuntimeError("reconciliation_required")
        op_id, key = str(uuid4()), str(uuid4())
        row = dict(
            operation_id=op_id,
            actor_id=draft.actor_id,
            session_id=session,
            tool_call_id=str(uuid4()),
            client_id="gianna-agent",
            profile_id=profile["profile_id"],
            profile_version=profile["version"],
            tool=draft.tool,
            resource=draft.resource,
            draft_id=draft.id,
            revision=draft.revision,
            confirmation_id=confirmation.id,
            payload=json.dumps(draft.payload, ensure_ascii=False),
            payload_hash=draft.digest,
            idempotency_key=key,
            expected_version=draft.payload.get("version"),
            status="prepared",
            created_at=utc(),
            updated_at=utc(),
        )
        with self.db.transaction() as c:
            names = list(row)
            c.execute(
                f"INSERT INTO operations({','.join(names)}) VALUES({','.join('?' for _ in names)})",
                list(row.values()),
            )
        self.pending = op_id
        return row

    def set_status(self, op_id, status, *, receipt=None, evidence=None):
        with self.db.transaction() as c:
            c.execute(
                "UPDATE operations SET status=?,receipt=COALESCE(?,receipt),evidence=?,updated_at=? WHERE operation_id=? AND (status!='succeeded' OR ?='succeeded')",
                (
                    status,
                    json.dumps(receipt) if receipt else None,
                    json.dumps(evidence),
                    utc(),
                    op_id,
                    status,
                ),
            )

    async def dispatch(self, row, draft, confirmation, valid_owner):
        await self.adapter.revalidate(row["actor_id"])
        async with self.ownership:
            # NO await between final ownership/confirmation validation and durable reservation.
            current = next(
                r for r in self.db.operations() if r["operation_id"] == row["operation_id"]
            )
            if hasattr(self, "registry"):
                tool = self.registry.validate(row["tool"], json.loads(row["payload"]))
                if self.adapter.user["role"] not in tool.roles:
                    raise RuntimeError("permission_denied")
            if current["status"] == "succeeded":
                return json.loads(current["receipt"])
            allowed = current["status"] == "prepared" or (
                row.get("reauthorized") and current["status"] == "outcome_unknown"
            )
            if (
                not allowed
                or not valid_owner()
                or not confirmation.valid(
                    draft,
                    row["actor_id"],
                    self.clock,
                    row.get("authorization_session_id", row["session_id"]),
                )
            ):
                if current["status"] == "prepared":
                    self.set_status(row["operation_id"], "cancelled_before_dispatch")
                raise RuntimeError("cancelled_before_dispatch")
            self.set_status(row["operation_id"], "dispatched")
            credential = getattr(self.adapter, "token", None)
        request = {**row, "payload": json.loads(row["payload"]), "credential": credential}
        # This owned task persists a late response even if its caller is cancelled.
        task = asyncio.create_task(self.execute_reserved(row, request))
        self.inflight = getattr(self, "inflight", set())
        self.inflight.add(task)
        task.add_done_callback(self.inflight.discard)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # Shielded HTTP may complete; durable identity remains reconcilable, never auto-resend.
            self.set_status(row["operation_id"], "outcome_unknown")
            raise

    async def execute_reserved(self, row, request):
        try:
            result = await self.adapter.execute(request)
        except (httpx.HTTPError, ValueError) as exc:
            self.set_status(
                row["operation_id"], "outcome_unknown", evidence={"error": type(exc).__name__}
            )
            raise RuntimeError("outcome_unknown") from exc
        except TicketError as exc:
            # 5xx may have followed a commit (proxy/backend failure); treat as unknown.
            status = "outcome_unknown" if exc.status >= 500 else "failed_known"
            self.set_status(
                row["operation_id"],
                status,
                evidence={"code": exc.code, "request_id": exc.request_id},
            )
            raise
        if (
            result.get("operation_id") != row["operation_id"]
            or result.get("payload_hash") != row["payload_hash"]
            or not result.get("event_ids")
        ):
            self.set_status(row["operation_id"], "outcome_unknown")
            raise RuntimeError("invalid_receipt")
        if hasattr(self, "registry"):
            from jsonschema import Draft202012Validator

            schema = self.registry.tools[row["tool"]].output_schema
            try:
                Draft202012Validator(schema).validate(result)
            except Exception as exc:
                self.set_status(row["operation_id"], "outcome_unknown")
                raise RuntimeError("invalid_receipt_schema") from exc
        self.set_status(row["operation_id"], "succeeded", receipt=result)
        return result

    async def close(self):
        await asyncio.gather(*getattr(self, "inflight", set()), return_exceptions=True)

    def prepare_retry(self, session, row, draft, confirmation):
        if (
            row["status"] != "outcome_unknown"
            or row["payload_hash"] != draft.digest
            or row["actor_id"] != draft.actor_id
            or row["tool"] != draft.tool
            or row["resource"] != draft.resource
        ):
            raise RuntimeError("retry_identity_mismatch")
        if not confirmation.valid(draft, draft.actor_id, self.clock, session):
            raise RuntimeError("confirmation_invalid")
        with self.db.transaction() as c:
            c.execute(
                "INSERT INTO operation_authorizations VALUES(?,?,?,?,?,?,?)",
                (
                    str(uuid4()),
                    row["operation_id"],
                    session,
                    draft.actor_id,
                    confirmation.id,
                    draft.digest,
                    utc(),
                ),
            )
        # Unknown stays unknown until the FINAL ownership + reservation boundary.
        return {**row, "reauthorized": True, "authorization_session_id": session}

    async def recover(self, actor):
        results = []
        for row in self.db.operations(actor, nonterminal=True):
            if row["status"] == "prepared":
                self.set_status(
                    row["operation_id"],
                    "cancelled_before_dispatch",
                    evidence={"reason": "restart_or_expired_confirmation"},
                )
                results.append(
                    {"operation_id": row["operation_id"], "status": "cancelled_before_dispatch"}
                )
                continue
            try:
                receipt = await self.adapter.verify(row)
                if (
                    receipt.get("payload_hash") != row["payload_hash"]
                    or receipt.get("operation_id") != row["operation_id"]
                    or not receipt.get("event_ids")
                ):
                    raise RuntimeError("receipt_identity_mismatch")
                self.set_status(row["operation_id"], "succeeded", receipt=receipt)
                results.append(receipt)
            except (TicketError, httpx.HTTPError, ValueError, KeyError, RuntimeError):
                # 404 is NOT proof of no effect; the first transaction could still be running.
                self.set_status(row["operation_id"], "outcome_unknown")
                results.append({"operation_id": row["operation_id"], "status": "outcome_unknown"})
        return results

    async def handoff(self, draft):
        async with self.ownership:
            pending = [r for r in self.db.operations(draft.actor_id) if r["draft_id"] == draft.id]
            if any(r["status"] in {"dispatched", "outcome_unknown"} for r in pending):
                raise RuntimeError("handoff_requires_reconciliation")
            committed = next((r for r in pending if r["status"] == "succeeded"), None)
            if committed:
                return {"committed": json.loads(committed["receipt"])}
            for row in pending:
                if row["status"] == "prepared":
                    self.set_status(row["operation_id"], "cancelled_before_dispatch")
            draft.owner = "human"
            draft.transferred = True
            self.db.save_draft(
                draft
            )  # Ownership transfer survives crash before opening manual form.
            return {"transferred": True}
