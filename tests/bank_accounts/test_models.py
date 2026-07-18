"""Unit tests for the BankAccount model (R-04 slice 1)."""
from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.bank_accounts.models import BankAccount
from app.journal_entries.models import JournalEntry

pytestmark = [pytest.mark.integration]


def _mk(account_id, branch_id, code='BA-1'):
    return BankAccount(branch_id=branch_id, code=code, name='BPI Main',
                       account_id=account_id, opening_balance=Decimal('1000.00'),
                       opening_date=date(2026, 1, 1))


def test_account_id_is_unique(db_session, main_branch, cash_account):
    db.session.add(_mk(cash_account.id, main_branch.id, 'BA-1')); db.session.commit()
    db.session.add(_mk(cash_account.id, main_branch.id, 'BA-2'))
    with pytest.raises(Exception):        # IntegrityError on the unique index
        db.session.commit()
    db.session.rollback()


def test_opening_balance_posts_no_je(db_session, main_branch, cash_account):
    before = JournalEntry.query.count()
    db.session.add(_mk(cash_account.id, main_branch.id)); db.session.commit()
    assert JournalEntry.query.count() == before      # opening balance is a reference, not a JE
