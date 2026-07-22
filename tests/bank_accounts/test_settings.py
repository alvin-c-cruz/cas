"""Tests for the cash/bank-parent setting + fail-soft leaf-account helper (R-04 slice 1)."""
import pytest
from app.settings import AppSettings

pytestmark = [pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


# Mirrors VALID_FORM_DATA in tests/integration/test_company_settings_views.py --
# minimal set of values that satisfies CompanySettingsForm validation (only
# company_name is DataRequired; the rest are Optional but included so the
# SelectFields round-trip a real choice).
VALID_FORM_DATA = {
    'company_name': 'Acme Trading Corp.',
    'trade_name': 'Acme',
    'company_tin': '123-456-789-000',
    'tin_branch_code': '000',
    'rdo_code': '050',
    'vat_registration_type': 'VAT',
    'company_address': '123 Rizal Ave, Manila',
    'postal_code': '1000',
    'phone': '02-8123-4567',
    'email': 'info@acme.ph',
    'fiscal_year_start': '01',
    'officer_president': 'Juan Dela Cruz',
    'officer_treasurer': 'Maria Santos',
    'officer_secretary': 'Pedro Reyes',
}


def test_leaf_choices_filtered_to_parent(db_session, cash_account, revenue_account):
    from app.bank_accounts import service
    AppSettings.set_setting('cash_bank_parent_account_code', cash_account.code)
    db_session.commit()
    ids = {aid for aid, _ in service.cash_bank_leaf_account_choices()}
    assert cash_account.id in ids
    assert revenue_account.id not in ids


def test_leaf_choices_falls_back_to_cash_named_account_when_unassigned(
        db_session, cash_account, revenue_account):
    """Regression (BUG-CASHBANK-DEFAULT-CODE-STALE): when unassigned AND the
    hardcoded DEFAULT_CASH_BANK_PARENT_CODE ('10100') doesn't exist in this
    instance's COA, the fallback must narrow to whichever top-level Asset account
    has "cash" in its name (here, cash_account itself) -- NOT fail wide open to
    every leaf account in the whole COA."""
    from app.bank_accounts import service
    AppSettings.set_setting('cash_bank_parent_account_code', '')   # unassigned
    db_session.commit()
    ids = {aid for aid, _ in service.cash_bank_leaf_account_choices()}
    assert cash_account.id in ids
    assert revenue_account.id not in ids


def test_leaf_choices_falls_back_to_cash_named_account_when_configured_code_is_stale(
        db_session, cash_account, revenue_account):
    """The literal repro: an explicitly-configured code that doesn't exist in this
    instance's COA (e.g. a leftover '10100' on a 6-digit-scheme instance) must also
    narrow to the cash-named account, not fail wide open."""
    from app.bank_accounts import service
    AppSettings.set_setting('cash_bank_parent_account_code', '99999-does-not-exist')
    db_session.commit()
    ids = {aid for aid, _ in service.cash_bank_leaf_account_choices()}
    assert cash_account.id in ids
    assert revenue_account.id not in ids


def test_leaf_choices_fail_soft_to_all_leaves_when_no_cash_account_exists_either(
        db_session, revenue_account):
    """True last resort: unassigned/stale code AND no top-level "cash"-named Asset
    account exists at all -- only then does it fail all the way open."""
    from app.bank_accounts import service
    AppSettings.set_setting('cash_bank_parent_account_code', '')
    db_session.commit()
    ids = {aid for aid, _ in service.cash_bank_leaf_account_choices()}
    assert revenue_account.id in ids


def test_leaf_choices_excludes_inactive_accounts_when_parent_configured(db_session):
    """Critical fix: _leaf_accounts(parent) must filter is_active=True.

    When a parent account is configured, _leaf_accounts() walks the tree but was
    NOT filtering is_active, inconsistent with the fail-soft branch which filters
    to active leaves only. This test proves inactive descendants are excluded.
    """
    from app.bank_accounts import service
    from app.accounts.models import Account

    # Create a parent account (active, has children so is not itself a leaf)
    parent = Account(
        code='1010', name='Cash and Cash Equivalents',
        account_type='Asset', classification='Current Asset',
        normal_balance='Debit'
    )
    db_session.add(parent)
    db_session.flush()

    # Create an active child leaf
    active_child = Account(
        code='1011', name='Cash on Hand (Active)',
        account_type='Asset', classification='Current Asset',
        normal_balance='Debit', parent_id=parent.id, is_active=True
    )
    db_session.add(active_child)
    db_session.flush()

    # Create an inactive child leaf (should NOT appear in choices)
    inactive_child = Account(
        code='1012', name='Cash on Hand (Archived)',
        account_type='Asset', classification='Current Asset',
        normal_balance='Debit', parent_id=parent.id, is_active=False
    )
    db_session.add(inactive_child)
    db_session.commit()

    # Configure the parent as the cash_bank_parent_account_code
    AppSettings.set_setting('cash_bank_parent_account_code', parent.code)
    db_session.commit()

    # Get the choices
    ids = {aid for aid, _ in service.cash_bank_leaf_account_choices()}

    # Active child should be included
    assert active_child.id in ids, "Active child should be in choices"
    # Inactive child should NOT be included
    assert inactive_child.id not in ids, "Inactive child should NOT be in choices"


class TestCashBankParentAccountCodeSettingsField:
    """Critical-finding fix: cash_bank_parent_account_code was added to
    CompanySettingsForm + SETTINGS_KEYS but never rendered on the Company
    Settings template, so an accountant had no way to set it -- and any other
    settings-page save would silently blank it back to '' (unrendered field ->
    empty POST value -> resaved as ''). This proves the field renders on GET
    and round-trips a real value through POST."""

    def test_field_renders_on_settings_page(self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.get('/settings')
        assert resp.status_code == 200
        assert b'name="cash_bank_parent_account_code"' in resp.data

    def test_saved_when_posted(self, client, db_session, admin_user, main_branch):
        login(client)
        data = dict(VALID_FORM_DATA)
        data['cash_bank_parent_account_code'] = '10150'
        resp = client.post('/settings', data=data, follow_redirects=True)
        assert resp.status_code == 200
        assert b'saved successfully' in resp.data

        assert AppSettings.get_setting('cash_bank_parent_account_code') == '10150'

    def test_get_rerender_shows_the_saved_value(self, client, db_session, admin_user, main_branch):
        login(client)
        data = dict(VALID_FORM_DATA)
        data['cash_bank_parent_account_code'] = '10199'
        client.post('/settings', data=data, follow_redirects=True)

        resp = client.get('/settings')
        assert b'value="10199"' in resp.data

    def test_other_field_save_does_not_blank_this_setting(
            self, client, db_session, admin_user, main_branch):
        """Regression for the exact bug this fix closes: saving the settings
        page for an unrelated field must NOT silently blank this one back to
        '' just because the template didn't render (and therefore didn't
        re-POST) it."""
        login(client)
        first = dict(VALID_FORM_DATA)
        first['cash_bank_parent_account_code'] = '10175'
        client.post('/settings', data=first, follow_redirects=True)
        assert AppSettings.get_setting('cash_bank_parent_account_code') == '10175'

        second = dict(VALID_FORM_DATA)
        second['trade_name'] = 'Acme Renamed'
        second['cash_bank_parent_account_code'] = '10175'  # as the rendered form would re-submit
        resp = client.post('/settings', data=second, follow_redirects=True)
        assert resp.status_code == 200

        assert AppSettings.get_setting('cash_bank_parent_account_code') == '10175'
