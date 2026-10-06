import secrets
from datetime import timedelta

import click
from flask import current_app
from sqlalchemy import select

from app.extensions import db
from app.models import OrgUnit, ProblemType, Ticket, User, now
from app.services.auth import hasher


def seed_catalogs():
    units = [
        ("TI", "Informática", "area", True),
        ("TRANSITO", "Tránsito", "area", False),
        ("SECRETARIA_GENERAL", "Secretaría General", "office", False),
        ("URBANISMO", "Urbanismo", "area", False),
        ("SOCIALES", "Sociales", "area", False),
        ("OFICINA_EJEMPLO", "Oficina de ejemplo (editable)", "office", False),
        ("MUNICIPIO_EJEMPLO", "Municipio de ejemplo (editable)", "municipality", False),
    ]
    for code, name, kind, receives in units:
        if not db.session.scalar(select(OrgUnit).where(OrgUnit.code == code)):
            db.session.add(OrgUnit(code=code, name=name, kind=kind, can_receive_tickets=receives))
    for code, name in [
        ("INTERNET", "Conectividad / Internet"),
        ("IMPRESORA", "Impresoras"),
        ("SISTEMAS", "Acceso a sistemas"),
        ("HARDWARE", "Hardware"),
        ("OTROS", "Otros"),
    ]:
        if not db.session.scalar(select(ProblemType).where(ProblemType.code == code)):
            db.session.add(ProblemType(code=code, name=name))
    db.session.commit()


def register_cli(app):
    @app.cli.command("seed-catalogs")
    def seed():
        """Catálogos iniciales; nunca modifica registros existentes."""
        seed_catalogs()
        click.echo("Catálogos listos")

    @app.cli.command("create-admin")
    @click.option("--email", prompt=True)
    @click.option("--name", prompt="Nombre")
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin(email, name, password):
        if len(password) < 12:
            raise click.ClickException("La contraseña debe tener al menos 12 caracteres")
        if db.session.scalar(select(User).where(User.email == email.lower())):
            raise click.ClickException("El email ya existe")
        db.session.add(
            User(email=email.lower(), name=name, role="admin", password_hash=hasher.hash(password))
        )
        db.session.commit()
        click.echo("Administrador creado")

    @app.cli.command("reset-password")
    @click.option("--email", prompt=True)
    @click.option(
        "--password", prompt="Nueva contraseña", hide_input=True, confirmation_prompt=True
    )
    def reset_password(email, password):
        user = db.session.scalar(select(User).where(User.email == email.lower()).with_for_update())
        if not user or len(password) < 12:
            raise click.ClickException("Usuario inexistente o contraseña menor a 12 caracteres")
        user.password_hash = hasher.hash(password)
        user.auth_version += 1
        user.challenge_nonce = None
        db.session.commit()
        click.echo(
            "Contraseña restablecida; sesiones anteriores invalidadas. Entregá la credencial por un canal seguro"
        )

    @app.cli.command("seed-test-users")
    @click.option(
        "--reset", is_flag=True, help="Restablecer explícitamente sólo cuentas example.test"
    )
    def test_users(reset):
        """Explicit development/test bootstrap; random passwords in an ignored file."""
        if current_app.config["APP_ENV"] not in {"development", "test"}:
            raise click.ClickException("Sólo disponible en development/test")
        import json
        from pathlib import Path

        output = {}
        for role in ("admin", "operator", "viewer"):
            email = f"{role}@example.test"
            user = db.session.scalar(select(User).where(User.email == email))
            if user and not reset:
                raise click.ClickException(
                    "Usuarios de prueba ya existen; no se restablecen automáticamente"
                )
            password = secrets.token_urlsafe(24)
            if user:
                user.password_hash = hasher.hash(password)
                user.auth_version += 1
                user.challenge_nonce = None
                user.last_otp_sent_at = None
            else:
                db.session.add(
                    User(
                        email=email,
                        name=f"Prueba {role}",
                        role=role,
                        password_hash=hasher.hash(password),
                    )
                )
            output[role] = {"email": email, "password": password}
        target = Path.home() / ".test-users.json"
        target.write_text(json.dumps(output), encoding="utf-8")
        target.chmod(0o600)
        db.session.commit()
        click.echo("Credenciales locales generadas en ~/.test-users.json (no versionar)")

    @app.cli.command("purge-idempotency")
    def purge():
        """Retain at least 48h (minimum guaranteed: 24h). Run only as maintenance."""
        from app.models import Idempotency

        db.session.execute(
            db.delete(Idempotency).where(Idempotency.created_at < now() - timedelta(hours=48))
        )
        db.session.commit()
        click.echo("Claves anteriores a 48 horas eliminadas")

    @app.cli.command("seed-previous-day")
    def previous_day():
        if current_app.config["APP_ENV"] not in {"test", "development"}:
            raise click.ClickException("Sólo development/test")
        from flask import g

        from app.services.tickets import audit

        user = db.session.scalar(select(User).where(User.role == "admin"))
        origin = db.session.scalar(select(OrgUnit).where(OrgUnit.code == "TRANSITO"))
        destination = db.session.scalar(select(OrgUnit).where(OrgUnit.code == "TI"))
        kind = db.session.scalar(select(ProblemType).where(ProblemType.code == "IMPRESORA"))
        if not all([user, origin, destination, kind]):
            raise click.ClickException("Ejecutá seed-catalogs y creá un admin primero")
        g.user, g.request_id = user, secrets.token_hex(16)
        ticket = Ticket(
            origin_unit_id=origin.id,
            destination_unit_id=destination.id,
            problem_type_id=kind.id,
            description="[PRUEBA] Impresora pendiente desde el día anterior",
            created_by_user_id=user.id,
            created_at=now() - timedelta(days=1),
            status="new",
        )
        db.session.add(ticket)
        db.session.flush()
        ticket.code = f"IDL-TI-{ticket.id:06d}"
        audit(ticket, "created")
        db.session.commit()
        click.echo(ticket.code)
