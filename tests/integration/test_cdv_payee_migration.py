"""The CDV's polymorphic payee: columns, properties and the migration.

Mirrors the APV's 2026-07-08 change (d9bebfed48f3). Every pre-existing CDV is
a vendor payment, so the backfill sets payee_type='vendor', payee_id=vendor_id
and changes no meaning.
"""
import os
import sqlite3
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.cash_disbursements]


def test_model_defaults_to_a_vendor_payee(db_session, main_branch):
    from app.cash_disbursements.models import CashDisbursementVoucher
    from app.vendors.models import Vendor
    from app.accounts.models import Account
    v = Vendor(code='MIGV1', name='Mig Vendor', is_active=True)
    cash = Account(code='10190', name='Cash', account_type='Asset', normal_balance='debit', is_active=True)
    db_session.add_all([v, cash]); db_session.commit()
    cdv = CashDisbursementVoucher(branch_id=main_branch.id, cdv_number='MIG-1', cdv_date=date(2026, 9, 24),
                                  vendor_id=v.id, vendor_name=v.name, payee_type='vendor', payee_id=v.id,
                                  payment_method='cash', cash_account_id=cash.id, status='draft',
                                  total_amount=Decimal('1'))
    db_session.add(cdv); db_session.commit()
    assert cdv.payee is v
    assert cdv.payee_display_name == 'Mig Vendor'
    assert cdv.to_dict()['payee_type'] == 'vendor'


def test_an_employee_payee_needs_no_vendor(db_session, main_branch):
    from app.cash_disbursements.models import CashDisbursementVoucher
    from app.employees.models import Employee
    from app.accounts.models import Account
    e = Employee(employee_no='E-MIG', first_name='Ana', last_name='Cruz', branch_id=main_branch.id, is_active=True)
    cash = Account(code='10191', name='Cash', account_type='Asset', normal_balance='debit', is_active=True)
    db_session.add_all([e, cash]); db_session.commit()
    cdv = CashDisbursementVoucher(branch_id=main_branch.id, cdv_number='MIG-2', cdv_date=date(2026, 9, 24),
                                  vendor_id=None, vendor_name=e.full_name, payee_type='employee', payee_id=e.id,
                                  payment_method='cash', cash_account_id=cash.id, status='draft',
                                  total_amount=Decimal('1'))
    db_session.add(cdv); db_session.commit()          # vendor_id NULL must be allowed
    assert cdv.payee is e
    assert cdv.payee_display_name == e.full_name


CAS_ROOT = Path(__file__).resolve().parents[2]


def _run_flask(args, db_path):
    env = dict(os.environ, SECRET_KEY='migration-test', FLASK_APP='flask_app.py',
               SQLALCHEMY_DATABASE_URI=f'sqlite:///{db_path}', CAS_EXPECT_COMPANY='')
    env.pop('CAS_EXPECT_COMPANY')          # the company guard is for the launcher, not for tests
    return subprocess.run([sys.executable, '-m', 'flask', 'db', *args], cwd=CAS_ROOT, env=env,
                          capture_output=True, text=True, check=True)


def test_upgrade_backfills_every_existing_cdv_as_a_vendor_payment(tmp_path):
    """Real migration history, not create_all(): the pre-cdvpay schema is built by
    upgrading a fresh file to vbank_0001, a vendor CDV is inserted the OLD way, then
    cdvpay_0001 runs."""
    db_path = tmp_path / 'cdvpay.db'; db_path.touch()
    _run_flask(['upgrade', 'vbank_0001'], db_path)
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO branches (code, name, is_active) VALUES ('B', 'B', 1)")
    con.execute("INSERT INTO vendors (code, name, is_active) VALUES ('V1', 'Vendor One', 1)")
    con.execute("INSERT INTO accounts (code, name, account_type, normal_balance, is_active) "
                "VALUES ('1010', 'Cash', 'Asset', 'debit', 1)")
    con.execute("INSERT INTO cash_disbursement_vouchers (branch_id, cdv_number, cdv_date, vendor_id, "
                "vendor_name, payment_method, cash_account_id, status, notes, total_ap_applied, "
                "total_expense, total_vat, total_wt, total_amount, vat_override, wt_override, "
                "created_at, updated_at) "
                "VALUES (1, 'OLD-1', '2026-09-01', 1, 'Vendor One', 'cash', 1, 'posted', '', 0, 0, 0, 0, 1, "
                "0, 0, '2026-09-01 00:00:00', '2026-09-01 00:00:00')")
    con.commit(); con.close()

    _run_flask(['upgrade', 'cdvpay_0001'], db_path)

    con = sqlite3.connect(db_path)
    assert con.execute("SELECT payee_type, payee_id, vendor_id FROM cash_disbursement_vouchers").fetchall() \
        == [('vendor', 1, 1)]
    cols = {r[1]: r[3] for r in con.execute("PRAGMA table_info(cash_disbursement_vouchers)")}
    assert cols['vendor_id'] == 0, 'vendor_id must be nullable now'
    assert con.execute("PRAGMA integrity_check").fetchone() == ('ok',)
    con.close()


def test_downgrade_reverses_cleanly_without_employee_rows(tmp_path):
    db_path = tmp_path / 'cdvpay-down.db'; db_path.touch()
    _run_flask(['upgrade', 'cdvpay_0001'], db_path)
    _run_flask(['downgrade', 'vbank_0001'], db_path)
    con = sqlite3.connect(db_path)
    names = {r[1] for r in con.execute("PRAGMA table_info(cash_disbursement_vouchers)")}
    assert 'payee_type' not in names and 'payee_id' not in names
    con.close()


def test_downgrade_refuses_over_an_employee_cdv(tmp_path):
    db_path = tmp_path / 'cdvpay-refuse.db'; db_path.touch()
    _run_flask(['upgrade', 'cdvpay_0001'], db_path)
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO branches (code, name, is_active) VALUES ('B', 'B', 1)")
    con.execute("INSERT INTO accounts (code, name, account_type, normal_balance, is_active) "
                "VALUES ('1010', 'Cash', 'Asset', 'debit', 1)")
    con.execute("INSERT INTO cash_disbursement_vouchers (branch_id, cdv_number, cdv_date, vendor_id, "
                "vendor_name, payee_type, payee_id, payment_method, cash_account_id, status, notes, "
                "total_ap_applied, total_expense, total_vat, total_wt, total_amount, vat_override, "
                "wt_override, created_at, updated_at) VALUES (1, 'EMP-1', '2026-09-24', NULL, 'Ana Cruz', "
                "'employee', 7, 'cash', 1, 'posted', '', 0, 0, 0, 0, 1, 0, 0, "
                "'2026-09-24 00:00:00', '2026-09-24 00:00:00')")
    con.commit(); con.close()
    with pytest.raises(subprocess.CalledProcessError) as exc:
        _run_flask(['downgrade', 'vbank_0001'], db_path)
    assert 'employee-payee CDV' in exc.value.stderr
