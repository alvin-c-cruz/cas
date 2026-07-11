"""Credit/Debit memo JE builder resolves AR + Creditable WHT via control-account settings,
not hardcoded legacy codes (same bug class as BUG-POSTING-HARDCODED-CONTROL-ACCOUNTS)."""
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
from app.posting.control_accounts import ControlAccountError

from tests.conftest import assign_control_accounts

pytestmark = [pytest.mark.integration, pytest.mark.credit_memos]


def _acct(code, name, atype, nb):
    a = Account(code=code, name=name, account_type=atype, classification='General',
                normal_balance=nb)
    db.session.add(a)
    return a


def _setup_coa(assign_ar='1210', assign_wht='1215', assign_settings=True):
    """Non-legacy COA (AR at 1210, Creditable WHT at 1215 -- neither is the legacy
    10201/10212 code) to prove settings-driven resolution, not the magic default."""
    coa = {
        'ar': _acct('1210', 'Trade Receivables', 'Asset', 'Debit'),
        'wt': _acct('1215', 'Creditable Withholding Tax', 'Asset', 'Debit'),
        'outvat': _acct('20401', 'Output VAT', 'Liability', 'Credit'),
        'contra': _acct('40103', 'Sales Returns and Allowances', 'Income', 'Debit'),
        'cust_credit': _acct('20301', 'Customer Credits', 'Liability', 'Credit'),
        'cash': _acct('10110', 'Cash in Bank', 'Asset', 'Debit'),
        'rev': _acct('40101', 'Sales - Goods', 'Income', 'Credit'),
    }
    db.session.commit()
    vat = SalesVATCategory(code='V12', name='VATABLE', rate=Decimal('12'),
                           output_vat_account_id=coa['outvat'].id, is_active=True)
    db.session.add(vat)
    db.session.commit()
    AppSettings.set_setting(service.SALES_RETURNS_KEY, '40103')
    AppSettings.set_setting(service.CUSTOMER_CREDITS_KEY, '20301')
    if assign_settings:
        assign_control_accounts(db.session, ar=assign_ar, creditable_wht=assign_wht)
    return coa


def _credit_memo(branch, coa, destination='ar', wt_rate=None, credit='560'):
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

    memo = SalesMemo(memo_type='credit', memo_number='CM-1', memo_date=date(2026, 7, 10),
                     branch_id=branch.id, sales_invoice_id=si.id, original_invoice_number='SI-1',
                     customer_id=c.id, customer_name='Acme', reason='return',
                     destination=destination, status='draft',
                     cash_account_id=(coa['cash'].id if destination == 'cash_refund' else None))
    ml = SalesMemoItem(line_number=1, sales_invoice_item_id=li.id, amount=Decimal(credit),
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


def test_credit_memo_je_resolves_ar_and_wht_via_settings_on_non_legacy_coa(
        db_session, admin_user, main_branch):
    """AR (destination='ar') and creditable WHT resolve through the settings-assigned
    control accounts -- not the hardcoded 10201/10212 -- so a self-built COA (AR at a
    different code) posts a credit memo successfully."""
    coa = _setup_coa(assign_ar='1210', assign_wht='1215')
    memo = _credit_memo(main_branch, coa, destination='ar', wt_rate='2', credit='560')
    je = post_memo_je(memo, admin_user.id)
    assert je.is_balanced
    legs = _legs(je)
    assert legs['1215'] == (Decimal('0.00'), Decimal('10.00'))   # WHT receivable unwound (Cr)
    assert legs['1210'] == (Decimal('0.00'), Decimal('550.00'))  # AR Cr = gross - wht (settings code)


def test_post_memo_je_raises_control_account_error_when_ar_unassigned(
        db_session, admin_user, main_branch):
    """Unassigned ar_trade control account -> friendly ControlAccountError, not a raw
    'not found in Chart of Accounts' or KeyError/AttributeError."""
    coa = _setup_coa(assign_settings=False)
    memo = _credit_memo(main_branch, coa, destination='ar', credit='560')
    with pytest.raises(ControlAccountError) as exc_info:
        post_memo_je(memo, admin_user.id)
    assert 'Accounts Receivable control account' in str(exc_info.value)
