"""Pure data layer for the columnar Accounts Payable Journal.

No Flask request access here — callers pass plain dicts/values so these
functions are unit-testable in isolation.
"""
import calendar
from datetime import date, datetime
from decimal import Decimal


from app.journals.legacy_xlsx import (build_legacy_journal_xlsx, journal_row,
                                      order_account_columns, posted_flag, text_date)


def _parse_iso(value):
    """Parse an ISO date string; return None on failure/empty."""
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def resolve_period(args, today):
    """Resolve the journal's date filter from request args.

    args: a mapping (request.args) with optional keys:
        mode='month'|'custom', year, month, date_from, date_to
    today: a date used for defaults.

    Returns dict: mode, year, month, date_from, date_to, label.
    Custom mode with unparseable dates falls back to the current month.
    """
    mode = args.get('mode', 'month')

    if mode == 'custom':
        df = _parse_iso(args.get('date_from'))
        dt = _parse_iso(args.get('date_to'))
        if df and dt and df <= dt:
            return {
                'mode': 'custom',
                'year': df.year,
                'month': df.month,
                'date_from': df,
                'date_to': dt,
                'label': (
                    f"From {df.strftime('%B')} {df.day}, {df.year}"
                    f" to {dt.strftime('%B')} {dt.day}, {dt.year}"
                ),
            }
        # bad/missing/inverted custom dates → fall through to month default

    try:
        year = int(args.get('year', today.year))
        month = int(args.get('month', today.month))
        if not 1 <= month <= 12:
            raise ValueError
    except (ValueError, TypeError):
        year, month = today.year, today.month

    last_day = calendar.monthrange(year, month)[1]
    df = date(year, month, 1)
    dt = date(year, month, last_day)
    return {
        'mode': 'month',
        'year': year,
        'month': month,
        'date_from': df,
        'date_to': dt,
        'label': df.strftime('For the month of %B %Y'),
        'label_body': df.strftime('the month of %B %Y'),
    }


def _column_sort_key(account, ap_account_id, wt_account_id, input_vat_account_ids):
    """Order: AP (0), WHT (1), Input VAT (2, by code), others (3, by code)."""
    if account.id == ap_account_id:
        return (0, account.code)
    if account.id == wt_account_id:
        return (1, account.code)
    if account.id in input_vat_account_ids:
        return (2, account.code)
    return (3, account.code)


def _group_for(account, ap_account_id, wt_account_id, input_vat_account_ids):
    if account.id == ap_account_id:
        return 'ap'
    if account.id == wt_account_id:
        return 'wht'
    if account.id in input_vat_account_ids:
        return 'vat'
    return 'other'


def build_columnar(posted_entries, draft_entries, ap_account_id,
                   wt_account_id, input_vat_account_ids, voided_bills=None,
                   draft_amounts=False):
    """Pivot journal-entry lines into a columnar matrix.

    Columns are built only from POSTED entries' accounts, ordered
    credits-first (AP, WHT, Input VAT, then other accounts by code).
    Posted rows carry signed amounts (debit - credit) per account and
    contribute to per-column totals. Draft and voided rows are listed
    with a flag and no amounts, excluded from totals -- except that
    draft_amounts=True (the .xlsx download) pivots drafts like posted rows.

    Returns dict: columns, rows, totals, grand_total, balanced.
    """
    if voided_bills is None:
        voided_bills = []

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
        rows.append({'entry': je, 'cells': pivot(je), 'is_draft': False, 'is_voided': False})

    for je in draft_entries:
        cells = pivot(je) if draft_amounts else {}
        rows.append({'entry': je, 'cells': cells, 'is_draft': True, 'is_voided': False})

    for ap in voided_bills:
        rows.append({'ap': ap, 'entry': None, 'cells': {}, 'is_draft': False, 'is_voided': True})

    ordered = sorted(
        accounts_by_id.values(),
        key=lambda a: _column_sort_key(a, ap_account_id, wt_account_id, input_vat_account_ids),
    )
    columns = [{
        'account_id': a.id,
        'code': a.code,
        'name': a.name,
        'group': _group_for(a, ap_account_id, wt_account_id, input_vat_account_ids),
    } for a in ordered]

    def _row_sort_key(r):
        if r['is_voided']:
            return (r['ap'].ap_date, r['ap'].ap_number)
        return (r['entry'].entry_date, r['entry'].entry_number or '')

    rows.sort(key=_row_sort_key)

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


def build_ap_journal_xlsx(columns, rows, date_from, date_to, company_name,
                          branch_name, filename, identity, ap_account_ids=()):
    """Build the AP Journal download in the legacy Accounts Payable Journal layout.

    identity(entry) -> (ap_no, vendor_invoice_no, vendor, particulars)
    ap_account_ids: the trade payable accounts; their columns come first, as the legacy
    app puts "Accounts Payable" first. Then every account by code.
    Voided bills never reached the books: a marked row with no amounts.
    """
    out = []
    for r in rows:
        if r.get('is_voided'):
            b = r['ap']
            out.append(journal_row([text_date(b.ap_date), b.ap_number, b.vendor_invoice_number,
                                    b.vendor_name, '[VOIDED] ' + (b.notes or '')], {}, [posted_flag(False)]))
            continue
        no, invoice, vendor, particulars = identity(r['entry'])
        out.append(journal_row([text_date(r['entry'].entry_date), no, invoice, vendor, particulars],
                               r['cells'], [posted_flag(not r['is_draft'])]))
    return build_legacy_journal_xlsx(
        'APJ', 'Accounts Payable Journal', ('Date', 'No.', 'Invoice Number', 'Vendor', 'Particulars'),
        order_account_columns(columns, first_ids=ap_account_ids), [('Total', out)],
        date_from, date_to, company_name, branch_name, filename)
