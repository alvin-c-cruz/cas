"""Statement generators under both bases. Invariants: GAAP figures equal the hand-computed
books; owners' NI - GAAP NI == basis_summary.net_income_effect; owners' TB and BS balance."""
from datetime import date, datetime
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
from app.year_end.models import FiscalYearClose
from app.reports.basis import GAAP, OWNERS
from app.reports.financial import (generate_trial_balance, generate_income_statement,
                                   generate_balance_sheet, generate_cash_flow)
from app.reports.two_column import merge_is_two_column

pytestmark = [pytest.mark.owners_basis, pytest.mark.integration]
D = Decimal


def _acct(code, name, atype, normal, classification=None):
    a = Account(code=code, name=name, account_type=atype, normal_balance=normal,
                classification=classification, is_active=True)
    db.session.add(a); db.session.commit()
    return a


def _je(branch_id, number, on, legs, entry_type='sale'):
    total = sum(D(str(d)) for _, d, _ in legs)
    je = JournalEntry(entry_number=number, entry_date=on, description=number, reference=number,
                      entry_type=entry_type, branch_id=branch_id, status='posted',
                      is_balanced=True, total_debit=total, total_credit=total)
    db.session.add(je); db.session.flush()
    for i, (acct, d, c) in enumerate(legs, start=1):
        db.session.add(JournalEntryLine(entry_id=je.id, line_number=i, account_id=acct.id,
                                        debit_amount=D(str(d)), credit_amount=D(str(c))))
    db.session.commit()
    return je


@pytest.fixture
def books(db_session, main_branch, vl_customer, vl_vendor):
    """2026-03: one sale 100 + 12 VAT, one purchase 40 + 4.80 VAT. GAAP NI = 60.
    Owners: sales 112, supplies 44.80 -> NI 67.20 (effect +7.20)."""
    c = {
        'cash': _acct('111001', 'CASH', 'Asset', 'Debit', 'Current'),
        'ar': _acct('112001', 'AR', 'Asset', 'Debit', 'Current'),
        'input': _acct('129008', 'INPUT TAX', 'Asset', 'Debit', 'Current'),
        'ap': _acct('211001', 'AP', 'Liability', 'Credit', 'Current'),
        'output': _acct('213005', 'OUTPUT TAX', 'Liability', 'Credit', 'Current'),
        'capital': _acct('301001', 'CAPITAL', 'Equity', 'Credit'),
        're': _acct('302001', 'RETAINED EARNINGS', 'Equity', 'Credit'),
        'sales': _acct('411001', 'SALES', 'Revenue', 'Credit'),
        'supplies': _acct('721001', 'SUPPLIES', 'Administrative Expense', 'Debit'),
    }
    db.session.add(SalesVATCategory(code='V12', name='V', rate=D('12'), transaction_nature='regular',
                                    output_vat_account_id=c['output'].id))
    db.session.add(VATCategory(code='V12DG', name='I', rate=D('12'), transaction_nature='domestic_goods',
                               input_vat_account_id=c['input'].id))
    db.session.commit()
    _je(main_branch.id, 'CAP', date(2026, 1, 1), [(c['cash'], '1000.00', 0), (c['capital'], 0, '1000.00')],
        entry_type='opening_balance')
    sale = _je(main_branch.id, 'S1', date(2026, 3, 10), [
        (c['ar'], '112.00', 0), (c['sales'], 0, '100.00'), (c['output'], 0, '12.00')])
    inv = SalesInvoice(branch_id=main_branch.id, invoice_number='SI-1', invoice_date=date(2026, 3, 10),
                       due_date=date(2026, 3, 10), customer_id=vl_customer.id, customer_name=vl_customer.name,
                       customer_tin=vl_customer.tin, status='posted', journal_entry_id=sale.id)
    inv.line_items.append(SalesInvoiceItem(line_number=1, description='x', amount=D('112'), vat_rate=D('12'),
                                           vat_category='V12', vat_nature='regular', line_total=D('112'),
                                           vat_amount=D('12'), account_id=c['sales'].id))
    buy = _je(main_branch.id, 'P1', date(2026, 3, 12), [
        (c['supplies'], '40.00', 0), (c['input'], '4.80', 0), (c['ap'], 0, '44.80')], entry_type='purchase')
    ap = AccountsPayable(branch_id=main_branch.id, ap_number='AP-1', ap_date=date(2026, 3, 12),
                         due_date=date(2026, 3, 12), payee_type='vendor', payee_id=vl_vendor.id,
                         vendor_id=vl_vendor.id, vendor_name=vl_vendor.name, notes='', status='posted',
                         journal_entry_id=buy.id)
    ap.line_items.append(AccountsPayableItem(line_number=1, description='x', amount=D('44.80'), vat_rate=D('12'),
                                             line_total=D('44.80'), vat_amount=D('4.80'), account_id=c['supplies'].id))
    db.session.add_all([inv, ap]); db.session.commit()
    c['branch'] = main_branch.id
    return c


