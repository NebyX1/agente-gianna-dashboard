import asyncio
from urllib.parse import urlsplit
from gianna.adapters.base import ExecutorAdapter, Capability


class BrowserContractError(RuntimeError):
    pass


class PlaywrightBrowser(ExecutorAdapter):
    def __init__(self, config, profile, pairing_cookie):
        self.config, self.profile, self.cookie = config, profile, pairing_cookie
        self.lock = asyncio.Lock()
        self.context = self.page = self.playwright = None
        self.human_control = False
        self.broker = None

    async def start(self, broker, *, visible=True, audio_fixture=None):
        import os
        from playwright.async_api import async_playwright

        root = self.config.data_dir / "browser"
        root.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            root.chmod(0o700)
        else:
            # Restrict inherited desktop profile ACL to the current Windows user.
            import subprocess

            user = os.environ["USERNAME"]
            subprocess.run(
                ["icacls", str(root), "/inheritance:r", "/grant:r", f"{user}:(OI)(CI)F"],
                check=True,
                capture_output=True,
            )
        self.playwright = await async_playwright().start()
        # Exercise the same browser audio policy as a normal user window.
        args = ["--start-maximized"] if visible else []
        if audio_fixture:
            if not audio_fixture.is_file() or audio_fixture.suffix != ".wav":
                raise ValueError("Test audio fixture must be a local WAV")
            args += [
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
                f"--use-file-for-fake-audio-capture={audio_fixture}%noloop",
            ]
        self.context = await self.playwright.chromium.launch_persistent_context(
            str(root),
            headless=not visible,
            args=args,
            # A visible window must follow its native size, including every new
            # ticket/console/display tab. Keep deterministic sizing only in headless tests.
            no_viewport=visible,
            viewport=None if visible else {"width": 1280, "height": 860},
        )
        await self.context.add_cookies(
            [
                {
                    "name": "gianna_pairing",
                    "value": self.cookie,
                    "url": self.config.console_origin,
                    "httpOnly": True,
                    "sameSite": "Strict",
                }
            ]
        )
        self.broker = broker
        self.context.on("page", broker.bind)
        for page in self.context.pages:
            broker.bind(page)
        self.page = await self.context.new_page()
        await self.page.goto(self.config.tickets_web + "/tickets")
        console = await self.context.new_page()
        await console.goto(self.config.console_origin)
        await console.bring_to_front()

    def discover(self):
        return [Capability("playwright_browser_v1", "1", bool(self.page))]

    async def health(self):
        return {
            "available": bool(self.page and not self.page.is_closed()),
            "managed": True,
            "browser": self.context.browser.version if self.context else None,
        }

    def check_origin(self):
        if not self.page or self.human_control:
            raise BrowserContractError("human_control_or_browser_closed")
        u = urlsplit(self.page.url)
        if f"{u.scheme}://{u.netloc}" != self.config.tickets_web:
            raise BrowserContractError("unexpected_page_origin")

    async def unique(self, locator):
        await locator.first.wait_for(state="visible", timeout=10000)
        if await locator.count() != 1 or not await locator.is_visible():
            raise BrowserContractError("locator_not_unique_visible")
        return locator

    def locator(self, name, scope=None):
        spec = self.profile["locators_data"][name]
        scope = scope or self.page
        if "test_id" in spec:
            return scope.get_by_test_id(spec["test_id"])
        if "label" in spec:
            return scope.get_by_label(spec["label"], exact=True)
        return scope.get_by_role(spec["role"], name=spec["name"], exact=True)

    async def observe(self, resource="tickets"):
        async with self.lock:
            self.check_origin()
            return {"url": self.page.url, "title": await self.page.title()}

    async def show(self, ticket_id=None, query=None):
        async with self.lock:
            if not self.page or self.page.is_closed():
                raise BrowserContractError("browser_closed")
            if self.human_control:
                raise BrowserContractError("human_control")
            self.check_origin()
            url = self.config.tickets_web + (
                f"/tickets/{int(ticket_id)}" if ticket_id else "/tickets"
            )
            if query:
                # Existing board search is driven via the semantic control, not an undocumented query.
                await self.page.goto(url)
                search = await self.unique(self.locator("search"))
                await search.fill(query)
            else:
                await self.page.goto(url)
            await self.page.bring_to_front()
            self.check_origin()
            if ticket_id:
                marker = await self.unique(self.locator("detail"))
                if await marker.get_attribute("data-ticket-id") != str(ticket_id):
                    raise BrowserContractError("ticket_identity_mismatch")
                code = await marker.get_attribute("data-ticket-code")
                await self.unique(self.page.get_by_role("heading", name=code, exact=True))
            else:
                await self.unique(self.locator("board"))
            return {"url": self.page.url, "shown": True}

    async def prepare(self, request):
        draft = request["draft"]
        return await self.form(draft, preview=True)

    async def form(self, draft, *, preview):
        async with self.lock:
            if not self.page or self.page.is_closed():
                raise BrowserContractError("browser_closed")
            if self.human_control and preview:
                raise BrowserContractError("human_control")
            if (
                urlsplit(self.page.url).netloc != urlsplit(self.config.tickets_web).netloc
                or urlsplit(self.page.url).scheme != urlsplit(self.config.tickets_web).scheme
            ):
                raise BrowserContractError("unexpected_page_origin")
            await self.page.goto(
                self.config.tickets_web + ("/gianna/preview" if preview else "/gianna/manual")
            )
            marker = (
                self.locator("preview") if preview else self.page.get_by_test_id("gianna-manual")
            )
            await marker.wait_for(state="visible")
            if await marker.get_attribute("data-actor-id") != str(draft.actor_id):
                raise BrowserContractError("actor_mismatch")
            packet = {
                "contract": "idl.gianna.form.v1",
                "draft_id": draft.id,
                "revision": draft.revision,
                "actor_id": draft.actor_id,
                "payload": draft.payload,
            }
            # Calls the installed app's data contract; never injects submit-blocking or UI logic.
            await self.page.evaluate(
                "packet => window.postMessage(packet, window.location.origin)", packet
            )
            form = self.locator("form")
            await form.wait_for(state="visible")
            # The form's catalogue query and React field registration can finish
            # after its container mounts. Wait for each actual labelled control.
            if await marker.get_attribute("data-draft-id") != draft.id:
                raise BrowserContractError("draft_mismatch")
            fields = {
                "origin_unit_id": "origin",
                "destination_unit_id": "destination",
                "problem_type_id": "type",
                "description": "description",
            }
            for key, name in fields.items():
                locator = await self.unique(self.locator(name, form))
                if key in draft.payload and await locator.input_value() != str(draft.payload[key]):
                    raise BrowserContractError("field_verification_failed")
                if preview and not await locator.is_disabled():
                    raise BrowserContractError("preview_is_editable")
            if preview and not await self.locator("submit", form).is_disabled():
                raise BrowserContractError("preview_submit_enabled")
            await self.page.bring_to_front()
            return {
                "draft_id": draft.id,
                "revision": draft.revision,
                "preview": preview,
                "verified": True,
            }

    async def execute(self, request):
        command = request["command"]
        if command in {"open", "show"}:
            return await self.show(request.get("ticket_id"))
        if command == "filter":
            return await self.show(query=request["query"])
        if command == "prepare":
            return await self.prepare(request)
        raise BrowserContractError("unsupported_browser_command")

    async def verify(self, evidence):
        # Surface evidence never substitutes a server commit receipt.
        return {"surface": await self.observe(), "commit_verified": False}

    async def cancel(self, operation_id):
        return {"cancelled": True, "operation_id": operation_id}

    async def handoff(self, draft):
        # Discard the immutable preview and construct a NEW manual form.
        result = await self.form(draft, preview=False)
        self.human_control = True
        return result

    async def close(self):
        if self.context:
            await self.context.close()  # Only this managed browser's own process tree.
            self.context = self.page = None
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None
