"""
Financial Statements Generator

This module generates the three core financial statements:
1. Trial Balance - Verify debits = credits
2. Income Statement (P&L) - Show profitability
3. Balance Sheet - Show financial position

All statements use the double-entry accounting system and pull data from
posted journal entries.
"""
from datetime import date, datetime
from sqlalchemy import func, and_, extract
from decimal import Decimal

from app import db
from app.accounts.models import Account
from app.journal_entries.models import JournalEntry, JournalEntryLine


def generate_trial_balance(as_of_date=None, branch_id=None):
    """
    Generate Trial Balance as of a specific date

    The Trial Balance lists all accounts with their debit or credit balances.
    It verifies that total debits equal total credits.

    Args:
        as_of_date: date - As of date for the report (defaults to today)

    Returns:
        dict with:
        - as_of_date: The report date
        - accounts: List of account balances
        - total_debit: Sum of all debit balances
        - total_credit: Sum of all credit balances
        - is_balanced: Whether debits = credits
    """
    if as_of_date is None:
        as_of_date = date.today()

    # Get all active accounts
    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()

    account_balances = []
    total_debit = Decimal('0.00')
    total_credit = Decimal('0.00')

    for account in accounts:
        # Calculate balance for this account from journal entry lines
        # Get all posted journal entries up to the as_of_date
        branch_filter = [JournalEntry.branch_id == branch_id] if branch_id else []
        debit_sum = db.session.query(
            func.sum(JournalEntryLine.debit_amount)
        ).join(JournalEntry).filter(
            JournalEntry.status == 'posted',
            JournalEntry.entry_date <= as_of_date,
            JournalEntryLine.account_id == account.id,
            *branch_filter
        ).scalar() or Decimal('0.00')

        credit_sum = db.session.query(
            func.sum(JournalEntryLine.credit_amount)
        ).join(JournalEntry).filter(
            JournalEntry.status == 'posted',
            JournalEntry.entry_date <= as_of_date,
            JournalEntryLine.account_id == account.id,
            *branch_filter
        ).scalar() or Decimal('0.00')

        # Calculate net balance
        balance = debit_sum - credit_sum

        # Skip accounts with zero balance
        if balance == 0:
            continue

        # Determine debit or credit balance based on normal balance
        debit_balance = Decimal('0.00')
        credit_balance = Decimal('0.00')

        if balance > 0:
            debit_balance = balance
            total_debit += balance
        else:
            credit_balance = abs(balance)
            total_credit += abs(balance)

        account_balances.append({
            'code': account.code,
            'name': account.name,
            'account_type': account.account_type,
            'debit_balance': float(debit_balance),
            'credit_balance': float(credit_balance)
        })

    return {
        'as_of_date': as_of_date,
        'accounts': account_balances,
        'total_debit': float(total_debit),
        'total_credit': float(total_credit),
        'is_balanced': (total_debit == total_credit),
        'difference': float(abs(total_debit - total_credit))
    }


