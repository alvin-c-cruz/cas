"""
Value-assertion tests for the dashboard's numeric aggregations
(backlog item 8 — the dashboard aggregate-MATH test gap).

Earlier dashboard tests only cover role visibility and branch-scoping presence;
nobody asserted the actual sums/counts/buckets are correct. This seeds a known
set of posted (and a few draft) documents across TWO branches and TWO months,
then asserts each helper's exact output for branch A as of a fixed date — which
simultaneously pins the MTD/YTD split, status filtering, overdue logic, ranking,
trend bucketing, and category grouping.

Dates are pinned (not ph_now) so the expected values are deterministic
regardless of when the suite runs.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.accounts.models import Account
from app.customers.models import Customer
from app.vendors.models import Vendor
from app.sales_invoices.models import SalesInvoice
from app.accounts_payable.models import AccountsPayable
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.dashboard.dashboard_data import (
    get_revenue_stats, get_expense_stats,
    get_receivables_stats, get_payables_stats,
    get_top_customers, get_top_vendors,
    get_monthly_revenue_trend, get_expense_breakdown,
)

pytestmark = [pytest.mark.integration]

AS_OF = date(2026, 6, 15)      # the "as of" cutoff
CUR = date(2026, 6, 10)        # current month, on/before cutoff
PREV = date(2026, 5, 10)       # previous month, same year
FUTURE_DUE = date(2026, 12, 31)
OVERDUE_DUE = date(2026, 6, 1)  # < AS_OF


def _je(db_session, branch, number, entry_date, account, amount, side, status='posted'):
    amt = Decimal(amount)
    je = JournalEntry(
        entry_number=number, entry_date=entry_date, description='math test',
        status=status, branch_id=branch.id,
        total_debit=amt if side == 'debit' else Decimal('0.00'),
        total_credit=amt if side == 'credit' else Decimal('0.00'),
        is_balanced=False)
    db_session.add(je)
    db_session.flush()
    db_session.add(JournalEntryLine(
        entry_id=je.id, line_number=1, account_id=account.id,
        debit_amount=amt if side == 'debit' else Decimal('0.00'),
        credit_amount=amt if side == 'credit' else Decimal('0.00')))


@pytest.fixture
def seeded(db_session, main_branch, branch_manila):
    """Known documents in branch A (main) and branch B (manila)."""
    a, b = main_branch, branch_manila

    rev = Account(code='4001', name='Sales', account_type='Revenue',
                  normal_balance='Credit')
    # Expense hierarchy: two top-level group headers (non-postable) each with a
    # postable child. The breakdown must roll each child up to its top-level
    # ancestor's NAME (derived from parent_id), not a hardcoded code->name map.
    cos = Account(code='5000', name='Cost of Sales', account_type='Cost of Goods Sold',
                  normal_balance='Debit')
    opex = Account(code='5200', name='Operating Expenses', account_type='Administrative Expense',
                   normal_balance='Debit')
    db_session.add_all([rev, cos, opex])
    db_session.flush()
    cogs = Account(code='5001', name='Cost of goods', account_type='Cost of Goods Sold',
                   normal_balance='Debit', parent_id=cos.id)
    admin = Account(code='5201', name='Admin exp', account_type='Administrative Expense',
                    normal_balance='Debit', parent_id=opex.id)
    db_session.add_all([cogs, admin])
    db_session.flush()

    # Branch A journal entries: revenue 1000 this month + 500 last month;
    # expense 300 (COGS) this month + 200 (Admin) last month; one DRAFT (excluded).
    _je(db_session, a, 'JE-A-1', CUR, rev, '1000.00', 'credit')
    _je(db_session, a, 'JE-A-2', PREV, rev, '500.00', 'credit')
    _je(db_session, a, 'JE-A-3', CUR, cogs, '300.00', 'debit')
    _je(db_session, a, 'JE-A-4', PREV, admin, '200.00', 'debit')
    _je(db_session, a, 'JE-A-5', CUR, rev, '7777.00', 'credit', status='draft')
    # Branch B revenue (must NOT leak into branch A figures).
    _je(db_session, b, 'JE-B-1', CUR, rev, '9999.00', 'credit')

    acme = Customer(code='C-ACME', name='Acme')
    beta = Customer(code='C-BETA', name='Beta')
    zeta = Customer(code='C-ZETA', name='Zeta')
    sup = Vendor(code='V-SUP', name='Supplier')
    oth = Vendor(code='V-OTH', name='Other')
    db_session.add_all([acme, beta, zeta, sup, oth])
    db_session.flush()

    # Branch A receivables: Acme 1200 (paid 200, not overdue), Beta 800 (overdue),
    # plus a DRAFT 999 (excluded).
    db_session.add_all([
        SalesInvoice(invoice_number='SI-A-1', invoice_date=CUR, due_date=FUTURE_DUE,
                     customer_id=acme.id, customer_name='Acme', status='posted',
                     total_amount=Decimal('1200.00'), amount_paid=Decimal('200.00'),
                     balance=Decimal('1000.00'), branch_id=a.id),
        SalesInvoice(invoice_number='SI-A-2', invoice_date=PREV, due_date=OVERDUE_DUE,
                     customer_id=beta.id, customer_name='Beta', status='posted',
                     total_amount=Decimal('800.00'), amount_paid=Decimal('0.00'),
                     balance=Decimal('800.00'), branch_id=a.id),
        SalesInvoice(invoice_number='SI-A-3', invoice_date=CUR, due_date=FUTURE_DUE,
                     customer_id=acme.id, customer_name='Acme', status='draft',
                     total_amount=Decimal('999.00'), amount_paid=Decimal('0.00'),
                     balance=Decimal('999.00'), branch_id=a.id),
        # Branch B receivable (must NOT leak).
        SalesInvoice(invoice_number='SI-B-1', invoice_date=CUR, due_date=FUTURE_DUE,
                     customer_id=zeta.id, customer_name='Zeta', status='posted',
                     total_amount=Decimal('5555.00'), amount_paid=Decimal('0.00'),
                     balance=Decimal('5555.00'), branch_id=b.id),
    ])

    # Branch A payable: Supplier 700 (paid 100). Branch B payable must not leak.
    db_session.add_all([
        AccountsPayable(ap_number='AP-A-1', ap_date=CUR, due_date=FUTURE_DUE,
                        vendor_id=sup.id, vendor_name='Supplier', status='posted',
                        total_amount=Decimal('700.00'), amount_paid=Decimal('100.00'),
                        balance=Decimal('600.00'), branch_id=a.id),
        AccountsPayable(ap_number='AP-B-1', ap_date=CUR, due_date=FUTURE_DUE,
                        vendor_id=oth.id, vendor_name='Other', status='posted',
                        total_amount=Decimal('4444.00'), amount_paid=Decimal('0.00'),
                        balance=Decimal('4444.00'), branch_id=b.id),
    ])
    db_session.commit()
    return a


class TestDashboardAggregateMath:

    def test_revenue_stats_mtd_and_ytd(self, seeded):
        assert get_revenue_stats(2026, 6, branch_id=seeded.id, as_of_date=AS_OF) == {
            'mtd': 1000.0, 'ytd': 1500.0}

    def test_expense_stats_mtd_and_ytd(self, seeded):
        assert get_expense_stats(2026, 6, branch_id=seeded.id, as_of_date=AS_OF) == {
            'mtd': 300.0, 'ytd': 500.0}

    def test_receivables_total_count_and_overdue(self, seeded):
        assert get_receivables_stats(as_of_date=AS_OF, branch_id=seeded.id) == {
            'total': 1800.0, 'count': 2, 'overdue': 800.0}

    def test_payables_total_count_and_overdue(self, seeded):
        assert get_payables_stats(as_of_date=AS_OF, branch_id=seeded.id) == {
            'total': 600.0, 'count': 1, 'overdue': 0.0}

    def test_top_customers_ranked_by_sales(self, seeded):
        assert get_top_customers(as_of_date=AS_OF, branch_id=seeded.id) == [
            {'name': 'Acme', 'total_sales': 1200.0, 'invoice_count': 1},
            {'name': 'Beta', 'total_sales': 800.0, 'invoice_count': 1},
        ]

    def test_top_vendors_ranked_by_purchases(self, seeded):
        assert get_top_vendors(as_of_date=AS_OF, branch_id=seeded.id) == [
            {'name': 'Supplier', 'total_purchases': 700.0, 'bill_count': 1},
        ]

    def test_monthly_revenue_trend_buckets(self, seeded):
        trend = get_monthly_revenue_trend(months=6, as_of_date=AS_OF, branch_id=seeded.id)
        assert trend['labels'] == ['Jan 2026', 'Feb 2026', 'Mar 2026',
                                   'Apr 2026', 'May 2026', 'Jun 2026']
        assert trend['data'] == [0.0, 0.0, 0.0, 0.0, 500.0, 1000.0]

    def test_expense_breakdown_by_category(self, seeded):
        # Each child rolls up to its top-level ancestor's name: the 'Cost of
        # goods' (300) child -> 'Cost of Sales' header; the 'Admin exp' (200)
        # child -> 'Operating Expenses' header. The non-postable headers
        # contribute 0 and do not form their own buckets.
        bd = get_expense_breakdown(as_of_date=AS_OF, branch_id=seeded.id)
        assert dict(zip(bd['labels'], bd['data'])) == {
            'Cost of Sales': 300.0, 'Operating Expenses': 200.0}
