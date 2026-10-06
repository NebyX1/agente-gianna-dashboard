# API de tickets

Python 3.12, Flask 3.1, SQLAlchemy 2, MariaDB Connector/Python, Marshmallow, Alembic, Argon2, JWT, Flask-Mail y Redis para cuotas. Factory en `app/__init__.py`; validadores en `app/schemas`; servicios de negocio en `app/services`; rutas en `app/blueprints`; modelos en `app/models`.

Desde la raíz generar configuración con `python scripts/init-local.py`. Después, dentro de esta carpeta:

```sh
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
flask --app wsgi db upgrade
flask --app wsgi seed-catalogs
flask --app wsgi create-admin
flask --app wsgi run --port 5000
ruff check .
pytest -q
python contracts/generate.py --check
```

Las dependencias completas, incluidas transitivas, están fijadas en `requirements*.txt`; los `.in` sirven para actualizaciones deliberadas con `uv pip compile`. Para instalar el conector en Linux hacen falta `libmariadb-dev`, `pkg-config` y compilador. En Windows instalar MariaDB Connector/C o trabajar en Docker. SQLite sólo sirve para pruebas de unidad; `python ../scripts/test-backend.py` verifica la misma suite y concurrencia con MariaDB 11.4 real.

Los tests migran la base (no llaman `create_all`). `TEST_DATABASE_URI`, si se usa, debe apuntar a una base descartable cuyo nombre termine en `_test`: las fixtures ejecutan downgrade/upgrade. Nunca usar una base con datos operativos.

```sh
docker build -t idl-tickets-backend .
```

El runtime requiere `DATABASE_URI=mariadb+mariadbconnector://...`, `SECRET_KEY`, `JWT_SECRET_KEY`, `FRONTEND_URL`, `CORS_ORIGINS`, Redis y SMTP. `.env.example` contiene todos los nombres; los marcadores no son credenciales funcionales. La imagen ejecuta Gunicorn no root y migra antes de iniciar cuando `RUN_MIGRATIONS=true`. Para varias réplicas migrar una sola vez y configurar `false` en todas las réplicas. `/healthz` comprueba proceso; `/readyz` comprueba DB, esquema y almacenamiento de límites.

Operación:

```sh
flask --app wsgi reset-password --email persona@example.com
flask --app wsgi purge-idempotency
```

El restablecimiento solicita una contraseña oculta, invalida sesiones previas y requiere entrega por un canal seguro. `purge-idempotency` sólo elimina claves anteriores a 48 horas; sin ese mantenimiento se conservan indefinidamente. Nunca registra códigos OTP, tokens o cuerpos sensibles.

`seed-catalogs` agrega únicamente códigos faltantes. `seed-test-users` y `seed-previous-day` sólo pueden ejecutarse explícitamente en development/test. Las credenciales aleatorias de prueba se guardan en `~/.test-users.json` con permisos del propietario. `--reset` es una acción explícita limitada a cuentas de prueba, nunca al inicio.

Si el login responde 503, comprobar SMTP, timeout y TLS/SSL; no se informa envío exitoso cuando falla. Un 429 incluye `Retry-After`. Si `/readyz` falla, comprobar DB, migraciones y Redis. En producción `memory://`, secretos cortos y CORS sin HTTPS son rechazados.
