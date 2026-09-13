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
from app.reports.basis import GAAP, OWNERS
from app.reports.ledger import period_balances, ledger_lines, owners_summary, ZERO


def generate_trial_balance(as_of_date=None, branch_id=None, reporting_basis=GAAP):
    """Trial Balance as of a date: every active account's debit or credit balance over
    posted lines, read through the ledger seam so the owners' basis is one argument."""
    if as_of_date is None:
        as_of_date = date.today()

    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    balances = period_balances(None, as_of_date, branch_id, reporting_basis)

    account_balances = []
    total_debit = Decimal('0.00')
    total_credit = Decimal('0.00')

    for account in accounts:
        debit_sum, credit_sum = balances.get(account.id, (ZERO, ZERO))
        balance = debit_sum - credit_sum
        if balance == 0:
            continue
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
        'difference': float(abs(total_debit - total_credit)),
        'reporting_basis': reporting_basis,
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


def generate_income_statement(start_date, end_date, branch_id=None, reporting_basis=GAAP):
    """Hierarchical, type-driven Income Statement for a period.

    Sections and their subtotal chain come from IS_SECTIONS; each account's
    placement is its account_type. Revenue-natured types are credit-positive,
    everything else debit-positive. Returns floats for template/export use.
    'net_income' key/semantics preserved (Balance Sheet + Year-End depend on it).
    Balances come through app/reports/ledger.py, so reporting_basis='owners' folds VAT
    into income/expense per app/reports/owners_ledger.py without touching this layout.
    """
    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    by_type = {}
    for a in accounts:
        by_type.setdefault(a.account_type, []).append(a)

    balances = period_balances(start_date, end_date, branch_id, reporting_basis, exclude_closing=True)

    def amount(a):
        d, c = balances.get(a.id, (ZERO, ZERO))
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

    out = {
        'period_start': start_date, 'period_end': end_date, 'sections': sections,
        'net_sales': subtotals.get('Net Sales', 0.0),
        'gross_profit': subtotals.get('Gross Profit', 0.0),
        'operating_income': subtotals.get('Operating Income', 0.0),
        'income_before_tax': subtotals.get('Income Before Tax', 0.0),
        'net_income': subtotals.get('Net Income', 0.0),
        'reporting_basis': reporting_basis,
    }
    if reporting_basis == OWNERS:
        out['basis_summary'] = owners_summary(start_date, end_date, branch_id, exclude_closing=True).as_dict()
    return out


PRIOR_YEARS_ADJ_LABEL = "Prior years' VAT adjustment (owners' basis)"


def _owners_prior_years_adjustment(upto, branch_id):
    """Closed years were closed at GAAP figures, so under the owners' basis the VAT that the
    lens moved into P&L accounts in those years is still sitting there. Return it
    (credit-positive) so the Balance Sheet can carry it as its own equity line."""
    from app.accounts.account_types import IS_TYPES
    balances = period_balances(None, upto, branch_id, OWNERS)
    is_ids = {a.id for a in Account.query.filter(Account.account_type.in_(IS_TYPES)).all()}
    return sum((c - d for aid, (d, c) in balances.items() if aid in is_ids), Decimal('0.00'))


