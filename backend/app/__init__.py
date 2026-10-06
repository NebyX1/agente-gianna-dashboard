import re
from uuid import uuid4

import sqlalchemy as sa
from flask import Flask, g, request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import config
from app.extensions import cors, db, jwt, limiter, mail, migrate
from app.utils.responses import APIError, failure, success


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.update(config() if overrides is None else overrides)
    hops = app.config.get("TRUSTED_PROXY_HOPS", 0)
    if hops:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=0, x_port=0)
    db.init_app(app)
    migrate.init_app(app, db, compare_type=True)
    jwt.init_app(app)
    mail.init_app(app)
    limiter.init_app(app)
    cors.init_app(
        app,
        resources={r"/api/v1/*": {"origins": app.config["CORS_ORIGINS"]}},
        supports_credentials=False,
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Idempotency-Key", "X-Agent-Operation-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
        methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"],
    )

    @app.before_request
    def request_id():
        incoming = request.headers.get("X-Request-ID", "")
        g.request_id = incoming if re.fullmatch(r"[A-Za-z0-9_-]{8,64}", incoming) else str(uuid4())

    @app.after_request
    def headers(response):
        response.headers["X-Request-ID"] = g.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(APIError)
    def api_error(exc):
        db.session.rollback()
        response, status = failure(exc)
        if status == 429:
            response.headers["Retry-After"] = str((exc.details or {}).get("retry_after", 60))
        return response, status

    @app.errorhandler(HTTPException)
    def http_error(exc):
        db.session.rollback()
        codes = {
            404: ("not_found", "Ruta no encontrada"),
            429: ("rate_limited", "Demasiados intentos. Esperá antes de reintentar"),
            413: ("payload_too_large", "La solicitud excede el tamaño permitido"),
            405: ("method_not_allowed", "Método no permitido"),
        }
        code, message = codes.get(exc.code, ("bad_request", "Solicitud inválida"))
        response, status = failure(APIError(code, message, exc.code))
        if exc.code == 429:
            response.headers["Retry-After"] = "60"
        return response, status

    @app.errorhandler(IntegrityError)
    def integrity_error(exc):
        db.session.rollback()
        return failure(
            APIError(
                "integrity_conflict",
                "El código o email ya existe, o una referencia no es válida",
                409,
            )
        )

    @app.errorhandler(StaleDataError)
    def version_error(exc):
        db.session.rollback()
        return failure(
            APIError(
                "version_conflict",
                "Otra persona modificó el registro. Recargá antes de continuar",
                409,
            )
        )

    @app.errorhandler(Exception)
    def unexpected_error(exc):
        db.session.rollback()
        app.logger.error(
            "Error interno request_id=%s exception_type=%s", g.request_id, type(exc).__name__
        )
        return failure(
            APIError(
                "internal_error",
                "Ocurrió un error interno. Conservá el identificador de solicitud",
                500,
            )
        )

    @jwt.unauthorized_loader
    def missing_token(reason):
        return failure(APIError("unauthorized", "Iniciá sesión para continuar", 401))

    @jwt.invalid_token_loader
    def invalid_token(reason):
        return failure(APIError("unauthorized", "La credencial no es válida", 401))

    @jwt.expired_token_loader
    def expired_token(header, payload):
        return failure(
            APIError("session_expired", "La sesión venció. Iniciá sesión nuevamente", 401)
        )

    from app.blueprints.auth import bp as auth_bp
    from app.blueprints.domain import bp as domain_bp
    from app.commands import register_cli

    app.register_blueprint(auth_bp)
    app.register_blueprint(domain_bp)
    register_cli(app)

    @app.get("/healthz")
    def health():
        return success({"status": "alive"})

    @app.get("/readyz")
    def ready():
        try:
            db.session.execute(sa.text("SELECT 1"))
            from app.models import User

            db.session.execute(sa.select(User.id).limit(1))  # Includes schema readiness.
            if not limiter.storage.check():
                raise RuntimeError()
            return success({"status": "ready"})
        except Exception:
            db.session.rollback()
            return failure(
                APIError("not_ready", "Las dependencias requeridas no están disponibles", 503)
            )

    return app
