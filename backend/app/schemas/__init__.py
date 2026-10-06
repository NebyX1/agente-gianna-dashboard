from datetime import UTC, datetime

from flask import request
from marshmallow import RAISE, Schema, ValidationError, fields, pre_load, validate

from app.utils.responses import APIError

STATUSES = {
    "new": {"label": "Nuevo", "transitions": ["in_progress", "cancelled"]},
    "in_progress": {"label": "En curso", "transitions": ["waiting", "resolved", "cancelled"]},
    "waiting": {"label": "En espera", "transitions": ["in_progress", "resolved", "cancelled"]},
    "resolved": {"label": "Resuelto", "transitions": ["in_progress"]},
    "cancelled": {"label": "Cancelado", "transitions": ["new"]},
}
ACTIVE = ["new", "in_progress", "waiting"]


class StrictSchema(Schema):
    class Meta:
        unknown = RAISE

    @pre_load
    def trim(self, data, **kwargs):
        if not isinstance(data, dict):
            raise ValidationError("Se espera un objeto JSON")
        return {
            k: v.strip() if isinstance(v, str) and "password" not in k else v
            for k, v in data.items()
        }


class AwareDate(fields.DateTime):
    def _deserialize(self, value, attr, data, **kwargs):
        result = super()._deserialize(value, attr, data, **kwargs)
        if result.tzinfo is None:
            raise ValidationError("Incluí Z u offset de zona horaria")
        if result > datetime.now(UTC):
            raise ValidationError("La fecha del problema no puede estar en el futuro")
        return result.astimezone(UTC)


positive = validate.Range(min=1)
text = validate.Length(
    min=10, max=4000, error="La descripción debe tener entre 10 y 4000 caracteres"
)
note = validate.Length(
    min=3, max=1000, error="Ingresá un motivo o nota de entre 3 y 1000 caracteres"
)


class TicketCreate(StrictSchema):
    origin_unit_id = fields.Integer(required=True, strict=True, validate=positive)
    destination_unit_id = fields.Integer(required=True, strict=True, validate=positive)
    problem_type_id = fields.Integer(required=True, strict=True, validate=positive)
    description = fields.String(required=True, validate=text)
    occurred_at = AwareDate(allow_none=True, load_default=None)


class TicketUpdate(TicketCreate):
    version = fields.Integer(required=True, strict=True, validate=positive)


class TicketStatusChange(StrictSchema):
    version = fields.Integer(required=True, strict=True, validate=positive)
    status = fields.String(required=True, validate=validate.OneOf(list(STATUSES)))
    note = fields.String(allow_none=True, validate=note)


class TicketArchive(StrictSchema):
    version = fields.Integer(required=True, strict=True, validate=positive)
    reason = fields.String(required=True, validate=note)


class TicketRestore(TicketArchive):
    pass


class Login(StrictSchema):
    email = fields.Email(required=True, validate=validate.Length(max=254))
    password = fields.String(required=True, validate=validate.Length(min=1, max=256))


class Verify(StrictSchema):
    pending_token = fields.String(required=True, validate=validate.Length(max=2048))
    code = fields.String(required=True, validate=validate.Regexp(r"^\d{6}$"))


class Resend(StrictSchema):
    pending_token = fields.String(required=True, validate=validate.Length(max=2048))


class PasswordChange(StrictSchema):
    current_password = fields.String(required=True, validate=validate.Length(min=1, max=256))
    new_password = fields.String(required=True, validate=validate.Length(min=12, max=256))


class OrgUnitCreate(StrictSchema):
    code = fields.String(required=True, validate=validate.Regexp(r"^[A-Z0-9_-]{1,32}$"))
    name = fields.String(required=True, validate=validate.Length(min=2, max=160))
    kind = fields.String(required=True, validate=validate.OneOf(["area", "office", "municipality"]))
    is_active = fields.Boolean(load_default=True)
    can_receive_tickets = fields.Boolean(load_default=False)
    parent_id = fields.Integer(allow_none=True, load_default=None, strict=True, validate=positive)


class ProblemTypeCreate(StrictSchema):
    code = fields.String(required=True, validate=validate.Regexp(r"^[A-Z0-9_-]{1,32}$"))
    name = fields.String(required=True, validate=validate.Length(min=2, max=160))
    description = fields.String(allow_none=True, validate=validate.Length(max=400))
    is_active = fields.Boolean(load_default=True)


class UserCreate(StrictSchema):
    name = fields.String(required=True, validate=validate.Length(min=2, max=120))
    email = fields.Email(required=True, validate=validate.Length(max=254))
    role = fields.String(required=True, validate=validate.OneOf(["admin", "operator", "viewer"]))
    is_active = fields.Boolean(load_default=True)
    password = fields.String(required=True, validate=validate.Length(min=12, max=256))


class UserUpdate(StrictSchema):
    name = fields.String(validate=validate.Length(min=2, max=120))
    role = fields.String(validate=validate.OneOf(["admin", "operator", "viewer"]))
    is_active = fields.Boolean()


def load(schema, *, partial=False, excluded=()):
    data = request.get_json(silent=True)
    if data is None:
        raise APIError("validation_error", "Enviá un objeto JSON válido")
    try:
        return schema(exclude=excluded).load(data, partial=partial)
    except ValidationError as exc:
        raise APIError(
            "validation_error", "Revisá los campos indicados", errors=exc.messages
        ) from exc