def generate_balance_sheet(as_of_date=None, branch_id=None, reporting_basis=GAAP):
    """Classified, type-driven Balance Sheet. Assets/Liabilities split into
    Current/Non-Current by classification; Equity carries Retained Earnings +
    current-year Net Income. Verifies Assets = Liabilities + Equity."""
    if as_of_date is None:
        as_of_date = date.today()
    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    by_type = {}
    for a in accounts:
        by_type.setdefault(a.account_type, []).append(a)

    balances = period_balances(None, as_of_date, branch_id, reporting_basis)

    def bal(account_id, credit_positive):
        d, c = balances.get(account_id, (ZERO, ZERO))
        return (c - d) if credit_positive else (d - c)

    sections, totals = [], {}
    for spec in BS_SECTIONS:
        accts = by_type.get(spec['type'], [])
        divisions = []
        section_total = Decimal('0.00')
        groups_for = spec['divisions'] or [None]
        for div in groups_for:
            rows = []
            div_total = Decimal('0.00')
            for a in accts:
                if div is not None and a.classification != div:
                    continue
                amt = bal(a.id, spec['credit_positive'])
                if amt != 0:
                    rows.append({'account_id': a.id, 'code': a.code, 'name': a.name, 'amount': float(amt)})
                    div_total += amt
            label = f'{div} {spec["label"].title()}' if div else spec['label'].title()
            divisions.append({'label': label, 'total': float(div_total), 'lines': rollup(rows, accounts)})
            section_total += div_total
        totals[spec['key']] = section_total
        sections.append({'key': spec['key'], 'label': spec['label'],
                         'total': float(section_total), 'divisions': divisions})

    # Net income for the open span added to Equity (unchanged policy)
    from app.year_end.service import latest_closed_year_end
    last_close = latest_closed_year_end(branch_id)
    open_start = date(last_close.year + 1, 1, 1) if last_close else date(1900, 1, 1)
    ni = Decimal(str(generate_income_statement(open_start, as_of_date, branch_id=branch_id,
                                               reporting_basis=reporting_basis)['net_income']))
    equity = next(s for s in sections if s['key'] == 'equity')

    def _add_equity_line(name, amount):
        eded = equity['divisions'][0] if equity['divisions'] else None
        line = {'code': '', 'name': name, 'account_id': None, 'total': float(amount), 'children': []}
        if eded:
            eded['lines'].append(line); eded['total'] = float(Decimal(str(eded['total'])) + amount)
        else:
            equity['divisions'].append({'label': 'Equity', 'total': float(amount), 'lines': [line]})
        equity['total'] = float(Decimal(str(equity['total'])) + amount)
        totals['equity'] += amount

    if ni != 0:
        _add_equity_line('Net Income (current year)', ni)
    if reporting_basis == OWNERS and last_close:
        prior = _owners_prior_years_adjustment(open_start - timedelta(days=1), branch_id)
        if prior != 0:
            _add_equity_line(PRIOR_YEARS_ADJ_LABEL, prior)

    tle = totals['liabilities'] + totals['equity']
    diff = abs(totals['assets'] - tle)
    out = {'as_of_date': as_of_date, 'sections': sections,
           'total_assets': float(totals['assets']),
           'total_liabilities': float(totals['liabilities']),
           'total_equity': float(totals['equity']),
           'total_liabilities_equity': float(tle),
           'is_balanced': bool(diff < Decimal('0.01')), 'difference': float(diff),
           'reporting_basis': reporting_basis}
    if reporting_basis == OWNERS:
        out['basis_summary'] = owners_summary(None, as_of_date, branch_id).as_dict()
    return out


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


def _activity_bucket(account):
    """Cash-flow activity for a non-cash account, by type + classification.
    Investing: Non-Current Assets (excl. accumulated depreciation by name).
    Financing: Non-Current Liabilities + all Equity. Operating: everything else."""
    t, cls = account.account_type, account.classification
    if t == 'Asset' and cls == 'Non-Current' and not _is_depreciation_name(account):
        return 'investing'
    if (t == 'Liability' and cls == 'Non-Current') or t == 'Equity':
        return 'financing'
    return 'operating'


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


