"""Manufacturing mode settings tests (R-07 Wave 0)."""
import pytest
from app.settings import AppSettings

pytestmark = [pytest.mark.integration]


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def test_settings_default_off(db_session):
    assert AppSettings.get_setting('manufacturing_discrete_enabled', '0') == '0'
    assert AppSettings.get_setting('manufacturing_process_enabled', '0') == '0'


def test_settings_save_via_form(client, admin_user, db_session, main_branch):
    _login(client, admin_user, main_branch)
    resp = client.post('/settings', data={
        'company_name': 'Test Co', 'vat_registration_type': 'VAT',
        'fiscal_year_start': '01', 'manufacturing_discrete_enabled': 'y',
        'manufacturing_process_enabled': '',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert AppSettings.get_setting('manufacturing_discrete_enabled') == '1'
    # Unchanged False->False is a no-op write (matches every other boolean setting's
    # diff-optimization) -- read with the same default the app itself always uses.
    assert AppSettings.get_setting('manufacturing_process_enabled', '0') == '0'
