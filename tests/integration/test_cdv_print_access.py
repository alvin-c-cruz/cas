"""Integration tests for cd_print_access gate on the CDV detail page."""
import pytest
from decimal import Decimal
from datetime import date

from app.settings import AppSettings
from app.vendors.models import Vendor
from app.accounts.models import Account
from app.cash_disbursements.models import CashDisbursementVoucher

pytestmark = [pytest.mark.cash_disbursements, pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


@pytest.fixture
def _vendor(db_session):
    v = Vendor(code='V001', name='Test Vendor',
               check_payee_name='Test Vendor', is_active=True)
    db_session.add(v)
    db_session.commit()
    return v


@pytest.fixture
def _cash_account(db_session):
    a = Account(code='10101', name='Cash on Hand',
                account_type='Asset', normal_balance='debit', is_active=True)
    db_session.add(a)
    db_session.commit()
    return a


@pytest.fixture
def _draft_cdv(db_session, main_branch, _vendor, _cash_account):
    cdv = CashDisbursementVoucher(
        branch_id=main_branch.id,
        cdv_number='CD-2026-06-0001',
        cdv_date=date(2026, 6, 14),
        vendor_id=_vendor.id,
        vendor_name=_vendor.name,
        payment_method='cash',
        cash_account_id=_cash_account.id,
        notes='',
        status='draft',
        total_amount=Decimal('0.00'),
    )
    db_session.add(cdv)
    db_session.commit()
    return cdv


class TestCdvPrintAccessGate:
    def test_posted_only_hides_print_on_draft(
            self, client, db_session, admin_user, main_branch,
            _vendor, _cash_account, _draft_cdv):
        AppSettings.set_setting('cd_print_access', 'posted_only', 'system')
        login(client)
        resp = client.get(f'/cash-disbursements/{_draft_cdv.id}')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert f'/cash-disbursements/{_draft_cdv.id}/print' not in html

    def test_draft_and_posted_shows_print_on_draft(
            self, client, db_session, admin_user, main_branch,
            _vendor, _cash_account, _draft_cdv):
        AppSettings.set_setting('cd_print_access', 'draft_and_posted', 'system')
        login(client)
        resp = client.get(f'/cash-disbursements/{_draft_cdv.id}')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert f'/cash-disbursements/{_draft_cdv.id}/print' in html

    def test_posted_only_shows_print_on_posted(
            self, client, db_session, admin_user, main_branch,
            _vendor, _cash_account, _draft_cdv):
        _draft_cdv.status = 'posted'
        db_session.commit()
        AppSettings.set_setting('cd_print_access', 'posted_only', 'system')
        login(client)
        resp = client.get(f'/cash-disbursements/{_draft_cdv.id}')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert f'/cash-disbursements/{_draft_cdv.id}/print' in html

    def test_route_itself_refuses_a_draft_under_posted_only(
            self, client, db_session, admin_user, main_branch,
            _vendor, _cash_account, _draft_cdv):
        """BUG-DOCPRINT-ACCESS-GATE-ROUTE-BYPASS: the button hides correctly, but the
        ROUTE must refuse too -- a direct GET must not bypass the same gate."""
        AppSettings.set_setting('cd_print_access', 'posted_only', 'system')
        login(client)
        resp = client.get(f'/cash-disbursements/{_draft_cdv.id}/print', follow_redirects=False)
        assert resp.status_code in (302, 303)

    def test_route_allows_once_posted(
            self, client, db_session, admin_user, main_branch,
            _vendor, _cash_account, _draft_cdv):
        AppSettings.set_setting('cd_print_access', 'posted_only', 'system')
        _draft_cdv.status = 'posted'
        db_session.commit()
        login(client)
        resp = client.get(f'/cash-disbursements/{_draft_cdv.id}/print')
        assert resp.status_code == 200

    def test_button_hidden_when_cd_print_form_is_hidden_even_if_access_allows(
            self, client, db_session, admin_user, main_branch,
            _vendor, _cash_account, _draft_cdv):
        """Button-side addendum: cd_print_form=hidden must hide the button too, not
        just cd_print_access -- previously the button ignored print_form entirely
        (BUG-DOCPRINT-ACCESS-GATE-ROUTE-BYPASS button-side addendum)."""
        AppSettings.set_setting('cd_print_access', 'draft_and_posted', 'system')
        AppSettings.set_setting('cd_print_form', 'hidden', 'system')
        login(client)
        resp = client.get(f'/cash-disbursements/{_draft_cdv.id}')
        assert resp.status_code == 200
        assert f'/cash-disbursements/{_draft_cdv.id}/print' not in resp.data.decode()
