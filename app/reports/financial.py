"""
Financial Statements Generator

This module generates the three core financial statements:
1. Trial Balance - Verify debits = credits
2. Income Statement (P&L) - Show profitability
3. Balance Sheet - Show financial position

All statements use the double-entry accounting system and pull data from
posted journal entries.
"""
from datetime import date, datetime, timedelta
from sqlalchemy import func, and_, extract
from decimal import Decimal

from app import db
from app.accounts.models import Account
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.reports.sections import IS_SECTIONS, BS_SECTIONS, rollup
from app.accounts.account_types import BASE_CATEGORY, DEFAULT_NORMAL_BALANCE


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


def _period_balance(account_id, start_date, end_date, branch_id):
    branch_filter = [JournalEntry.branch_id == branch_id] if branch_id else []
    d, c = db.session.query(
        func.coalesce(func.sum(JournalEntryLine.debit_amount), 0),
        func.coalesce(func.sum(JournalEntryLine.credit_amount), 0),
    ).join(JournalEntry).filter(
        JournalEntry.status == 'posted',
        JournalEntry.entry_type.notin_(['closing', 'closing_reversal']),
        JournalEntry.entry_date >= start_date,
        JournalEntry.entry_date <= end_date,
        JournalEntryLine.account_id == account_id,
        *branch_filter
    ).one()
    return Decimal(str(d)), Decimal(str(c))


def generate_income_statement(start_date, end_date, branch_id=None):
    """Hierarchical, type-driven Income Statement for a period.

    Sections and their subtotal chain come from IS_SECTIONS; each account's
    placement is its account_type. Revenue-natured types are credit-positive,
    everything else debit-positive. Returns floats for template/export use.
    'net_income' key/semantics preserved (Balance Sheet + Year-End depend on it).
    """
    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    by_type = {}
    for a in accounts:
        by_type.setdefault(a.account_type, []).append(a)

    def amount(a):
        d, c = _period_balance(a.id, start_date, end_date, branch_id)
        return float((c - d) if DEFAULT_NORMAL_BALANCE.get(a.account_type) == 'credit' else (d - c))

    sections, running, subtotals = [], Decimal('0.00'), {}
    for spec in IS_SECTIONS:
        rows = []
        sec_total = Decimal('0.00')
        for t in spec['types']:
            for a in by_type.get(t, []):
                amt = amount(a)
                if amt != 0:
                    rows.append({'account_id': a.id, 'code': a.code, 'name': a.name, 'amount': amt})
                    sec_total += Decimal(str(amt))
        running += spec['sign'] * sec_total
        section = {'key': spec['key'], 'label': spec['label'], 'sign': spec['sign'],
                   'total': float(sec_total), 'lines': rollup(rows, accounts)}
        if spec['subtotal']:
            section['subtotal_label'] = spec['subtotal']
            section['subtotal'] = float(running)
            subtotals[spec['subtotal']] = float(running)
        sections.append(section)

    return {
        'period_start': start_date, 'period_end': end_date, 'sections': sections,
        'net_sales': subtotals.get('Net Sales', 0.0),
        'gross_profit': subtotals.get('Gross Profit', 0.0),
        'operating_income': subtotals.get('Operating Income', 0.0),
        'income_before_tax': subtotals.get('Income Before Tax', 0.0),
        'net_income': subtotals.get('Net Income', 0.0),
    }


# Balance Sheet categories: (key, label, code prefix, credit-normal?)
_BS_CATEGORIES = [
    ('assets', 'ASSETS', '1', False),
    ('liabilities', 'LIABILITIES', '2', True),
    ('equity', 'EQUITY', '3', True),
]


