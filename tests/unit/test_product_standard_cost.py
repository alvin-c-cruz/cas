from decimal import Decimal
import pytest
from app import db
from app.products.models import Product

pytestmark = [pytest.mark.unit]


def test_standard_cost_column_persists(db_session):
    p = Product(code='P1', name='Widget', standard_cost=Decimal('12.3456'))
    db.session.add(p)
    db.session.commit()
    fetched = db.session.get(Product, p.id)
    assert fetched.standard_cost == Decimal('12.3456')


def test_standard_cost_defaults_to_none(db_session):
    p = Product(code='P2', name='Widget2')
    db.session.add(p)
    db.session.commit()
    assert db.session.get(Product, p.id).standard_cost is None


def test_to_dict_includes_standard_cost(db_session):
    p = Product(code='P3', name='Widget3', standard_cost=Decimal('5.00'))
    db.session.add(p)
    db.session.commit()
    assert p.to_dict()['standard_cost'] == 5.00


def test_to_dict_standard_cost_none_when_unset(db_session):
    p = Product(code='P4', name='Widget4')
    db.session.add(p)
    db.session.commit()
    assert p.to_dict()['standard_cost'] is None
