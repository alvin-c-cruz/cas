"""Quotation VAT display: strip the per-line VT column + the Subtotal/VAT summary
rows, keeping the header VAT-Treatment control and the Total. Owner-directed
2026-07-11 (BUG-QUOTE-SUBTOTAL-SHOWN + BUG-QUOTE-VT-COLUMN-SHOWN, 'strip all').

The per-line vat_category still flows to the DB + the Quote->SO handoff (it's a
hidden value populated from the customer default); only its column is removed.
The JS-driven submit path is covered by tests/e2e/test_quotation_smoke.py.
"""
import json
import pytest
from decimal import Decimal

from app import db
from app.customers.models import Customer
from app.products.models import Product

pytestmark = [pytest.mark.integration, pytest.mark.quotations]


@pytest.fixture(autouse=True)
def quotations_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('quotations', 'sales_orders', 'products', 'units_of_measure', 'employees'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield; clear_module_config_cache()


def _login(client, u, branch):
    with client.session_transaction() as s:
        s['_user_id'] = str(u.id); s['_fresh'] = True
        s['selected_branch_id'] = branch.id


def _make_quote(client, db_session, admin_user, branch):
    from app.quotations.models import Quotation
    c = Customer(code='C1', name='Acme', is_active=True)
    p = Product(code='W', name='Widget', is_active=True)
    db.session.add_all([c, p]); db.session.commit()
    _login(client, admin_user, branch)
    lines = json.dumps([{'product_id': str(p.id), 'quantity': '2', 'unit_price': '100.00',
                         'vat_category': 'V12', 'vat_rate': '12'}])
    client.post('/quotations/create', data={'customer_id': str(c.id),
        'quotation_date': '2026-07-09', 'valid_until': '2026-08-09',
        'vat_treatment': 'inclusive', 'payment_terms': 'Net 30', 'lines': lines},
        follow_redirects=True)
    return Quotation.query.filter_by(customer_id=c.id).first()


def test_create_form_hides_subtotal_and_vt_keeps_total_and_treatment(client, db_session,
                                                                     admin_user, main_branch):
    _login(client, admin_user, main_branch)
    data = client.get('/quotations/create').data
    assert b'>Subtotal<' not in data          # Subtotal summary row removed
    assert b'>VT<' not in data                 # per-line VT column removed
    assert b'>Total<' in data                  # Total kept
    assert b'VAT Treatment' in data            # header VAT-Treatment control kept


def test_detail_hides_subtotal_and_vt_keeps_total_and_treatment(client, db_session,
                                                                admin_user, main_branch):
    q = _make_quote(client, db_session, admin_user, main_branch)
    data = client.get(f'/quotations/{q.id}').data
    assert b'>Subtotal<' not in data
    assert b'>VT<' not in data
    assert b'>Total<' in data
    assert b'VAT Treatment' in data            # treatment still shown on the detail


def test_print_hides_subtotal_and_vt_keeps_total(client, db_session, admin_user, main_branch):
    q = _make_quote(client, db_session, admin_user, main_branch)
    data = client.get(f'/quotations/{q.id}/print').data
    assert b'>Subtotal<' not in data
    assert b'>VT<' not in data
    assert b'Total' in data


def test_line_vat_category_still_persisted(client, db_session, admin_user, main_branch):
    """Hiding the column must NOT drop the data: the line still stores its
    vat_category (fed to the Quote->SO handoff)."""
    q = _make_quote(client, db_session, admin_user, main_branch)
    assert q.line_items[0].vat_category == 'V12'
    assert q.line_items[0].vat_rate == Decimal('12')
