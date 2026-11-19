"""The General Ledger's Excel export, in the owner's layout (GLX A, owner 14 Nov 2026; work order
app-docs/bug-reports/2026-11-09-recommendation-gl-export-format.md, from his own edit of an October export).

    A1  company name (bold)
    A2  account "code - name"        (one-account export; with several accounts each block starts with it)
    A3  General Ledger (bold)
    A4  From October 1 to 31, 2026
    row 6: Date | Source | Particulars | Debit | Credit | Balance
    Opening balance -> each entry, Balance a LIVE formula (=F7+D8-E8 ...) -> Closing balance

Amounts are numbers in the accounting format, dates are real dates. The Closing row's Debit and Credit are SUMs of
the block and its Balance is the last running balance: his file's =F25+D26-E26 counted the period twice. Balance is
debit-positive, so a credit balance is negative -- what he asked ("if yes, it should be negative").
"""
import io
from datetime import date

from flask import make_response
from openpyxl import Workbook
from openpyxl.styles import Font

#: The owner's own number format, copied from his file.
ACCOUNTING = '_-* #,##0.00_-;\\-* #,##0.00_-;_-* "-"??_-;_-@_-'
HEADERS = ['Date', 'Source', 'Particulars', 'Debit', 'Credit', 'Balance']
WIDTHS = {'A': 12, 'B': 14, 'C': 45, 'D': 15, 'E': 15, 'F': 16}


def period_text(start, end):
    """'From October 1 to 31, 2026'; across months or years both dates in full."""
    if start.year == end.year and start.month == end.month:
        return f'From {start.strftime("%B")} {start.day} to {end.day}, {end.year}'
    return f'From {start.strftime("%B")} {start.day}, {start.year} to {end.strftime("%B")} {end.day}, {end.year}'


def _money(cell, value):
    cell.value = float(value) if value not in (None, '') else None
    cell.number_format = ACCOUNTING


def _block(ws, row, acct, with_account_line):
    """Write one account's block from *row*; return the next free row."""
    bold = Font(bold=True)
    if with_account_line:
        ws.cell(row, 1, f"{acct['code']} - {acct['name']}").font = bold
        row += 1
    for c, h in enumerate(HEADERS, start=1):
        ws.cell(row, c, h).font = bold
    row += 1
    opening_row = row
    ws.cell(row, 3, 'Opening balance')
    _money(ws.cell(row, 6), acct['opening_balance'])
    row += 1
    first = row
    for line in acct['lines']:
        when = line['entry_date']
        cell = ws.cell(row, 1, when)
        if isinstance(when, date):
            cell.number_format = 'yyyy-mm-dd'
        ws.cell(row, 2, line['source']['label'])
        ws.cell(row, 3, line['description'] + (f"  (from {line['moved_from']})" if line.get('moved_from') else ''))
        if line['debit']:
            _money(ws.cell(row, 4), line['debit'])
        if line['credit']:
            _money(ws.cell(row, 5), line['credit'])
        f = ws.cell(row, 6, f'=F{row - 1}+D{row}-E{row}')
        f.number_format = ACCOUNTING
        row += 1
    last = row - 1
    ws.cell(row, 3, 'Closing balance').font = bold
    if last >= first:
        for col in ('D', 'E'):
            c = ws[f'{col}{row}']
            c.value = f'=SUM({col}{first}:{col}{last})'
            c.number_format = ACCOUNTING
            c.font = bold
    closing = ws.cell(row, 6, f'=F{last if last >= first else opening_row}')
    closing.number_format = ACCOUNTING
    closing.font = bold
    return row + 1


def gl_excel_response(ledger, start, end, company_name, filename, note=None):
    wb = Workbook()
    ws = wb.active
    ws.title = 'General Ledger'
    bold = Font(bold=True)
    accounts = ledger['accounts']
    single = len(accounts) == 1
    ws['A1'] = company_name or ''
    ws['A1'].font = bold
    row = 2
    if single:
        ws.cell(row, 1, f"{accounts[0]['code']} - {accounts[0]['name']}")
        row += 1
    ws.cell(row, 1, 'General Ledger').font = bold
    ws.cell(row + 1, 1, period_text(start, end))
    row += 2
    if note:
        ws.cell(row, 1, note)
    row += 1                                   # the blank row before the table, as in his file
    for acct in accounts:
        row = _block(ws, row, acct, with_account_line=not single) + (0 if single else 1)
    for col, w in WIDTHS.items():
        ws.column_dimensions[col].width = w
    out = io.BytesIO()
    wb.save(out)
    resp = make_response(out.getvalue())
    resp.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    resp.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return resp


__all__ = ['gl_excel_response', 'period_text']
