import pytest
from decimal import Decimal
from sqlalchemy.exc import IntegrityError
from app import db
from app.products.models import Product
from app.units_of_measure.models import UnitOfMeasure


def test_product_create_and_to_dict(db_session):
    u = UnitOfMeasure(code='pcs', name='Pieces'); db.session.add(u); db.session.commit()
    p = Product(code='WID-1', name='Widget', default_unit_of_measure_id=u.id,
                default_unit_price=Decimal('112.00'), is_active=True)
    db.session.add(p); db.session.commit()
    assert p.id is not None
    d = p.to_dict()
    assert d['code'] == 'WID-1' and d['name'] == 'Widget'
    assert d['default_unit_price'] == 112.0
    assert d['default_uom_id'] == u.id and d['default_uom_code'] == 'pcs'


def test_product_code_unique(db_session):
    db.session.add(Product(code='A', name='A1')); db.session.commit()
    db.session.add(Product(code='A', name='A2'))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_product_job_order_name_optional_and_in_dict(db_session):
    # Blank job_order_name is valid — falls back to `name` at display time (Task 3), not here.
    p1 = Product(code='JON-1', name='Widget A', is_active=True)
    db.session.add(p1); db.session.commit()
    assert p1.job_order_name is None
    assert p1.to_dict()['job_order_name'] is None

    p2 = Product(code='JON-2', name='Widget B', job_order_name='WGT-B-PROD', is_active=True)
    db.session.add(p2); db.session.commit()
    assert p2.job_order_name == 'WGT-B-PROD'
    assert p2.to_dict()['job_order_name'] == 'WGT-B-PROD'