def generate_income_statement(start_date, end_date, branch_id=None):
    """
    Generate Income Statement (Profit & Loss) for a period

    Shows:
    - Revenue (4xxxx accounts)
    - Expenses (5xxxx accounts)
    - Net Income = Revenue - Expenses

    Args:
        start_date: date - Start of period
        end_date: date - End of period

    Returns:
        dict with:
        - period_start: Start date
        - period_end: End date
        - revenue: List of revenue accounts with amounts
        - total_revenue: Sum of all revenue
        - expenses: List of expense accounts with amounts
        - total_expenses: Sum of all expenses
        - net_income: Revenue - Expenses
    """
    # Get revenue accounts (4xxxx)
    revenue_accounts = Account.query.filter(
        Account.code.like('4%'),
        Account.is_active == True
    ).order_by(Account.code).all()

    # Get expense accounts (5xxxx)
    expense_accounts = Account.query.filter(
        Account.code.like('5%'),
        Account.is_active == True
    ).order_by(Account.code).all()

    revenue_list = []
    total_revenue = Decimal('0.00')

    for account in revenue_accounts:
        # Revenue accounts have credit normal balance
        # Credit increases revenue, debit decreases
        branch_filter = [JournalEntry.branch_id == branch_id] if branch_id else []
        debit_sum = db.session.query(
            func.sum(JournalEntryLine.debit_amount)
        ).join(JournalEntry).filter(
            JournalEntry.status == 'posted',
            JournalEntry.entry_date >= start_date,
            JournalEntry.entry_date <= end_date,
            JournalEntryLine.account_id == account.id,
            *branch_filter
        ).scalar() or Decimal('0.00')

        credit_sum = db.session.query(
            func.sum(JournalEntryLine.credit_amount)
        ).join(JournalEntry).filter(
            JournalEntry.status == 'posted',
            JournalEntry.entry_date >= start_date,
            JournalEntry.entry_date <= end_date,
            JournalEntryLine.account_id == account.id,
            *branch_filter
        ).scalar() or Decimal('0.00')

        # Net revenue = credits - debits
        amount = credit_sum - debit_sum

        if amount != 0:
            revenue_list.append({
                'code': account.code,
                'name': account.name,
                'amount': float(amount)
            })
            total_revenue += amount

    expense_list = []
    total_expenses = Decimal('0.00')

    for account in expense_accounts:
        # Expense accounts have debit normal balance
        # Debit increases expense, credit decreases
        branch_filter = [JournalEntry.branch_id == branch_id] if branch_id else []
        debit_sum = db.session.query(
            func.sum(JournalEntryLine.debit_amount)
        ).join(JournalEntry).filter(
            JournalEntry.status == 'posted',
            JournalEntry.entry_date >= start_date,
            JournalEntry.entry_date <= end_date,
            JournalEntryLine.account_id == account.id,
            *branch_filter
        ).scalar() or Decimal('0.00')

        credit_sum = db.session.query(
            func.sum(JournalEntryLine.credit_amount)
        ).join(JournalEntry).filter(
            JournalEntry.status == 'posted',
            JournalEntry.entry_date >= start_date,
            JournalEntry.entry_date <= end_date,
            JournalEntryLine.account_id == account.id,
            *branch_filter
        ).scalar() or Decimal('0.00')

        # Net expense = debits - credits
        amount = debit_sum - credit_sum

        if amount != 0:
            expense_list.append({
                'code': account.code,
                'name': account.name,
                'amount': float(amount)
            })
            total_expenses += amount

    net_income = total_revenue - total_expenses

    return {
        'period_start': start_date,
        'period_end': end_date,
        'revenue': revenue_list,
        'total_revenue': float(total_revenue),
        'expenses': expense_list,
        'total_expenses': float(total_expenses),
        'net_income': float(net_income),
        'net_income_percentage': float((net_income / total_revenue * 100) if total_revenue > 0 else 0)
    }


