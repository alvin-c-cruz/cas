"""CRV printout: Product and Description collapse into a single Description
column. Product (code — name) wins when present; otherwise the description
field; otherwise empty. Printout only — detail/form keep both fields.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache

pytestmark = [pytest.mark.cash_receipts, pytest.mark.integration]


def _login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)


def _crv_with_revenue_lines(db_session, main_branch, cash_account):
    """A posted CRV with two direct-revenue lines: one carrying a product plus a
    decoy description, one carrying only a description."""
    from app.products.models import Product
    from app.customers.models import Customer
    from app.cash_receipts.models import CashReceiptVoucher, CRVRevenueLine
    prod = Product(code='MANGO-001', name='A ONE DRIED MANGO SLICES 100g', is_active=True)
    cust = Customer(code='LONG1', name='Lysander Ong', is_active=True)
    db_session.add_all([prod, cust]); db_session.commit()

    crv = CashReceiptVoucher(branch_id=main_branch.id, crv_number='CRV-MERGE-1',
                             crv_date=date(2026, 9, 16), customer_id=cust.id,
                             customer_name='Lysander Ong',
                             cash_account_id=cash_account.id, status='posted',
                             total_amount=Decimal('1800'))
    crv.revenue_lines.append(CRVRevenueLine(
        line_number=1, product_id=prod.id, description='DECOY-MUST-NOT-PRINT',
        amount=Decimal('1500'), line_total=Decimal('1500')))
    crv.revenue_lines.append(CRVRevenueLine(
        line_number=2, description='CONTRIBUTION MARGIN',
        amount=Decimal('300'), line_total=Decimal('300')))
    db_session.add(crv); db_session.commit()
    return crv


def _get_print(client, db_session, main_branch, cash_account):
    AppSettings.set_setting('module_enabled:products', '1')
    AppSettings.set_setting('cr_print_form', 'current', 'admin')  # the print.html form
    db_session.commit(); clear_module_config_cache()
    crv = _crv_with_revenue_lines(db_session, main_branch, cash_account)
    _login(client)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    resp = client.get(f'/cash-receipts/{crv.id}/print')
    assert resp.status_code == 200
    return resp.data.decode()


def test_printout_has_no_separate_product_column(client, db_session, admin_user, main_branch, cash_account):
    body = _get_print(client, db_session, main_branch, cash_account)
    assert '<th>Product</th>' not in body      # column removed
    assert '<th>Description</th>' in body       # single merged column kept


def test_product_line_shows_product_and_hides_its_description(
        client, db_session, admin_user, main_branch, cash_account):
    body = _get_print(client, db_session, main_branch, cash_account)
    assert 'MANGO-001 — A ONE DRIED MANGO SLICES 100g' in body   # product wins
    assert 'DECOY-MUST-NOT-PRINT' not in body                    # its description is not shown


def test_description_only_line_shows_description(
        client, db_session, admin_user, main_branch, cash_account):
    body = _get_print(client, db_session, main_branch, cash_account)
    assert 'CONTRIBUTION MARGIN' in body
