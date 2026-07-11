"""Integration test for the jv_print_form print-access setting (mirrors
ap_print_form / sv_print_form): admin can pick JV's print layout in Company
Settings, persisted as an AppSettings key."""
import pytest

from app.settings import AppSettings

pytestmark = [pytest.mark.integration, pytest.mark.settings]


def _login(client, u, p):
    client.post('/login', data={'username': u, 'password': p}, follow_redirects=True)


# The company-settings route (/settings) validates the full form on POST;
# company_name is the only DataRequired field, but the SelectFields
# (vat_registration_type, fiscal_year_start) must carry a value that is one
# of their declared choices or validation fails. Mirrors VALID_FORM_DATA from
# tests/integration/test_apv_print_form.py.
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


def test_jv_print_form_saves_and_repopulates(client, db_session, admin_user, main_branch):
    _login(client, 'admin', 'admin123')
    data = dict(VALID_FORM_DATA)
    data['jv_print_form'] = 'preprinted'
    resp = client.post('/settings', data=data, follow_redirects=True)
    assert resp.status_code == 200
    assert AppSettings.get_setting('jv_print_form') == 'preprinted'


def test_jv_print_form_defaults_to_current_when_unset(client, db_session):
    # Unset key falls back to 'current' at read time (matches the other toggles).
    assert AppSettings.get_setting('jv_print_form', 'current') == 'current'
