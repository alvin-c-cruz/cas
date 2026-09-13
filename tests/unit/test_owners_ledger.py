"""remap() re-points VAT legs of posted lines. Every case asserts two invariants on top of
its own expectation: each entry still balances after the lens, and the summary's
net_income_effect equals what moved into P&L accounts."""
from datetime import date
from decimal import Decimal
import pytest

from app import db
from app.accounts.models import Account
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.sales_vat_categories.models import SalesVATCategory
from app.settings import AppSettings
from app.vat_categories.models import VATCategory
from app.reports import ledger as L
from app.reports import owners_ledger as O

pytestmark = [pytest.mark.owners_basis, pytest.mark.unit]

D = Decimal


def _acct(code, name, atype, normal):
    a = Account(code=code, name=name, account_type=atype, normal_balance=normal, is_active=True)
    db.session.add(a); db.session.commit()
    return a


def _je(branch_id, number, on, legs, entry_type='sale', reversed_entry_id=None):
    """legs: [(account, debit, credit), ...] -> posted JournalEntry."""
    total = sum(D(str(d)) for _, d, _ in legs)
    je = JournalEntry(entry_number=number, entry_date=on, description=f'desc {number}',
                      reference=number, entry_type=entry_type, branch_id=branch_id,
                      status='posted', is_balanced=True, total_debit=total, total_credit=total,
                      reversed_entry_id=reversed_entry_id)
    db.session.add(je); db.session.flush()
    for i, (acct, d, c) in enumerate(legs, start=1):
        db.session.add(JournalEntryLine(entry_id=je.id, line_number=i, account_id=acct.id,
                                        debit_amount=D(str(d)), credit_amount=D(str(c))))
    db.session.commit()
    return je


@pytest.fixture
def coa(db_session):
    """Chart: AR, cash, two income accounts, two expense accounts, one asset, VAT accounts."""
    c = {
        'ar': _acct('112001', 'AR TRADE', 'Asset', 'Debit'),
        'cash': _acct('111001', 'CASH', 'Asset', 'Debit'),
        'ap': _acct('211001', 'AP TRADE', 'Liability', 'Credit'),
        'sales_tin': _acct('411001', 'SALES - TINCAN', 'Revenue', 'Credit'),
        'sales_pla': _acct('411005', 'SALES - PLASTIC', 'Revenue', 'Credit'),
        'supplies': _acct('721001', 'SUPPLIES', 'Administrative Expense', 'Debit'),
        'machine': _acct('151001', 'MACHINERY', 'Asset', 'Debit'),
        'output': _acct('213005', 'OUTPUT TAX', 'Liability', 'Credit'),
        'input': _acct('129008', 'INPUT TAX - DOMESTIC', 'Asset', 'Debit'),
        'payable': _acct('213004', 'VAT PAYABLE', 'Liability', 'Credit'),
    }
    db.session.add(SalesVATCategory(code='V12', name='VATABLE', rate=D('12.00'),
                                    transaction_nature='regular', output_vat_account_id=c['output'].id))
    db.session.add(VATCategory(code='V12DG', name='INPUT DG', rate=D('12.00'),
                               transaction_nature='domestic_goods', input_vat_account_id=c['input'].id))
    db.session.commit()
    AppSettings.set_setting('vat_payable_account_code', c['payable'].code)
    return c


def _si(branch_id, customer, je, items, number='SI-1', on=date(2026, 3, 10)):
    inv = SalesInvoice(branch_id=branch_id, invoice_number=number, invoice_date=on,
                       due_date=on, customer_id=customer.id, customer_name=customer.name,
                       customer_tin=customer.tin, status='posted', journal_entry_id=je.id)
    for i, (acct, amount, vat) in enumerate(items, start=1):
        inv.line_items.append(SalesInvoiceItem(
            line_number=i, description='x', amount=D(str(amount)), vat_rate=D('12.00'),
            vat_category='V12', vat_nature='regular', line_total=D(str(amount)),
            vat_amount=D(str(vat)), account_id=acct.id if acct else None))
    db.session.add(inv); db.session.commit()
    return inv