def test_gaap_income_statement_unchanged(books):
    is_ = generate_income_statement(date(2026, 1, 1), date(2026, 3, 31), branch_id=books['branch'])
    assert is_['net_income'] == 60.0 and is_['reporting_basis'] == GAAP
    assert 'basis_summary' not in is_


def test_owners_income_statement_and_identity(books):
    gaap = generate_income_statement(date(2026, 1, 1), date(2026, 3, 31), branch_id=books['branch'])
    own = generate_income_statement(date(2026, 1, 1), date(2026, 3, 31), branch_id=books['branch'],
                                    reporting_basis=OWNERS)
    assert own['net_income'] == pytest.approx(67.20)
    assert own['net_sales'] == pytest.approx(112.0)
    s = own['basis_summary']
    assert s['moved_to_income'] == 12.0 and s['moved_to_expense'] == 4.8 and s['untraced'] == []
    assert own['net_income'] - gaap['net_income'] == pytest.approx(s['net_income_effect'])


def test_two_column_merge_carries_summary(books):
    mtd = generate_income_statement(date(2026, 3, 1), date(2026, 3, 31), branch_id=books['branch'], reporting_basis=OWNERS)
    ytd = generate_income_statement(date(2026, 1, 1), date(2026, 3, 31), branch_id=books['branch'], reporting_basis=OWNERS)
    merged = merge_is_two_column(mtd, ytd)
    assert merged['reporting_basis'] == OWNERS
    assert merged['basis_summary']['ytd']['net_income_effect'] == pytest.approx(7.2)


def test_owners_trial_balance_balances_without_vat_accounts(books):
    tb = generate_trial_balance(date(2026, 3, 31), branch_id=books['branch'], reporting_basis=OWNERS)
    assert tb['is_balanced']
    codes = {r['code'] for r in tb['accounts']}
    assert '213005' not in codes and '129008' not in codes
    gaap = generate_trial_balance(date(2026, 3, 31), branch_id=books['branch'])
    assert {r['code'] for r in gaap['accounts']} >= {'213005', '129008'}


def test_owners_balance_sheet_balances_and_drops_vat(books):
    gaap = generate_balance_sheet(date(2026, 3, 31), branch_id=books['branch'])
    own = generate_balance_sheet(date(2026, 3, 31), branch_id=books['branch'], reporting_basis=OWNERS)
    assert gaap['is_balanced'] and own['is_balanced']
    assert own['total_assets'] == pytest.approx(gaap['total_assets'] - 4.8)
    assert own['total_liabilities'] == pytest.approx(gaap['total_liabilities'] - 12.0)
    assert own['total_equity'] == pytest.approx(gaap['total_equity'] + 7.2)
    assert own['basis_summary']['net_income_effect'] == pytest.approx(7.2)


def test_owners_balance_sheet_carries_prior_closed_year_adjustment(books, admin_user):
    """A closed year closed GAAP figures into RE; the owners' VAT effect of that year is
    still sitting in the P&L accounts and must appear as its own equity line."""
    c = books
    sale = _je(c['branch'], 'S0', date(2025, 6, 1), [
        (c['ar'], '224.00', 0), (c['sales'], 0, '200.00'), (c['output'], 0, '24.00')])
    inv = SalesInvoice(branch_id=c['branch'], invoice_number='SI-0', invoice_date=date(2025, 6, 1),
                       due_date=date(2025, 6, 1), customer_id=SalesInvoice.query.first().customer_id,
                       customer_name='x', customer_tin='',
                       status='posted', journal_entry_id=sale.id)
    inv.line_items.append(SalesInvoiceItem(line_number=1, description='x', amount=D('224'), vat_rate=D('12'),
                                           vat_category='V12', vat_nature='regular', line_total=D('224'),
                                           vat_amount=D('24'), account_id=c['sales'].id))
    db.session.add(inv)
    _je(c['branch'], 'CLOSE-2025', date(2025, 12, 31), [(c['sales'], '200.00', 0), (c['re'], 0, '200.00')],
        entry_type='closing')
    db.session.add(FiscalYearClose(fiscal_year=2025, branch_id=c['branch'], status='closed',
                                   net_income=D('200'), closed_at=datetime(2026, 1, 5), closed_by_id=admin_user.id))
    db.session.commit()
    own = generate_balance_sheet(date(2026, 3, 31), branch_id=c['branch'], reporting_basis=OWNERS)
    assert own['is_balanced']
    equity = next(s for s in own['sections'] if s['key'] == 'equity')
    names = {ln['name']: ln['total'] for dv in equity['divisions'] for ln in dv['lines']}
    assert names["Prior years' VAT adjustment (owners' basis)"] == pytest.approx(24.0)
    assert names['Net Income (current year)'] == pytest.approx(67.2)


