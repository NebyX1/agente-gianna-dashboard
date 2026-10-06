from uuid import uuid4

from flask import Blueprint, g, request
from flask_jwt_extended import create_access_token

from app.extensions import db, limiter
from app.models import AuthSession, now
from app.schemas import Login, PasswordChange, Resend, Verify, load
from app.services.auth import (
    account_key,
    authorize,
    check_password,
    hasher,
    issue_challenge,
    locked_user,
    login,
    pending_user,
    user_read,
    verify,
)
from app.utils.responses import APIError, iso, success

bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")
account_limit = limiter.shared_limit("40 per hour", scope="auth-account", key_func=account_key)
ip_limit = limiter.shared_limit("300 per hour", scope="auth-ip")


@bp.post("/login")
@account_limit
@ip_limit
def auth_login():
    return success(login(load(Login)))


@bp.post("/verify-2fa")
@account_limit
@ip_limit
def verify_2fa():
    return success(verify(load(Verify)))


@bp.post("/resend-2fa")
@account_limit
@ip_limit
def resend_2fa():
    user, _ = pending_user(load(Resend)["pending_token"])
    return success(issue_challenge(user))


@bp.get("/me")
@authorize()
def me():
    return success(user_read(g.user))


@bp.post("/agent-session")
@authorize("admin", "operator")
def agent_session():
    if g.auth_session.client_id != "manual-ui" or g.auth_session.parent_session_id:
        raise APIError("forbidden", "La delegación requiere la sesión verificada del usuario", 403)
    if request.get_json(silent=True) != {}:
        raise APIError("validation_error", "El cuerpo debe ser un objeto vacío")
    lifetime = g.auth_session.expires_at - now()
    child = AuthSession(
        id=str(uuid4()), user_id=g.user.id, auth_version=g.user.auth_version,
        parent_session_id=g.auth_session.id, client_id="gianna-agent",
        expires_at=g.auth_session.expires_at,
    )
    db.session.add(child)
    token = create_access_token(identity=str(g.user.id), expires_delta=lifetime,
        additional_claims={"purpose": "session", "sid": child.id})
    db.session.commit()
    return success({"access_token": token, "expires_at": iso(child.expires_at),
                    "client_id": "gianna-agent", "scope": ["tickets"], "user": user_read(g.user)})


@bp.post("/logout")
@authorize()
def logout():
    g.auth_session.revoked_at = now()
    db.session.commit()
    return success({"message": "Sesión cerrada"})


@bp.put("/change-password")
@authorize()
def change_password():
    data = load(PasswordChange)
    user = locked_user(g.user.id)
    if not check_password(user.password_hash, data["current_password"]):
        raise APIError(
            "invalid_credentials",
            "La contraseña actual no es correcta",
            422,
            {"current_password": ["Contraseña incorrecta"]},
        )
    user.password_hash = hasher.hash(data["new_password"])
    user.auth_version += 1
    user.challenge_nonce = None
    db.session.commit()
    return success({"message": "Contraseña cambiada. Iniciá sesión nuevamente"})
