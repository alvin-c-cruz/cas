"""Cancellation reversals are General Journal entries → they get a JV-#### number."""
from datetime import date
from decimal import Decimal
import pytest

from app import db
from app.customers.models import Customer
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.sales_invoices.models import SalesInvoice
from app.sales_invoices.views import _create_reversal_je

pytestmark = [pytest.mark.integration]


def test_si_cancellation_reversal_gets_jv_number(db_session, main_branch, admin_user,
                                                 cash_account, revenue_account):
    cust = Customer(code='C001', name='ACME')
    db.session.add(cust)
    db.session.commit()
    inv = SalesInvoice(invoice_number='AR-2026-06-0001', customer_name='ACME',
                       customer_id=cust.id, invoice_date=date(2026, 6, 5),
                       due_date=date(2026, 7, 5), branch_id=main_branch.id, status='posted',
                       subtotal=Decimal('100'), total_amount=Decimal('100'), balance=Decimal('100'))
    db.session.add(inv)
    db.session.flush()
    je = JournalEntry(entry_number='JE-2026-0001', entry_date=date(2026, 6, 5),
                      description='Sales', reference='AR-2026-06-0001', entry_type='sale',
                      branch_id=main_branch.id, status='posted', is_balanced=True,
                      total_debit=Decimal('100'), total_credit=Decimal('100'))
    db.session.add(je)
    db.session.flush()
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=1, account_id=cash_account.id,
                                    debit_amount=Decimal('100'), credit_amount=Decimal('0')))
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=2, account_id=revenue_account.id,
                                    debit_amount=Decimal('0'), credit_amount=Decimal('100')))
    inv.journal_entry_id = je.id
    db.session.commit()

    reversal = _create_reversal_je(inv, date(2026, 6, 10), admin_user.id, label='Cancel')
    db.session.commit()

    assert reversal.entry_number.startswith('JV-')      # numbered as a General Journal entry, not JE-
    assert reversal.entry_type == 'reversal'
    # A reversal keeps its JV number in the user-facing display (it lives in the JV book).
    assert reversal.display_number == reversal.entry_number
