"""Company setting si_dr_billing_consolidate (default OFF)."""
import pytest
from app.settings import AppSettings

pytestmark = [pytest.mark.integration]


def _login(client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)


def _base_form(**overrides):
    data = {
        'company_name': 'ABC Company',
        'vat_registration_type': 'VAT',
        'fiscal_year_start': '01',
        'apv_print_access': 'posted_only',
        'sv_print_access': 'posted_only',
        'cd_print_access': 'posted_only',
        'cd_check_print_access': 'posted_only',
        'cr_print_access': 'posted_only',
    }
    data.update(overrides)
    return data


def test_default_consolidate_is_off(client, db_session, admin_user, main_branch):
    assert AppSettings.get_setting('si_dr_billing_consolidate', '0') == '0'


def test_admin_enables_consolidate(client, db_session, admin_user, main_branch):
    _login(client)
    resp = client.post('/settings', data=_base_form(si_dr_billing_consolidate='y'),
                       follow_redirects=True)
    assert resp.status_code == 200
    assert AppSettings.get_setting('si_dr_billing_consolidate') == '1'


def test_admin_disables_consolidate(client, db_session, admin_user, main_branch):
    AppSettings.set_setting('si_dr_billing_consolidate', '1')
    _login(client)
    resp = client.post('/settings', data=_base_form(), follow_redirects=True)  # checkbox omitted
    assert resp.status_code == 200
    assert AppSettings.get_setting('si_dr_billing_consolidate') == '0'
