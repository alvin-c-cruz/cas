"""Pure data layer for the columnar Cash Receipts Journal.

No Flask request access here — callers pass plain dicts/values so these
functions are unit-testable in isolation.
"""
from decimal import Decimal


from app.journals.legacy_xlsx import (build_legacy_journal_xlsx, journal_row,
                                      order_account_columns, posted_flag, text_date)

# resolve_period is shared — import from the AP data layer
from app.journals.ap_journal_data import resolve_period  # noqa: F401


def _group(account, ar_account_id, wt_account_id, output_vat_account_ids, totals):
    """Classify an account into a CR journal column group.

    Groups determine column colour (debit=blue, credit=red) and sort order.
    Cash/bank accounts are identified by their net debit sign in totals
    (they go up when we receive cash).
    """
    if account.id == ar_account_id:
        return 'ar_applied'   # credit — paying down AR
    if account.id == wt_account_id:
        return 'wht_recv'     # debit — WHT receivable
    if account.id in output_vat_account_ids:
        return 'vat'          # credit
    if totals.get(account.id, Decimal('0')) > 0:
        return 'cash'         # debit — net inflow
    return 'revenue'          # credit


def _col_key(account, ar_account_id, wt_account_id, output_vat_account_ids, totals):
    """Sort: ar_applied(0) -> vat(1) -> revenue(2) -> wht_recv(3) -> cash(4), then by code."""
    order = {'ar_applied': 0, 'vat': 1, 'revenue': 2, 'wht_recv': 3, 'cash': 4}
    g = _group(account, ar_account_id, wt_account_id, output_vat_account_ids, totals)
    return (order.get(g, 2), account.code)


def build_columnar_cr(posted_entries, draft_entries, ar_account_id,
                      wt_account_id, output_vat_account_ids, cancelled_refs=None,
                      draft_amounts=False):
    """Pivot receipt journal-entry lines into a columnar matrix.

    Columns are built only from POSTED entries' accounts. Cancelled CRVs
    (whose JEs remain posted) are included in totals but flagged is_cancelled=True
    for visual display (strikethrough + badge). Draft rows carry no amounts unless
    draft_amounts=True (the .xlsx download), which pivots them like posted rows.

    cancelled_refs: set of CRV numbers (entry.reference) that are cancelled.

    Returns dict: columns, rows, totals, grand_total, balanced.
    """
    if cancelled_refs is None:
        cancelled_refs = set()
    if output_vat_account_ids is None:
        output_vat_account_ids = set()

    accounts_by_id = {}
    totals = {}
    rows = []

    def pivot(je):
        cells = {}
        for line in je.lines.all():
            acct = line.account
            accounts_by_id[acct.id] = acct
            signed = (line.debit_amount or Decimal('0')) - (line.credit_amount or Decimal('0'))
            cells[acct.id] = cells.get(acct.id, Decimal('0')) + signed
            totals[acct.id] = totals.get(acct.id, Decimal('0')) + signed
        return cells

    for je in posted_entries:
        is_cancelled = je.reference in cancelled_refs
        rows.append({'entry': je, 'cells': pivot(je), 'is_draft': False, 'is_cancelled': is_cancelled})

    for je in draft_entries:
        cells = pivot(je) if draft_amounts else {}
        rows.append({'entry': je, 'cells': cells, 'is_draft': True, 'is_cancelled': False})

    ordered = sorted(
        accounts_by_id.values(),
        key=lambda a: _col_key(a, ar_account_id, wt_account_id, output_vat_account_ids, totals),
    )
    columns = [{
        'account_id': a.id,
        'code': a.code,
        'name': a.name,
        'group': _group(a, ar_account_id, wt_account_id, output_vat_account_ids, totals),
    } for a in ordered]

    rows.sort(key=lambda r: (r['entry'].entry_date, r['entry'].entry_number))

    grand_total = sum(totals.values(), Decimal('0'))
    return {
        'columns': columns,
        'rows': rows,
        'totals': totals,
        'grand_total': grand_total,
        'balanced': grand_total == Decimal('0'),
    }


def _fmt(value):
    """Render a signed Decimal: debits (positive) plain, credits (negative) in parentheses."""
    if value is None or value == Decimal('0'):
        return ''
    if value < 0:
        return f'({-value:,.2f})'
    return f'{value:,.2f}'


def build_cr_journal_xlsx(columns, rows, date_from, date_to, company_name, branch_name,
                          filename, identity, first_account_ids=(), revenue_account_ids=()):
    """Build the CR Journal download in the legacy Cash Receipts Journal layout.

    identity(entry) -> (cr_no, invoice_numbers, customer, particulars)
    first_account_ids: the Cash & Bank and trade receivable accounts, first by code;
    revenue_account_ids: the sales accounts, last by code descending -- the legacy order.
    """
    out = []
    for r in rows:
        no, invoices, customer, particulars = identity(r['entry'])
        if r['is_cancelled']:
            particulars = '[CANCELLED] ' + (particulars or '')
        out.append(journal_row([text_date(r['entry'].entry_date), no, invoices, customer, particulars],
                               r['cells'], [posted_flag(not r['is_draft'])]))
    return build_legacy_journal_xlsx(
        'CRJ', 'Cash Receipts Journal', ('Date', 'No.', 'Invoice Number', 'Customer', 'Particulars'),
        order_account_columns(columns, first_ids=first_account_ids, last_ids=revenue_account_ids),
        [('Total', out)], date_from, date_to, company_name, branch_name, filename)
