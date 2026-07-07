"""The CDV/CRV detail "Entry" (JE section) always lists DEBITS before CREDITS.

Posted vouchers store their JE legs credit-first, so reading them in stored order shows
credits above debits on the detail page -- against the house rule "journal entry previews
are always debit-first" ([[crv-cdv-je-debit-order]]). The builders must re-sort for
presentation. Parity: both CDV and CRV.
"""
from decimal import Decimal
from datetime import date

import pytest

pytestmark = pytest.mark.integration


def _acct(db_session, code, name, atype, nb):
    from app.accounts.models import Account
    a = Account(code=code, name=name, account_type=atype, normal_balance=nb, is_active=True)
    db_session.add(a); db_session.commit()
    return a


def _credit_first_je(db_session, main_branch, entry_type, ar_or_ap_acct, cash_acct):
    """A posted JE whose lines are stored CREDIT leg first, then the debit leg."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    je = JournalEntry(entry_number=f'JE-{entry_type[:2].upper()}-ORD', entry_date=date(2026, 7, 7),
                      description='order', entry_type=entry_type, branch_id=main_branch.id,
                      status='posted', total_debit=Decimal('1000'), total_credit=Decimal('1000'),
                      is_balanced=True)
    db_session.add(je); db_session.commit()
    # Stored credit-first: line 1 credit, line 2 debit
    db_session.add(JournalEntryLine(entry_id=je.id, line_number=1, account_id=ar_or_ap_acct.id,
                                    debit_amount=Decimal('0'), credit_amount=Decimal('1000')))
    db_session.add(JournalEntryLine(entry_id=je.id, line_number=2, account_id=cash_acct.id,
                                    debit_amount=Decimal('1000'), credit_amount=Decimal('0')))
    db_session.commit()
    return je


def _assert_debits_first(rows):
    debit_idx = [i for i, r in enumerate(rows) if (r['debit'] or 0) > 0]
    credit_idx = [i for i, r in enumerate(rows) if (r['credit'] or 0) > 0]
    assert debit_idx and credit_idx
    assert max(debit_idx) < min(credit_idx), f'credits appear before debits: {rows}'


@pytest.mark.cash_receipts
def test_crv_detail_entry_debits_first(db_session, main_branch, app):
    from app.customers.models import Customer
    from app.cash_receipts.models import CashReceiptVoucher
    from app.cash_receipts.views import _build_crv_je_preview
    c = Customer(code='ORDC', name='ABC', tin='1-2-3-000', is_active=True)
    ar = _acct(db_session, '1200', 'AR', 'Asset', 'debit')
    cash = _acct(db_session, '1011', 'Cash', 'Asset', 'debit')
    db_session.add(c); db_session.commit()
    je = _credit_first_je(db_session, main_branch, 'receipt', ar, cash)
    crv = CashReceiptVoucher(branch_id=main_branch.id, crv_number='CR-ORD', crv_date=date(2026, 7, 7),
                             customer_id=c.id, customer_name=c.name, payment_method='cash',
                             cash_account_id=cash.id, status='posted', total_amount=Decimal('1000'),
                             journal_entry_id=je.id)
    db_session.add(crv); db_session.commit()
    _assert_debits_first(_build_crv_je_preview(crv))


@pytest.mark.cash_disbursements
def test_cdv_detail_entry_debits_first(db_session, main_branch, app):
    from app.vendors.models import Vendor
    from app.cash_disbursements.models import CashDisbursementVoucher
    from app.cash_disbursements.views import _build_cdv_je_preview
    v = Vendor(code='ORDV', name='XYZ', tin='1-2-3-000', is_active=True)
    ap = _acct(db_session, '2100', 'AP', 'Liability', 'credit')
    cash = _acct(db_session, '1011', 'Cash', 'Asset', 'debit')
    db_session.add(v); db_session.commit()
    je = _credit_first_je(db_session, main_branch, 'disbursement', ap, cash)
    cdv = CashDisbursementVoucher(branch_id=main_branch.id, cdv_number='CD-ORD', cdv_date=date(2026, 7, 7),
                                  vendor_id=v.id, vendor_name=v.name, payment_method='cash',
                                  cash_account_id=cash.id, status='posted', total_amount=Decimal('1000'),
                                  journal_entry_id=je.id)
    db_session.add(cdv); db_session.commit()
    _assert_debits_first(_build_cdv_je_preview(cdv))
