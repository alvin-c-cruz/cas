"""
Dashboard data service - provides real business metrics

This module calculates real-time business statistics from the database:
- Revenue and expense figures
- Accounts receivable and payable
- Top customers and vendors
- Monthly trends
"""
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
from sqlalchemy import func, extract, and_, or_
from decimal import Decimal

from app import db
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.accounts.models import Account
from app.sales_invoices.models import SalesInvoice
from app.accounts_payable.models import AccountsPayable


def get_revenue_stats(year, month, branch_id=None, as_of_date=None):
    """
    Get revenue statistics for MTD and YTD from revenue accounts (4xxxx)

    Args:
        year: int - Year to calculate for
        month: int - Month to calculate for (1-12)
        branch_id: int - Branch ID to filter by (optional, filters by current branch if provided)
        as_of_date: date - Cut-off date for calculations (optional, defaults to today)

    Returns:
        dict with 'mtd' and 'ytd' revenue totals
    """
    if as_of_date is None:
        as_of_date = date.today()

    # Get all revenue accounts (by type — code prefixes vary per company COA)
    revenue_accounts = Account.query.filter(
        Account.account_type == 'Revenue',
        Account.is_active == True
    ).all()

    revenue_account_ids = [acc.id for acc in revenue_accounts]

    if not revenue_account_ids:
        return {'mtd': 0.00, 'ytd': 0.00}

    # MTD (Month-To-Date): All posted journal entries for this month up to as_of_date
    mtd_query = db.session.query(
        func.sum(JournalEntryLine.credit_amount - JournalEntryLine.debit_amount)
    ).join(JournalEntry).filter(
        JournalEntry.status == 'posted',
        JournalEntryLine.account_id.in_(revenue_account_ids),
        extract('year', JournalEntry.entry_date) == year,
        extract('month', JournalEntry.entry_date) == month,
        JournalEntry.entry_date <= as_of_date
    )

    # Filter by branch if specified
    if branch_id is not None:
        mtd_query = mtd_query.filter(JournalEntry.branch_id == branch_id)

    mtd_revenue = mtd_query.scalar() or Decimal('0.00')

    # YTD (Year-To-Date): All posted journal entries for this year up to as_of_date
    ytd_query = db.session.query(
        func.sum(JournalEntryLine.credit_amount - JournalEntryLine.debit_amount)
    ).join(JournalEntry).filter(
        JournalEntry.status == 'posted',
        JournalEntryLine.account_id.in_(revenue_account_ids),
        extract('year', JournalEntry.entry_date) == year,
        JournalEntry.entry_date <= as_of_date
    )

    # Filter by branch if specified
    if branch_id is not None:
        ytd_query = ytd_query.filter(JournalEntry.branch_id == branch_id)

    ytd_revenue = ytd_query.scalar() or Decimal('0.00')

    return {
        'mtd': float(mtd_revenue),
        'ytd': float(ytd_revenue)
    }


def get_expense_stats(year, month, branch_id=None, as_of_date=None):
    """
    Get expense statistics for MTD and YTD from expense accounts (5xxxx)

    Args:
        year: int - Year to calculate for
        month: int - Month to calculate for (1-12)
        branch_id: int - Branch ID to filter by (optional, filters by current branch if provided)
        as_of_date: date - Cut-off date for calculations (optional, defaults to today)

    Returns:
        dict with 'mtd' and 'ytd' expense totals
    """
    if as_of_date is None:
        as_of_date = date.today()

    # Get all expense accounts (by type — code prefixes vary per company COA)
    expense_accounts = Account.query.filter(
        Account.account_type == 'Expense',
        Account.is_active == True
    ).all()

    expense_account_ids = [acc.id for acc in expense_accounts]

    if not expense_account_ids:
        return {'mtd': 0.00, 'ytd': 0.00}

    # MTD: All posted journal entries for this month up to as_of_date
    mtd_query = db.session.query(
        func.sum(JournalEntryLine.debit_amount - JournalEntryLine.credit_amount)
    ).join(JournalEntry).filter(
        JournalEntry.status == 'posted',
        JournalEntryLine.account_id.in_(expense_account_ids),
        extract('year', JournalEntry.entry_date) == year,
        extract('month', JournalEntry.entry_date) == month,
        JournalEntry.entry_date <= as_of_date
    )

    # Filter by branch if specified
    if branch_id is not None:
        mtd_query = mtd_query.filter(JournalEntry.branch_id == branch_id)

    mtd_expense = mtd_query.scalar() or Decimal('0.00')

    # YTD: All posted journal entries for this year up to as_of_date
    ytd_query = db.session.query(
        func.sum(JournalEntryLine.debit_amount - JournalEntryLine.credit_amount)
    ).join(JournalEntry).filter(
        JournalEntry.status == 'posted',
        JournalEntryLine.account_id.in_(expense_account_ids),
        extract('year', JournalEntry.entry_date) == year,
        JournalEntry.entry_date <= as_of_date
    )

    # Filter by branch if specified
    if branch_id is not None:
        ytd_query = ytd_query.filter(JournalEntry.branch_id == branch_id)

    ytd_expense = ytd_query.scalar() or Decimal('0.00')

    return {
        'mtd': float(mtd_expense),
        'ytd': float(ytd_expense)
    }


