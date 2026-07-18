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


def test_leaf_choices_fail_soft_when_unassigned(db_session, cash_account, revenue_account):
    from app.bank_accounts import service
    AppSettings.set_setting('cash_bank_parent_account_code', '')   # unassigned
    db_session.commit()
    ids = {aid for aid, _ in service.cash_bank_leaf_account_choices()}
    assert revenue_account.id in ids              # falls back to ALL leaves


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
