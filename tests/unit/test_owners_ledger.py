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
    # Untraced.amount is SIGNED debit-positive: this is an output-VAT credit share.
    assert s.untraced[0].reason == 'no_line_account' and s.untraced[0].amount == D('-12.00')
    assert s.untraced_total == D('-12.00')


def test_document_with_no_vat_lines_is_flagged(coa, main_branch, vl_customer):
    je = _je(main_branch.id, 'J1', date(2026, 3, 10), [
        (coa['ar'], '112.00', 0), (coa['sales_tin'], 0, '100.00'), (coa['output'], 0, '12.00')])
    _si(main_branch.id, vl_customer, je, [(coa['sales_tin'], '112.00', '0.00')])
    lines, s = O.remap(L.fetch_lines(None, None, main_branch.id))
    assert _bal(lines, coa['output']) == D('-12.00')
    assert s.untraced[0].reason == 'no_vat_on_document_lines'


from datetime import datetime
from app.product_categories.models import ProductCategory
from app.products.models import Product
from app.vat_settlement.models import VatSettlement
from app.reports.basis import vat_expense_setting_key


@pytest.fixture
def lines_of_business(db_session, coa, main_branch, vl_customer, admin_user):
    """TINCAN 24.00 and PLASTIC 12.00 of output VAT invoiced in Q1 2026, one settlement of
    Q1 recorded on 2026-04-20, VAT expense accounts mapped for both categories."""
    tin = ProductCategory(code='TIN', name='Tincan'); pla = ProductCategory(code='PLA', name='Plastic')
    db.session.add_all([tin, pla]); db.session.commit()
    p_tin = Product(name='Can', category_id=tin.id, track_inventory=False)
    p_pla = Product(name='Tub', category_id=pla.id, track_inventory=False)
    db.session.add_all([p_tin, p_pla]); db.session.commit()
    je = _je(main_branch.id, 'J1', date(2026, 3, 10), [
        (coa['ar'], '336.00', 0), (coa['sales_tin'], 0, '200.00'),
        (coa['sales_pla'], 0, '100.00'), (coa['output'], 0, '36.00')])
    inv = _si(main_branch.id, vl_customer, je, [(coa['sales_tin'], '224.00', '24.00'),
                                                (coa['sales_pla'], '112.00', '12.00')])
    inv.line_items[0].product_id = p_tin.id; inv.line_items[1].product_id = p_pla.id
    db.session.add(VatSettlement(fiscal_year=2026, quarter=1, status='settled',
                                 output_vat=D('36.00'), net_payable=D('36.00'),
                                 settled_at=datetime(2026, 4, 20, 9, 0), settled_by_id=admin_user.id))
    db.session.commit()
    vat_tin = _acct('811001', 'VAT EXPENSE - TINCAN', 'Other Expense', 'Debit')
    vat_pla = _acct('811003', 'VAT EXPENSE - PLASTIC', 'Other Expense', 'Debit')
    AppSettings.set_setting(vat_expense_setting_key(tin.id), vat_tin.code)
    AppSettings.set_setting(vat_expense_setting_key(pla.id), vat_pla.code)
    return {'tin': tin, 'pla': pla, 'vat_tin': vat_tin, 'vat_pla': vat_pla, 'je': je}


def test_remittance_splits_by_output_vat_of_settled_quarter(coa, main_branch, lines_of_business):
    _je(main_branch.id, 'JV-2', date(2026, 4, 25), [
        (coa['payable'], '36.00', 0), (coa['cash'], 0, '36.00')], entry_type='adjustment')
    lines, s = O.remap(L.fetch_lines(date(2026, 4, 1), None, main_branch.id))
    assert _balanced(lines) and _bal(lines, coa['payable']) == D('0.00')
    assert _bal(lines, lines_of_business['vat_tin']) == D('24.00')
    assert _bal(lines, lines_of_business['vat_pla']) == D('12.00')
    assert s.vat_expense_by_category == {lines_of_business['tin'].id: D('24.00'),
                                         lines_of_business['pla'].id: D('12.00')}
    assert s.net_income_effect == D('-36.00') and s.untraced == []


def test_remittance_before_any_settlement_uses_its_own_quarter(coa, main_branch, lines_of_business):
    VatSettlement.query.delete(); db.session.commit()
    _je(main_branch.id, 'JV-3', date(2026, 3, 28), [
        (coa['payable'], '9.00', 0), (coa['cash'], 0, '9.00')], entry_type='adjustment')
    lines, s = O.remap(L.fetch_lines(date(2026, 3, 20), None, main_branch.id))
    assert _bal(lines, lines_of_business['vat_tin']) == D('6.00')     # 24:12 of Q1 2026
    assert _bal(lines, lines_of_business['vat_pla']) == D('3.00')


