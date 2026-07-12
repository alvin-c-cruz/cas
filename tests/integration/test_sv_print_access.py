"""Integration tests for sv_print_access gate on the Sales Invoice detail page."""
import pytest
from decimal import Decimal
from datetime import date

from app.settings import AppSettings
from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice

pytestmark = [pytest.mark.sales_invoices, pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


@pytest.fixture
def _customer(db_session):
    c = Customer(code='C001', name='Test Customer', is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


@pytest.fixture
def _invoice(db_session, main_branch, _customer):
    inv = SalesInvoice(
        branch_id=main_branch.id,
        invoice_number='SI-2026-0001',
        invoice_date=date(2026, 6, 14),
        due_date=date(2026, 7, 14),
        customer_id=_customer.id,
        customer_name='Test Customer',
        notes='',
        status='draft',
        amount_paid=Decimal('0.00'),
    )
    db_session.add(inv)
    db_session.commit()
    return inv


class TestSvPrintAccessGate:
    def test_posted_only_hides_print_on_draft(
            self, client, db_session, admin_user, main_branch, _customer, _invoice):
        AppSettings.set_setting('sv_print_access', 'posted_only', 'system')
        login(client)
        resp = client.get(f'/sales-invoices/{_invoice.id}')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert f'/sales-invoices/{_invoice.id}/print' not in html

    def test_draft_and_posted_shows_print_on_draft(
            self, client, db_session, admin_user, main_branch, _customer, _invoice):
        AppSettings.set_setting('sv_print_access', 'draft_and_posted', 'system')
        login(client)
        resp = client.get(f'/sales-invoices/{_invoice.id}')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert f'/sales-invoices/{_invoice.id}/print' in html

    def test_route_itself_refuses_a_draft_under_posted_only(
            self, client, db_session, admin_user, main_branch, _customer, _invoice):
        """BUG-DOCPRINT-ACCESS-GATE-ROUTE-BYPASS: the button hides correctly (tests
        above), but the ROUTE must refuse too -- a direct GET must not bypass the
        same gate the button enforces."""
        AppSettings.set_setting('sv_print_access', 'posted_only', 'system')
        login(client)
        resp = client.get(f'/sales-invoices/{_invoice.id}/print', follow_redirects=False)
        assert resp.status_code in (302, 303)

    def test_route_allows_once_posted(
            self, client, db_session, admin_user, main_branch, _customer, _invoice):
        AppSettings.set_setting('sv_print_access', 'posted_only', 'system')
        _invoice.status = 'posted'
        db_session.commit()
        login(client)
        resp = client.get(f'/sales-invoices/{_invoice.id}/print')
        assert resp.status_code == 200