def generate_balance_sheet(as_of_date=None, branch_id=None):
    """
    Generate Balance Sheet as of a specific date

    Shows:
    - Assets (1xxxx accounts)
    - Liabilities (2xxxx accounts)
    - Equity (3xxxx accounts)

    Verifies: Assets = Liabilities + Equity

    Args:
        as_of_date: date - As of date for the report (defaults to today)

    Returns:
        dict with:
        - as_of_date: Report date
        - assets: List of asset accounts with amounts
        - total_assets: Sum of all assets
        - liabilities: List of liability accounts with amounts
        - total_liabilities: Sum of all liabilities
        - equity: List of equity accounts with amounts
        - total_equity: Sum of all equity
        - total_liabilities_equity: Liabilities + Equity
        - is_balanced: Whether Assets = Liabilities + Equity
    """
    if as_of_date is None:
        as_of_date = date.today()

    # Get asset accounts (1xxxx) - debit normal balance
    asset_accounts = Account.query.filter(
        Account.code.like('1%'),
        Account.is_active == True
    ).order_by(Account.code).all()

    # Get liability accounts (2xxxx) - credit normal balance
    liability_accounts = Account.query.filter(
        Account.code.like('2%'),
        Account.is_active == True
    ).order_by(Account.code).all()

    # Get equity accounts (3xxxx) - credit normal balance
    equity_accounts = Account.query.filter(
        Account.code.like('3%'),
        Account.is_active == True
    ).order_by(Account.code).all()

    # Calculate Assets
    asset_list = []
    total_assets = Decimal('0.00')

    for account in asset_accounts:
        # Assets have debit normal balance
        branch_filter = [JournalEntry.branch_id == branch_id] if branch_id else []
        debit_sum = db.session.query(
            func.sum(JournalEntryLine.debit_amount)
        ).join(JournalEntry).filter(
            JournalEntry.status == 'posted',
            JournalEntry.entry_date <= as_of_date,
            JournalEntryLine.account_id == account.id,
            *branch_filter
        ).scalar() or Decimal('0.00')

        credit_sum = db.session.query(
            func.sum(JournalEntryLine.credit_amount)
        ).join(JournalEntry).filter(
            JournalEntry.status == 'posted',
            JournalEntry.entry_date <= as_of_date,
            JournalEntryLine.account_id == account.id,
            *branch_filter
        ).scalar() or Decimal('0.00')

        balance = debit_sum - credit_sum

        if balance != 0:
            asset_list.append({
                'code': account.code,
                'name': account.name,
                'amount': float(balance)
            })
            total_assets += balance

    # Calculate Liabilities
    liability_list = []
    total_liabilities = Decimal('0.00')

    for account in liability_accounts:
        # Liabilities have credit normal balance
        branch_filter = [JournalEntry.branch_id == branch_id] if branch_id else []
        debit_sum = db.session.query(
            func.sum(JournalEntryLine.debit_amount)
        ).join(JournalEntry).filter(
            JournalEntry.status == 'posted',
            JournalEntry.entry_date <= as_of_date,
            JournalEntryLine.account_id == account.id,
            *branch_filter
        ).scalar() or Decimal('0.00')

        credit_sum = db.session.query(
            func.sum(JournalEntryLine.credit_amount)
        ).join(JournalEntry).filter(
            JournalEntry.status == 'posted',
            JournalEntry.entry_date <= as_of_date,
            JournalEntryLine.account_id == account.id,
            *branch_filter
        ).scalar() or Decimal('0.00')

        balance = credit_sum - debit_sum

        if balance != 0:
            liability_list.append({
                'code': account.code,
                'name': account.name,
                'amount': float(balance)
            })
            total_liabilities += balance

    # Calculate Equity
    equity_list = []
    total_equity = Decimal('0.00')

    for account in equity_accounts:
        # Equity has credit normal balance
        branch_filter = [JournalEntry.branch_id == branch_id] if branch_id else []
        debit_sum = db.session.query(
            func.sum(JournalEntryLine.debit_amount)
        ).join(JournalEntry).filter(
            JournalEntry.status == 'posted',
            JournalEntry.entry_date <= as_of_date,
            JournalEntryLine.account_id == account.id,
            *branch_filter
        ).scalar() or Decimal('0.00')

        credit_sum = db.session.query(
            func.sum(JournalEntryLine.credit_amount)
        ).join(JournalEntry).filter(
            JournalEntry.status == 'posted',
            JournalEntry.entry_date <= as_of_date,
            JournalEntryLine.account_id == account.id,
            *branch_filter
        ).scalar() or Decimal('0.00')

        balance = credit_sum - debit_sum

        if balance != 0:
            equity_list.append({
                'code': account.code,
                'name': account.name,
                'amount': float(balance)
            })
            total_equity += balance

    # Calculate net income YTD and add to equity
    year_start = date(as_of_date.year, 1, 1)
    income_stmt = generate_income_statement(year_start, as_of_date, branch_id=branch_id)
    net_income_ytd = Decimal(str(income_stmt['net_income']))

    # Add net income to equity
    equity_list.append({
        'code': '',
        'name': 'Net Income (YTD)',
        'amount': float(net_income_ytd)
    })
    total_equity += net_income_ytd

    total_liabilities_equity = total_liabilities + total_equity

    return {
        'as_of_date': as_of_date,
        'assets': asset_list,
        'total_assets': float(total_assets),
        'liabilities': liability_list,
        'total_liabilities': float(total_liabilities),
        'equity': equity_list,
        'total_equity': float(total_equity),
        'total_liabilities_equity': float(total_liabilities_equity),
        'is_balanced': (abs(total_assets - total_liabilities_equity) < Decimal('0.01')),
        'difference': float(abs(total_assets - total_liabilities_equity))
    }


