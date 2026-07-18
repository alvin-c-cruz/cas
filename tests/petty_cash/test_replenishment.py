"""Replenishment JE tests (R-04 slice 4)."""
from decimal import Decimal
import pytest
from app import db

pytestmark = [pytest.mark.integration]


def _setup(db_session, main_branch, cash_account, revenue_account, staff_user):
    from app.petty_cash.models import PettyCashFund
    from app.petty_cash.posting import record_voucher
    from app.accounts.models import Account
    from app.settings import AppSettings
    fund = PettyCashFund(branch_id=main_branch.id, code='PCF-REP', name='Fund',
                         account_id=cash_account.id, float_amount=Decimal('5000.00'))
    db_session.add(fund); db_session.commit()
    # 'petty_cash_due_to_custodian' is ALWAYS required (the credit leg of every
    # replenishment) -- assign it here so every test using this helper starts
    # from a working baseline; test_short_over_plug.py's fail-closed test
    # deliberately does NOT call this helper's control-account assignment.
    # A GL account distinct from revenue_account (used as the vouchers' expense
    # account below) -- two lines sharing one account_id would collapse in a
    # naive {account_id: (dr, cr)} assertion dict; keeping them distinct also
    # matches the real-world shape (a liability control account is never also
    # an expense account).
    due_to_gl = Account(code='20120', name='Due to Petty Cash Custodian', account_type='Liability',
                        normal_balance='Credit', is_active=True)
    db_session.add(due_to_gl); db_session.commit()
    AppSettings.set_setting('petty_cash_due_to_custodian_account_code', due_to_gl.code)
    db_session.commit()
    v1 = record_voucher(fund, payee='A', expense_account_id=revenue_account.id, amount=Decimal('1000.00'),
                        description='', receipt_ref='', created_by=staff_user)
    v2 = record_voucher(fund, payee='B', expense_account_id=revenue_account.id, amount=Decimal('500.00'),
                        description='', receipt_ref='', created_by=staff_user)
    db_session.commit()
    return fund, due_to_gl, v1, v2


def test_replenishment_groups_vouchers_and_restores_float(db_session, main_branch, cash_account,
                                                           revenue_account, admin_user, staff_user):
    from app.petty_cash.replenishment import post_replenishment
    fund, due_to_gl, v1, v2 = _setup(db_session, main_branch, cash_account, revenue_account, staff_user)
    # exact tie: physical count matches expected (5000 - 1500 = 3500)
    rep = post_replenishment(fund, [v1.id, v2.id], physical_cash_counted=Decimal('3500.00'),
                             actor=admin_user)
    db_session.commit()
    assert rep is not None
    assert rep.vouchers_total == Decimal('1500.00')
    assert rep.short_over_amount == Decimal('0.00')
    assert rep.replenish_amount == Decimal('1500.00')
    db_session.refresh(v1); db_session.refresh(v2)
    assert v1.status == 'replenished' and v1.replenishment_id == rep.id
    assert v2.status == 'replenished'


def test_replenishment_je_groups_by_expense_account(db_session, main_branch, cash_account,
                                                     revenue_account, admin_user, staff_user):
    from app.petty_cash.replenishment import post_replenishment
    fund, due_to_gl, v1, v2 = _setup(db_session, main_branch, cash_account, revenue_account, staff_user)
    rep = post_replenishment(fund, [v1.id, v2.id], physical_cash_counted=Decimal('3500.00'),
                             actor=admin_user)
    db_session.commit()
    je = rep.journal_entry
    assert je.entry_type == 'petty_cash_replenishment'
    lines = {l.account_id: (l.debit_amount, l.credit_amount) for l in je.lines}
    # both vouchers share revenue_account as their expense account -> ONE grouped debit line
    assert lines[revenue_account.id] == (Decimal('1500.00'), Decimal('0.00'))
    assert lines[due_to_gl.id] == (Decimal('0.00'), Decimal('1500.00'))
    assert je.total_debit == je.total_credit == Decimal('1500.00')


def test_replenishing_an_already_claimed_voucher_loses_cleanly(
        db_session, main_branch, cash_account, revenue_account, admin_user, staff_user):
    """The invariant two concurrent accountants replenishing overlapping held
    vouchers must never violate: a voucher can be claimed by at most one
    replenishment. Proven the same way this codebase proves its other lost-
    update guards (e.g. test_double_confirm_second_writer_loses): call the
    guarded operation twice against the same voucher and confirm only the
    first succeeds. See replenishment.py's module docstring for the two-layer
    guard this exercises (read-time filter + the atomic claim UPDATE's
    rowcount check, the latter being what actually protects a genuine
    thread-level race that a synchronous test can't itself interleave)."""
    from app.petty_cash.replenishment import post_replenishment
    fund, due_to_gl, v1, v2 = _setup(db_session, main_branch, cash_account, revenue_account, staff_user)

    first = post_replenishment(fund, [v1.id], physical_cash_counted=Decimal('4000.00'),
                               actor=admin_user)
    db_session.commit()
    assert first is not None

    # a second attempt racing on the SAME v1 (already claimed by `first` above)
    second = post_replenishment(fund, [v1.id, v2.id], physical_cash_counted=Decimal('3500.00'),
                                actor=admin_user)
    assert second is None   # lost the race -- v1 is no longer 'held'
    db_session.rollback()
    db_session.refresh(v2)
    assert v2.status == 'held'   # untouched -- no partial/silent replenishment
