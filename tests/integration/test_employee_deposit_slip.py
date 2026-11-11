"""Employee bank details and slip form, so a payroll CDV's deposit slip fills itself.

Owner, 10 Nov 2026, while printing the payroll slips (CDVs 1731-1735, 1359E-1364E): "anissa and
lawrence are BDO", "is the deposit slips saved per employee and vendor?" -> "EMP-B, yes queue it";
then "both vendor and employee master data should fill in the deposit slip with account number
as well as the receipt's bank, ei. CBC or BDO"; the slip form on both masters, "VS-1 A ... VS-5 A";
and "A: Build all, no deploy". Work order:
app-docs/bug-reports/2026-11-10-employee-bank-fields-for-deposit-slip.md (beside the checkout).

The employee's fields mirror the vendor's (vbank_0001 and dslip_0001): bank, account name,
account number (text: leading zeros), and the slip form (blank follows the bank name).
"""
import re
from decimal import Decimal

import pytest

from app import db
from app.audit.models import AuditLog
from app.employees.models import Employee
from tests.integration.test_cd_check_print import _check_cdv, _open
from tests.integration.test_employees_crud import employees_module_enabled  # noqa: F401 (fixture)
from tests.integration.test_vendor_deposit_slip_form import BDO, CBC, _notice, _selected, _slip
from tests.integration.test_deposit_slip_cdv import _input, _value

pytestmark = [pytest.mark.integration, pytest.mark.cash_disbursements]

BANK = {'bank_name': 'BDO', 'bank_account_name': 'ANISSA THERESE V. TANG',
        'bank_account_number': '00658 0123 3295'}


def _post(branch, **extra):
    data = {'employee_no': 'EMP-B01', 'first_name': 'Anissa', 'last_name': 'Tang',
            'branch_id': str(branch.id), 'is_active': '1', 'qualified_dependents': '0', 'user_id': ''}
    data.update(extra)
    return data


def _employee(branch, **fields):
    e = Employee(employee_no='EMP-S01', first_name='Anissa', middle_name='Therese V.', last_name='Tang',
                 branch_id=branch.id, is_active=True)
    for k, v in fields.items():
        setattr(e, k, v)
    db.session.add(e); db.session.commit()
    return e


def _employee_cdv(db_session, branch, employee):
    """A posted cheque CDV paid to an employee (payee_type 'employee', no vendor)."""
    cdv = _check_cdv(db_session, branch)
    cdv.payee_type, cdv.payee_id = 'employee', employee.id
    cdv.vendor_id, cdv.vendor_name = None, employee.full_name
    db.session.commit()
    return cdv


def _input_value(html, name):
    m = re.search(r'<input[^>]*name="%s"[^>]*>' % name, html)
    assert m, '%s is not rendered on the employee form' % name
    v = re.search(r'value="([^"]*)"', m.group(0))
    return v.group(1) if v else ''


def _deposit_to(html):
    m = re.search(r'<div class="ds-deposit-to[^"]*"[^>]*>(.*?)</div>', html, re.S)
    return re.sub(r'<[^>]+>', '', m.group(1)).strip() if m else None


# ------------------------------------------------------------- the employee master
class TestEmployeeMaster:

    def test_create_stores_the_bank_details_and_form_and_audits_them(
            self, client, admin_user, branch_manila, login_user, employees_module_enabled):
        login_user(client, 'admin', 'admin123')
        client.post('/employees/create', data=_post(branch_manila, deposit_slip_form=BDO, **BANK),
                    follow_redirects=True)
        e = Employee.query.filter_by(employee_no='EMP-B01').first()
        assert e is not None, 'anti-vacuity: the employee was not created'
        assert (e.bank_name, e.bank_account_name, e.bank_account_number) == (
            'BDO', 'ANISSA THERESE V. TANG', '00658 0123 3295')
        assert e.deposit_slip_form == BDO
        audit = AuditLog.query.filter_by(module='employee', action='create', record_id=e.id).first()
        assert '00658 0123 3295' in (audit.new_values or '') and BDO in (audit.new_values or '')

    def test_blank_details_store_null(self, client, admin_user, branch_manila, login_user,
                                      employees_module_enabled):
        login_user(client, 'admin', 'admin123')
        client.post('/employees/create', data=_post(branch_manila, bank_name='', bank_account_name='',
                                                    bank_account_number='', deposit_slip_form=''),
                    follow_redirects=True)
        e = Employee.query.filter_by(employee_no='EMP-B01').first()
        assert e is not None
        assert e.deposit_slip_form is None
        assert not e.bank_name and not e.bank_account_number

    def test_a_post_without_the_new_fields_still_creates(self, client, admin_user, branch_manila,
                                                         login_user, employees_module_enabled):
        login_user(client, 'admin', 'admin123')
        client.post('/employees/create', data=_post(branch_manila), follow_redirects=True)
        e = Employee.query.filter_by(employee_no='EMP-B01').first()
        assert e is not None and e.deposit_slip_form is None

    def test_an_unknown_form_is_refused(self, client, admin_user, branch_manila, login_user,
                                        employees_module_enabled):
        login_user(client, 'admin', 'admin123')
        client.post('/employees/create', data=_post(branch_manila, deposit_slip_form='bpi_nope'),
                    follow_redirects=True)
        assert Employee.query.filter_by(employee_no='EMP-B01').first() is None

    def test_edit_changes_them_and_audits_before_and_after(
            self, client, admin_user, branch_manila, login_user, employees_module_enabled):
        login_user(client, 'admin', 'admin123')
        e = _employee(branch_manila, bank_account_number='1111')
        client.post(f'/employees/{e.id}/edit',
                    data=_post(branch_manila, employee_no='EMP-S01', bank_name='BDO',
                               bank_account_name='LAWRENCE L KIOK', bank_account_number='2222',
                               deposit_slip_form=BDO),
                    follow_redirects=True)
        db.session.refresh(e)
        assert (e.bank_name, e.bank_account_name, e.bank_account_number, e.deposit_slip_form) == (
            'BDO', 'LAWRENCE L KIOK', '2222', BDO)
        audit = AuditLog.query.filter_by(module='employee', action='update', record_id=e.id).first()
        assert '1111' in (audit.old_values or '') and '2222' in (audit.new_values or '')
        assert BDO in (audit.new_values or '')

    def test_an_edit_without_the_slip_form_keeps_working(
            self, client, admin_user, branch_manila, login_user, employees_module_enabled):
        login_user(client, 'admin', 'admin123')
        e = _employee(branch_manila)
        client.post(f'/employees/{e.id}/edit',
                    data=_post(branch_manila, employee_no='EMP-S01', first_name='Anisa'),
                    follow_redirects=True)
        db.session.refresh(e)
        assert e.first_name == 'Anisa', 'the edit was refused'

    def test_the_edit_form_shows_the_stored_details(
            self, client, admin_user, branch_manila, login_user, employees_module_enabled):
        login_user(client, 'admin', 'admin123')
        e = _employee(branch_manila, deposit_slip_form=BDO, **BANK)
        html = client.get(f'/employees/{e.id}/edit').get_data(as_text=True)
        for k, v in BANK.items():
            assert _input_value(html, k) == v
        assert _selected(html, 'deposit_slip_form') == BDO
        assert 'Bank Details' in html

    def test_the_to_dict_carries_them(self, db_session, branch_manila):
        e = _employee(branch_manila, deposit_slip_form=BDO, **BANK)
        d = e.to_dict()
        assert d['bank_account_number'] == '00658 0123 3295' and d['deposit_slip_form'] == BDO


