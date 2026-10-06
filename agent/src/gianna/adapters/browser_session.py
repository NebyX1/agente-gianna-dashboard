import asyncio
from urllib.parse import urlsplit
from gianna.adapters.credentials import Credentials
from gianna.adapters.tickets_http import TicketError


class BrowserSessionBroker:
    """Observe only installed ticket auth contract in OWN managed browser, never storage."""

    def __init__(self, config, adapter, on_authenticated, on_invalidated, database=None):
        self.config, self.adapter = config, adapter
        self.on_authenticated, self.on_invalidated = on_authenticated, on_invalidated
        self.credentials = Credentials()
        self.tasks = set()
        self.lock = asyncio.Lock()
        self.last_token = None
        self.epoch = 0
        self.ref = None
        self.db = database

    def bind(self, page):
        def own_ticket_page():
            u = urlsplit(page.url)
            return f"{u.scheme}://{u.netloc}" == self.config.tickets_web

        def schedule(coro):
            task = asyncio.create_task(coro)
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

        page.on(
            "response",
            lambda response: schedule(self.response(response)) if own_ticket_page() else None,
        )

        def on_request(request):
            if not own_ticket_page():
                return
            if self.is_auth_url(request.url, "/api/v1/auth/logout") or self.is_auth_url(
                request.url, "/api/v1/auth/login"
            ):
                # Block ownership synchronously at the network event boundary, before any next await.
                self.epoch += 1
                self.adapter.token, old_token = None, self.adapter.token
                self.last_token = None
                schedule(self.invalidate(old_token))
            else:
                schedule(self.request(request))

        page.on("request", on_request)

    async def invalidate(self, old_token):
        await self.on_invalidated()
        ref, self.ref = self.ref, None
        if old_token:
            try:
                await self.revoke(old_token)
                if ref:
                    self.credentials.delete(ref)
            except Exception:
                # Revocation is retried while local writes remain blocked.
                self.pending_revocation = old_token
                if ref and self.credentials.secure and self.db:
                    with self.db.transaction() as c:
                        c.execute(
                            "INSERT OR IGNORE INTO pending_revocations VALUES(?,datetime('now'))",
                            (ref,),
                        )

    async def retry_revocations(self):
        refs = (
            list(self.db.connection.execute("SELECT credential_ref FROM pending_revocations"))
            if self.db
            else []
        )
        for (ref,) in refs:
            token = self.credentials.get(ref)
            if not token:
                raise RuntimeError("revocation_credential_unavailable")
            await self.revoke(token)
            self.credentials.delete(ref)
            with self.db.transaction() as c:
                c.execute("DELETE FROM pending_revocations WHERE credential_ref=?", (ref,))
        if getattr(self, "pending_revocation", None):
            await self.revoke(self.pending_revocation)
            self.pending_revocation = None

    async def revoke(self, token):
        try:
            await self.adapter.request("POST", "/api/v1/auth/logout", token=token)
        except TicketError as exc:
            # The authorized endpoint rejects an already expired/revoked credential with 401.
            if exc.status != 401:
                raise

    def is_auth_url(self, url, path):
        u = urlsplit(url)
        return f"{u.scheme}://{u.netloc}" == self.config.tickets_api and u.path == path

    async def request(self, request):
        if self.is_auth_url(request.url, "/api/v1/auth/me"):
            headers = await request.all_headers()
            auth = headers.get("authorization", "")
            if auth.startswith("Bearer "):
                await self.accept(auth[7:])

    async def response(self, response):
        if self.is_auth_url(response.url, "/api/v1/auth/verify-2fa") and response.status == 200:
            body = await response.json()
            if body.get("ok") is True:
                await self.accept(body["data"]["access_token"])

    async def accept(self, token):
        async with self.lock:
            if self.last_token == token:
                return
            epoch = self.epoch
            try:
                await self.retry_revocations()
                user = await self.adapter.delegate(token)
                if epoch != self.epoch:
                    await self.adapter.close()
                    return
                self.last_token = token
                self.ref = self.credentials.put(user["id"], self.adapter.token)
                await self.on_authenticated(user)
            except Exception:
                await self.on_invalidated()

    async def close(self):
        self.epoch += 1
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        token, self.adapter.token = self.adapter.token, None
        self.last_token = None
        await self.invalidate(token)
