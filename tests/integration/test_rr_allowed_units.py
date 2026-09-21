"""No-PO receiving lines are constrained to a product's curated allowed units
(prodau_0001). Opt-in: no set => any active unit. Default always allowed. The
server guard is authoritative — _create_via_form posts through the real route,
which is the seam a raw POST reaches.
"""
import pytest
from decimal import Decimal

from app import db
from app.products.models import Product
from app.receiving_reports.models import ReceivingReport
from app.units_of_measure.models import UnitOfMeasure
from tests.integration.test_rr_direct_receipt import (  # noqa: F401
    _create_via_form, vendor)
from tests.integration.test_rr_submit import _login, rr_enabled  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]


def _units():
    box = UnitOfMeasure(code='BOX', name='Box', is_active=True)
    kg = UnitOfMeasure(code='KG', name='Kilogram', is_active=True)
    pc = UnitOfMeasure(code='PC', name='Piece', is_active=True)
    db.session.add_all([box, kg, pc]); db.session.commit()
    return box, kg, pc


def test_unit_in_allowed_set_is_accepted(client, db_session, main_branch, vendor,
                                         admin_user, rr_enabled):
    box, kg, pc = _units()
    p = Product(name='Boxed', track_inventory=False, is_active=True,
                default_unit_of_measure_id=pc.id)
    p.allowed_units = [box]
    db.session.add(p); db.session.commit()
    _login(client, admin_user, main_branch)
    _, rr = _create_via_form(client, vendor, [{'product_id': p.id,
                                               'received_quantity': '2',
                                               'unit_of_measure_id': box.id}])
    assert rr is not None
    assert rr.line_items[0].unit_of_measure_id == box.id


def test_unit_outside_allowed_set_is_rejected(client, db_session, main_branch, vendor,
                                              admin_user, rr_enabled):
    box, kg, pc = _units()
    p = Product(name='Boxed2', track_inventory=False, is_active=True,
                default_unit_of_measure_id=pc.id)
    p.allowed_units = [box]
    db.session.add(p); db.session.commit()
    _login(client, admin_user, main_branch)
    resp, rr = _create_via_form(client, vendor, [{'product_id': p.id,
                                                  'received_quantity': '2',
                                                  'unit_of_measure_id': kg.id}])
    assert rr is None
    assert 'not an allowed unit' in resp.get_data(as_text=True)


def test_blank_unit_falls_back_to_default_even_if_default_not_listed(
        client, db_session, main_branch, vendor, admin_user, rr_enabled):
    box, kg, pc = _units()
    p = Product(name='Boxed3', track_inventory=False, is_active=True,
                default_unit_of_measure_id=pc.id)
    p.allowed_units = [box]           # default (PC) intentionally NOT in the set
    db.session.add(p); db.session.commit()
    _login(client, admin_user, main_branch)
    _, rr = _create_via_form(client, vendor, [{'product_id': p.id,
                                               'received_quantity': '2'}])
    assert rr is not None
    assert rr.line_items[0].unit_of_measure_id is None


def test_empty_set_accepts_any_active_unit(client, db_session, main_branch, vendor,
                                           admin_user, rr_enabled):
    box, kg, pc = _units()
    p = Product(name='Unconstrained', track_inventory=False, is_active=True)
    db.session.add(p); db.session.commit()      # no allowed_units
    _login(client, admin_user, main_branch)
    _, rr = _create_via_form(client, vendor, [{'product_id': p.id,
                                               'received_quantity': '2',
                                               'unit_of_measure_id': kg.id}])
    assert rr is not None
    assert rr.line_items[0].unit_of_measure_id == kg.id


def test_payload_includes_allowed_unit_ids(db_session, app):
    box, kg, pc = _units()
    p = Product(name='PayloadProd', track_inventory=False, is_active=True)
    p.allowed_units = [box]
    db.session.add(p); db.session.commit()
    from app.receiving_reports.views import _direct_products_payload
    with app.test_request_context():
        rows = _direct_products_payload()
    row = next(r for r in rows if r['product_id'] == p.id)
    assert row['allowed_unit_ids'] == [box.id]