def get_receivables_stats(as_of_date=None, branch_id=None):
    """
    Get accounts receivable statistics from sales invoices

    Args:
        as_of_date: date - Calculate receivables as of this date (optional, defaults to today)
        branch_id: int - Branch ID to filter by (optional)

    Returns:
        dict with:
        - total: Total outstanding receivables
        - count: Number of unpaid invoices
        - overdue: Amount overdue (past due date)
    """
    if as_of_date is None:
        as_of_date = date.today()

    base_filter = [
        SalesInvoice.status.in_(['posted', 'partially_paid']),
        SalesInvoice.invoice_date <= as_of_date,
    ]
    if branch_id is not None:
        base_filter.append(SalesInvoice.branch_id == branch_id)

    total_receivable, count = db.session.query(
        func.sum(SalesInvoice.total_amount - SalesInvoice.amount_paid),
        func.count(SalesInvoice.id)
    ).filter(*base_filter).one()

    overdue_amount = db.session.query(
        func.sum(SalesInvoice.total_amount - SalesInvoice.amount_paid)
    ).filter(*base_filter, SalesInvoice.due_date < as_of_date).scalar()

    return {
        'total': float(total_receivable or Decimal('0.00')),
        'count': count or 0,
        'overdue': float(overdue_amount or Decimal('0.00')),
    }


def get_payables_stats(as_of_date=None, branch_id=None):
    """
    Get accounts payable statistics from purchase bills

    Args:
        as_of_date: date - Calculate payables as of this date (optional, defaults to today)
        branch_id: int - Branch ID to filter by (optional)

    Returns:
        dict with:
        - total: Total outstanding payables
        - count: Number of unpaid bills
        - overdue: Amount overdue (past due date)
    """
    if as_of_date is None:
        as_of_date = date.today()

    base_filter = [
        AccountsPayable.status.in_(['posted', 'partially_paid']),
        AccountsPayable.ap_date <= as_of_date,
    ]
    if branch_id is not None:
        base_filter.append(AccountsPayable.branch_id == branch_id)

    total_payable, count = db.session.query(
        func.sum(AccountsPayable.total_amount - AccountsPayable.amount_paid),
        func.count(AccountsPayable.id)
    ).filter(*base_filter).one()

    overdue_amount = db.session.query(
        func.sum(AccountsPayable.total_amount - AccountsPayable.amount_paid)
    ).filter(*base_filter, AccountsPayable.due_date < as_of_date).scalar()

    return {
        'total': float(total_payable or Decimal('0.00')),
        'count': count or 0,
        'overdue': float(overdue_amount or Decimal('0.00')),
    }


def get_top_customers(limit=5, as_of_date=None, branch_id=None):
    """
    Get top customers by total sales amount

    Args:
        limit: Maximum number of customers to return
        as_of_date: date - Consider invoices up to this date (optional, defaults to today)
        branch_id: int - Branch ID to filter by (optional)

    Returns:
        List of dicts with customer info and sales totals
    """
    if as_of_date is None:
        as_of_date = date.today()

    query = db.session.query(
        SalesInvoice.customer_name,
        func.sum(SalesInvoice.total_amount).label('total_sales'),
        func.count(SalesInvoice.id).label('invoice_count')
    ).filter(
        SalesInvoice.status.in_(['posted', 'paid', 'partially_paid']),
        SalesInvoice.invoice_date <= as_of_date
    )
    if branch_id is not None:
        query = query.filter(SalesInvoice.branch_id == branch_id)
    top_customers_data = query.group_by(
        SalesInvoice.customer_name
    ).order_by(
        func.sum(SalesInvoice.total_amount).desc()
    ).limit(limit).all()

    customers = []
    for customer_name, total_sales, invoice_count in top_customers_data:
        customers.append({
            'name': customer_name,
            'total_sales': float(total_sales or 0),
            'invoice_count': invoice_count
        })

    return customers


def get_top_vendors(limit=5, as_of_date=None, branch_id=None):
    """
    Get top vendors by total purchase amount

    Args:
        limit: Maximum number of vendors to return
        as_of_date: date - Consider bills up to this date (optional, defaults to today)
        branch_id: int - Branch ID to filter by (optional)

    Returns:
        List of dicts with vendor info and purchase totals
    """
    if as_of_date is None:
        as_of_date = date.today()

    query = db.session.query(
        AccountsPayable.vendor_name,
        func.sum(AccountsPayable.total_amount).label('total_purchases'),
        func.count(AccountsPayable.id).label('bill_count')
    ).filter(
        AccountsPayable.status.in_(['posted', 'paid', 'partially_paid']),
        AccountsPayable.ap_date <= as_of_date
    )
    if branch_id is not None:
        query = query.filter(AccountsPayable.branch_id == branch_id)
    top_vendors_data = query.group_by(
        AccountsPayable.vendor_name
    ).order_by(
        func.sum(AccountsPayable.total_amount).desc()
    ).limit(limit).all()

    vendors = []
    for vendor_name, total_purchases, bill_count in top_vendors_data:
        vendors.append({
            'name': vendor_name,
            'total_purchases': float(total_purchases or 0),
            'bill_count': bill_count
        })

    return vendors


