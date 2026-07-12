"""Integration tests for apv_print_access gate on the Accounts Payable detail page."""
import pytest
from decimal import Decimal
from datetime import date

from app.settings import AppSettings
from app.vendors.models import Vendor
from app.accounts_payable.models import AccountsPayable

pytestmark = [pytest.mark.accounts_payable, pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


@pytest.fixture
def _vendor(db_session):
    v = Vendor(code='V001', name='Test Vendor', check_payee_name='Test Vendor', is_active=True)
    db_session.add(v); db_session.commit()
    return v


@pytest.fixture
def _ap(db_session, main_branch, admin_user, _vendor):
    ap = AccountsPayable(
        branch_id=main_branch.id, ap_number='APV-ACCESS-0001',
        vendor_id=_vendor.id, vendor_name=_vendor.name,
        ap_date=date(2026, 6, 14), due_date=date(2026, 7, 14),
        payment_terms='Net 30', notes='', status='draft',
        created_by_id=admin_user.id,
        amount_paid=Decimal('0.00'), balance=Decimal('0.00'), total_amount=Decimal('0.00'),
    )
    db_session.add(ap); db_session.commit()
    return ap


class TestApvPrintAccessGate:
    def test_posted_only_hides_print_on_draft(
            self, client, db_session, admin_user, main_branch, _vendor, _ap):
        AppSettings.set_setting('apv_print_access', 'posted_only', 'system')
        login(client)
        resp = client.get(f'/accounts-payable/{_ap.id}')
        assert resp.status_code == 200
        assert f'/accounts-payable/{_ap.id}/print' not in resp.data.decode()

    def test_draft_and_posted_shows_print_on_draft(
            self, client, db_session, admin_user, main_branch, _vendor, _ap):
        AppSettings.set_setting('apv_print_access', 'draft_and_posted', 'system')
        login(client)
        resp = client.get(f'/accounts-payable/{_ap.id}')
        assert resp.status_code == 200
        assert f'/accounts-payable/{_ap.id}/print' in resp.data.decode()

    def test_route_itself_refuses_a_draft_under_posted_only(
            self, client, db_session, admin_user, main_branch, _vendor, _ap):
        """BUG-DOCPRINT-ACCESS-GATE-ROUTE-BYPASS: the button hides correctly, but the
        ROUTE must refuse too -- a direct GET must not bypass the same gate."""
        AppSettings.set_setting('apv_print_access', 'posted_only', 'system')
        login(client)
        resp = client.get(f'/accounts-payable/{_ap.id}/print', follow_redirects=False)
        assert resp.status_code in (302, 303)

    def test_route_allows_once_posted(
            self, client, db_session, admin_user, main_branch, _vendor, _ap):
        AppSettings.set_setting('apv_print_access', 'posted_only', 'system')
        _ap.status = 'posted'
        db_session.commit()
        login(client)
        resp = client.get(f'/accounts-payable/{_ap.id}/print')
        assert resp.status_code == 200

    def test_button_hidden_when_ap_print_form_is_hidden_even_if_access_allows(
            self, client, db_session, admin_user, main_branch, _vendor, _ap):
        """The button-side addendum: apv_print_form=hidden must hide the button too,
        not just apv_print_access -- previously the button ignored print_form
        entirely (BUG-DOCPRINT-ACCESS-GATE-ROUTE-BYPASS button-side addendum)."""
        AppSettings.set_setting('apv_print_access', 'draft_and_posted', 'system')
        AppSettings.set_setting('ap_print_form', 'hidden', 'system')
        login(client)
        resp = client.get(f'/accounts-payable/{_ap.id}')
        assert resp.status_code == 200
        assert f'/accounts-payable/{_ap.id}/print' not in resp.data.decode()
