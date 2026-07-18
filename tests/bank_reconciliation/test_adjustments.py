"""Inline adjustment tests (R-04 slice 3)."""
from datetime import date
from decimal import Decimal
import pytest
from app import db

pytestmark = [pytest.mark.integration]


def test_adjustment_posts_balanced_je_and_autoclears(db_session, main_branch, cash_account,
                                                      revenue_account, admin_user):
    from app.bank_reconciliation import service
    from app.bank_accounts.models import BankAccount
    from app.bank_reconciliation.models import BankReconciliation, ReconciliationItem
    ba = BankAccount(branch_id=main_branch.id, code='BA-ADJ', name='Adj',
                     account_id=cash_account.id, account_type='checking', opening_balance=0)
    db_session.add(ba); db_session.commit()
    rec = BankReconciliation(bank_account_id=ba.id, statement_date=date(2026, 6, 30),
                             statement_ending_balance=Decimal('0.00'), beginning_balance=Decimal('0.00'))
    db_session.add(rec); db_session.commit()

    bank_line = service.post_adjustment(rec, account_id=revenue_account.id, amount=Decimal('25.00'),
                                        direction='credit', description='Bank service charge',
                                        actor=admin_user)
    db_session.commit()
    je = bank_line.entry
    assert je.total_debit == je.total_credit == Decimal('25.00')
    assert je.entry_type == 'adjustment'
    assert ReconciliationItem.query.filter_by(je_line_id=bank_line.id, reconciliation_id=rec.id).count() == 1
