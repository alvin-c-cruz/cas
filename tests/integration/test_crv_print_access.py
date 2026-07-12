"""Integration tests for cr_print_access gate on the Cash Receipt detail page."""
import pytest
from decimal import Decimal
from datetime import date

from app.settings import AppSettings
from app.customers.models import Customer
from app.accounts.models import Account
from app.cash_receipts.models import CashReceiptVoucher

pytestmark = [pytest.mark.cash_receipts, pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


@pytest.fixture
def _customer(db_session):
    c = Customer(code='C001', name='Test Customer', is_active=True)
    db_session.add(c); db_session.commit()
    return c


@pytest.fixture
def _cash_account(db_session):
    a = Account(code='10101', name='Cash on Hand',
                account_type='Asset', normal_balance='debit', is_active=True)
    db_session.add(a); db_session.commit()
    return a


@pytest.fixture
def _draft_crv(db_session, main_branch, _customer, _cash_account):
    crv = CashReceiptVoucher(
        branch_id=main_branch.id,
        crv_number='CR-2026-06-0001',
        crv_date=date(2026, 6, 14),
        customer_id=_customer.id,
        customer_name=_customer.name,
        payment_method='cash',
        cash_account_id=_cash_account.id,
        notes='',
        status='draft',
        total_amount=Decimal('0.00'),
    )
    db_session.add(crv); db_session.commit()
    return crv


class TestCrvPrintAccessGate:
    def test_posted_only_hides_print_on_draft(
            self, client, db_session, admin_user, main_branch,
            _customer, _cash_account, _draft_crv):
        AppSettings.set_setting('cr_print_access', 'posted_only', 'system')
        login(client)
        resp = client.get(f'/cash-receipts/{_draft_crv.id}')
        assert resp.status_code == 200
        assert f'/cash-receipts/{_draft_crv.id}/print' not in resp.data.decode()

    def test_draft_and_posted_shows_print_on_draft(
            self, client, db_session, admin_user, main_branch,
            _customer, _cash_account, _draft_crv):
        AppSettings.set_setting('cr_print_access', 'draft_and_posted', 'system')
        login(client)
        resp = client.get(f'/cash-receipts/{_draft_crv.id}')
        assert resp.status_code == 200
        assert f'/cash-receipts/{_draft_crv.id}/print' in resp.data.decode()

    def test_route_itself_refuses_a_draft_under_posted_only(
            self, client, db_session, admin_user, main_branch,
            _customer, _cash_account, _draft_crv):
        """BUG-DOCPRINT-ACCESS-GATE-ROUTE-BYPASS: the button hides correctly, but the
        ROUTE must refuse too -- a direct GET must not bypass the same gate."""
        AppSettings.set_setting('cr_print_access', 'posted_only', 'system')
        login(client)
        resp = client.get(f'/cash-receipts/{_draft_crv.id}/print', follow_redirects=False)
        assert resp.status_code in (302, 303)

    def test_route_allows_once_posted(
            self, client, db_session, admin_user, main_branch,
            _customer, _cash_account, _draft_crv):
        AppSettings.set_setting('cr_print_access', 'posted_only', 'system')
        _draft_crv.status = 'posted'
        db_session.commit()
        login(client)
        resp = client.get(f'/cash-receipts/{_draft_crv.id}/print')
        assert resp.status_code == 200

    def test_button_hidden_when_cr_print_form_is_hidden_even_if_access_allows(
            self, client, db_session, admin_user, main_branch,
            _customer, _cash_account, _draft_crv):
        """Button-side addendum: cr_print_form=hidden must hide the button too, not
        just cr_print_access -- previously the button ignored print_form entirely
        (BUG-DOCPRINT-ACCESS-GATE-ROUTE-BYPASS button-side addendum, first caught by
        clients/cas/ui-tests/cash_receipt_crud_post.py)."""
        AppSettings.set_setting('cr_print_access', 'draft_and_posted', 'system')
        AppSettings.set_setting('cr_print_form', 'hidden', 'system')
        login(client)
        resp = client.get(f'/cash-receipts/{_draft_crv.id}')
        assert resp.status_code == 200
        assert f'/cash-receipts/{_draft_crv.id}/print' not in resp.data.decode()
