"""
Tests for two dashboard fixes logged 2026-06-19 via /analyze-page /dashboard:

  * FINDING-001 — branch_id=None must NOT aggregate across all branches.
    Defense-in-depth: every dashboard_data helper returns an empty result when
    no branch is in scope, instead of silently summing every branch's figures.

  * FINDING-002 — the active revenue/expense account lists must be fetched once
    per dashboard render, not re-queried by each helper (4 queries -> 2).
"""
from datetime import timedelta
from decimal import Decimal

import pytest

from app import db
from app.utils import ph_now
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

pytestmark = [pytest.mark.integration, pytest.mark.security]


def _seed_branch_data(db_session, branch):
    """Post one of each money document inside `branch` so every dashboard
    helper has something it *could* wrongly aggregate when unscoped."""
    today = ph_now().date()
    due = today + timedelta(days=30)

    rev = Account(code='4001', name='Sales Revenue', account_type='Revenue',
                  normal_balance='Credit')
    exp = Account(code='5001', name='Office Supplies', account_type='Administrative Expense',
                  normal_balance='Debit')
    db_session.add_all([rev, exp])
    db_session.flush()

    je = JournalEntry(entry_number='JE-SCOPE-0001', entry_date=today,
                      description='scope test', status='posted',
                      branch_id=branch.id, total_debit=Decimal('100.00'),
                      total_credit=Decimal('100.00'), is_balanced=True)
    db_session.add(je)
    db_session.flush()
    db_session.add_all([
        JournalEntryLine(entry_id=je.id, line_number=1, account_id=rev.id,
                         credit_amount=Decimal('100.00'), debit_amount=Decimal('0.00')),
        JournalEntryLine(entry_id=je.id, line_number=2, account_id=exp.id,
                         debit_amount=Decimal('100.00'), credit_amount=Decimal('0.00')),
    ])

    cust = Customer(code='C001', name='Acme Co')
    vend = Vendor(code='V001', name='Supplier Co')
    db_session.add_all([cust, vend])
    db_session.flush()

    db_session.add(SalesInvoice(
        invoice_number='SI-SCOPE-0001', invoice_date=today, due_date=due,
        customer_id=cust.id, customer_name='Acme Co', status='posted',
        total_amount=Decimal('500.00'), amount_paid=Decimal('0.00'),
        balance=Decimal('500.00'), branch_id=branch.id))
    db_session.add(AccountsPayable(
        ap_number='AP-SCOPE-0001', ap_date=today, due_date=due,
        vendor_id=vend.id, vendor_name='Supplier Co', status='posted',
        total_amount=Decimal('300.00'), amount_paid=Decimal('0.00'),
        balance=Decimal('300.00'), branch_id=branch.id))
    db_session.commit()
    return today


@pytest.mark.integration
@pytest.mark.security
class TestNoneBranchDoesNotAggregate:
    """FINDING-001 — a None branch must see nothing, not everything."""

    def test_revenue_stats(self, db_session, main_branch):
        today = _seed_branch_data(db_session, main_branch)
        assert get_revenue_stats(today.year, today.month,
                                 branch_id=main_branch.id)['mtd'] > 0
        assert get_revenue_stats(today.year, today.month,
                                 branch_id=None) == {'mtd': 0.0, 'ytd': 0.0}

    def test_expense_stats(self, db_session, main_branch):
        today = _seed_branch_data(db_session, main_branch)
        assert get_expense_stats(today.year, today.month,
                                 branch_id=main_branch.id)['mtd'] > 0
        assert get_expense_stats(today.year, today.month,
                                 branch_id=None) == {'mtd': 0.0, 'ytd': 0.0}

    def test_receivables_stats(self, db_session, main_branch):
        _seed_branch_data(db_session, main_branch)
        assert get_receivables_stats(branch_id=main_branch.id)['total'] > 0
        assert get_receivables_stats(branch_id=None) == {
            'total': 0.0, 'count': 0, 'overdue': 0.0}

    def test_payables_stats(self, db_session, main_branch):
        _seed_branch_data(db_session, main_branch)
        assert get_payables_stats(branch_id=main_branch.id)['total'] > 0
        assert get_payables_stats(branch_id=None) == {
            'total': 0.0, 'count': 0, 'overdue': 0.0}

    def test_top_customers(self, db_session, main_branch):
        _seed_branch_data(db_session, main_branch)
        assert get_top_customers(branch_id=main_branch.id)
        assert get_top_customers(branch_id=None) == []

    def test_top_vendors(self, db_session, main_branch):
        _seed_branch_data(db_session, main_branch)
        assert get_top_vendors(branch_id=main_branch.id)
        assert get_top_vendors(branch_id=None) == []

    def test_monthly_revenue_trend(self, db_session, main_branch):
        _seed_branch_data(db_session, main_branch)
        assert sum(get_monthly_revenue_trend(branch_id=main_branch.id)['data']) > 0
        assert get_monthly_revenue_trend(branch_id=None) == {'labels': [], 'data': []}

    def test_expense_breakdown(self, db_session, main_branch):
        _seed_branch_data(db_session, main_branch)
        assert sum(get_expense_breakdown(branch_id=main_branch.id)['data']) > 0
        assert get_expense_breakdown(branch_id=None) == {'labels': [], 'data': []}


@pytest.mark.integration
class TestAccountListsFetchedOnce:
    """FINDING-002 — account-type lists fetched once per render, not per helper."""

    def test_dashboard_queries_accounts_by_type_twice(
            self, client, db_session, admin_user, main_branch, login_user):
        # Revenue + Expense accounts present so both type-lookups fire.
        db_session.add_all([
            Account(code='4001', name='Sales', account_type='Revenue',
                    normal_balance='Credit'),
            Account(code='5001', name='Supplies', account_type='Administrative Expense',
                    normal_balance='Debit'),
        ])
        db_session.commit()
        login_user(client, 'admin', 'admin123')

        from sqlalchemy import event
        seen = []

        def _rec(conn, cursor, statement, parameters, context, executemany):
            seen.append(statement)

        engine = db.engine
        event.listen(engine, 'after_cursor_execute', _rec)
        try:
            resp = client.get('/dashboard')
        finally:
            event.remove(engine, 'after_cursor_execute', _rec)

        assert resp.status_code == 200
        acct_type_queries = [s for s in seen
                             if 'from accounts' in s.lower()
                             and 'account_type' in s.lower()]
        assert len(acct_type_queries) == 2, (
            f'expected 2 account-by-type queries, got {len(acct_type_queries)}')