def generate_cash_flow(start_date, end_date, branch_id=None, method='indirect', reporting_basis=GAAP):
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

    Balances and lines come through app/reports/ledger.py; under the owners' basis the
    remapped lines still balance per entry, so both methods reconcile to the same cash.

    NOTE (closing-entries caveat): equity movement feeds Financing. If year-end
    closing entries are ever posted to a Retained Earnings equity account, that
    movement would double-count net income here (same caveat as the Balance
    Sheet). Not an issue on books without closing entries.
    """
    if method not in ('indirect', 'direct'):
        raise ValueError("Cash-flow method must be 'indirect' or 'direct'")

    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    period = period_balances(start_date, end_date, branch_id, reporting_basis, exclude_closing=True)

    def movement(account_id):
        """Net period movement in debit-positive terms: Sigma(debit) - Sigma(credit)."""
        d, c = period.get(account_id, (ZERO, ZERO))
        return d - c

    def cash_balance(as_of):
        """Sigma over cash accounts of (debit - credit) posted on/before as_of."""
        upto = period_balances(None, as_of, branch_id, reporting_basis)
        total = Decimal('0.00')
        for a in accounts:
            if _is_cash(a):
                d, c = upto.get(a.id, (ZERO, ZERO))
                total += d - c
        return total

    # Operating
    net_income = Decimal(str(generate_income_statement(
        start_date, end_date, branch_id=branch_id, reporting_basis=reporting_basis)['net_income']))

    depreciation = Decimal('0.00')
    for a in accounts:
        if ((a.base_category == 'Expense' or (a.code or '').startswith('5')) and _is_depreciation_name(a)):
            depreciation += movement(a.id)        # debit-positive expense -> positive add-back

    working_capital = []
    wc_total = Decimal('0.00')
    for a in accounts:
        is_curr_asset = (a.account_type == 'Asset' and a.classification == 'Current'
                         and not _is_cash(a))
        is_curr_liab = (a.account_type == 'Liability' and a.classification == 'Current')
        if not (is_curr_asset or is_curr_liab):
            continue
        effect = -movement(a.id)                  # asset up uses cash; liability up frees cash
        if effect != 0:
            verb = '(Increase)/decrease in ' if is_curr_asset else 'Increase/(decrease) in '
            working_capital.append({'name': verb + a.name, 'amount': float(effect)})
            wc_total += effect

    operating_total = net_income + depreciation + wc_total

    # Investing: non-current assets excluding accumulated depreciation
    investing_lines = []
    investing_total = Decimal('0.00')
    for a in accounts:
        if _activity_bucket(a) != 'investing':
            continue
        effect = -movement(a.id)                  # purchase (debit up) -> outflow (negative)
        if effect != 0:
            investing_lines.append({'name': '(Acquisition)/disposal of ' + a.name,
                                    'amount': float(effect)})
            investing_total += effect

    # Financing: non-current liabilities + equity
    financing_lines = []
    financing_total = Decimal('0.00')
    for a in accounts:
        if _activity_bucket(a) != 'financing':
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
        'reporting_basis': reporting_basis,
    }
    if method == 'indirect':
        return indirect

    # method == 'direct': decompose the period's ACTUAL cash into the three
    # activities from cash-touching JEs. Non-cash transactions (no cash line) are
    # excluded and listed in `noncash`. Ties to the cash movement by construction.
    acct_by_id = {a.id: a for a in accounts}
    cash_ids = {a.id for a in accounts if _is_cash(a)}
    lines = ledger_lines(start_date, end_date, branch_id, reporting_basis, exclude_closing=True)

    op_buckets = {k: Decimal('0.00') for k in _DIRECT_SUBLINE_ORDER}
    inv_by_acct, fin_by_acct = {}, {}
    cash_je_ids = {l.entry_id for l in lines if l.account_id in cash_ids}
    if cash_ids:
        contra = {}
        for l in lines:
            if l.entry_id in cash_je_ids and l.account_id not in cash_ids:
                contra[l.account_id] = contra.get(l.account_id, Decimal('0.00')) + (l.credit - l.debit)
        for account_id, effect in contra.items():
            a = acct_by_id.get(account_id)
            if a is None:
                continue
            activity = _activity_bucket(a)
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
    invfin_ids = {a.id for a in accounts if _activity_bucket(a) in ('investing', 'financing')}
    if invfin_ids:
        cand = {}
        for l in lines:
            if l.account_id in invfin_ids and l.entry_id not in cash_je_ids:
                cand.setdefault(l.entry_id, (l.description, l.reference))
        gross = {}
        for l in lines:
            if l.entry_id in cand:
                gross[l.entry_id] = gross.get(l.entry_id, Decimal('0.00')) + l.debit
        for eid in sorted(cand):
            desc, ref = cand[eid]
            noncash.append({'description': desc or ref or f'JE {eid}', 'amount': float(gross.get(eid, 0))})

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
        'reporting_basis': reporting_basis,
    }


def generate_general_ledger(start_date, end_date, branch_id, account_id=None, reporting_basis=GAAP):
    """All-accounts General Ledger book over posted journal entries.

    Per account: opening balance (debit-positive) carried from before start_date,
    each in-range posted line with a running balance, and a closing subtotal.
    Accounts with no opening balance and no in-range activity are omitted.
    Under the owners' basis a line the lens moved carries 'moved_from' naming the VAT
    account it came from; GAAP lines carry None.
    """
    accounts_q = Account.query.filter_by(is_active=True)
    if account_id:
        accounts_q = accounts_q.filter(Account.id == account_id)
    accounts = accounts_q.order_by(Account.code).all()
    all_accounts = {a.id: a for a in Account.query.all()}

    opening_by = period_balances(None, start_date - timedelta(days=1), branch_id, reporting_basis)
    lines_by = {}
    for ln in ledger_lines(start_date, end_date, branch_id, reporting_basis):
        lines_by.setdefault(ln.account_id, []).append(ln)

    result_accounts = []
    grand_debit = Decimal('0.00')
    grand_credit = Decimal('0.00')

    for account in accounts:
        od, oc = opening_by.get(account.id, (ZERO, ZERO))
        opening = od - oc
        rows = lines_by.get(account.id, [])
        if opening == 0 and not rows:
            continue

        running = opening
        total_debit = Decimal('0.00')
        total_credit = Decimal('0.00')
        line_dicts = []
        for line in rows:
            running += (line.debit - line.credit)
            total_debit += line.debit
            total_credit += line.credit
            src = all_accounts.get(line.moved_from_account_id) if line.moved_from_account_id else None
            line_dicts.append({
                'entry_id': line.entry_id,
                'entry_number': line.entry_number,
                'display_number': line.display_number,
                'entry_date': line.entry_date,
                'entry_type': line.entry_type,
                'reference': line.reference,
                'description': line.description,
                'debit': float(line.debit),
                'credit': float(line.credit),
                'running_balance': float(running),
                'moved_from': f'{src.code} {src.name}' if src else None,
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
        'reporting_basis': reporting_basis,
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
