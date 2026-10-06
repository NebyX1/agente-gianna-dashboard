from dataclasses import dataclass, field
from uuid import uuid4
import hashlib
import json


def payload_hash(payload):
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass
class Draft:
    actor_id: int
    id: str = field(default_factory=lambda: str(uuid4()))
    revision: int = 0
    tool: str = "tickets.create.v1"
    resource: str = "tickets"
    payload: dict = field(default_factory=dict)
    owner: str = "agent"
    transferred: bool = False
    display_code: str | None = None

    def change(self, **values):
        if self.owner != "agent" or self.transferred:
            raise RuntimeError("Draft transferred to human")
        self.payload.update(values)
        self.revision += 1

    @property
    def digest(self):
        return payload_hash(self.payload)
