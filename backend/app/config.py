import os
from datetime import timedelta
from urllib.parse import urlparse

from dotenv import load_dotenv


def config():
    load_dotenv()
    env = os.getenv("APP_ENV", "development")
    if env not in {"development", "test", "production"}:
        raise ValueError("APP_ENV debe ser development, test o production")
    required = ["DATABASE_URI", "SECRET_KEY", "JWT_SECRET_KEY", "CORS_ORIGINS", "FRONTEND_URL"]
    for key in required:
        if not os.getenv(key):
            raise ValueError(f"Falta {key}; ejecutá scripts/init-local.py o configurá el entorno")
    uri = os.environ["DATABASE_URI"]
    if env != "test" and not uri.startswith("mariadb+mariadbconnector://"):
        raise ValueError("DATABASE_URI debe usar mariadb+mariadbconnector")
    origins = list(
        dict.fromkeys(
            filter(
                None,
                [
                    *[v.strip() for v in os.environ["CORS_ORIGINS"].split(",")],
                    os.getenv("DASHBOARD_ALLOWED_ORIGIN", ""),
                ],
            )
        )
    )
    for origin in origins:
        parsed = urlparse(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("CORS_ORIGINS y DASHBOARD_ALLOWED_ORIGIN deben ser orígenes exactos")
        if env == "production" and parsed.scheme != "https":
            raise ValueError("CORS_ORIGINS requiere HTTPS en producción")
    storage = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
    if env == "production":
        if not storage.startswith(("redis://", "rediss://")):
            raise ValueError("RATELIMIT_STORAGE_URI requiere Redis en producción")
        for key in ("SECRET_KEY", "JWT_SECRET_KEY"):
            if len(os.environ[key]) < 32 or "<" in os.environ[key]:
                raise ValueError(f"{key} requiere un secreto fuerte de al menos 32 caracteres")
        for key in ("MAIL_SERVER", "MAIL_DEFAULT_SENDER"):
            if not os.getenv(key):
                raise ValueError(f"Falta {key}")
    result = dict(
        APP_ENV=env,
        SECRET_KEY=os.environ["SECRET_KEY"],
        JWT_SECRET_KEY=os.environ["JWT_SECRET_KEY"],
        SQLALCHEMY_DATABASE_URI=uri,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(hours=float(os.getenv("JWT_ACCESS_HOURS", "14"))),
        DISPLAY_JWT_ACCESS_HOURS=float(os.getenv("DISPLAY_JWT_ACCESS_HOURS", "14")),
        CORS_ORIGINS=origins,
        JWT_TOKEN_LOCATION=["headers"],
        FRONTEND_URL=os.environ["FRONTEND_URL"],
        RATELIMIT_STORAGE_URI=storage,
        RATELIMIT_STRATEGY="moving-window",
        MAX_CONTENT_LENGTH=32 * 1024,
        TRUSTED_PROXY_HOPS=int(os.getenv("TRUSTED_PROXY_HOPS", "0")),
        DEFAULT_DESTINATION_UNIT_CODE=os.getenv("DEFAULT_DESTINATION_UNIT_CODE", "TI"),
        MAIL_SERVER=os.getenv("MAIL_SERVER", "localhost"),
        MAIL_PORT=int(os.getenv("MAIL_PORT", "1025")),
        MAIL_USE_TLS=os.getenv("MAIL_USE_TLS", "false").lower() == "true",
        MAIL_USE_SSL=os.getenv("MAIL_USE_SSL", "false").lower() == "true",
        MAIL_USERNAME=os.getenv("MAIL_USERNAME") or None,
        MAIL_PASSWORD=os.getenv("MAIL_PASSWORD") or None,
        MAIL_DEFAULT_SENDER=os.getenv("MAIL_DEFAULT_SENDER", "Tickets IDL <tickets@example.test>"),
        MAIL_TIMEOUT=float(os.getenv("MAIL_TIMEOUT", "10")),
    )
    if result["MAIL_USE_TLS"] and result["MAIL_USE_SSL"]:
        raise ValueError("MAIL_USE_TLS y MAIL_USE_SSL son excluyentes")
    if not 0 < result["DISPLAY_JWT_ACCESS_HOURS"] <= 48 or not timedelta(0) < result[
        "JWT_ACCESS_TOKEN_EXPIRES"
    ] <= timedelta(hours=48):
        raise ValueError("JWT_ACCESS_HOURS y DISPLAY_JWT_ACCESS_HOURS deben estar entre 0 y 48")
    return result
