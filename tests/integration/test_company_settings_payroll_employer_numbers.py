import pytest
from app.settings import AppSettings
from app.utils.bir_books import get_company_identity

pytestmark = [pytest.mark.integration]


def _login_admin(client):
    """Login as admin user"""
    client.post('/login', data={
        'username': 'admin',
        'password': 'admin123'
    }, follow_redirects=True)


# Minimal form data with all required fields
VALID_FORM_DATA = {
    'company_name': 'Test Co',
    'trade_name': '',
    'company_tin': '',
    'tin_branch_code': '',
    'rdo_code': '',
    'vat_registration_type': 'VAT',
    'company_address': '',
    'postal_code': '',
    'phone': '',
    'email': '',
    'fiscal_year_start': '01',
    'officer_president': '',
    'officer_treasurer': '',
    'officer_secretary': '',
    'apv_print_access': 'posted_only',
    'sv_print_access': 'posted_only',
    'sv_print_form': 'current',
    'so_print_form': 'current',
    'cd_print_access': 'posted_only',
    'cd_check_print_access': 'posted_only',
    'cr_print_access': 'posted_only',
    'cr_print_form': 'current',
    'ap_print_form': 'current',
    'cd_print_form': 'current',
    'jv_print_form': 'current',
    'payroll_semi_monthly_timing': 'second_cutoff',
    'payslip_print_access': 'posted_only',
    'payslip_print_form': 'current',
    'sss_employer_no': '03-1234567-8',
    'philhealth_employer_no': '01-234567890-1',
    'pagibig_employer_no': '1234-5678-9012',
}


class TestPayrollEmployerNumberSettings:
    def test_save_and_read_back_employer_numbers(self, client, db_session, admin_user, main_branch):
        _login_admin(client)
        resp = client.post('/settings', data=VALID_FORM_DATA, follow_redirects=True)
        assert resp.status_code == 200
        assert AppSettings.get_setting('sss_employer_no') == '03-1234567-8'
        assert AppSettings.get_setting('philhealth_employer_no') == '01-234567890-1'
        assert AppSettings.get_setting('pagibig_employer_no') == '1234-5678-9012'

    def test_get_company_identity_includes_employer_numbers(self, db_session):
        AppSettings.set_setting('sss_employer_no', '03-1234567-8')
        company = get_company_identity()
        assert company['sss_employer_no'] == '03-1234567-8'
        assert company['philhealth_employer_no'] == ''
        assert company['pagibig_employer_no'] == ''
