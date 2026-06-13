"""Pure data layer for the columnar Accounts Payable Journal.

No Flask request access here — callers pass plain dicts/values so these
functions are unit-testable in isolation.
"""
import calendar
import io
from datetime import date, datetime
from decimal import Decimal

from flask import make_response
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font


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
                   wt_account_id, input_vat_account_ids):
    """Pivot journal-entry lines into a columnar matrix.

    Columns are built only from POSTED entries' accounts, ordered
    credits-first (AP, WHT, Input VAT, then other accounts by code).
    Posted rows carry signed amounts (debit - credit) per account and
    contribute to per-column totals. Draft rows are listed with a flag
    and no amounts, excluded from totals.

    Returns dict: columns, rows, totals, grand_total, balanced.
    """
    accounts_by_id = {}          # account_id -> Account
    totals = {}                  # account_id -> Decimal
    rows = []

    for je in posted_entries:
        cells = {}
        for line in je.lines.all():
            acct = line.account
            accounts_by_id[acct.id] = acct
            signed = (line.debit_amount or Decimal('0')) - (line.credit_amount or Decimal('0'))
            cells[acct.id] = cells.get(acct.id, Decimal('0')) + signed
            totals[acct.id] = totals.get(acct.id, Decimal('0')) + signed
        rows.append({'entry': je, 'cells': cells, 'is_draft': False})

    for je in draft_entries:
        rows.append({'entry': je, 'cells': {}, 'is_draft': True})

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

    # Sort rows by entry date then number for a stable, chronological journal
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


def build_ap_journal_xlsx(columns, rows, totals, period_label, company_name,
                          branch_name, filename, identity):
    """Build the columnar AP Journal as an .xlsx Flask response.

    identity(entry) -> (no, invoice_no, vendor, particulars) for the left columns.
    Credits render in parentheses; draft rows show identifiers only.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = 'AP Journal'
    bold = Font(bold=True)
    right = Alignment(horizontal='right')

    ws.append([company_name])
    ws['A1'].font = Font(bold=True, size=14)
    ws.append(['Accounts Payable Journal'])
    ws['A2'].font = bold
    ws.append([f'{period_label} — {branch_name}'])
    ws.append([])

    fixed = ['Date', 'No.', 'Invoice No.', 'Vendor', 'Particulars']
    header = fixed + [c['name'] for c in columns]
    ws.append(header)
    for cell in ws[ws.max_row]:
        cell.font = bold

    for r in rows:
        e = r['entry']
        no, invoice, vendor, particulars = identity(e)
        line = [
            e.entry_date.strftime('%Y-%m-%d'),
            no or '',
            invoice or '',
            vendor or '',
            ('[DRAFT] ' + (particulars or '')) if r['is_draft'] else (particulars or ''),
        ]
        for c in columns:
            line.append('' if r['is_draft'] else _fmt(r['cells'].get(c['account_id'])))
        ws.append(line)
        for i in range(len(fixed) + 1, len(header) + 1):
            ws.cell(row=ws.max_row, column=i).alignment = right

    total_line = ['TOTAL', '', '', '', ''] + [_fmt(totals.get(c['account_id'])) for c in columns]
    ws.append(total_line)
    for cell in ws[ws.max_row]:
        cell.font = bold

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    resp.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp
