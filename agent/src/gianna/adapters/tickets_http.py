import httpx
import time
from gianna.adapters.base import ExecutorAdapter, Capability


class TicketError(Exception):
    def __init__(self, code, status, request_id=""):
        self.code, self.status, self.request_id = code, status, request_id
        super().__init__(code)


class TicketsHTTP(ExecutorAdapter):
    def __init__(self, config, client):
        self.config, self.client = config, client
        self.token = None
        self.user = None
        self.expires_at = None

    def discover(self):
        return [
            Capability(
                "idl_tickets_http_v1",
                "1",
                bool(self.token),
                "Iniciá sesión" if not self.token else "",
            )
        ]

    async def health(self):
        r = await self.client.get(self.config.tickets_api + "/readyz", timeout=5)
        r.raise_for_status()
        return r.json()

    async def request(self, method, path, *, payload=None, headers=None, query=None, token=None):
        if not path.startswith("/api/v1/"):
            raise ValueError("Ticket adapter path boundary")
        credential = token or self.token
        if not credential:
            raise TicketError("auth_required", 401)
        start = time.perf_counter()
        r = await self.client.request(
            method,
            self.config.tickets_api + path,
            json=payload,
            params=query,
            headers={"Authorization": "Bearer " + credential, **(headers or {})},
            timeout=15,
        )
        if hasattr(self, "metrics"):
            self.metrics.add("tickets_api", (time.perf_counter() - start) * 1000)
        body = r.json()
        if not r.is_success or body.get("ok") is not True:
            raise TicketError(
                body.get("error", {}).get("code", "api_error"),
                r.status_code,
                r.headers.get("X-Request-ID", ""),
            )
        return body["data"]

    async def delegate(self, parent_token):
        user = await self.request("GET", "/api/v1/auth/me", token=parent_token)
        if user.get("role") not in {"admin", "operator"} or not user.get("is_active"):
            raise TicketError("forbidden", 403)
        session = await self.request(
            "POST", "/api/v1/auth/agent-session", payload={}, token=parent_token
        )
        if (
            session["client_id"] != "gianna-agent"
            or session["scope"] != ["tickets"]
            or session["user"] != user
        ):
            raise TicketError("delegation_contract_changed", 409)
        child = session["access_token"]
        verified = await self.request("GET", "/api/v1/auth/me", token=child)
        if verified != user:
            raise TicketError("actor_changed", 409)
        self.token, self.user, self.expires_at = child, user, session["expires_at"]
        return user

    async def revalidate(self, actor_id):
        token, previous = self.token, self.user
        user = await self.request("GET", "/api/v1/auth/me", token=token)
        if token != self.token or user["id"] != actor_id or user != previous:
            if token == self.token:
                self.token = None
            raise TicketError("actor_changed", 401)
        return user

    async def observe(self, resource):
        return await self.request("GET", "/api/v1/" + resource)

    async def prepare(self, request):
        await self.revalidate(request["actor_id"])
        return {"prepared": True, "resource": request["resource"]}

    async def execute(self, request):
        routes = {
            "tickets.create.v1": ("POST", "/api/v1/tickets"),
            "tickets.update.v1": ("PATCH", "/api/v1/" + request["resource"]),
            "tickets.status.v1": ("PATCH", "/api/v1/" + request["resource"] + "/status"),
            "tickets.archive.v1": ("POST", "/api/v1/" + request["resource"] + "/archive"),
            "tickets.restore.v1": ("POST", "/api/v1/admin/" + request["resource"] + "/restore"),
        }
        method, path = routes[request["tool"]]
        return await self.request(
            method,
            path,
            payload=request["payload"],
            token=request.get("credential"),
            headers={
                "X-Agent-Operation-ID": request["operation_id"],
                "Idempotency-Key": request["idempotency_key"],
            },
        )

    async def verify(self, evidence):
        return await self.request("GET", "/api/v1/agent/operations/" + evidence["operation_id"])

    async def cancel(self, operation_id):
        return {
            "operation_id": operation_id,
            "remote_cancel_supported": False,
            "message": "Una solicitud enviada debe reconciliarse",
        }

    async def close(self):
        token, self.token = self.token, None
        self.user = None
        if token:
            try:
                await self.request("POST", "/api/v1/auth/logout", token=token)
            except (httpx.HTTPError, TicketError):
                return {"revocation_pending": True}
        return {"revocation_pending": False}
