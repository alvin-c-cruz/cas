"""Integration tests for the CRV pre-printed print form: the cr_print_form
setting (P2) and the print-route branch + save route (P3)."""
import pytest

from app.settings import AppSettings
pytestmark = [pytest.mark.cash_receipts, pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


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


class TestCrPrintFormSetting:
    def test_default_is_current_when_unset(self, db_session):
        assert AppSettings.get_setting('cr_print_form', 'current') == 'current'

    def test_settings_page_renders_cr_print_form_control(
            self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.get('/settings')
        assert resp.status_code == 200
        assert b'cr_print_form' in resp.data          # the select name is present

    def test_admin_post_persists_cr_print_form(
            self, client, db_session, admin_user, main_branch):
        login(client)
        data = dict(VALID_FORM_DATA)
        data['cr_print_form'] = 'preprinted'
        resp = client.post('/settings', data=data, follow_redirects=True)
        assert resp.status_code == 200
        assert AppSettings.get_setting('cr_print_form') == 'preprinted'

    def test_accountant_cannot_set_cr_print_form(
            self, client, db_session, accountant_user, main_branch):
        login(client, username='accountant', password='accountant123')
        data = dict(VALID_FORM_DATA)
        data['cr_print_form'] = 'preprinted'
        client.post('/settings', data=data, follow_redirects=True)
        # admin_panel_required: non-admin can't write the setting
        assert AppSettings.get_setting('cr_print_form', 'current') == 'current'
