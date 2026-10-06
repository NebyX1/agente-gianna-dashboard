import hashlib
import secrets
import smtplib
from datetime import timedelta
from functools import wraps
from uuid import uuid4

import jwt as pyjwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from flask import current_app, g, request
from flask_jwt_extended import (
    create_access_token,
    decode_token,
    get_jwt,
    get_jwt_identity,
    verify_jwt_in_request,
)
from flask_mail import Connection, Message
from sqlalchemy import select

from app.extensions import db
from app.models import AuthSession, Challenge, User, now
from app.utils.responses import APIError, iso

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))


def check_password(encoded, password):
    try:
        return hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def user_read(user):
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
    }


def authorize(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            verify_jwt_in_request()
            claims = get_jwt()
            if claims.get("purpose") != "session":
                raise APIError("unauthorized", "Completá la verificación de identidad", 401)
            user = db.session.get(User, int(get_jwt_identity()))
            session = db.session.get(AuthSession, claims.get("sid"))
            parent = (
                db.session.get(AuthSession, session.parent_session_id)
                if session and session.parent_session_id else None
            )
            if (
                not user
                or not user.is_active
                or not session
                or session.user_id != user.id
                or session.revoked_at
                or session.expires_at <= now()
                or session.auth_version != user.auth_version
                or (session.parent_session_id and (
                    not parent or parent.user_id != user.id or parent.revoked_at
                    or parent.expires_at <= now() or parent.auth_version != user.auth_version
                ))
            ):
                raise APIError(
                    "session_expired",
                    "La sesión venció o fue revocada. Iniciá sesión nuevamente",
                    401,
                )
            if roles and user.role not in roles:
                raise APIError("forbidden", "No tenés permiso para realizar esta operación", 403)
            if session.client_id == "gianna-agent":
                # Server-owned capability boundary; an admin delegation is not an admin API token.
                allowed = (
                    request.path in {"/api/v1/auth/me", "/api/v1/auth/logout", "/api/v1/catalogs"}
                    or request.path.startswith("/api/v1/tickets")
                    or request.path.startswith("/api/v1/agent/operations/")
                    or request.path.startswith("/api/v1/admin/tickets/")
                )
                if not allowed:
                    raise APIError("agent_scope_forbidden", "La sesión delegada sólo permite tickets", 403)
            g.user, g.auth_session = user, session
            return fn(*args, **kwargs)

        return wrapped

    return decorator


def account_key():
    """One aggregate quota across login, verification and resend; never reset on challenge rotation."""
    body = request.get_json(silent=True) or {}
    identity = str(body.get("email", "")).lower().strip()
    if body.get("pending_token"):
        try:
            identity = "uid:" + str(decode_token(body["pending_token"])["sub"])
            user = db.session.get(User, int(identity[4:]))
            identity = user.email if user else identity
        except (pyjwt.PyJWTError, ValueError, KeyError, TypeError):
            identity = "invalid"
    return hashlib.sha256(identity.encode()).hexdigest()


class TimedConnection(Connection):
    def configure_host(self):
        ctor = smtplib.SMTP_SSL if self.mail.use_ssl else smtplib.SMTP
        host = ctor(self.mail.server, self.mail.port, timeout=current_app.config["MAIL_TIMEOUT"])
        if self.mail.use_tls:
            host.starttls()
        if self.mail.username and self.mail.password:
            host.login(self.mail.username, self.mail.password)
        return host


def send_code(email, code):
    message = Message("[Tickets IDL] Código de verificación", recipients=[email])
    message.body = f"Tu código es {code}. Expira en 10 minutos. No lo compartas."
    if current_app.testing and "TEST_MAIL_OUTBOX" in current_app.config:
        current_app.config["TEST_MAIL_OUTBOX"].append(message)
        return
    try:
        with TimedConnection(current_app.extensions["mail"]) as connection:
            connection.send(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise APIError(
            "mail_unavailable", "No se pudo enviar el código. Intentá nuevamente más tarde", 503
        ) from exc


def locked_user(user_id):
    return db.session.execute(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def issue_challenge(user):
    if user.last_otp_sent_at and now() - user.last_otp_sent_at < timedelta(seconds=60):
        raise APIError(
            "otp_cooldown",
            "Esperá 60 segundos desde el último envío para solicitar otro código",
            429,
            details={"retry_after": 60},
        )
    challenge = Challenge(
        id=str(uuid4()), user_id=user.id, code_hash="", expires_at=now() + timedelta(minutes=10)
    )
    code = f"{secrets.randbelow(1000000):06d}"
    challenge.code_hash = hasher.hash(code)
    user.challenge_nonce = challenge.id
    user.last_otp_sent_at = now()
    db.session.add(challenge)
    db.session.flush()
    send_code(user.email, code)
    pending = create_access_token(
        identity=str(user.id),
        expires_delta=timedelta(minutes=10),
        additional_claims={"purpose": "2fa", "cid": challenge.id, "av": user.auth_version},
    )
    db.session.commit()
    return {"pending_token": pending, "expires_in": 600, "resend_after": 60}


def login(data):
    user = db.session.execute(
        select(User).where(User.email == data["email"].lower()).with_for_update()
    ).scalar_one_or_none()
    valid = check_password(user.password_hash if user else DUMMY_HASH, data["password"])
    if not valid or not user or not user.is_active:
        raise APIError("invalid_credentials", "Email o contraseña incorrectos", 401)
    return issue_challenge(user)


def pending_user(token):
    try:
        claims = decode_token(token)
        if claims.get("purpose") != "2fa":
            raise ValueError()
        user = locked_user(int(claims["sub"]))
        if (
            not user
            or not user.is_active
            or user.challenge_nonce != claims.get("cid")
            or user.auth_version != claims.get("av")
        ):
            raise ValueError()
        challenge = db.session.scalar(
            select(Challenge)
            .where(Challenge.id == claims["cid"])
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not challenge or challenge.consumed_at or challenge.expires_at <= now():
            raise ValueError()
        return user, challenge
    except (pyjwt.PyJWTError, ValueError, KeyError, TypeError) as exc:
        raise APIError(
            "invalid_challenge",
            "El código venció o ya fue utilizado. Iniciá sesión nuevamente",
            401,
        ) from exc


def verify(data):
    user, challenge = pending_user(data["pending_token"])
    if challenge.attempts >= 5:
        raise APIError("otp_attempts_exceeded", "Se agotaron los intentos de este código", 429)
    challenge.attempts += 1
    if not check_password(challenge.code_hash, data["code"]):
        db.session.commit()  # Failed attempts survive a rejected request.
        raise APIError(
            "invalid_otp", "El código no es correcto", 422, {"code": ["Código incorrecto"]}
        )
    challenge.consumed_at = now()
    user.challenge_nonce = None
    lifetime = (
        timedelta(hours=current_app.config["DISPLAY_JWT_ACCESS_HOURS"])
        if user.role == "viewer"
        else current_app.config["JWT_ACCESS_TOKEN_EXPIRES"]
    )
    session = AuthSession(
        id=str(uuid4()),
        user_id=user.id,
        auth_version=user.auth_version,
        expires_at=now() + lifetime,
    )
    db.session.add(session)
    token = create_access_token(
        identity=str(user.id),
        expires_delta=lifetime,
        additional_claims={"purpose": "session", "sid": session.id},
    )
    db.session.commit()
    return {
        "access_token": token,
        "expires_in": int(lifetime.total_seconds()),
        "expires_at": iso(session.expires_at),
        "user": user_read(user),
    }
