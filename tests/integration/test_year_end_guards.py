# tests/integration/test_year_end_guards.py
import pytest
from decimal import Decimal
from datetime import date

from app import db
from app.accounts.models import Account
from app.sales_invoices.models import SalesInvoice
from app.customers.models import Customer
from tests.integration.test_year_end_close import _world

pytestmark = [pytest.mark.integration]


def test_cannot_close_year_that_has_not_ended(db_session, admin_user, main_branch):
    from app.year_end import service
    _world(main_branch.id)
    db.session.commit()
    with pytest.raises(ValueError, match='not ended|has not ended'):
        service.assert_closeable(2025, today=date(2025, 6, 1))


def test_cannot_close_already_closed(db_session, admin_user, main_branch):
    from app.year_end import service
    _world(main_branch.id)
    db.session.commit()
    service.close_fiscal_year(2025, admin_user.id)
    db.session.commit()
    with pytest.raises(ValueError, match='already closed'):
        service.assert_closeable(2025, today=date(2026, 1, 15))


def test_drafts_block_close(db_session, admin_user, main_branch):
    from app.year_end import service
    _world(main_branch.id)
    cust = Customer(code='C1', name='C', is_active=True)
    db.session.add(cust); db.session.flush()
    db.session.add(SalesInvoice(branch_id=main_branch.id, invoice_number='SI-DRAFT',
                                invoice_date=date(2025, 5, 1), due_date=date(2025, 6, 1),
                                customer_id=cust.id, customer_name='C', notes='',
                                status='draft', amount_paid=Decimal('0.00')))
    db.session.commit()
    with pytest.raises(ValueError, match='draft'):
        service.assert_closeable(2025, today=date(2026, 1, 15))


def test_sequential_requires_prior_year_closed(db_session, admin_user, main_branch):
    from app.year_end import service
    # data in BOTH 2024 and 2025; closing 2025 first must fail
    w = _world(main_branch.id)
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    je = JournalEntry(entry_number='JE-2024-1', entry_date=date(2024, 5, 1), description='t',
                      reference='t', entry_type='sale', branch_id=main_branch.id, status='posted',
                      is_balanced=True, total_debit=0, total_credit=0)
    db.session.add(je); db.session.flush()
    db.session.add_all([
        JournalEntryLine(entry_id=je.id, line_number=1, account_id=w['cash'].id,
                         debit_amount=Decimal('500'), credit_amount=Decimal('0')),
        JournalEntryLine(entry_id=je.id, line_number=2, account_id=w['rev'].id,
                         debit_amount=Decimal('0'), credit_amount=Decimal('500')),
    ])
    db.session.commit()
    with pytest.raises(ValueError, match='2024'):
        service.assert_closeable(2025, today=date(2026, 1, 15))
