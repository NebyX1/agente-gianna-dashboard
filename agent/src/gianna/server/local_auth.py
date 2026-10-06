import secrets
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class LocalAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, config, secret):
        super().__init__(app)
        self.config, self.secret = config, secret

    async def dispatch(self, request, call_next):
        origins = {self.config.console_origin, f"http://localhost:{self.config.port}"}
        if self.config.dev_origin:
            origins.add(self.config.dev_origin)
        hosts = {f"127.0.0.1:{self.config.port}", f"localhost:{self.config.port}"}
        if request.headers.get("host") not in hosts:
            return JSONResponse({"code": "invalid_host"}, 403)
        origin = request.headers.get("origin")
        if origin and origin not in origins:
            return JSONResponse({"code": "invalid_origin"}, 403)
        if request.method == "OPTIONS" and origin in origins:
            return JSONResponse(
                {},
                200,
                headers={
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Credentials": "true",
                    "Access-Control-Allow-Headers": "Content-Type,X-Gianna-Pairing",
                    "Access-Control-Allow-Methods": "GET,POST,PATCH,OPTIONS",
                },
            )
        # The local console can be opened in any browser. Pair only a same-origin
        # browser fetch; foreign sites/forms/iframes cannot obtain this capability.
        local_origin = f"http://{request.headers['host']}"
        pair = request.url.path == "/api/pair" and request.method == "POST"
        navigation = (
            request.url.path == "/"
            and request.method == "GET"
            and request.headers.get("sec-fetch-mode") == "navigate"
            and request.headers.get("sec-fetch-dest") == "document"
            and request.headers.get("sec-fetch-site") in {"none", "same-origin"}
        )
        if pair:
            if not (
                origin == local_origin
                and request.headers.get("sec-fetch-site") == "same-origin"
                and request.headers.get("sec-fetch-mode") in {"cors", "same-origin"}
                and request.headers.get("sec-fetch-dest") == "empty"
                and request.headers.get("content-type", "").split(";")[0] == "application/json"
            ):
                return JSONResponse({"code": "local_browser_required"}, 403)
            response = JSONResponse({"paired": True})
        if request.url.path.startswith("/api/"):
            token = request.cookies.get("gianna_pairing") or request.headers.get(
                "X-Gianna-Pairing", ""
            )
            if not pair and (not token or not secrets.compare_digest(token, self.secret)):
                return JSONResponse({"code": "local_auth_required"}, 401)
            if (
                request.method not in {"GET", "OPTIONS"}
                and not origin
                and not request.headers.get("X-Gianna-Pairing")
            ):
                return JSONResponse({"code": "origin_required"}, 403)
        if not pair:
            response = await call_next(request)
        if pair or (navigation and response.status_code == 200):
            response.set_cookie("gianna_pairing", self.secret, httponly=True, samesite="strict")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        if origin in origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
        return response