def generate_balance_sheet(as_of_date=None, branch_id=None):
    """Classified Balance Sheet as of a date, grouped by the parent-account hierarchy.

    Each category (Assets / Liabilities / Equity) lists its top-level parent groups
    (e.g. Current Assets, Non-Current Assets), each with its postable child accounts
    (non-zero balances only) and a group total. Net Income (YTD) is added to Equity.
    Returns floats for template/export consumption; verifies Assets = Liabilities + Equity.
    """
    if as_of_date is None:
        as_of_date = date.today()

    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    children_of = {}
    for a in accounts:
        children_of.setdefault(a.parent_id, []).append(a)

    def leaves(group):
        kids = children_of.get(group.id, [])
        if not kids:
            # top-level account with no children is itself a postable leaf
            return [group]
        out, stack = [], list(kids)
        while stack:
            n = stack.pop()
            grandkids = children_of.get(n.id, [])
            if grandkids:
                stack.extend(grandkids)
            else:
                out.append(n)
        return sorted(out, key=lambda x: x.code or '')

    branch_filter = [JournalEntry.branch_id == branch_id] if branch_id else []

    def balance(account_id, credit_positive):
        debit_sum, credit_sum = db.session.query(
            func.coalesce(func.sum(JournalEntryLine.debit_amount), 0),
            func.coalesce(func.sum(JournalEntryLine.credit_amount), 0),
        ).join(JournalEntry).filter(
            JournalEntry.status == 'posted',
            JournalEntry.entry_date <= as_of_date,
            JournalEntryLine.account_id == account_id,
            *branch_filter
        ).one()
        d, c = Decimal(str(debit_sum)), Decimal(str(credit_sum))
        return (c - d) if credit_positive else (d - c)

    sections = []
    totals = {}
    for key, label, prefix, credit_positive in _BS_CATEGORIES:
        top_groups = sorted(
            (a for a in accounts if a.parent_id is None and (a.code or '').startswith(prefix)),
            key=lambda a: a.code or '')
        groups = []
        section_total = Decimal('0.00')
        for g in top_groups:
            accts = []
            gtotal = Decimal('0.00')
            for leaf in leaves(g):
                bal = balance(leaf.id, credit_positive)
                if bal != 0:
                    accts.append({'code': leaf.code, 'name': leaf.name, 'amount': float(bal)})
                    gtotal += bal
            if accts:
                groups.append({'label': (g.name or '').title(), 'total': float(gtotal),
                               'accounts': accts})
                section_total += gtotal
        totals[key] = section_total
        sections.append({'key': key, 'label': label, 'total': float(section_total), 'groups': groups})

    # Net Income for the OPEN (not-yet-closed) span is added to Equity as a computed line.
    # Closed years are already in the ledger as posted Retained Earnings (account 30201),
    # captured by the normal equity-account loop above — so we must NOT recompute them.
    from app.year_end.service import latest_closed_year_end
    last_close = latest_closed_year_end(branch_id)
    open_start = date(last_close.year + 1, 1, 1) if last_close else date(1900, 1, 1)
    ni_current = Decimal(str(
        generate_income_statement(open_start, as_of_date, branch_id=branch_id)['net_income']))

    extra = []
    if ni_current != 0:
        extra.append({'code': '', 'name': 'Net Income (current year)', 'amount': float(ni_current)})
    added = ni_current

    equity = next(s for s in sections if s['key'] == 'equity')
    if equity['groups']:
        grp = equity['groups'][0]
        grp['accounts'].extend(extra)
        grp['total'] = float(Decimal(str(grp['total'])) + added)
    elif extra:
        equity['groups'].append({'label': 'Equity', 'total': float(added), 'accounts': extra})
    equity['total'] = float(Decimal(str(equity['total'])) + added)
    totals['equity'] += added

    tle = totals['liabilities'] + totals['equity']
    diff = abs(totals['assets'] - tle)
    return {
        'as_of_date': as_of_date,
        'sections': sections,
        'total_assets': float(totals['assets']),
        'total_liabilities': float(totals['liabilities']),
        'total_equity': float(totals['equity']),
        'total_liabilities_equity': float(tle),
        'is_balanced': bool(diff < Decimal('0.01')),
        'difference': float(diff),
    }


def _is_cash(account):
    """Cash & cash equivalents: an account whose name contains 'cash'."""
    return 'cash' in (account.name or '').lower()