def generate_general_ledger(start_date, end_date, branch_id, account_id=None):
    """All-accounts General Ledger book over posted journal entries.

    Per account: opening balance (debit-positive) carried from before start_date,
    each in-range posted line with a running balance, and a closing subtotal.
    Accounts with no opening balance and no in-range activity are omitted.
    """
    accounts_q = Account.query.filter_by(is_active=True)
    if account_id:
        accounts_q = accounts_q.filter(Account.id == account_id)
    accounts = accounts_q.order_by(Account.code).all()

    result_accounts = []
    grand_debit = Decimal('0.00')
    grand_credit = Decimal('0.00')

    for account in accounts:
        opening = db.session.query(
            func.coalesce(
                func.sum(JournalEntryLine.debit_amount - JournalEntryLine.credit_amount),
                0)
        ).join(JournalEntry).filter(
            JournalEntry.status == 'posted',
            JournalEntry.branch_id == branch_id,
            JournalEntry.entry_date < start_date,
            JournalEntryLine.account_id == account.id,
        ).scalar()
        opening = Decimal(str(opening or '0.00'))

        rows = db.session.query(JournalEntryLine, JournalEntry).join(JournalEntry).filter(
            JournalEntry.status == 'posted',
            JournalEntry.branch_id == branch_id,
            JournalEntry.entry_date >= start_date,
            JournalEntry.entry_date <= end_date,
            JournalEntryLine.account_id == account.id,
        ).order_by(
            JournalEntry.entry_date,
            JournalEntry.entry_number,
            JournalEntryLine.line_number,
        ).all()

        if opening == 0 and not rows:
            continue

        running = opening
        total_debit = Decimal('0.00')
        total_credit = Decimal('0.00')
        line_dicts = []
        for line, entry in rows:
            running += (line.debit_amount - line.credit_amount)
            total_debit += line.debit_amount
            total_credit += line.credit_amount
            line_dicts.append({
                'entry_id': entry.id,
                'entry_number': entry.entry_number,
                'entry_date': entry.entry_date,
                'entry_type': entry.entry_type,
                'reference': entry.reference,
                'description': line.description or entry.description,
                'debit': float(line.debit_amount),
                'credit': float(line.credit_amount),
                'running_balance': float(running),
            })

        closing = opening + (total_debit - total_credit)
        grand_debit += total_debit
        grand_credit += total_credit
        result_accounts.append({
            'code': account.code,
            'name': account.name,
            'account_type': account.account_type,
            'opening_balance': float(opening),
            'lines': line_dicts,
            'total_debit': float(total_debit),
            'total_credit': float(total_credit),
            'closing_balance': float(closing),
        })

    # Resolve the contra-account (opposite side of each line's own JE) in one batched query.
    entry_ids = {l['entry_id'] for a in result_accounts for l in a['lines']}
    if entry_ids:
        sibling_rows = db.session.query(
            JournalEntryLine.entry_id,
            JournalEntryLine.account_id,
            Account.name,
            JournalEntryLine.debit_amount,
        ).join(Account, JournalEntryLine.account_id == Account.id).filter(
            JournalEntryLine.entry_id.in_(entry_ids)
        ).all()
        by_entry = {}
        for eid, acct_id, name, dr in sibling_rows:
            by_entry.setdefault(eid, []).append((acct_id, name, dr > 0))
        for a in result_accounts:
            for l in a['lines']:
                near_is_debit = l['debit'] > 0
                opposite = {acct_id: name
                            for (acct_id, name, is_debit) in by_entry.get(l['entry_id'], [])
                            if is_debit != near_is_debit}
                if len(opposite) == 1:
                    l['contra'] = next(iter(opposite.values()))
                elif len(opposite) > 1:
                    l['contra'] = 'Various'
                else:
                    l['contra'] = ''

    return {
        'start_date': start_date,
        'end_date': end_date,
        'accounts': result_accounts,
        'grand_total_debit': float(grand_debit),
        'grand_total_credit': float(grand_credit),
    }


def get_account_category_name(account_code):
    """
    Get friendly category name based on account code

    Args:
        account_code: str - Account code (e.g., '1010', '2020')

    Returns:
        str - Category name
    """
    if account_code.startswith('10'):
        return 'Current Assets'
    elif account_code.startswith('11'):
        return 'Fixed Assets'
    elif account_code.startswith('12'):
        return 'Other Assets'
    elif account_code.startswith('20'):
        return 'Current Liabilities'
    elif account_code.startswith('21'):
        return 'Long-term Liabilities'
    elif account_code.startswith('30'):
        return 'Capital'
    elif account_code.startswith('31'):
        return 'Retained Earnings'
    elif account_code.startswith('40'):
        return 'Sales Revenue'
    elif account_code.startswith('41'):
        return 'Other Revenue'
    elif account_code.startswith('50'):
        return 'Cost of Sales'
    elif account_code.startswith('51'):
        return 'Personnel Expenses'
    elif account_code.startswith('52'):
        return 'Administrative Expenses'
    elif account_code.startswith('53'):
        return 'Selling Expenses'
    elif account_code.startswith('54'):
        return 'Financial Expenses'
    else:
        return 'Other'
