from sqlalchemy import select

from app.commands import seed_catalogs
from app.extensions import db
from app.models import OrgUnit


def test_secretariat_seed_is_idempotent_and_preserves_admin_changes(app):
    with app.app_context():
        unit = db.session.scalar(select(OrgUnit).where(OrgUnit.code == "SECRETARIA_GENERAL"))
        assert unit.name == "Secretaría General" and unit.kind == "office"
        assert not unit.can_receive_tickets
        ids = list(db.session.scalars(select(OrgUnit.id).order_by(OrgUnit.id)))
        unit.name = "Secretaría General (personalizada)"
        unit.is_active = False
        db.session.commit()
        seed_catalogs()
        assert list(db.session.scalars(select(OrgUnit.id).order_by(OrgUnit.id))) == ids
        db.session.refresh(unit)
        assert unit.name == "Secretaría General (personalizada)" and not unit.is_active
