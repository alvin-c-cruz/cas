"""Books-of-account registration for the Replenishment entry_type (R-04 slice 4).
Mirrors tests/bank_transfers/test_journal_reporting.py's pattern (R-04 slice 2),
which caught the identical class of gap: a new system-posted entry_type must be
registered in BOTH VOUCHER_TYPES (app/journals/views.py) and
VOUCHER_ENTRY_TYPES (app/reports/general_journal_data.py), or it's genuinely
invisible in the General Journal / Books of Accounts report."""
from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.journal_entries.models import JournalEntry

pytestmark = [pytest.mark.integration]


def test_petty_cash_replenishment_is_a_registered_voucher_type():
    from app.journals.views import VOUCHER_TYPES
    from app.reports.general_journal_data import VOUCHER_ENTRY_TYPES
    assert 'petty_cash_replenishment' in VOUCHER_TYPES
    assert 'petty_cash_replenishment' in VOUCHER_ENTRY_TYPES


def test_posted_replenishment_je_appears_in_voucher_query(db_session, main_branch, cash_account,
                                                           revenue_account, admin_user, staff_user):
    from app.reports.general_journal_data import VOUCHER_ENTRY_TYPES
    from app.petty_cash.models import PettyCashFund
    from app.petty_cash.posting import record_voucher
    from app.petty_cash.replenishment import post_replenishment
    from app.accounts.models import Account
    from app.settings import AppSettings

    due_to_gl = Account(code='20121', name='Due to Petty Cash Custodian', account_type='Liability',
                        normal_balance='Credit', is_active=True)
    db_session.add(due_to_gl); db_session.commit()
    AppSettings.set_setting('petty_cash_due_to_custodian_account_code', due_to_gl.code)
    db_session.commit()

    fund = PettyCashFund(branch_id=main_branch.id, code='PCF-JR', name='Fund',
                         account_id=cash_account.id, float_amount=Decimal('2000.00'))
    db_session.add(fund); db_session.commit()
    v1 = record_voucher(fund, payee='A', expense_account_id=revenue_account.id, amount=Decimal('300.00'),
                        description='', receipt_ref='', created_by=staff_user)
    db_session.commit()

    rep = post_replenishment(fund, [v1.id], physical_cash_counted=Decimal('1700.00'), actor=admin_user)
    db_session.commit()

    found = JournalEntry.query.filter(
        JournalEntry.id == rep.journal_entry_id,
        JournalEntry.entry_type.in_(VOUCHER_ENTRY_TYPES),
    ).first()
    assert found is not None