def test_owners_balance_sheet_prior_year_adjustment_can_be_negative(books, admin_user):
    """The mirror image of the credit-side case: a closed year whose only owners'-basis
    residual is INPUT VAT moved into expense. The prior-years line must go NEGATIVE
    (owners' equity is lower than the books say) and the sheet must still balance."""
    c = books
    buy = _je(c['branch'], 'P0', date(2025, 6, 1), [
        (c['supplies'], '40.00', 0), (c['input'], '4.80', 0), (c['ap'], 0, '44.80')],
        entry_type='purchase')
    ap = AccountsPayable(branch_id=c['branch'], ap_number='AP-0', ap_date=date(2025, 6, 1),
                         due_date=date(2025, 6, 1), payee_type='vendor',
                         payee_id=AccountsPayable.query.first().vendor_id,
                         vendor_id=AccountsPayable.query.first().vendor_id, vendor_name='x',
                         notes='', status='posted', journal_entry_id=buy.id)
    ap.line_items.append(AccountsPayableItem(line_number=1, description='x', amount=D('44.80'),
                                             vat_rate=D('12'), line_total=D('44.80'),
                                             vat_amount=D('4.80'), account_id=c['supplies'].id))
    db.session.add(ap)
    _je(c['branch'], 'CLOSE-2025', date(2025, 12, 31), [(c['re'], '40.00', 0), (c['supplies'], 0, '40.00')],
        entry_type='closing')
    db.session.add(FiscalYearClose(fiscal_year=2025, branch_id=c['branch'], status='closed',
                                   net_income=D('-40'), closed_at=datetime(2026, 1, 5),
                                   closed_by_id=admin_user.id))
    db.session.commit()
    own = generate_balance_sheet(date(2026, 3, 31), branch_id=c['branch'], reporting_basis=OWNERS)
    assert own['is_balanced']
    equity = next(s for s in own['sections'] if s['key'] == 'equity')
    names = {ln['name']: ln['total'] for dv in equity['divisions'] for ln in dv['lines']}
    assert names["Prior years' VAT adjustment (owners' basis)"] == pytest.approx(-4.8)


def test_cash_flow_gaap_unchanged_and_reconciled(books):
    cf = generate_cash_flow(date(2026, 1, 1), date(2026, 3, 31), branch_id=books['branch'])
    assert cf['is_reconciled'] and cf['reporting_basis'] == GAAP
    assert cf['operating']['net_income'] == 60.0
    direct = generate_cash_flow(date(2026, 1, 1), date(2026, 3, 31), branch_id=books['branch'], method='direct')
    assert direct['is_reconciled'] and direct['net_change'] == pytest.approx(1000.0)


def test_cash_flow_owners_reconciles_to_same_cash(books):
    gaap = generate_cash_flow(date(2026, 1, 1), date(2026, 3, 31), branch_id=books['branch'])
    own = generate_cash_flow(date(2026, 1, 1), date(2026, 3, 31), branch_id=books['branch'], reporting_basis=OWNERS)
    assert own['is_reconciled']
    assert own['operating']['net_income'] == pytest.approx(67.2)
    assert own['cash_end'] == gaap['cash_end'] and own['net_change'] == pytest.approx(gaap['net_change'])
    wc = {w['name']: w['amount'] for w in own['operating']['working_capital']}
    assert '(Increase)/decrease in INPUT TAX' not in wc and 'Increase/(decrease) in OUTPUT TAX' not in wc
    assert wc['(Increase)/decrease in AR'] == pytest.approx(-112.0)
    d = generate_cash_flow(date(2026, 1, 1), date(2026, 3, 31), branch_id=books['branch'],
                           method='direct', reporting_basis=OWNERS)
    assert d['is_reconciled']


from app.reports.financial import generate_general_ledger


def test_general_ledger_gaap_unchanged(books):
    gl = generate_general_ledger(date(2026, 3, 1), date(2026, 3, 31), books['branch'])
    sales = next(a for a in gl['accounts'] if a['code'] == '411001')
    assert sales['closing_balance'] == -100.0 and sales['lines'][0]['moved_from'] is None
    assert gl['reporting_basis'] == GAAP