# ------------------------------------------------------------- the payroll slip
class TestThePayrollSlip:

    def test_the_employees_details_fill_the_slip_on_their_banks_form(
            self, client, db_session, admin_user, main_branch):
        e = _employee(main_branch, **BANK)
        cdv = _employee_cdv(db_session, main_branch, e)
        _open(client, main_branch)
        html = _slip(client, cdv)
        assert _value(html, 'account_name') == 'ANISSA THERESE V. TANG'
        assert _value(html, 'account_number') == '00658 0123 3295'
        assert _input(html, 'account_number') == '00658 0123 3295'
        assert f'<option value="{BDO}" selected>' in html          # BDO in the bank name
        assert _notice(html) is None

    def test_no_account_name_falls_back_to_the_employees_name(
            self, client, db_session, admin_user, main_branch):
        e = _employee(main_branch, bank_name='BDO', bank_account_number='2222')
        cdv = _employee_cdv(db_session, main_branch, e)
        _open(client, main_branch)
        assert _value(_slip(client, cdv), 'account_name') == 'Anissa Therese V. Tang'

    def test_an_employee_with_no_bank_details_prints_blanks_to_type(
            self, client, db_session, admin_user, main_branch):
        e = _employee(main_branch)
        cdv = _employee_cdv(db_session, main_branch, e)
        _open(client, main_branch)
        html = _slip(client, cdv)
        assert _value(html, 'account_number') == ''
        assert f'<option value="{CBC}" selected>' in html
        assert _notice(html) is None

    def test_the_employees_form_wins_over_the_bank_name(self, client, db_session, admin_user, main_branch):
        e = _employee(main_branch, bank_name='CBC', deposit_slip_form=BDO)
        cdv = _employee_cdv(db_session, main_branch, e)
        _open(client, main_branch)
        assert f'<option value="{BDO}" selected>' in _slip(client, cdv)

    def test_another_bank_opens_with_an_employee_notice(self, client, db_session, admin_user, main_branch):
        e = _employee(main_branch, bank_name='BPI')
        cdv = _employee_cdv(db_session, main_branch, e)
        _open(client, main_branch)
        notice = _notice(_slip(client, cdv))
        assert notice and 'BPI' in notice and 'employee maintenance' in notice


# ------------------------------------------------------------- "Deposit to" on the screen
class TestDepositTo:

    def test_a_vendor_slip_names_the_bank_and_account(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        cdv.vendor.bank_name = 'CBC'
        cdv.vendor.bank_account_name = 'MERALCO CORP'
        cdv.vendor.bank_account_number = '188 1109 718'
        db.session.commit()
        _open(client, main_branch)
        assert _deposit_to(_slip(client, cdv)) == 'Deposit to: CBC — MERALCO CORP, 188 1109 718'

    def test_an_employee_slip_names_the_bank_and_account(self, client, db_session, admin_user, main_branch):
        e = _employee(main_branch, **BANK)
        cdv = _employee_cdv(db_session, main_branch, e)
        _open(client, main_branch)
        assert _deposit_to(_slip(client, cdv)) == \
            'Deposit to: BDO — ANISSA THERESE V. TANG, 00658 0123 3295'

    def test_missing_details_are_said_so(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        assert _deposit_to(_slip(client, cdv)) == \
            'Deposit to: bank not on file — Meralco, account number not on file'

    def test_it_is_not_printed(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        assert re.search(r'<div class="ds-deposit-to screen-only"', _slip(client, cdv))
