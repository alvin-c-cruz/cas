"""Pure data layer for the columnar Cash Disbursements Journal.

No Flask request access here — callers pass plain dicts/values so these
functions are unit-testable in isolation.
"""
from decimal import Decimal

from app.journals.legacy_xlsx import (build_legacy_journal_xlsx, journal_row,
                                      order_account_columns, posted_flag, text_date)


def _group(account, ap_account_id, wt_account_id, input_vat_account_ids, totals):
    """Classify an account into a CD journal column group.

    Groups determine column colour (debit=blue, credit=red) and sort order.
    Cash/bank accounts are identified by their net credit sign in totals.
    """
    if account.id == ap_account_id:
        return 'ap_applied'  # debit — paying down AP
    if account.id == wt_account_id:
        return 'wht'          # credit
    if account.id in input_vat_account_ids:
        return 'vat'          # debit
    if totals.get(account.id, Decimal('0')) < 0:
        return 'cash'         # credit — net outflow
    return 'expense'          # debit


def _col_key(account, ap_account_id, wt_account_id, input_vat_account_ids, totals):
    """Sort: ap_applied(0) -> vat(1) -> expense(2) -> wht(3) -> cash(4), then by code."""
    order = {'ap_applied': 0, 'vat': 1, 'expense': 2, 'wht': 3, 'cash': 4}
    g = _group(account, ap_account_id, wt_account_id, input_vat_account_ids, totals)
    return (order.get(g, 2), account.code)


def build_columnar_cd(posted_entries, draft_entries, ap_account_id,
                      wt_account_id, input_vat_account_ids, cancelled_refs=None,
                      draft_amounts=False):
    """Pivot disbursement journal-entry lines into a columnar matrix.

    Columns are built only from POSTED entries' accounts. Cancelled CDVs
    (whose JEs remain posted) are included in totals but flagged is_cancelled=True
    for visual display (strikethrough + badge). Draft rows carry no amounts unless
    draft_amounts=True (the .xlsx download), which pivots them like posted rows.

    cancelled_refs: set of CDV numbers (entry.reference) that are cancelled.

    Returns dict: columns, rows, totals, grand_total, balanced.
    """
    if cancelled_refs is None:
        cancelled_refs = set()

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
        key=lambda a: _col_key(a, ap_account_id, wt_account_id, input_vat_account_ids, totals),
    )
    columns = [{
        'account_id': a.id,
        'code': a.code,
        'name': a.name,
        'group': _group(a, ap_account_id, wt_account_id, input_vat_account_ids, totals),
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
    """Render a signed Decimal: credits (negative) in parentheses, blanks for zero/None."""
    if value is None or value == Decimal('0'):
        return ''
    if value < 0:
        return f'({-value:,.2f})'
    return f'{value:,.2f}'


def build_cd_journal_xlsx(columns, rows, date_from, date_to, company_name,
                          branch_name, filename, identity, cash_account_ids=()):
    """Build the CD Journal download in the legacy Disbursement Journal layout.

    identity(entry) -> (cd_no, check_no, vendor, particulars)
    cash_account_ids: the Cash & Bank accounts; their columns come first, as the
    legacy app puts "Cash and Cash Equivalents" first. Then every account by code.
    """
    out = []
    for r in rows:
        no, check_no, vendor, particulars = identity(r['entry'])
        if r['is_cancelled']:
            particulars = '[CANCELLED] ' + (particulars or '')
        out.append(journal_row([text_date(r['entry'].entry_date), no, check_no, vendor, particulars],
                               r['cells'], [posted_flag(not r['is_draft'])]))
    return build_legacy_journal_xlsx(
        'CDJ', 'Disbursement Journal', ('Date', 'No.', 'Check Number', 'Vendor', 'Particulars'),
        order_account_columns(columns, first_ids=cash_account_ids), [('Total', out)],
        date_from, date_to, company_name, branch_name, filename)