def _ap(branch_id, vendor, je, items, number='AP-1', on=date(2026, 3, 12)):
    ap = AccountsPayable(branch_id=branch_id, ap_number=number, ap_date=on, due_date=on,
                         payee_type='vendor', payee_id=vendor.id, vendor_id=vendor.id,
                         vendor_name=vendor.name, notes='', status='posted', journal_entry_id=je.id)
    for i, (acct, amount, vat) in enumerate(items, start=1):
        ap.line_items.append(AccountsPayableItem(
            line_number=i, description='x', amount=D(str(amount)), vat_rate=D('12.00'),
            line_total=D(str(amount)), vat_amount=D(str(vat)), account_id=acct.id))
    db.session.add(ap); db.session.commit()
    return ap


def _balanced(lines):
    by = {}
    for l in lines:
        d, c = by.get(l.entry_id, (D('0'), D('0')))
        by[l.entry_id] = (d + l.debit, c + l.credit)
    return all(d == c for d, c in by.values())


def _bal(lines, acct):
    return sum((l.debit - l.credit for l in lines if l.account_id == acct.id), D('0'))


def test_distribute_pro_rata_rounding_to_largest():
    out = O.distribute(D('100.00'), {'a': D('1'), 'b': D('1'), 'c': D('1')})
    assert out == {'a': D('33.34'), 'b': D('33.33'), 'c': D('33.33')}
    assert O.distribute(D('10.00'), {}) == {}
    assert O.distribute(D('0.00'), {'a': D('1')}) == {}
    assert O.distribute(D('-9.00'), {'a': D('2'), 'b': D('1')}) == {'a': D('-6.00'), 'b': D('-3.00')}


def test_no_vat_accounts_configured_is_passthrough(db_session, main_branch):
    cash = _acct('111001', 'CASH', 'Asset', 'Debit'); rev = _acct('411001', 'SALES', 'Revenue', 'Credit')
    _je(main_branch.id, 'J1', date(2026, 3, 1), [(cash, 112, 0), (rev, 0, 112)])
    raw = L.fetch_lines(None, None, main_branch.id)
    lines, s = O.remap(raw)
    assert lines == raw and s.untraced == [] and s.net_income_effect == D('0.00')


def test_output_vat_moves_to_income_accounts_pro_rata(coa, main_branch, vl_customer):
    je = _je(main_branch.id, 'J1', date(2026, 3, 10), [
        (coa['ar'], '224.00', 0), (coa['sales_tin'], 0, '100.00'),
        (coa['sales_pla'], 0, '100.00'), (coa['output'], 0, '24.00')])
    _si(main_branch.id, vl_customer, je, [(coa['sales_tin'], '112.00', '12.00'),
                                          (coa['sales_pla'], '112.00', '12.00')])
    lines, s = O.remap(L.fetch_lines(None, None, main_branch.id))
    assert _balanced(lines)
    assert _bal(lines, coa['output']) == D('0.00')
    assert _bal(lines, coa['sales_tin']) == D('-112.00')
    assert _bal(lines, coa['sales_pla']) == D('-112.00')
    moved = [l for l in lines if l.moved_from_account_id == coa['output'].id]
    assert len(moved) == 2 and all(l.credit > 0 and l.debit == 0 for l in moved)
    assert s.moved_to_income == D('24.00') and s.net_income_effect == D('24.00')
    assert s.untraced == []


def test_output_vat_rounding_goes_to_largest_line(coa, main_branch, vl_customer):
    je = _je(main_branch.id, 'J1', date(2026, 3, 10), [
        (coa['ar'], '0.10', 0), (coa['sales_tin'], 0, '0.07'), (coa['output'], 0, '0.03')])
    _si(main_branch.id, vl_customer, je, [(coa['sales_tin'], '0.05', '0.01'),
                                          (coa['sales_pla'], '0.05', '0.01'),
                                          (coa['sales_tin'], '0.05', '0.01')])
    lines, s = O.remap(L.fetch_lines(None, None, main_branch.id))
    assert _balanced(lines) and _bal(lines, coa['output']) == D('0.00')
    assert _bal(lines, coa['sales_tin']) == D('-0.09')      # 0.07 + 0.02 (largest weight takes the cent)
    assert _bal(lines, coa['sales_pla']) == D('-0.01')


