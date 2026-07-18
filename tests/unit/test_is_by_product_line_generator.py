from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.customers.models import Customer
from app.branches.models import Branch
from app.products.models import Product
from app.product_categories.models import ProductCategory
from app.accounts.models import Account
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.expense_allocation_rules.models import ExpenseAllocationRule
from app.reports.financial import generate_income_statement
from app.reports.income_statement_by_product_line import (
    generate_income_statement_by_product_line, UNALLOCATED, TOTAL)

pytestmark = [pytest.mark.unit]

D = lambda v: Decimal(str(v))


def _branch():
    b = Branch(name='Main', code='MAIN'); db.session.add(b); db.session.commit()
    return b


def _acct(code, name, atype, normal='debit'):
    a = Account(code=code, name=name, account_type=atype, normal_balance=normal, is_active=True)
    db.session.add(a); db.session.commit()
    return a


def _je(branch_id, lines, number):
    je = JournalEntry(entry_number=number, entry_date=date(2026, 5, 10), description='d',
                      reference=number, entry_type='adjustment', branch_id=branch_id,
                      status='posted', is_balanced=True, total_debit=Decimal('0'),
                      total_credit=Decimal('0'))
    db.session.add(je); db.session.flush()
    n = 1
    for acct, dr, cr in lines:
        db.session.add(JournalEntryLine(entry_id=je.id, line_number=n, account_id=acct.id,
                                        debit_amount=D(dr), credit_amount=D(cr)))
        n += 1
    db.session.commit()


def _full_scenario():
    """One branch, one category (BEV), a full P&L with a posted revenue/COGS/opex JE set
    AND a matching Sales Invoice (so the product-line side has real per-category signal)."""
    b = _branch()
    cash = _acct('10101', 'Cash', 'Asset', 'credit')
    sales = _acct('40101', 'Sales - Goods', 'Revenue', 'credit')
    cogs = _acct('50101', 'Cost of Goods Sold', 'Cost of Goods Sold', 'debit')
    sell = _acct('50211', 'Sales Commissions', 'Selling Expense', 'debit')
    admin = _acct('50221', 'Office Salaries', 'Administrative Expense', 'debit')

    cat = ProductCategory(code='BEV', name='Beverages', is_active=True)
    db.session.add(cat); db.session.flush()
    p = Product(code='P1', name='Cola', category_id=cat.id, standard_cost=D('40'))
    db.session.add(p); db.session.flush()

    cust = Customer(code='C1', name='Acme'); db.session.add(cust); db.session.flush()
    inv = SalesInvoice(invoice_number='SI-1', invoice_date=date(2026, 5, 10),
                       due_date=date(2026, 5, 10), customer_id=cust.id, customer_name='Acme',
                       status='posted', branch_id=b.id)
    db.session.add(inv); db.session.flush()
    db.session.add(SalesInvoiceItem(invoice_id=inv.id, line_number=1, description='Cola',
                                    product_id=p.id, quantity=D('10'),
                                    line_total=D('1000'), vat_amount=D('107.14')))
    db.session.commit()

    # Net sales == 892.86; standard COGS == 10 x 40 == 400; actual GL COGS == 500 (variance 100)
    _je(b.id, [(cash, 1000, 0), (sales, 0, 892.86)], 'JE-S')
    _je(b.id, [(cogs, 500, 0), (cash, 0, 500)], 'JE-C')
    _je(b.id, [(sell, 30, 0), (cash, 0, 30)], 'JE-SE')
    _je(b.id, [(admin, 70, 0), (cash, 0, 70)], 'JE-AE')
    return b, cat, sell, admin


