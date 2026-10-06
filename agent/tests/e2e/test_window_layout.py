"""Check native Chromium resize rather than emulating another fixed viewport.

Requires the isolated design-check portal and the local console. No ticket or
conversation commands are submitted and no microphone connection is opened.
"""

import json
import os
from types import SimpleNamespace

import httpx
import pytest

from gianna.adapters.playwright_browser import PlaywrightBrowser
from gianna.config import ROOT
from tests.e2e.test_voice_flow import login_browser

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.getenv("GIANNA_WINDOW_E2E") != "1",
        reason="Explicit native window verification against isolated local portal",
    ),
]


async def test_all_managed_tabs_follow_native_window_width(tmp_path):
    config = SimpleNamespace(
        data_dir=tmp_path,
        tickets_web="http://localhost:5473",
        console_origin="http://127.0.0.1:7860",
    )
    broker = SimpleNamespace(bind=lambda page: None)
    browser = PlaywrightBrowser(config, {}, "layout-test-only")
    artifacts = ROOT.parent / "artifacts"
    evidence = {"resizes": [], "errors": []}
    try:
        await browser.start(broker, visible=True)
        page = browser.page
        page.on("pageerror", lambda error: evidence["errors"].append(str(error)))
        async with httpx.AsyncClient() as client:
            users = json.loads((artifacts / "design-check-users.json").read_text())
            await login_browser(page, client, users["admin"])
        await page.locator(".ticket-card").first.wait_for()
        console = next(p for p in browser.context.pages if p.url == config.console_origin + "/")
        await console.locator(".work-grid").wait_for()
        third = await browser.context.new_page()
        await third.goto(config.tickets_web + "/estadisticas")
        await third.locator(".metrics").wait_for()
        cdp = await browser.context.new_cdp_session(page)
        window = await cdp.send("Browser.getWindowForTarget")
        await cdp.send("Browser.setWindowBounds", {
            "windowId": window["windowId"], "bounds": {"windowState": "normal"}
        })
        for width in (1280, 1920, 1536):
            await cdp.send("Browser.setWindowBounds", {
                "windowId": window["windowId"],
                "bounds": {"width": width, "height": 1000, "left": 0, "top": 0},
            })
            for name, target in (("tickets", page), ("console", console), ("statistics", third)):
                assert target.viewport_size is None
                # Chromium defers laying out a background tab until it becomes visible.
                await target.bring_to_front()
                await target.wait_for_function(
                    "width => Math.abs(window.outerWidth - width) < 24 && Math.abs(window.innerWidth - width) < 40",
                    arg=width,
                )
                measurement = await target.evaluate("""() => {
                    const rect = e => {const r=e.getBoundingClientRect();return {left:r.left,right:r.right,width:r.width};};
                    return {innerWidth,outerWidth,clientWidth:document.documentElement.clientWidth,
                      root:rect(document.querySelector('#root')),main:rect(document.querySelector('main')),
                      scrollWidth:document.documentElement.scrollWidth};
                }""")
                assert measurement["scrollWidth"] <= measurement["clientWidth"]
                assert abs(measurement["root"]["width"] - measurement["clientWidth"]) < 2
                assert abs(measurement["main"]["right"] - measurement["clientWidth"]) < 2
                evidence["resizes"].append({"windowWidth": width, "tab": name, **measurement})
                if width == 1920:
                    await target.screenshot(path=str(artifacts / f"gianna-native-width-{name}.png"))
            if width == 1920:
                await page.get_by_test_id("new-ticket").click()
                dialog = page.get_by_role("dialog", name="Nuevo ticket", exact=True)
                await dialog.wait_for()
                box = await page.locator(".modal-box").bounding_box()
                assert box["width"] > 1800
                await page.screenshot(path=str(artifacts / "gianna-native-width-form.png"))
                await page.keyboard.press("Escape")
        assert not evidence["errors"], evidence["errors"]
        evidence["passed"] = True
    finally:
        (artifacts / "gianna-native-window-layout.json").write_text(
            json.dumps(evidence, indent=2), encoding="utf-8"
        )
        await browser.close()
