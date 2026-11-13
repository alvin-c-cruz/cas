"""The cheque payee is the voucher's own field, defaulted from the payee's master (plan item 2.3).

Owner, 28 Oct 2026 (root work order 2026-10-28-recommendation-cdv-check-payee-per-voucher): "the CDV
should have option to change the Payee of the check in the CDV. the default will come from the
maintenance"; "employee should have option to change payee name. sometimes employee has no own bank
account." Owner's answers, 2 Nov 2026: backfill existing CDVs from the alias they print today; V202 and
V063's master Check Payee Name go back to blank at the deploy (data, not code); employees too.

Pinned here:
- A cheque CDV stores "Pay to (on cheque)"; blank means the master default, filled on the server:
  the vendor's Check Payee Name, else its name; the employee's Check Payee Name, else the full name.
- The cheque prints the voucher's value; a CDV with none (saved before this) prints exactly as before.
- A typed override (CASH) never touches the vendor master.
- The pre-printed voucher's "Check Payee" line prints the stored name only when it differs from the
  payee name, so untouched vouchers print as before (owner, 12 Nov 2026: "PNT C" -- the printed-twice
  question is decided after this is built).
- Employees get a Check Payee Name on their master.
- The migration backfills every cheque CDV with what it prints today.
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app import db
from app.audit.models import AuditLog
from app.cash_disbursements.models import CashDisbursementVoucher
from app.employees.models import Employee
from app.vendors.models import Vendor
from tests.integration.test_cdv_number_editable import login, setup_accounts

pytestmark = [pytest.mark.integration, pytest.mark.cash_disbursements]


@pytest.fixture
def accounts(db_session):
    ap, wt, cash, exp = setup_accounts(db_session)
    return dict(ap=ap, wt=wt, cash=cash, exp=exp)


@pytest.fixture
def vendors(db_session):
    plain = Vendor(code='PAY01', name='Plain Vendor Inc.', is_active=True)
    aliased = Vendor(code='PAY02', name='Aliased Vendor Corp.', check_payee_name='ALIAS ON CHEQUE', is_active=True)
    db_session.add_all([plain, aliased]); db_session.commit()
    return plain, aliased


@pytest.fixture
def employee(db_session, main_branch):
    e = Employee(employee_no='E-PAY-1', first_name='Lawrence', last_name='Kiok',
                 branch_id=main_branch.id, is_active=True)
    db_session.add(e); db_session.commit()
    return e


def _open(client, branch):
    login(client)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id


def _post(client, accounts, payee, number='CHQ-1', method='check', check_payee=None, url='/cash-disbursements/create',
          row_version=None):
    data = {
        'cdv_number': number, 'cdv_date': '2026-11-12', 'payee': payee,
        'payment_method': method, 'cash_account_id': accounts['cash'].id, 'notes': 'cheque payee test',
        'check_number': number + '-S' if method == 'check' else '', 'check_date': '2026-11-12',
        'check_bank': 'CHINA BANK' if method == 'check' else '',
        'ap_lines': json.dumps([]),
        'expense_lines': json.dumps([{'description': 'x', 'amount': 100.0, 'vat_category': '',
                                      'account_id': accounts['exp'].id, 'wt_id': None}]),
        'vat_override': '0', 'vat_override_value': '0', 'wt_override': '0', 'wt_override_value': '0',
    }
    if check_payee is not None:
        data['check_payee_name'] = check_payee
    if row_version is not None:
        data['row_version'] = row_version
    return client.post(url, data=data, follow_redirects=True)


def _cdv(number='CHQ-1'):
    return CashDisbursementVoucher.query.filter_by(cdv_number=number).one()


# ------------------------------------------------------------- saving it
class TestSaving:

    def test_a_vendor_without_an_alias_defaults_to_its_name(self, client, db_session, admin_user, main_branch,
                                                              accounts, vendors):
        plain, _ = vendors
        _open(client, main_branch)
        _post(client, accounts, f'vendor:{plain.id}')          # no field posted, as a drafting script does
        assert _cdv().check_payee_name == 'Plain Vendor Inc.'

    def test_a_vendor_with_an_alias_defaults_to_the_alias(self, client, db_session, admin_user, main_branch,
                                                            accounts, vendors):
        _, aliased = vendors
        _open(client, main_branch)
        _post(client, accounts, f'vendor:{aliased.id}', check_payee='')
        assert _cdv().check_payee_name == 'ALIAS ON CHEQUE'

    def test_a_typed_payee_is_kept_and_the_master_is_untouched(self, client, db_session, admin_user, main_branch,
                                                                 accounts, vendors):
        _, aliased = vendors
        _open(client, main_branch)
        _post(client, accounts, f'vendor:{aliased.id}', check_payee='  CASH ')
        assert _cdv().check_payee_name == 'CASH'
        db_session.refresh(aliased)
        assert aliased.check_payee_name == 'ALIAS ON CHEQUE'

    def test_a_cash_payment_stores_none(self, client, db_session, admin_user, main_branch, accounts, vendors):
        plain, _ = vendors
        _open(client, main_branch)
        _post(client, accounts, f'vendor:{plain.id}', method='cash', check_payee='CASH')
        assert _cdv().check_payee_name is None

    def test_an_employee_defaults_to_the_full_name(self, client, db_session, admin_user, main_branch,
                                                     accounts, employee):
        _open(client, main_branch)
        _post(client, accounts, f'employee:{employee.id}')
        assert _cdv().check_payee_name == employee.full_name

    def test_an_employee_with_a_check_payee_name_defaults_to_it(self, client, db_session, admin_user, main_branch,
                                                                  accounts, employee):
        employee.check_payee_name = 'CASH'
        db_session.commit()
        _open(client, main_branch)
        _post(client, accounts, f'employee:{employee.id}')
        assert _cdv().check_payee_name == 'CASH'

    def test_an_edit_changes_it_and_the_audit_shows_both(self, client, db_session, admin_user, main_branch,
                                                           accounts, vendors):
        plain, _ = vendors
        _open(client, main_branch)
        _post(client, accounts, f'vendor:{plain.id}')
        cdv = _cdv()
        _post(client, accounts, f'vendor:{plain.id}', check_payee='CASH', url=f'/cash-disbursements/{cdv.id}/edit',
              row_version=cdv.row_version)
        db_session.refresh(cdv)
        assert cdv.check_payee_name == 'CASH'
        audit = (AuditLog.query.filter_by(module='cash_disbursement', action='update', record_id=cdv.id)
                 .order_by(AuditLog.id.desc()).first())
        assert audit is not None
        assert 'Plain Vendor Inc.' in (audit.old_values or '') and 'CASH' in (audit.new_values or '')

    def test_the_form_has_the_box_beside_the_cheque_fields(self, client, db_session, admin_user, main_branch,
                                                             accounts, vendors):
        _open(client, main_branch)
        html = client.get('/cash-disbursements/create').get_data(as_text=True)
        block = re.search(r'<div id="checkFields".*?</div>\s*</div>?', html, re.S)
        assert 'name="check_payee_name"' in html
        assert 'Pay to (on cheque)' in html

    def test_the_payee_defaults_give_the_cheque_payee(self, client, db_session, admin_user, main_branch,
                                                        accounts, vendors, employee):
        plain, aliased = vendors
        _open(client, main_branch)
        get = lambda p: client.get('/cash-disbursements/payee-defaults', query_string={'payee': p}).get_json()
        assert get(f'vendor:{plain.id}')['check_payee'] == 'Plain Vendor Inc.'
        assert get(f'vendor:{aliased.id}')['check_payee'] == 'ALIAS ON CHEQUE'
        assert get(f'employee:{employee.id}')['check_payee'] == employee.full_name

    def test_the_view_page_shows_it(self, client, db_session, admin_user, main_branch, accounts, vendors):
        plain, _ = vendors
        _open(client, main_branch)
        _post(client, accounts, f'vendor:{plain.id}', check_payee='CASH')
        html = client.get(f'/cash-disbursements/{_cdv().id}').get_data(as_text=True)
        assert 'Pay to (on cheque)' in html and 'CASH' in html


# ------------------------------------------------------------- printing it
class TestPrinting:

    def test_the_cheque_prints_the_vouchers_payee(self, app, db_session, main_branch, accounts, vendors):
        from app.cash_disbursements.views import _build_check_values
        from app.cash_disbursements.check_layout import get_layout
        _, aliased = vendors
        cdv = _make_cdv(db_session, main_branch, accounts, aliased, check_payee_name='CASH')
        values, err = _build_check_values(cdv, get_layout())
        assert err is None and values['payee'] == 'CASH'

    def test_a_cdv_without_a_value_prints_as_before(self, app, db_session, main_branch, accounts, vendors):
        from app.cash_disbursements.views import _build_check_values
        from app.cash_disbursements.check_layout import get_layout
        plain, aliased = vendors
        old_aliased = _make_cdv(db_session, main_branch, accounts, aliased, number='OLD-1')
        old_plain = _make_cdv(db_session, main_branch, accounts, plain, number='OLD-2')
        assert _build_check_values(old_aliased, get_layout())[0]['payee'] == 'ALIAS ON CHEQUE'
        assert _build_check_values(old_plain, get_layout())[0]['payee'] == 'Plain Vendor Inc.'

    @pytest.mark.parametrize('vendor_index, stored, expected', [
        (1, 'CASH', 'CASH'),                       # an override prints
        (0, 'Plain Vendor Inc.', ''),              # the payee's own name: blank, as before (no alias)
        (1, 'ALIAS ON CHEQUE', 'ALIAS ON CHEQUE'), # the alias, as before
        (1, None, 'ALIAS ON CHEQUE'),              # saved before 2.3: the live alias, as before
        (0, None, ''),
    ])
    def test_the_voucher_check_payee_line(self, client, db_session, admin_user, main_branch, accounts, vendors,
                                          vendor_index, stored, expected):
        from app.settings import AppSettings
        vendor = vendors[vendor_index]
        cdv = _make_cdv(db_session, main_branch, accounts, vendor, check_payee_name=stored)
        AppSettings.set_setting('cd_print_form', 'preprinted'); db.session.commit()
        _open(client, main_branch)
        html = client.get(f'/cash-disbursements/{cdv.id}/print').get_data(as_text=True)
        m = re.search(r'data-el="check_payee"[^>]*>([^<]*)<', html)
        assert m, 'check_payee field not drawn'
        assert m.group(1).strip() == expected


def _make_cdv(db_session, branch, accounts, vendor, number='PRN-1', check_payee_name=None):
    from datetime import date
    from decimal import Decimal
    cdv = CashDisbursementVoucher(
        branch_id=branch.id, cdv_number=number, cdv_date=date(2026, 11, 12),
        payee_type='vendor', payee_id=vendor.id, vendor_id=vendor.id, vendor_name=vendor.name,
        payment_method='check', check_number=number + '-S', check_date=date(2026, 11, 12),
        check_bank='CHINA BANK', cash_account_id=accounts['cash'].id, notes='print test',
        status='posted', total_amount=Decimal('1234.50'), check_payee_name=check_payee_name)
    db_session.add(cdv); db_session.commit()
    return cdv


# ------------------------------------------------------------- the employee master
class TestEmployeeMaster:

    @pytest.fixture
    def employees_on(self, db_session):
        from app.settings import AppSettings
        from app.utils.cache_helpers import clear_module_config_cache
        AppSettings.set_setting('module_enabled:employees', '1'); db.session.commit()
        clear_module_config_cache()
        yield
        clear_module_config_cache()

    def test_the_employee_form_saves_and_audits_it(self, client, db_session, admin_user, main_branch, employee,
                                                     employees_on):
        _open(client, main_branch)
        client.post(f'/employees/{employee.id}/edit', data={
            'employee_no': employee.employee_no, 'first_name': 'Lawrence', 'last_name': 'Kiok',
            'branch_id': str(main_branch.id), 'is_active': '1', 'qualified_dependents': '0', 'user_id': '',
            'check_payee_name': 'CASH'}, follow_redirects=True)
        db_session.refresh(employee)
        assert employee.check_payee_name == 'CASH'
        audit = AuditLog.query.filter_by(module='employee', action='update', record_id=employee.id).first()
        assert 'CASH' in (audit.new_values or '')
        assert employee.to_dict()['check_payee_name'] == 'CASH'


# ------------------------------------------------------------- the migration
CAS_ROOT = Path(__file__).resolve().parents[2]


def _flask_db(args, db_path):
    env = dict(os.environ, SECRET_KEY='migration-test', FLASK_APP='flask_app.py',
               SQLALCHEMY_DATABASE_URI=f'sqlite:///{db_path}')
    env.pop('CAS_EXPECT_COMPANY', None)
    return subprocess.run([sys.executable, '-m', 'flask', 'db', *args], cwd=CAS_ROOT, env=env,
                          capture_output=True, text=True, check=True)


def test_the_migration_backfills_what_each_cheque_prints_today(tmp_path):
    db_path = tmp_path / 'chqpay.db'; db_path.touch()
    _flask_db(['upgrade', 'dslip_0001'], db_path)
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO branches (id, code, name, is_active) VALUES (1, 'B', 'B', 1)")
    con.execute("INSERT INTO accounts (id, code, name, account_type, normal_balance, is_active) "
                "VALUES (1, '1010', 'Cash', 'Asset', 'debit', 1)")
    con.execute("INSERT INTO vendors (id, code, name, check_payee_name, is_active) VALUES "
                "(1, 'V202', 'ASHERPEAK COMPUTER STORE', 'CASH', 1), (2, 'V9', 'PLAIN CO', NULL, 1), "
                "(3, 'V8', 'BLANK ALIAS CO', '  ', 1)")
    con.execute("INSERT INTO employees (id, employee_no, first_name, last_name, branch_id, is_active, "
                "is_salesperson, created_at, updated_at) VALUES (7, 'E1', 'Ana', 'Tang', 1, 1, 0, "
                "'2026-11-12 00:00:00', '2026-11-12 00:00:00')")
    rows = [  # number, payee_type, payee_id, vendor_id, vendor_name, method
        ('1338E', 'vendor', 1, 1, 'ASHERPEAK COMPUTER STORE', 'check'),
        ('C2', 'vendor', 2, 2, 'PLAIN CO', 'check'),
        ('C3', 'vendor', 3, 3, 'BLANK ALIAS CO', 'check'),
        ('C4', 'employee', 7, None, 'Ana Tang', 'check'),
        ('C5', 'vendor', 1, 1, 'ASHERPEAK COMPUTER STORE', 'cash'),
    ]
    for n, ptype, pid, vid, vname, method in rows:
        con.execute("INSERT INTO cash_disbursement_vouchers (branch_id, cdv_number, cdv_date, vendor_id, "
                    "vendor_name, payee_type, payee_id, payment_method, cash_account_id, status, notes, "
                    "total_ap_applied, total_expense, total_vat, total_wt, total_amount, vat_override, "
                    "wt_override, created_at, updated_at) VALUES (1, ?, '2026-10-22', ?, ?, ?, ?, ?, 1, "
                    "'posted', '', 0, 0, 0, 0, 1, 0, 0, '2026-10-22 00:00:00', '2026-10-22 00:00:00')",
                    (n, vid, vname, ptype, pid, method))
    con.commit(); con.close()

    _flask_db(['upgrade', 'chqpay_0001'], db_path)
    con = sqlite3.connect(db_path)
    got = dict(con.execute("SELECT cdv_number, check_payee_name FROM cash_disbursement_vouchers"))
    assert got == {'1338E': 'CASH', 'C2': 'PLAIN CO', 'C3': 'BLANK ALIAS CO', 'C4': 'Ana Tang', 'C5': None}
    assert con.execute("SELECT check_payee_name FROM employees").fetchall() == [(None,)]
    assert con.execute("SELECT check_payee_name FROM vendors WHERE id = 1").fetchone() == ('CASH',)  # master untouched
    con.close()

    _flask_db(['downgrade', 'dslip_0001'], db_path)
    con = sqlite3.connect(db_path)
    assert 'check_payee_name' not in {r[1] for r in con.execute("PRAGMA table_info(cash_disbursement_vouchers)")}
    assert 'check_payee_name' not in {r[1] for r in con.execute("PRAGMA table_info(employees)")}
    assert con.execute("PRAGMA integrity_check").fetchone() == ('ok',)
    con.close()
