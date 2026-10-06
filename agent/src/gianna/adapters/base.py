from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    name: str
    version: str
    available: bool
    reason: str = ""


class ExecutorAdapter(ABC):
    @abstractmethod
    def discover(self) -> list[Capability]: ...
    @abstractmethod
    async def health(self) -> dict: ...
    @abstractmethod
    async def observe(self, resource: str) -> dict: ...
    @abstractmethod
    async def prepare(self, request: dict) -> dict: ...
    @abstractmethod
    async def execute(self, request: dict) -> dict: ...
    @abstractmethod
    async def verify(self, evidence: dict) -> dict: ...
    @abstractmethod
    async def cancel(self, operation_id: str) -> dict: ...
    @abstractmethod
    async def close(self): ...


class CapabilityProvider(ABC):
    @abstractmethod
    def capabilities(self) -> list[Capability]: ...


UNAVAILABLE = [
    Capability(n, "1", False, "Adaptador no instalado")
    for n in ("desktop", "files", "processes", "mcp")
]
