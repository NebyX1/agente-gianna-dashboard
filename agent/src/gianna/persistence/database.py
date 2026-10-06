import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
import threading
from datetime import UTC, datetime


def utc():
    return datetime.now(UTC).isoformat()


class Database:
    """Single bounded local WAL writer, short synchronous transactions under owner lock.

    No network/native awaits occur inside an ownership + durable reservation boundary.
    """

    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, isolation_level=None, check_same_thread=True)
        self.connection.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
        INSERT OR IGNORE INTO schema_version VALUES(1);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, session_id TEXT NOT NULL,
          generation_id TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL, at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY, actor_id INTEGER NOT NULL,
          data TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS operations(operation_id TEXT PRIMARY KEY, actor_id INTEGER NOT NULL,
          session_id TEXT NOT NULL, client_id TEXT NOT NULL, profile_id TEXT NOT NULL,
          profile_version TEXT NOT NULL, tool TEXT NOT NULL, resource TEXT NOT NULL,
          draft_id TEXT NOT NULL, revision INTEGER NOT NULL, confirmation_id TEXT NOT NULL,
          payload TEXT NOT NULL, payload_hash TEXT NOT NULL, idempotency_key TEXT UNIQUE NOT NULL,
          expected_version INTEGER, status TEXT NOT NULL, receipt TEXT, evidence TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, spoken_ack INTEGER NOT NULL DEFAULT 0);
        """)
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(operations)")}
        if "tool_call_id" not in columns:
            self.connection.execute("ALTER TABLE operations ADD COLUMN tool_call_id TEXT")
            self.connection.execute(
                "UPDATE operations SET tool_call_id=operation_id WHERE tool_call_id IS NULL"
            )
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS pending_revocations(credential_ref TEXT PRIMARY KEY, at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS preferences(actor_id INTEGER PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS operation_authorizations(id TEXT PRIMARY KEY, operation_id TEXT NOT NULL,
          session_id TEXT NOT NULL, actor_id INTEGER NOT NULL, confirmation_id TEXT NOT NULL,
          payload_hash TEXT NOT NULL, at TEXT NOT NULL);
        INSERT OR IGNORE INTO schema_version VALUES(2);
        """)
        event_columns = {r[1] for r in self.connection.execute("PRAGMA table_info(events)")}
        for name in ("event_id", "turn_id"):
            if name not in event_columns:
                self.connection.execute(f"ALTER TABLE events ADD COLUMN {name} TEXT")
        self.connection.execute("INSERT OR IGNORE INTO schema_version VALUES(3)")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS conversation_resets(actor_id INTEGER PRIMARY KEY, at TEXT NOT NULL)"
        )
        if "actor_id" not in event_columns:
            with self.transaction() as c:
                c.execute("ALTER TABLE events ADD COLUMN actor_id INTEGER")
                actors = {}
                for row in c.execute(
                    "SELECT id,session_id,kind,data FROM events ORDER BY id"
                ).fetchall():
                    if row["kind"] == "state":
                        user = json.loads(row["data"]).get("user")
                        actors[row["session_id"]] = user.get("id") if user else None
                    actor = actors.get(row["session_id"])
                    if actor is not None:
                        c.execute("UPDATE events SET actor_id=? WHERE id=?", (actor, row["id"]))
                c.execute("INSERT OR IGNORE INTO schema_version VALUES(4)")

    @contextmanager
    def transaction(self):
        with self.lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                yield self.connection
                self.connection.execute("COMMIT")
            except BaseException:
                self.connection.execute("ROLLBACK")
                raise

    def event(self, session, generation, kind, data, turn_id=None, actor_id=None):
        # Credentials/audio are never event payloads.
        from uuid import uuid4

        event_id = str(uuid4())
        with self.transaction() as c:
            c.execute(
                "INSERT INTO events(session_id,generation_id,kind,data,at,event_id,turn_id,actor_id) VALUES(?,?,?,?,?,?,?,?)",
                (
                    session,
                    generation,
                    kind,
                    json.dumps(data, ensure_ascii=False),
                    utc(),
                    event_id,
                    turn_id,
                    actor_id,
                ),
            )
        return event_id

    def clear_conversation(self, actor, session):
        """Remove local conversation content; durable business operations stay intact."""
        with self.transaction() as c:
            if actor is None:
                c.execute("DELETE FROM events WHERE actor_id IS NULL AND session_id=?", (session,))
                return
            pending = c.execute(
                "SELECT 1 FROM operations WHERE actor_id=? AND status IN ('prepared','dispatched','outcome_unknown')",
                (actor,),
            ).fetchone()
            if pending:
                raise ValueError(
                    "Primero hay que comprobar el resultado de la operación pendiente."
                )
            c.execute("DELETE FROM events WHERE actor_id=?", (actor,))
            c.execute("INSERT OR REPLACE INTO conversation_resets VALUES(?,?)", (actor, utc()))
            c.execute(
                "DELETE FROM drafts WHERE actor_id=? "
                "AND json_extract(data,'$.transferred')=0 AND json_extract(data,'$.owner')!='human'",
                (actor,),
            )

    def conversation_start(self, actor):
        row = self.connection.execute(
            "SELECT at FROM conversation_resets WHERE actor_id=?", (actor,)
        ).fetchone()
        return row[0] if row else ""

    def conversation_messages(self, actor, session):
        """Bounded real history; only completed tool exchanges enter model context."""
        rows = self.connection.execute(
            "SELECT kind,data FROM events WHERE actor_id=? AND session_id=? AND kind IN ('transcript','speech','agent_exchange') ORDER BY id DESC LIMIT 72",
            (actor, session),
        ).fetchall()
        messages, budget, included_speech = [], 48000, set()
        for row in rows:
            data = json.loads(row["data"])
            if row["kind"] == "agent_exchange":
                chunk = data["messages"]
                if data.get("spoken_utterance_id"):
                    included_speech.add(data["spoken_utterance_id"])
            else:
                if row["kind"] == "speech" and data.get("utterance_id") in included_speech:
                    continue
                chunk = [
                    {
                        "role": "user" if row["kind"] == "transcript" else "assistant",
                        "content": data["text"],
                    }
                ]
            size = len(json.dumps(chunk, ensure_ascii=False))
            if size > budget:
                break
            messages[0:0] = chunk
            budget -= size
        return messages

    def save_draft(self, draft):
        from dataclasses import asdict

        with self.transaction() as c:
            c.execute(
                "INSERT OR REPLACE INTO drafts VALUES(?,?,?,?)",
                (draft.id, draft.actor_id, json.dumps(asdict(draft), ensure_ascii=False), utc()),
            )

    def load_drafts(self, actor):
        from gianna.dialogue.draft import Draft

        return [
            Draft(**json.loads(r[0]))
            for r in self.connection.execute(
                "SELECT data FROM drafts WHERE actor_id=? ORDER BY updated_at DESC", (actor,)
            )
        ]

    def operations(self, actor=None, nonterminal=False):
        sql, params = "SELECT * FROM operations WHERE 1=1", []
        if actor is not None:
            sql += " AND actor_id=?"
            params.append(actor)
        if nonterminal:
            sql += " AND status IN ('prepared','dispatched','outcome_unknown')"
        return [dict(r) for r in self.connection.execute(sql, params)]

    def preferences(self, actor):
        from gianna.profiles.loader import load_preferences

        row = self.connection.execute(
            "SELECT data FROM preferences WHERE actor_id=?", (actor,)
        ).fetchone()
        return json.loads(row[0]) if row else load_preferences()

    def save_preferences(self, actor, data):
        from gianna.config import ROOT
        from jsonschema import Draft202012Validator

        schema = json.loads((ROOT / "schemas/user-preferences.schema.json").read_text())
        Draft202012Validator(schema).validate(data)
        with self.transaction() as c:
            c.execute("INSERT OR REPLACE INTO preferences VALUES(?,?)", (actor, json.dumps(data)))

    def prune(self):
        # Keep unresolved intent and minimal receipt/identity indefinitely. Content is time bounded.
        from datetime import timedelta

        now = datetime.now(UTC)
        recent = (now - timedelta(days=7)).isoformat()
        old = (now - timedelta(days=30)).isoformat()
        with self.transaction() as c:
            c.execute("DELETE FROM events WHERE at < ?", (recent,))
            c.execute(
                "DELETE FROM drafts WHERE updated_at < ? AND id NOT IN (SELECT draft_id FROM operations WHERE status IN ('prepared','dispatched','outcome_unknown'))",
                (old,),
            )
            c.execute(
                "UPDATE operations SET payload='{}',evidence=NULL WHERE updated_at < ? AND status IN ('succeeded','failed_known','cancelled_before_dispatch')",
                (old,),
            )

    def close(self):
        self.connection.close()