def test_remittance_with_no_output_vat_in_window_is_flagged(coa, main_branch, lines_of_business):
    _je(main_branch.id, 'JV-4', date(2027, 2, 1), [
        (coa['payable'], '5.00', 0), (coa['cash'], 0, '5.00')], entry_type='adjustment')
    VatSettlement.query.delete(); db.session.commit()
    lines, s = O.remap(L.fetch_lines(date(2027, 1, 1), None, main_branch.id))
    assert _bal(lines, coa['payable']) == D('5.00')
    assert s.untraced[0].reason == 'no_output_vat_in_window'


def test_unmapped_category_share_stays_flagged_others_move(coa, main_branch, lines_of_business):
    AppSettings.set_setting(vat_expense_setting_key(lines_of_business['pla'].id), '')
    _je(main_branch.id, 'JV-2', date(2026, 4, 25), [
        (coa['payable'], '36.00', 0), (coa['cash'], 0, '36.00')], entry_type='adjustment')
    lines, s = O.remap(L.fetch_lines(date(2026, 4, 1), None, main_branch.id))
    assert _balanced(lines)
    assert _bal(lines, lines_of_business['vat_tin']) == D('24.00')
    assert _bal(lines, coa['payable']) == D('12.00')
    assert s.untraced[0].reason == 'unmapped_category:Plastic' and s.untraced[0].amount == D('12.00')


def test_reversal_follows_original_document_and_nets_to_zero(coa, main_branch, vl_customer):
    je = _je(main_branch.id, 'J1', date(2026, 3, 10), [
        (coa['ar'], '112.00', 0), (coa['sales_tin'], 0, '100.00'), (coa['output'], 0, '12.00')])
    _si(main_branch.id, vl_customer, je, [(coa['sales_tin'], '112.00', '12.00')])
    _je(main_branch.id, 'JV-R', date(2026, 3, 15), [
        (coa['sales_tin'], '100.00', 0), (coa['output'], '12.00', 0), (coa['ar'], 0, '112.00')],
        entry_type='reversal', reversed_entry_id=je.id)
    lines, s = O.remap(L.fetch_lines(None, None, main_branch.id))
    assert _balanced(lines)
    assert _bal(lines, coa['output']) == D('0.00') and _bal(lines, coa['sales_tin']) == D('0.00')
    assert s.moved_to_income == D('0.00') and s.untraced == []


def test_untraced_reversal_nets_against_its_original(coa, main_branch):
    """Finding 9: a flagged line and its reversal must cancel in untraced_total, not
    double-count. Signed, debit-positive amounts are what make that true."""
    jv = _je(main_branch.id, 'JV-1', date(2026, 3, 20), [
        (coa['output'], '5.00', 0), (coa['cash'], 0, '5.00')], entry_type='adjustment')
    _je(main_branch.id, 'JV-1R', date(2026, 3, 21), [
        (coa['cash'], '5.00', 0), (coa['output'], 0, '5.00')],
        entry_type='reversal', reversed_entry_id=jv.id)
    lines, s = O.remap(L.fetch_lines(None, None, main_branch.id))
    assert _balanced(lines) and _bal(lines, coa['output']) == D('0.00')
    assert [u.amount for u in s.untraced] == [D('5.00'), D('-5.00')]
    assert s.untraced_total == D('0.00')


def test_vat_payable_debit_on_a_non_payment_document_is_manual_entry(coa, main_branch, vl_customer):
    """Finding 10: the document WAS found, it just isn't a CDV -- so it is not a
    remittance, and 'no_source_document' would have been a lie."""
    je = _je(main_branch.id, 'J1', date(2026, 3, 10), [
        (coa['payable'], '10.00', 0), (coa['sales_tin'], 0, '10.00')])
    _si(main_branch.id, vl_customer, je, [(coa['sales_tin'], '10.00', '0.00')])
    lines, s = O.remap(L.fetch_lines(None, None, main_branch.id))
    assert _bal(lines, coa['payable']) == D('10.00')
    assert s.untraced[0].reason == 'manual_entry'


# --- Finding 4: the remittance split is memo-aware -------------------------------------

from app.sales_memos.models import SalesMemo, SalesMemoItem   # noqa: E402


