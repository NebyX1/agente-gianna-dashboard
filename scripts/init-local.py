"""Generate local secrets without printing them or replacing existing configuration."""

import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
if (root / ".env").exists():
    raise SystemExit(
        "Ya existe .env; no se reemplazan secretos. Para repetir, conservá el archivo actual."
    )
values = {
    key: secrets.token_hex(32)
    for key in ("DB_PASSWORD", "DB_ROOT_PASSWORD", "SECRET_KEY", "JWT_SECRET_KEY")
}
root.joinpath(".env").write_text(
    "\n".join(f"{k}={v}" for k, v in values.items()) + "\n", encoding="utf-8"
)
backend = root / "backend/.env"
if not backend.exists():
    backend.write_text(
        f"""APP_ENV=development
PORT=5000
DATABASE_URI=mariadb+mariadbconnector://idl_tickets:{values["DB_PASSWORD"]}@localhost:3307/idl_tickets
SECRET_KEY={values["SECRET_KEY"]}
JWT_SECRET_KEY={values["JWT_SECRET_KEY"]}
FRONTEND_URL=http://localhost:5173
CORS_ORIGINS=http://localhost:5173,http://localhost:5174
DASHBOARD_ALLOWED_ORIGIN=http://localhost:5174
RATELIMIT_STORAGE_URI=redis://localhost:6379/0
MAIL_SERVER=localhost
MAIL_PORT=1025
MAIL_USE_TLS=false
MAIL_USE_SSL=false
MAIL_DEFAULT_SENDER=Tickets IDL <tickets@example.test>
DEFAULT_DESTINATION_UNIT_CODE=TI
JWT_ACCESS_HOURS=14
DISPLAY_JWT_ACCESS_HOURS=14
""",
        encoding="utf-8",
    )
for app in ("frontend", "visualizer"):
    target = root / app / ".env"
    if not target.exists():
        target.write_text(
            (root / app / ".env.example").read_text(encoding="utf-8"), encoding="utf-8"
        )
print("Configuración local generada. Secretos guardados en archivos ignorados por Git.")
