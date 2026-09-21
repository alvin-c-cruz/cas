"""Per-product allowed-units resolver (prodau_0001).

Empty set = unconstrained (opt-in). A curated set constrains, but the product's
default unit is always allowed, and a blank unit (falls back to default) always passes.
"""
import pytest

from app import db
from app.products.models import Product
from app.units_of_measure.models import UnitOfMeasure

pytestmark = [pytest.mark.integration]


def _uom(code, name):
    u = UnitOfMeasure(code=code, name=name, is_active=True)
    db.session.add(u)
    db.session.commit()
    return u


def test_empty_set_allows_any_unit(db_session):
    kg = _uom('KG', 'Kilogram')
    p = Product(name='Unconstrained', is_active=True)
    db.session.add(p)
    db.session.commit()
    assert p.allowed_unit_ids() == set()
    assert p.unit_allowed(kg.id) is True      # unconstrained
    assert p.unit_allowed(None) is True        # blank -> default


def test_curated_set_constrains_but_default_always_allowed(db_session):
    box = _uom('BOX', 'Box')
    kg = _uom('KG', 'Kilogram')
    piece = _uom('PC', 'Piece')
    p = Product(name='Constrained', default_unit_of_measure_id=piece.id, is_active=True)
    p.allowed_units = [box]
    db.session.add(p)
    db.session.commit()
    assert p.allowed_unit_ids() == {box.id}
    assert p.unit_allowed(box.id) is True       # in the set
    assert p.unit_allowed(kg.id) is False       # not in set, not default
    assert p.unit_allowed(piece.id) is True     # default always allowed
    assert p.unit_allowed(None) is True         # blank -> default
    assert p.to_dict()['allowed_unit_ids'] == [box.id]
