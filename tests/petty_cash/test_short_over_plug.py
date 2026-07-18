"""Shortage/overage plug tests -- ASSERTED, never silently absorbed (R-04 slice 4)."""
from decimal import Decimal
import pytest
from app import db

pytestmark = [pytest.mark.integration]


def _setup(db_session, main_branch, cash_account, revenue_account, staff_user):
    from tests.petty_cash.test_replenishment import _setup as base_setup
    return base_setup(db_session, main_branch, cash_account, revenue_account, staff_user)


def test_shortage_books_debit_to_short_over(db_session, main_branch, cash_account, revenue_account,
                                            admin_user, staff_user):
    from app.petty_cash.replenishment import post_replenishment
    from app.accounts.models import Account
    from app.settings import AppSettings
    so_acct = Account(code='69990', name='Cash Short/Over', account_type='Expense',
                      normal_balance='Debit', is_active=True)
    db_session.add(so_acct); db_session.commit()
    AppSettings.set_setting('petty_cash_short_over_account_code', so_acct.code)
    db_session.commit()

    fund, bank_ba, v1, v2 = _setup(db_session, main_branch, cash_account, revenue_account, staff_user)
    # counted LESS than expected (3500 expected, 3450 counted) -> a 50 SHORTAGE
    rep = post_replenishment(fund, [v1.id, v2.id], physical_cash_counted=Decimal('3450.00'),
                             bank_account=bank_ba, actor=admin_user)
    db_session.commit()
    assert rep.short_over_amount == Decimal('50.00')
    je = rep.journal_entry
    lines = {l.account_id: (l.debit_amount, l.credit_amount) for l in je.lines}
    assert lines[so_acct.id] == (Decimal('50.00'), Decimal('0.00'))   # shortage = a debit (expense)
    assert je.total_debit == je.total_credit   # the JE still balances -- the plug is asserted, not just trusted


def test_overage_books_credit_to_short_over(db_session, main_branch, cash_account, revenue_account,
                                            admin_user, staff_user):
    from app.petty_cash.replenishment import post_replenishment
    from app.accounts.models import Account
    from app.settings import AppSettings
    so_acct = Account(code='69991', name='Cash Short/Over', account_type='Expense',
                      normal_balance='Debit', is_active=True)
    db_session.add(so_acct); db_session.commit()
    AppSettings.set_setting('petty_cash_short_over_account_code', so_acct.code)
    db_session.commit()

    fund, bank_ba, v1, v2 = _setup(db_session, main_branch, cash_account, revenue_account, staff_user)
    # counted MORE than expected (3500 expected, 3520 counted) -> a 20 OVERAGE
    rep = post_replenishment(fund, [v1.id, v2.id], physical_cash_counted=Decimal('3520.00'),
                             bank_account=bank_ba, actor=admin_user)
    db_session.commit()
    assert rep.short_over_amount == Decimal('-20.00')   # sign convention: negative = overage
    je = rep.journal_entry
    lines = {l.account_id: (l.debit_amount, l.credit_amount) for l in je.lines}
    assert lines[so_acct.id] == (Decimal('0.00'), Decimal('20.00'))   # overage = a credit


def test_nonzero_difference_without_assigned_account_raises_fail_closed(db_session, main_branch,
                                                                        cash_account, revenue_account,
                                                                        admin_user, staff_user):
    from app.petty_cash.replenishment import post_replenishment
    from app.posting.control_accounts import ControlAccountError
    fund, bank_ba, v1, v2 = _setup(db_session, main_branch, cash_account, revenue_account, staff_user)
    with pytest.raises(ControlAccountError):
        post_replenishment(fund, [v1.id, v2.id], physical_cash_counted=Decimal('3450.00'),   # a real shortage
                           bank_account=bank_ba, actor=admin_user)


def test_exact_tie_posts_fine_without_assigned_account(db_session, main_branch, cash_account,
                                                        revenue_account, admin_user, staff_user):
    """The setting stays unassigned, but physical count matches expected exactly --
    must NOT raise, since no short/over line is needed at all."""
    from app.petty_cash.replenishment import post_replenishment
    fund, bank_ba, v1, v2 = _setup(db_session, main_branch, cash_account, revenue_account, staff_user)
    rep = post_replenishment(fund, [v1.id, v2.id], physical_cash_counted=Decimal('3500.00'),
                             bank_account=bank_ba, actor=admin_user)
    db_session.commit()
    assert rep is not None
    assert rep.short_over_amount == Decimal('0.00')