def _is_depreciation_name(account):
    """Depreciation expense or accumulated depreciation (name-based)."""
    return 'depreciation' in (account.name or '').lower()


_DIRECT_SUBLINE_ORDER = [
    'Cash received from customers',
    'Cash paid to suppliers',
    'Cash paid for operating expenses',
    'Taxes paid',
    'Other operating receipts/(payments)',
]


def _direct_activity(account):
    """Activity bucket for a non-cash contra account in the direct method."""
    code = account.code or ''
    if code.startswith('11') and not _is_depreciation_name(account):
        return 'investing'
    if code.startswith('21') or code.startswith('30'):
        return 'financing'
    return 'operating'   # 4x / 5x / 10x-ex-cash / 20x + any stray (catch-all)


def _direct_operating_subline(account):
    """PFRS operating sub-line for an operating contra account (first match wins)."""
    code = account.code or ''
    name = (account.name or '').lower()
    if any(t in name for t in ('vat', 'withholding', 'wht', 'income tax')):
        return 'Taxes paid'
    if code.startswith('4') or 'receivable' in name:
        return 'Cash received from customers'
    if code.startswith('501') or any(t in name for t in
                                      ('payable', 'inventory', 'construction in progress', 'materials')):
        return 'Cash paid to suppliers'
    if code.startswith('5'):
        return 'Cash paid for operating expenses'
    return 'Other operating receipts/(payments)'