class TestMasterInvariant:
    def test_total_column_ties_to_income_statement_every_subtotal(self, db_session):
        b, cat, sell, admin = _full_scenario()
        out = generate_income_statement_by_product_line(
            date(2026, 5, 31), date(2026, 5, 1), date(2026, 1, 1), branch_id=b.id)
        mtd_rec = out['mtd']['reconciliation']
        for key in ('net_sales', 'gross_profit', 'operating_income', 'income_before_tax', 'net_income'):
            assert mtd_rec[key]['ties'] is True, f'{key} did not tie: {mtd_rec[key]}'
            assert round(mtd_rec[key]['is_total'], 2) == round(mtd_rec[key]['matrix_total'], 2)

    def test_every_line_row_sums_to_its_section_total(self, db_session):
        # revenue/selling/admin ties come from _distribute's exact-sum guarantee on the
        # actual leaf amount. 'cogs' is the one exception: it shows STANDARD cost (400),
        # not the actual GL total (500) -- 'cogs_variance' (100) is the plug, so the pair
        # together (not 'cogs' alone) ties to the section total.
        b, cat, sell, admin = _full_scenario()
        stmt = generate_income_statement(date(2026, 5, 1), date(2026, 5, 31), b.id)
        out = generate_income_statement_by_product_line(
            date(2026, 5, 31), date(2026, 5, 1), date(2026, 1, 1), branch_id=b.id)
        rows_by_key = {r['key']: r for r in out['mtd']['rows']}
        section_by_key = {s['key']: s for s in stmt['sections']}
        for key in ('revenue', 'selling', 'admin'):
            assert round(rows_by_key[key]['by_column'][TOTAL], 2) == round(section_by_key[key]['total'], 2)
        cogs_plus_variance = (rows_by_key['cogs']['by_column'][TOTAL]
                             + rows_by_key['cogs_variance']['by_column'][TOTAL])
        assert round(cogs_plus_variance, 2) == round(section_by_key['cogs']['total'], 2)

    def test_cogs_variance_row_present_and_correct(self, db_session):
        b, cat, sell, admin = _full_scenario()
        out = generate_income_statement_by_product_line(
            date(2026, 5, 31), date(2026, 5, 1), date(2026, 1, 1), branch_id=b.id)
        rows_by_key = {r['key']: r for r in out['mtd']['rows']}
        # actual GL COGS 500 - standard COGS 400 == variance 100
        assert round(rows_by_key['cogs_variance']['by_column'][TOTAL], 2) == 100.0

    def test_unconfigured_expense_account_falls_to_unallocated(self, db_session):
        b, cat, sell, admin = _full_scenario()
        out = generate_income_statement_by_product_line(
            date(2026, 5, 31), date(2026, 5, 1), date(2026, 1, 1), branch_id=b.id)
        rows_by_key = {r['key']: r for r in out['mtd']['rows']}
        assert rows_by_key['selling']['by_column'][UNALLOCATED] == 30.0
        assert rows_by_key['selling']['by_column'][cat.id] == 0.0

    def test_configured_expense_account_allocates_by_revenue_share(self, db_session):
        b, cat, sell, admin = _full_scenario()
        db.session.add(ExpenseAllocationRule(account_id=admin.id, basis='revenue_share'))
        db.session.commit()
        out = generate_income_statement_by_product_line(
            date(2026, 5, 31), date(2026, 5, 1), date(2026, 1, 1), branch_id=b.id)
        rows_by_key = {r['key']: r for r in out['mtd']['rows']}
        # Only one category has revenue -> 100% of the admin account's 70 goes to it.
        assert rows_by_key['admin']['by_column'][cat.id] == 70.0
        assert rows_by_key['admin']['by_column'][UNALLOCATED] == 0.0

    def test_columns_include_category_unallocated_and_total(self, db_session):
        b, cat, sell, admin = _full_scenario()
        out = generate_income_statement_by_product_line(
            date(2026, 5, 31), date(2026, 5, 1), date(2026, 1, 1), branch_id=b.id)
        col_ids = {c['category_id'] for c in out['columns']}
        assert cat.id in col_ids
        assert UNALLOCATED in col_ids
        assert TOTAL in col_ids

    def test_empty_period_no_crash_and_reconciles(self, db_session):
        b = _branch()
        out = generate_income_statement_by_product_line(
            date(2026, 5, 31), date(2026, 5, 1), date(2026, 1, 1), branch_id=b.id)
        for key in ('net_sales', 'gross_profit', 'operating_income', 'income_before_tax', 'net_income'):
            assert out['mtd']['reconciliation'][key]['ties'] is True