def get_monthly_revenue_trend(months=6, as_of_date=None, branch_id=None):
    """
    Get revenue trend for the last N months

    Args:
        months: Number of months to include (default 6)
        as_of_date: date - End date for the trend (optional, defaults to today)
        branch_id: int - Branch ID to filter by (optional)

    Returns:
        dict with labels and data for Chart.js line chart
    """
    if as_of_date is None:
        as_of_date = date.today()

    revenue_accounts = Account.query.filter(
        Account.account_type == 'Revenue',
        Account.is_active == True
    ).all()

    revenue_account_ids = [acc.id for acc in revenue_accounts]

    if not revenue_account_ids:
        return {'labels': [], 'data': []}

    # Calculate months to query
    months_data = []

    for i in range(months - 1, -1, -1):
        # Calculate the month/year for this iteration
        target_date = as_of_date - relativedelta(months=i)
        target_year = target_date.year
        target_month = target_date.month

        # Get revenue for this month, but only up to as_of_date if it's the current month
        month_revenue_query = db.session.query(
            func.sum(JournalEntryLine.credit_amount - JournalEntryLine.debit_amount)
        ).join(JournalEntry).filter(
            JournalEntry.status == 'posted',
            JournalEntryLine.account_id.in_(revenue_account_ids),
            extract('year', JournalEntry.entry_date) == target_year,
            extract('month', JournalEntry.entry_date) == target_month
        )

        if branch_id is not None:
            month_revenue_query = month_revenue_query.filter(JournalEntry.branch_id == branch_id)

        # If this is the month of as_of_date, only include entries up to that date
        if target_year == as_of_date.year and target_month == as_of_date.month:
            month_revenue_query = month_revenue_query.filter(JournalEntry.entry_date <= as_of_date)

        month_revenue = month_revenue_query.scalar() or Decimal('0.00')

        # Format month label
        month_label = target_date.strftime('%b %Y')

        months_data.append({
            'label': month_label,
            'value': float(month_revenue)
        })

    return {
        'labels': [m['label'] for m in months_data],
        'data': [m['value'] for m in months_data]
    }


def get_expense_breakdown(as_of_date=None, branch_id=None):
    """
    Get expense breakdown by category for pie chart

    Args:
        as_of_date: date - Calculate expenses up to this date (optional, defaults to today)
        branch_id: int - Branch ID to filter by (optional)

    Returns:
        dict with labels and data for Chart.js pie chart
    """
    if as_of_date is None:
        as_of_date = date.today()

    expense_accounts = Account.query.filter(
        Account.account_type == 'Expense',
        Account.is_active == True
    ).all()

    if not expense_accounts:
        return {'labels': [], 'data': []}

    expense_account_ids = [acc.id for acc in expense_accounts]
    account_code_map = {acc.id: acc.code for acc in expense_accounts}

    totals_query = db.session.query(
        JournalEntryLine.account_id,
        func.sum(JournalEntryLine.debit_amount - JournalEntryLine.credit_amount).label('total')
    ).join(JournalEntry).filter(
        JournalEntry.status == 'posted',
        JournalEntryLine.account_id.in_(expense_account_ids),
        extract('year', JournalEntry.entry_date) == as_of_date.year,
        JournalEntry.entry_date <= as_of_date
    ).group_by(JournalEntryLine.account_id)

    if branch_id is not None:
        totals_query = totals_query.filter(JournalEntry.branch_id == branch_id)

    account_totals = {
        row.account_id: row.total or Decimal('0.00')
        for row in totals_query.all()
    }

    categories = {}
    for account in expense_accounts:
        category_code = account.code[:2] + 'xxx'
        category_name = _get_expense_category_name(category_code)
        account_total = account_totals.get(account.id, Decimal('0.00'))
        categories[category_name] = categories.get(category_name, Decimal('0.00')) + account_total

    # Convert to chart format
    labels = list(categories.keys())
    data = [float(v) for v in categories.values()]

    return {
        'labels': labels,
        'data': data
    }


def _get_expense_category_name(category_code):
    """
    Get friendly name for expense category code

    Args:
        category_code: 2-digit expense category (e.g., '51xxx', '52xxx')

    Returns:
        Friendly category name
    """
    category_names = {
        '50xxx': 'Cost of Sales',
        '51xxx': 'Personnel Expenses',
        '52xxx': 'Administrative Expenses',
        '53xxx': 'Selling Expenses',
        '54xxx': 'Financial Expenses',
        '55xxx': 'Other Expenses',
        '56xxx': 'Depreciation',
        '57xxx': 'Taxes and Licenses',
        '58xxx': 'Other Operating Expenses',
        '59xxx': 'Non-Operating Expenses'
    }

    return category_names.get(category_code, f'Expenses ({category_code})')
