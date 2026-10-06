from dataclasses import dataclass
from typing import Literal, Callable


@dataclass(frozen=True)
class Tool:
    name: str
    schema: dict
    description: str
    capability: str
    roles: tuple[str, ...]
    states: tuple[str, ...]
    effect: Literal["read", "local_draft", "remote_write"]
    confirmation: str
    deadline: float
    retries: int
    cancel: str
    evidence: str
    handler: Callable
    version: str = "1"
    output_schema: dict | None = None
    examples: tuple[str, ...] = ()
    resource_lock: str = "session"
    errors: tuple[str, ...] = ("validation_error", "permission_denied", "deadline_exceeded")