def generate_cash_flow(start_date, end_date, branch_id=None, method='indirect'):
    """Statement of Cash Flows (indirect method) for a period.

    Reorganizes every non-cash account's period movement (Sigma debit - credit)
    into Operating / Investing / Financing activities, adds back depreciation,
    and reconciles to the actual change in cash. Returns floats for
    template/export consumption.

    Because every journal entry balances, the change in cash equals the negative
    sum of all non-cash account movements; bucketing those movements therefore
    sums exactly to the change in cash. Depreciation is the one special case: it
    is added back in Operating and Accumulated Depreciation is excluded from
    Investing (the two are equal and opposite, so the total still ties).

    NOTE (closing-entries caveat): equity movement feeds Financing. If year-end
    closing entries are ever posted to a Retained Earnings equity account, that
    movement would double-count net income here (same caveat as the Balance
    Sheet). Not an issue on books without closing entries.
    """
    if method not in ('indirect', 'direct'):
        raise ValueError("Cash-flow method must be 'indirect' or 'direct'")

    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    branch_filter = [JournalEntry.branch_id == branch_id] if branch_id else []

    def movement(account_id):
        """Net period movement in debit-positive terms: Sigma(debit) - Sigma(credit)."""
        debit_sum, credit_sum = db.session.query(
            func.coalesce(func.sum(JournalEntryLine.debit_amount), 0),
            func.coalesce(func.sum(JournalEntryLine.credit_amount), 0),
        ).join(JournalEntry).filter(
            JournalEntry.status == 'posted',
            JournalEntry.entry_type.notin_(['closing', 'closing_reversal']),
            JournalEntry.entry_date >= start_date,
            JournalEntry.entry_date <= end_date,
            JournalEntryLine.account_id == account_id,
            *branch_filter
        ).one()
        return Decimal(str(debit_sum)) - Decimal(str(credit_sum))

    def cash_balance(as_of):
        """Sigma over cash accounts of (debit - credit) posted on/before as_of."""
        total = Decimal('0.00')
        for a in accounts:
            if not _is_cash(a):
                continue
            debit_sum, credit_sum = db.session.query(
                func.coalesce(func.sum(JournalEntryLine.debit_amount), 0),
                func.coalesce(func.sum(JournalEntryLine.credit_amount), 0),
            ).join(JournalEntry).filter(
                JournalEntry.status == 'posted',
                JournalEntry.entry_date <= as_of,
                JournalEntryLine.account_id == a.id,
                *branch_filter
            ).one()
            total += Decimal(str(debit_sum)) - Decimal(str(credit_sum))
        return total

    # Operating
    net_income = Decimal(str(
        generate_income_statement(start_date, end_date, branch_id=branch_id)['net_income']))

    depreciation = Decimal('0.00')
    for a in accounts:
        if (a.account_type == 'Expense' or (a.code or '').startswith('5')) and _is_depreciation_name(a):
            depreciation += movement(a.id)        # debit-positive expense -> positive add-back

    working_capital = []
    wc_total = Decimal('0.00')
    for a in accounts:
        code = a.code or ''
        is_curr_asset = code.startswith('10') and not _is_cash(a)
        is_curr_liab = code.startswith('20')
        if not (is_curr_asset or is_curr_liab):
            continue
        effect = -movement(a.id)                  # asset up uses cash; liability up frees cash
        if effect != 0:
            verb = '(Increase)/decrease in ' if is_curr_asset else 'Increase/(decrease) in '
            working_capital.append({'name': verb + a.name, 'amount': float(effect)})
            wc_total += effect

    operating_total = net_income + depreciation + wc_total

    # Investing: non-current asset cost (11...) excluding accumulated depreciation
    investing_lines = []
    investing_total = Decimal('0.00')
    for a in accounts:
        if not (a.code or '').startswith('11') or _is_depreciation_name(a):
            continue
        effect = -movement(a.id)                  # purchase (debit up) -> outflow (negative)
        if effect != 0:
            investing_lines.append({'name': '(Acquisition)/disposal of ' + a.name,
                                    'amount': float(effect)})
            investing_total += effect

    # Financing: non-current liabilities (21...) + equity (30...)
    financing_lines = []
    financing_total = Decimal('0.00')
    for a in accounts:
        code = a.code or ''
        if not (code.startswith('21') or code.startswith('30')):
            continue
        effect = -movement(a.id)                  # contribution / loan proceeds (credit up) -> inflow
        if effect != 0:
            financing_lines.append({'name': a.name, 'amount': float(effect)})
            financing_total += effect

    net_change = operating_total + investing_total + financing_total
    cash_begin = cash_balance(start_date - timedelta(days=1))
    cash_end = cash_balance(end_date)
    diff = abs(net_change - (cash_end - cash_begin))

    indirect = {
        'period_start': start_date,
        'period_end': end_date,
        'method': 'indirect',
        'operating': {
            'net_income': float(net_income),
            'depreciation': float(depreciation),
            'working_capital': working_capital,
            'total': float(operating_total),
        },
        'investing': {'lines': investing_lines, 'total': float(investing_total)},
        'financing': {'lines': financing_lines, 'total': float(financing_total)},
        'net_change': float(net_change),
        'cash_begin': float(cash_begin),
        'cash_end': float(cash_end),
        'is_reconciled': bool(diff < Decimal('0.01')),
        'difference': float(diff),
    }
    if method == 'indirect':
        return indirect

    # method == 'direct': decompose the period's ACTUAL cash into the three
    # activities from cash-touching JEs. Non-cash transactions (no cash line) are
    # excluded and listed in `noncash`. Ties to the cash movement by construction.
    acct_by_id = {a.id: a for a in accounts}
    cash_ids = [a.id for a in accounts if _is_cash(a)]

    op_buckets = {k: Decimal('0.00') for k in _DIRECT_SUBLINE_ORDER}
    inv_by_acct, fin_by_acct = {}, {}
    if cash_ids:
        cash_je_ids = db.session.query(JournalEntryLine.entry_id).join(JournalEntry).filter(
            JournalEntry.status == 'posted',
            JournalEntry.entry_type.notin_(['closing', 'closing_reversal']),
            JournalEntry.entry_date >= start_date,
            JournalEntry.entry_date <= end_date,
            JournalEntryLine.account_id.in_(cash_ids),
            *branch_filter
        ).distinct()
        contra = db.session.query(
            JournalEntryLine.account_id,
            (func.coalesce(func.sum(JournalEntryLine.credit_amount), 0)
             - func.coalesce(func.sum(JournalEntryLine.debit_amount), 0)).label('eff'),
        ).filter(
            JournalEntryLine.entry_id.in_(cash_je_ids),
            ~JournalEntryLine.account_id.in_(cash_ids),
        ).group_by(JournalEntryLine.account_id).all()
        for account_id, eff in contra:
            a = acct_by_id.get(account_id)
            if a is None:
                continue
            effect = Decimal(str(eff))
            activity = _direct_activity(a)
            if activity == 'investing':
                inv_by_acct[a.id] = (a, effect)
            elif activity == 'financing':
                fin_by_acct[a.id] = (a, effect)
            else:
                op_buckets[_direct_operating_subline(a)] += effect

    operating_lines = [{'name': k, 'amount': float(op_buckets[k])}
                       for k in _DIRECT_SUBLINE_ORDER if op_buckets[k] != 0]
    operating_dtotal = sum(op_buckets.values(), Decimal('0.00'))

    investing_dlines, investing_dtotal = [], Decimal('0.00')
    for a, eff in sorted(inv_by_acct.values(), key=lambda x: x[0].code or ''):
        if eff != 0:
            investing_dlines.append({'name': '(Acquisition)/disposal of ' + a.name,
                                     'amount': float(eff)})
            investing_dtotal += eff
    financing_dlines, financing_dtotal = [], Decimal('0.00')
    for a, eff in sorted(fin_by_acct.values(), key=lambda x: x[0].code or ''):
        if eff != 0:
            financing_dlines.append({'name': a.name, 'amount': float(eff)})
            financing_dtotal += eff

    # Non-cash investing & financing transactions: posted in-period branch JEs
    # not touching cash that hit a real investing (11x non-accum-depr) or
    # financing (21x/30x) account. (Depreciation entries hit only accumulated
    # depreciation among 11x accounts, so they do not qualify.)
    noncash = []
    invfin_ids = [a.id for a in accounts
                  if ((a.code or '').startswith('11') and not _is_depreciation_name(a))
                  or (a.code or '').startswith('21') or (a.code or '').startswith('30')]
    if invfin_ids:
        cash_je_set = set()
        if cash_ids:
            cash_je_set = {r[0] for r in db.session.query(JournalEntryLine.entry_id).filter(
                JournalEntryLine.account_id.in_(cash_ids)).distinct()}
        cand = db.session.query(JournalEntry).join(JournalEntryLine).filter(
            JournalEntry.status == 'posted',
            JournalEntry.entry_type.notin_(['closing', 'closing_reversal']),
            JournalEntry.entry_date >= start_date,
            JournalEntry.entry_date <= end_date,
            JournalEntryLine.account_id.in_(invfin_ids),
            *branch_filter
        ).distinct().all()
        for je in sorted(cand, key=lambda j: j.id):
            if je.id in cash_je_set:
                continue
            gross = db.session.query(
                func.coalesce(func.sum(JournalEntryLine.debit_amount), 0)
            ).filter(JournalEntryLine.entry_id == je.id).scalar()
            noncash.append({'description': je.description or je.reference or f'JE {je.id}',
                            'amount': float(gross or 0)})

    net_change_d = operating_dtotal + investing_dtotal + financing_dtotal
    diff_d = abs(net_change_d - (cash_end - cash_begin))
    return {
        'period_start': start_date,
        'period_end': end_date,
        'method': 'direct',
        'operating': {'lines': operating_lines, 'total': float(operating_dtotal)},
        'investing': {'lines': investing_dlines, 'total': float(investing_dtotal)},
        'financing': {'lines': financing_dlines, 'total': float(financing_dtotal)},
        'noncash': noncash,
        'reconciliation': indirect['operating'],
        'net_change': float(net_change_d),
        'cash_begin': float(cash_begin),
        'cash_end': float(cash_end),
        'is_reconciled': bool(diff_d < Decimal('0.01')),
        'difference': float(diff_d),
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
                'display_number': entry.display_number,
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
