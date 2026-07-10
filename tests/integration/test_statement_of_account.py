from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice

pytestmark = [pytest.mark.integration, pytest.mark.reports]


def _login(client, u):
    with client.session_transaction() as s:
        s['_user_id'] = str(u.id); s['_fresh'] = True


def _setup(client, admin_user, main_branch):
    c = Customer(code='C1', name='Acme', is_active=True)
    db.session.add(c); db.session.commit()
    si = SalesInvoice(branch_id=main_branch.id, invoice_number='SI-0007',
                      invoice_date=date(2026, 7, 3), due_date=date(2026, 7, 3),
                      customer_id=c.id, customer_name=c.name, notes='', status='posted',
                      total_amount=Decimal('5600.00'), balance=Decimal('5600.00'))
    db.session.add(si); db.session.commit()
    _login(client, admin_user)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    return c


def test_statement_screen_renders(client, db_session, admin_user, main_branch):
    c = _setup(client, admin_user, main_branch)
    resp = client.get(
        f'/reports/statement-of-account?customer_id={c.id}&mode=custom'
        '&date_from=2026-07-01&date_to=2026-07-31')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Statement of Account' in body
    assert 'Balance forward' in body
    assert 'SI-0007' in body
    assert '5,600.00' in body


def test_statement_no_customer_shows_picker(client, db_session, admin_user, main_branch):
    _setup(client, admin_user, main_branch)
    resp = client.get('/reports/statement-of-account')
    assert resp.status_code == 200
    assert 'customer_id' in resp.get_data(as_text=True)   # picker present, no statement yet


def test_statement_print_renders_bir_header(client, db_session, admin_user, main_branch):
    c = _setup(client, admin_user, main_branch)
    resp = client.get(
        f'/reports/statement-of-account/print?customer_id={c.id}&mode=custom'
        '&date_from=2026-07-01&date_to=2026-07-31')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'STATEMENT OF ACCOUNT' in body     # bir_book_header title (upper-case)
    assert 'window.print()' in body
    assert 'SI-0007' in body