def test_general_ledger_owners_shows_moved_lines(books):
    gl = generate_general_ledger(date(2026, 3, 1), date(2026, 3, 31), books['branch'], reporting_basis=OWNERS)
    codes = {a['code'] for a in gl['accounts']}
    assert '213005' not in codes and '129008' not in codes
    sales = next(a for a in gl['accounts'] if a['code'] == '411001')
    assert sales['closing_balance'] == -112.0
    moved = [l for l in sales['lines'] if l['moved_from']]
    assert moved == [dict(moved[0], moved_from='213005 OUTPUT TAX')] and moved[0]['credit'] == 12.0
    assert gl['grand_total_debit'] == pytest.approx(gl['grand_total_credit'])


def test_general_ledger_owners_opening_balance_is_remapped(books):
    gl = generate_general_ledger(date(2026, 4, 1), date(2026, 4, 30), books['branch'], reporting_basis=OWNERS)
    supplies = next(a for a in gl['accounts'] if a['code'] == '721001')
    assert supplies['opening_balance'] == 44.8 and supplies['lines'] == []


from app.journal_entries.models import JournalEntry as JE
from app.reports.general_journal_data import build_general_journal
from app.reports.ledger import ledger_lines


def test_general_journal_rows_from_remapped_lines(books):
    c = books
    jv = _je(c['branch'], 'JV-2026-03-0001', date(2026, 3, 20), [
        (c['output'], '5.00', 0), (c['cash'], 0, '5.00')], entry_type='adjustment')
    entries = [db.session.get(JE, jv.id)]
    gaap = build_general_journal(entries)
    assert gaap['rows'][0]['debits'][0]['account'].code == '213005'
    assert gaap['rows'][0]['debits'][0]['moved_from'] is None
    remapped = {}
    for ln in ledger_lines(date(2026, 3, 1), date(2026, 3, 31), c['branch'], reporting_basis=OWNERS):
        remapped.setdefault(ln.entry_id, []).append(ln)
    own = build_general_journal(entries, remapped=remapped)
    assert own['rows'][0]['debits'][0]['account'].code == '213005'      # manual voucher: kept, flagged
    assert own['balanced'] and own['total_debit'] == D('5.00')


from app.product_categories.models import ProductCategory
from app.products.models import Product
from app.reports.basis import vat_expense_setting_key
from app.reports.product_line import generate_sales_by_product_line
from app.reports.income_statement_by_product_line import generate_income_statement_by_product_line


@pytest.fixture
def categorized(books):
    tin = ProductCategory(code='TIN', name='Tincan'); db.session.add(tin); db.session.commit()
    p = Product(name='Can', category_id=tin.id, track_inventory=False); db.session.add(p); db.session.commit()
    inv = SalesInvoice.query.filter_by(invoice_number='SI-1').one()
    inv.line_items[0].product_id = p.id
    vat_tin = _acct('811001', 'VAT EXPENSE - TINCAN', 'Other Expense', 'Debit')
    AppSettings.set_setting(vat_expense_setting_key(tin.id), vat_tin.code)
    db.session.commit()
    _je(books['branch'], 'JV-VAT', date(2026, 3, 25), [(vat_tin, '3.00', 0), (books['cash'], 0, '3.00')],
        entry_type='adjustment')
    books['tin'] = tin
    return books


def test_sales_by_product_line_gross_under_owners(categorized):
    gaap = generate_sales_by_product_line(date(2026, 3, 1), date(2026, 3, 31), categorized['branch'])
    own = generate_sales_by_product_line(date(2026, 3, 1), date(2026, 3, 31), categorized['branch'],
                                         reporting_basis=OWNERS)
    assert gaap['rows'][0]['net'] == 100.0 and own['rows'][0]['net'] == 112.0
    assert own['reporting_basis'] == OWNERS


def test_is_by_product_line_ties_under_owners_and_attributes_vat_expense(categorized):
    data = generate_income_statement_by_product_line(date(2026, 3, 31), date(2026, 3, 1), date(2026, 1, 1),
                                                     branch_id=categorized['branch'], reporting_basis=OWNERS)
    assert data['reporting_basis'] == OWNERS
    assert all(chk['ties'] for chk in data['ytd']['reconciliation'].values())
    rows = {r['key']: r for r in data['ytd']['rows']}
    tin = categorized['tin'].id
    assert rows['revenue']['by_column'][tin] == pytest.approx(112.0)
    assert rows['other_expense']['by_column'][tin] == pytest.approx(3.0)        # direct, not "Unallocated"
    assert rows['other_expense']['by_column']['unallocated'] == pytest.approx(0.0)
