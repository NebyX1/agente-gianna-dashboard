from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from gianna.config import Settings
from gianna.server.local_auth import LocalAuthMiddleware


def test_pairing_host_and_origin_all_required_for_controls():
    app = FastAPI()
    app.add_middleware(LocalAuthMiddleware, config=Settings(), secret="test-pairing")

    @app.api_route("/api/control", methods=["GET", "POST"])
    async def control():
        return {"ok": True}

    with TestClient(app, base_url="http://127.0.0.1:7860") as c:
        assert c.post("/api/control").status_code == 401
        c.cookies.set("gianna_pairing", "test-pairing")
        assert c.post("/api/control").status_code == 403
        assert c.post("/api/control", headers={"Origin": "https://evil.example"}).status_code == 403
        assert (
            c.post(
                "/api/control",
                headers={"Origin": "http://127.0.0.1:7860", "Host": "evil.example:7860"},
            ).status_code
            == 403
        )
        assert (
            c.post("/api/control", headers={"Origin": "http://127.0.0.1:7860"}).status_code == 200
        )


@pytest.fixture
def console():
    app = FastAPI()
    app.add_middleware(LocalAuthMiddleware, config=Settings(), secret="current-runtime")

    @app.get("/")
    async def index():
        return {"console": True}

    @app.api_route("/api/control", methods=["GET", "POST"])
    async def control():
        return {"ok": True}

    return TestClient(app, base_url="http://127.0.0.1:7860")


def test_fresh_local_browser_navigation_pairs_without_another_browsers_cookie(console):
    with console as client:
        assert client.get("/api/control").status_code == 401
        response = client.get(
            "/",
            headers={
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Site": "none",
            },
        )
        assert response.status_code == 200
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "SameSite=strict" in response.headers["set-cookie"]
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Content-Security-Policy"] == "frame-ancestors 'none'"
        assert response.headers["Cross-Origin-Opener-Policy"] == "same-origin"
        assert "current-runtime" not in response.text
        assert client.get("/api/control").status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "iframe", "Sec-Fetch-Site": "same-origin"},
        {
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Site": "cross-site",
        },
        {"Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty", "Sec-Fetch-Site": "same-site"},
    ],
)
def test_non_navigation_cannot_obtain_a_pairing_cookie(console, headers):
    with console as client:
        assert "set-cookie" not in client.get("/", headers=headers).headers
        assert client.get("/api/control").status_code == 401


def pairing_headers(origin="http://127.0.0.1:7860"):
    return {
        "Origin": origin,
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }


def test_same_origin_console_can_recover_after_runtime_rotates_cookie(console):
    with console as client:
        client.cookies.set("gianna_pairing", "old-runtime", domain="127.0.0.1", path="/")
        assert client.get("/api/control").status_code == 401
        response = client.post("/api/pair", headers=pairing_headers(), json={})
        assert response.status_code == 200 and response.json() == {"paired": True}
        assert client.get("/api/control").status_code == 200
        assert client.post("/api/control", headers=pairing_headers()).status_code == 200


@pytest.mark.parametrize(
    "overrides",
    [
        {"Origin": "https://evil.example"},
        {"Origin": "http://localhost:7860"},
        {"Sec-Fetch-Site": "same-site"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"},
        {"Sec-Fetch-Dest": "iframe"},
        {"Sec-Fetch-Site": ""},
        {"Content-Type": "application/x-www-form-urlencoded"},
    ],
)
def test_foreign_site_and_html_form_cannot_pair(console, overrides):
    with console as client:
        response = client.post("/api/pair", headers={**pairing_headers(), **overrides}, json={})
        assert response.status_code == 403 and "set-cookie" not in response.headers
        assert client.get("/api/control").status_code == 401


def test_loopback_alias_is_usable_and_other_ports_remain_forbidden(console):
    with console as client:
        response = client.post(
            "http://localhost:7860/api/pair",
            headers=pairing_headers("http://localhost:7860"),
            json={},
        )
        assert response.status_code == 200
        assert (
            client.post(
                "http://localhost:7860/api/control", headers={"Origin": "http://localhost:7860"}
            ).status_code
            == 200
        )
        assert (
            client.post(
                "http://localhost:7860/api/control", headers={"Origin": "http://localhost:5373"}
            ).status_code
            == 403
        )
