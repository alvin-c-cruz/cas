import pytest
from sqlalchemy.exc import IntegrityError
from app import db
from app.units_of_measure.models import UnitOfMeasure


def test_unit_of_measure_create_and_to_dict(db_session):
    u = UnitOfMeasure(code='pcs', name='Pieces', is_active=True)
    db.session.add(u); db.session.commit()
    assert u.id is not None
    d = u.to_dict()
    assert d['code'] == 'pcs' and d['name'] == 'Pieces' and d['is_active'] is True


def test_unit_of_measure_code_unique(db_session):
    db.session.add(UnitOfMeasure(code='kg', name='Kilogram')); db.session.commit()
    db.session.add(UnitOfMeasure(code='kg', name='Kilo2'))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
