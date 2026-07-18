from decimal import Decimal
from app import db
from app.products.models import Product, COSTING_METHODS


def test_product_defaults_track_inventory_false(db_session):
    p = Product(code='INV-1', name='Untracked Widget', is_active=True)
    db.session.add(p)
    db.session.commit()
    assert p.track_inventory is False
    assert p.costing_method is None
    assert p.standard_cost is None
    assert p.reorder_level is None


def test_product_inventory_fields_settable(db_session):
    p = Product(code='INV-2', name='Tracked Widget', is_active=True,
                track_inventory=True, costing_method='moving_average',
                standard_cost=Decimal('150.00'), reorder_level=Decimal('20.00'))
    db.session.add(p)
    db.session.commit()
    assert p.track_inventory is True
    assert p.costing_method == 'moving_average'
    assert p.standard_cost == Decimal('150.00')
    assert p.reorder_level == Decimal('20.00')


def test_product_to_dict_includes_inventory_fields(db_session):
    p = Product(code='INV-3', name='Dict Widget', is_active=True,
                track_inventory=True, costing_method='fifo',
                standard_cost=Decimal('99.50'), reorder_level=Decimal('5.00'))
    db.session.add(p)
    db.session.commit()
    d = p.to_dict()
    assert d['track_inventory'] is True
    assert d['costing_method'] == 'fifo'
    assert d['standard_cost'] == 99.5
    assert d['reorder_level'] == 5.0


def test_costing_methods_constant_has_expected_values():
    assert set(COSTING_METHODS) == {'moving_average', 'fifo', 'standard', 'lifo',
                                     'specific_identification'}