def _credit_memo(branch_id, invoice, si_item, amount, vat, on, number='CM-1', memo_type='credit'):
    m = SalesMemo(branch_id=branch_id, memo_type=memo_type, memo_number=number, memo_date=on,
                  sales_invoice_id=invoice.id, original_invoice_number=invoice.invoice_number,
                  customer_id=invoice.customer_id, customer_name=invoice.customer_name,
                  reason='return', notes='', status='posted')
    m.line_items.append(SalesMemoItem(
        line_number=1, sales_invoice_item_id=si_item.id, product_id=si_item.product_id,
        amount=D(str(amount)), line_total=D(str(amount)),
        vat_rate=D('12.00'), vat_amount=D(str(vat)), account_id=si_item.account_id))
    db.session.add(m); db.session.commit()
    return m


def test_remittance_split_is_reduced_by_a_posted_credit_memo(coa, main_branch, lines_of_business):
    """TIN 24 / PLA 12 of output VAT invoiced in Q1; a posted credit memo returns 12.00 of
    TIN's VAT, so the quarter's split is 12:12 and a 36.00 remittance halves."""
    inv = SalesInvoice.query.filter_by(invoice_number='SI-1').one()
    _credit_memo(main_branch.id, inv, inv.line_items[0], '112.00', '12.00', date(2026, 3, 20))
    _je(main_branch.id, 'JV-2', date(2026, 4, 25), [
        (coa['payable'], '36.00', 0), (coa['cash'], 0, '36.00')], entry_type='adjustment')
    lines, s = O.remap(L.fetch_lines(date(2026, 4, 1), None, main_branch.id))
    assert _balanced(lines) and _bal(lines, coa['payable']) == D('0.00')
    assert _bal(lines, lines_of_business['vat_tin']) == D('18.00')
    assert _bal(lines, lines_of_business['vat_pla']) == D('18.00')


def test_remittance_split_is_increased_by_a_posted_debit_note(coa, main_branch, lines_of_business):
    """A debit note adds to that line's output VAT: TIN 36 / PLA 12 -> 3:1 of 36.00."""
    inv = SalesInvoice.query.filter_by(invoice_number='SI-1').one()
    _credit_memo(main_branch.id, inv, inv.line_items[0], '112.00', '12.00', date(2026, 3, 20),
                 number='DM-1', memo_type='debit')
    _je(main_branch.id, 'JV-2', date(2026, 4, 25), [
        (coa['payable'], '36.00', 0), (coa['cash'], 0, '36.00')], entry_type='adjustment')
    lines, s = O.remap(L.fetch_lines(date(2026, 4, 1), None, main_branch.id))
    assert _bal(lines, lines_of_business['vat_tin']) == D('27.00')
    assert _bal(lines, lines_of_business['vat_pla']) == D('9.00')


# --- Finding 3: the lens must not issue a query per source document ---------------------

from sqlalchemy import event   # noqa: E402


def _remap_statement_count(branch_id):
    """SQL statements issued by remap() alone (the fetch is done first, outside the count)."""
    raw = L.fetch_lines(None, None, branch_id)
    seen = []

    def _count(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    event.listen(db.engine, 'before_cursor_execute', _count)
    try:
        O.remap(raw)
    finally:
        event.remove(db.engine, 'before_cursor_execute', _count)
    return len(seen)


def _n_invoices(coa, branch_id, customer, n, start=1):
    for i in range(start, start + n):
        je = _je(branch_id, f'J{i}', date(2026, 3, 10), [
            (coa['ar'], '112.00', 0), (coa['sales_tin'], 0, '100.00'), (coa['output'], 0, '12.00')])
        _si(branch_id, customer, je, [(coa['sales_tin'], '112.00', '12.00')], number=f'SI-{i}')


def test_remap_query_count_does_not_grow_with_document_count(coa, main_branch, vl_customer):
    """Finding 3: _source_docs bulk-loads headers AND eager-loads their lines, so the lens
    costs a fixed number of statements no matter how many documents are in scope."""
    _n_invoices(coa, main_branch.id, vl_customer, 5)
    few = _remap_statement_count(main_branch.id)
    _n_invoices(coa, main_branch.id, vl_customer, 25, start=6)
    many = _remap_statement_count(main_branch.id)
    assert few == many, f'{few} statements for 5 documents, {many} for 30'
    # 15 today (2 VAT-account lookups, 2 settings, the COA, 6 document headers + 6 eager
    # line loads, categories); the bound is the tripwire, `few == many` is the invariant.
    assert many <= 16, f'{many} statements -- the lens got chattier'