def test_input_vat_moves_to_expense_and_asset(coa, main_branch, vl_vendor):
    je = _je(main_branch.id, 'J2', date(2026, 3, 12), [
        (coa['supplies'], '100.00', 0), (coa['machine'], '300.00', 0),
        (coa['input'], '48.00', 0), (coa['ap'], 0, '448.00')], entry_type='purchase')
    _ap(main_branch.id, vl_vendor, je, [(coa['supplies'], '112.00', '12.00'),
                                        (coa['machine'], '336.00', '36.00')])
    lines, s = O.remap(L.fetch_lines(None, None, main_branch.id))
    assert _balanced(lines) and _bal(lines, coa['input']) == D('0.00')
    assert _bal(lines, coa['supplies']) == D('112.00')
    assert _bal(lines, coa['machine']) == D('336.00')
    assert s.moved_to_expense == D('12.00') and s.moved_to_balance_sheet == D('36.00')
    assert s.net_income_effect == D('-12.00')


def test_settlement_entries_are_dropped(coa, main_branch):
    _je(main_branch.id, 'VS-1', date(2026, 4, 5), [
        (coa['output'], '24.00', 0), (coa['input'], 0, '10.00'), (coa['payable'], 0, '14.00')],
        entry_type='vat_settlement')
    lines, s = O.remap(L.fetch_lines(None, None, main_branch.id))
    assert lines == [] and s.settlement_entries_dropped == 1 and s.untraced == []


def test_manual_voucher_on_vat_account_is_kept_and_flagged(coa, main_branch):
    _je(main_branch.id, 'JV-1', date(2026, 3, 20), [
        (coa['output'], '5.00', 0), (coa['cash'], 0, '5.00')], entry_type='adjustment')
    lines, s = O.remap(L.fetch_lines(None, None, main_branch.id))
    assert _balanced(lines) and _bal(lines, coa['output']) == D('5.00')
    assert [(u.entry_number, u.account_code, u.amount, u.reason) for u in s.untraced] == \
        [('JV-1', '213005', D('5.00'), 'no_source_document')]
    assert s.untraced_total == D('5.00') and s.net_income_effect == D('0.00')


def test_document_line_without_account_keeps_its_share_flagged(coa, main_branch, vl_customer):
    je = _je(main_branch.id, 'J1', date(2026, 3, 10), [
        (coa['ar'], '224.00', 0), (coa['sales_tin'], 0, '200.00'), (coa['output'], 0, '24.00')])
    _si(main_branch.id, vl_customer, je, [(coa['sales_tin'], '112.00', '12.00'),
                                          (None, '112.00', '12.00')])
    lines, s = O.remap(L.fetch_lines(None, None, main_branch.id))
    assert _balanced(lines)
    assert _bal(lines, coa['output']) == D('-12.00')
    assert _bal(lines, coa['sales_tin']) == D('-212.00')
    assert s.untraced[0].reason == 'no_line_account' and s.untraced[0].amount == D('12.00')


def test_document_with_no_vat_lines_is_flagged(coa, main_branch, vl_customer):
    je = _je(main_branch.id, 'J1', date(2026, 3, 10), [
        (coa['ar'], '112.00', 0), (coa['sales_tin'], 0, '100.00'), (coa['output'], 0, '12.00')])
    _si(main_branch.id, vl_customer, je, [(coa['sales_tin'], '112.00', '0.00')])
    lines, s = O.remap(L.fetch_lines(None, None, main_branch.id))
    assert _bal(lines, coa['output']) == D('-12.00')
    assert s.untraced[0].reason == 'no_vat_on_document_lines'


def test_payable_debit_is_flagged_until_task_4(coa, main_branch):
    _je(main_branch.id, 'JV-2', date(2026, 4, 25), [
        (coa['payable'], '14.00', 0), (coa['cash'], 0, '14.00')], entry_type='adjustment')
    lines, s = O.remap(L.fetch_lines(None, None, main_branch.id))
    assert _bal(lines, coa['payable']) == D('14.00')
    assert s.untraced[0].reason == 'manual_entry'
