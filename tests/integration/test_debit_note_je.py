"""Debit-note journal-entry builder: increases AR (mirror of the Sales Invoice JE)."""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.accounts.models import Account
from app.customers.models import Customer
from app.sales_vat_categories.models import SalesVATCategory
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.sales_memos.models import SalesMemo, SalesMemoItem
from app.sales_memos.je import post_memo_je
from app.sales_memos import service
from app.settings import AppSettings

from tests.conftest import assign_control_accounts

pytestmark = [pytest.mark.integration, pytest.mark.credit_memos]


def _acct(code, name, atype, nb):
    a = Account(code=code, name=name, account_type=atype, classification='General',
                normal_balance=nb)
    db.session.add(a)
    return a


def _setup_coa():
    coa = {
        'ar': _acct('10201', 'Accounts Receivable - Trade', 'Asset', 'Debit'),
        'wt': _acct('10212', 'Creditable Withholding Tax', 'Asset', 'Debit'),
        'outvat': _acct('20401', 'Output VAT', 'Liability', 'Credit'),
        'contra': _acct('40103', 'Sales Returns and Allowances', 'Income', 'Debit'),
        'cust_credit': _acct('20301', 'Customer Credits', 'Liability', 'Credit'),
        'cash': _acct('10110', 'Cash in Bank', 'Asset', 'Debit'),
        'rev': _acct('40101', 'Sales - Goods', 'Income', 'Credit'),
    }
    db.session.commit()
    vat = SalesVATCategory(code='V12', name='VATABLE', rate=Decimal('12'),
                           output_vat_account_id=coa['outvat'].id, is_active=True)
    db.session.add(vat); db.session.commit()
    AppSettings.set_setting(service.SALES_RETURNS_KEY, '40103')
    AppSettings.set_setting(service.CUSTOMER_CREDITS_KEY, '20301')
    assign_control_accounts(db.session)
    return coa


def _debit_memo(branch, coa, destination='ar', wt_rate=None, charge='560'):
    c = Customer(code='C1', name='Acme', is_active=True)
    db.session.add(c); db.session.commit()
    si = SalesInvoice(branch_id=branch.id, invoice_number='SI-1', invoice_date=date(2026, 7, 1),
                      due_date=date(2026, 7, 31), customer_id=c.id, customer_name='Acme',
                      notes='', status='posted', total_amount=Decimal('1120'),
                      balance=Decimal('1120'))
    li = SalesInvoiceItem(line_number=1, description='Widget', amount=Decimal('1120'),
                          vat_category='V12', vat_rate=Decimal('12'), account_id=coa['rev'].id,
                          wt_rate=(Decimal(wt_rate) if wt_rate else None))
    li.calculate_amounts()
    si.line_items.append(li); db.session.add(si); db.session.commit()

    memo = SalesMemo(memo_type='debit', memo_number='DM-1', memo_date=date(2026, 7, 10),
                     branch_id=branch.id, sales_invoice_id=si.id, original_invoice_number='SI-1',
                     customer_id=c.id, customer_name='Acme', reason='undercharge',
                     destination=destination, status='draft',
                     cash_account_id=(coa['cash'].id if destination == 'cash_refund' else None))
    ml = SalesMemoItem(line_number=1, sales_invoice_item_id=li.id, amount=Decimal(charge),
                       vat_category='V12', vat_rate=Decimal('12'), account_id=coa['rev'].id,
                       wt_rate=li.wt_rate)
    ml.calculate_amounts()
    memo.line_items.append(ml)
    memo.calculate_totals()
    db.session.add(memo); db.session.commit()
    return memo


def _legs(je):
    from app.journal_entries.models import JournalEntryLine
    out = {}
    for l in JournalEntryLine.query.filter_by(entry_id=je.id).all():
        code = db.session.get(Account, l.account_id).code
        out[code] = (l.debit_amount, l.credit_amount)
    return out


def test_debit_note_je_increases_ar_and_ties(db_session, admin_user, main_branch):
    coa = _setup_coa()
    memo = _debit_memo(main_branch, coa, destination='ar', charge='560')  # net 500, vat 60
    je = post_memo_je(memo, admin_user.id)
    assert je.is_balanced
    legs = _legs(je)
    assert legs['10201'] == (Decimal('560.00'), Decimal('0.00'))   # AR debited (customer owes more)
    assert legs['40101'] == (Decimal('0.00'), Decimal('500.00'))   # revenue credited (net)
    assert legs['20401'] == (Decimal('0.00'), Decimal('60.00'))    # Output VAT credited
    assert je.total_debit == je.total_credit == Decimal('560.00')


def test_debit_note_je_with_wht(db_session, admin_user, main_branch):
    coa = _setup_coa()
    memo = _debit_memo(main_branch, coa, destination='ar', wt_rate='2', charge='560')
    # vat 60, net-of-vat 500, wht 10, total 550, net revenue 500
    je = post_memo_je(memo, admin_user.id)
    assert je.is_balanced
    legs = _legs(je)
    assert legs['10201'] == (Decimal('550.00'), Decimal('0.00'))   # AR = charge - wht
    assert legs['10212'] == (Decimal('10.00'), Decimal('0.00'))    # WHT receivable (Dr, like SI)
    assert legs['40101'] == (Decimal('0.00'), Decimal('500.00'))
    assert legs['20401'] == (Decimal('0.00'), Decimal('60.00'))


def test_debit_note_je_cash_destination(db_session, admin_user, main_branch):
    coa = _setup_coa()
    memo = _debit_memo(main_branch, coa, destination='cash_refund', charge='560')
    je = post_memo_je(memo, admin_user.id)
    assert je.is_balanced
    assert _legs(je)['10110'] == (Decimal('560.00'), Decimal('0.00'))  # collected to cash (Dr)
