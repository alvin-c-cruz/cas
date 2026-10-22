"""Pure data layer for the columnar Cash Disbursements Journal.

No Flask request access here — callers pass plain dicts/values so these
functions are unit-testable in isolation.
"""
import io
from decimal import Decimal

from flask import make_response
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter


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


# The download copies the legacy RIC app's Disbursement Journal cell for cell
# (alvinltv accounting/blueprints/disbursements/extentions.py): an Excel template
# reads the account titles in row 5 and the "Total" row (owner, 22 Oct 2026).
# Spec: app-docs/superpowers/specs/2026-10-22-cd-journal-xlsx-layout-design.md
_HEADER_ROW = 5
_FIXED = ('Date', 'No.', 'Check Number', 'Vendor', 'Particulars')
_THIN = Side(style='thin')
_BOX = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_DOUBLE_BOTTOM = Border(bottom=Side(style='double'))
_AMOUNT_FMT = '#,##0.00; (#,##0.00)'
_AMOUNT_ALIGN = Alignment(horizontal='right', vertical='top')
_AMOUNT_WIDTH = 14
_ALIGN = {
    'Date': Alignment(horizontal='center', vertical='top'),
    'No.': Alignment(horizontal='center', vertical='top'),
    'Check Number': Alignment(horizontal='center', vertical='top'),
    'Vendor': Alignment(horizontal='left', vertical='top', wrap_text=True),
    'Particulars': Alignment(horizontal='left', vertical='top', wrap_text=True),
    'Posted': Alignment(horizontal='center', vertical='center', wrap_text=True),
}
_WIDTH = {'Date': 12, 'No.': 10, 'Check Number': 12, 'Vendor': 20, 'Particulars': 25, 'Posted': 7}


def period_range_label(date_from, date_to):
    """Word a date range as the legacy app does: 'From September 01 to 30, 2026'."""
    if date_from.year != date_to.year:
        return f"From {date_from.strftime('%B %d, %Y')} to {date_to.strftime('%B %d, %Y')}"
    if date_from.month != date_to.month:
        return f"From {date_from.strftime('%B %d')} to {date_to.strftime('%B %d, %Y')}"
    if date_from == date_to:
        return f"For {date_from.strftime('%B %d, %Y')}"
    return f"From {date_from.strftime('%B %d')} to {date_to.strftime('%d, %Y')}"


def build_cd_journal_xlsx(columns, rows, date_from, date_to, company_name,
                          branch_name, filename, identity, cash_account_ids=()):
    """Build the columnar CD Journal as an .xlsx Flask response, in the legacy layout.

    branch_name=None leaves A2 as plain 'Disbursement Journal'.
    identity(entry) -> (cd_no, check_no, vendor, particulars)
    cash_account_ids: the Cash & Bank accounts; their columns come first, as the
    legacy app puts "Cash and Cash Equivalents" first. Then every account by code.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = 'CDJ'

    ws['A1'] = company_name
    ws['A1'].font = Font(size=14, bold=True)
    ws['A2'] = 'Disbursement Journal' + (f' - {branch_name}' if branch_name else '')
    ws['A2'].font = Font(size=10, bold=True)
    ws['A3'] = period_range_label(date_from, date_to)
    ws['A3'].font = Font(size=10, bold=True)

    cash_ids = set(cash_account_ids)
    columns = sorted(columns, key=lambda c: (c['account_id'] not in cash_ids, c['code']))
    kinds = list(_FIXED) + [None] * len(columns) + ['Posted']   # None = an account column
    header = list(_FIXED) + [c['name'] for c in columns] + ['Posted']
    for i, (kind, value) in enumerate(zip(kinds, header), 1):
        cell = ws.cell(row=_HEADER_ROW, column=i, value=value)
        cell.font = Font(size=10, bold=True)
        cell.alignment = Alignment(horizontal='center', wrap_text=True)
        cell.border = _BOX
        ws.column_dimensions[get_column_letter(i)].width = _WIDTH.get(kind, _AMOUNT_WIDTH)

    row_num = _HEADER_ROW
    for r in rows:
        row_num += 1
        no, check_no, vendor, particulars = identity(r['entry'])
        if r['is_cancelled']:
            particulars = '[CANCELLED] ' + (particulars or '')
        values = [r['entry'].entry_date.strftime('%d-%b-%Y'),
                  no or None, check_no or None, vendor or None, particulars or None]
        values += [float(r['cells'][c['account_id']]) if r['cells'].get(c['account_id']) else None
                   for c in columns]
        values.append('No' if r['is_draft'] else 'Yes')
        for i, (kind, value) in enumerate(zip(kinds, values), 1):
            cell = ws.cell(row=row_num, column=i, value=value)
            cell.font = Font(size=10)
            cell.border = _BOX
            cell.alignment = _ALIGN.get(kind, _AMOUNT_ALIGN)
            if kind is None:
                cell.number_format = _AMOUNT_FMT
            elif kind == 'Date':
                cell.number_format = 'yyyy-mmm-dd'

    # One empty row, then the totals, summed from the header row down to the empty row.
    empty_row = row_num + 1
    total_row = row_num + 2
    ws.cell(row=total_row, column=1, value='Total').font = Font(size=10, bold=True)
    for i in range(len(_FIXED) + 1, len(_FIXED) + len(columns) + 1):
        letter = get_column_letter(i)
        cell = ws.cell(row=total_row, column=i, value=f'=SUM({letter}{_HEADER_ROW}:{letter}{empty_row})')
        cell.font = Font(size=10)
        cell.alignment = Alignment(horizontal='right')
        cell.border = _DOUBLE_BOTTOM
        cell.number_format = _AMOUNT_FMT

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    resp.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp
