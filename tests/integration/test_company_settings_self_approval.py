import pytest
from app.settings import AppSettings
from app.audit.models import AuditLog

pytestmark = [pytest.mark.integration]


def _login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)


def _base_form(**overrides):
    data = {
        'company_name': 'ABC Company',
        'vat_registration_type': 'VAT',
        'fiscal_year_start': '01',
        'apv_print_access': 'posted_only',
        'sv_print_access': 'posted_only',
        'cd_print_access': 'posted_only',
        'cr_print_access': 'posted_only',
    }
    data.update(overrides)
    return data


def test_admin_enables_self_approval(client, db_session, admin_user, main_branch):
    _login(client)
    resp = client.post('/settings', data=_base_form(accountant_email_self_approval='y'),
                       follow_redirects=True)
    assert resp.status_code == 200
    assert AppSettings.get_setting('accountant_email_self_approval') == '1'
    audit = AuditLog.query.filter_by(module='settings', action='update').order_by(AuditLog.id.desc()).first()
    assert audit is not None
    assert 'accountant_email_self_approval' in (audit.new_values or '')


def test_admin_disables_self_approval(client, db_session, admin_user, main_branch):
    AppSettings.set_setting('accountant_email_self_approval', '1')
    _login(client)
    # checkbox omitted from POST → unchecked → stored '0'
    resp = client.post('/settings', data=_base_form(), follow_redirects=True)
    assert resp.status_code == 200
    assert AppSettings.get_setting('accountant_email_self_approval') == '0'
    audit = AuditLog.query.filter_by(module='settings', action='update').order_by(AuditLog.id.desc()).first()
    assert audit is not None
    assert 'accountant_email_self_approval' in (audit.new_values or '')
