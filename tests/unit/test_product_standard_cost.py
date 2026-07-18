from decimal import Decimal
import pytest
from app import db
from app.products.models import Product

pytestmark = [pytest.mark.unit]


def test_standard_cost_column_persists(db_session):
    p = Product(code='P1', name='Widget', standard_cost=Decimal('12.35'))
    db.session.add(p)
    db.session.commit()
    fetched = db.session.get(Product, p.id)
    assert fetched.standard_cost == Decimal('12.35')


def test_standard_cost_rounds_to_two_decimal_places(db_session):
    """standard_cost was narrowed from Numeric(15,4) to Numeric(15,2) (R-03/R-03a
    collision resolution, see docs/superpowers/plans/2026-07-19-product-standard-cost-collision-decision.md)
    to match every other monetary field on Product. A 4-decimal input must round
    to 2 places, not silently truncate."""
    p = Product(code='P1-ROUND', name='Widget', standard_cost=Decimal('12.3456'))
    db.session.add(p)
    db.session.commit()
    fetched = db.session.get(Product, p.id)
    assert fetched.standard_cost == Decimal('12.35')


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


def test_form_has_standard_cost_field(db_session):
    from app.products.forms import ProductForm
    form = ProductForm()
    assert hasattr(form, 'standard_cost')
