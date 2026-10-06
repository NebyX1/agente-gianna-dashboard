from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True)
class Confirmation:
    id: str
    actor_id: int
    draft_id: str
    revision: int
    tool: str
    resource: str
    digest: str
    expires: float
    session_id: str = ""

    @classmethod
    def issue(cls, draft, clock, lifetime, session_id=""):
        return cls(
            str(uuid4()),
            draft.actor_id,
            draft.id,
            draft.revision,
            draft.tool,
            draft.resource,
            draft.digest,
            clock() + lifetime,
            session_id,
        )

    def valid(self, draft, actor_id, clock, session_id=None):
        return (
            self.expires > clock()
            and (session_id is None or session_id == self.session_id)
            and actor_id == self.actor_id
            and draft.owner == "agent"
            and not draft.transferred
            and (self.draft_id, self.revision, self.tool, self.resource, self.digest)
            == (draft.id, draft.revision, draft.tool, draft.resource, draft.digest)
        )
