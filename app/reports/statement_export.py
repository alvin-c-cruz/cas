"""Line-flattening + professional .xlsx builders for the financial statements.

`income_statement_lines` is the single source of the printed/exported P&L layout
(shared by the print template and the Excel builder) so they stay identical.
"""
import io

from flask import make_response
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side

_XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
_NUM_FMT = '#,##0.00;(#,##0.00)'   # accounting style: parentheses for negatives

_IS_SUBTOTALS = {
    'cost_of_sales': ('Gross Profit', 'gross_profit'),
    'operating_expenses': ('Operating Income (Loss)', 'operating_income'),
    'financial': ('Income Before Income Tax', 'income_before_tax'),
}


def income_statement_lines(stmt):
    """Flatten the P&L into render-ready lines (shared by print + Excel).

    Each line: {'kind', 'label', 'amount' (or None), 'indent', 'rule'}.
      - section header: no amount on the header line.
      - single-account section: the one account line IS the section total → single
        bottom rule (no separate total line).
      - multi-account section: child account lines + a 'Total <section>' line with a
        top+bottom single rule.
      - empty section: one total line carrying the (zero) total, single bottom rule.
      - subtotals (Gross Profit / Operating Income / Income Before Tax): single
        bottom rule.
      - net income: double bottom rule.
    rule ∈ {None, 'bottom', 'top_bottom', 'double_bottom'}.
    """
    lines = []
    for sec in stmt['sections']:
        header = ('Less: ' if sec['deduction'] else '') + sec['label']
        accts = sec['accounts']
        if not accts:
            lines.append({'kind': 'total', 'label': header, 'amount': sec['total'],
                          'indent': False, 'rule': 'bottom'})
        elif len(accts) == 1:
            a = accts[0]
            lines.append({'kind': 'header', 'label': header, 'amount': None,
                          'indent': False, 'rule': None})
            lines.append({'kind': 'account', 'label': f"{a['code']}  {a['name']}",
                          'amount': a['amount'], 'indent': True, 'rule': 'bottom'})
        else:
            lines.append({'kind': 'header', 'label': header, 'amount': None,
                          'indent': False, 'rule': None})
            for a in accts:
                lines.append({'kind': 'account', 'label': f"{a['code']}  {a['name']}",
                              'amount': a['amount'], 'indent': True, 'rule': None})
            lines.append({'kind': 'total', 'label': 'Total ' + sec['label'],
                          'amount': sec['total'], 'indent': False, 'rule': 'top_bottom'})
        if sec['key'] in _IS_SUBTOTALS:
            slabel, skey = _IS_SUBTOTALS[sec['key']]
            lines.append({'kind': 'subtotal', 'label': slabel, 'amount': stmt[skey],
                          'indent': False, 'rule': 'bottom'})

    margin = stmt['net_income_percentage']
    nlabel = 'NET INCOME (LOSS)' + (f'  —  {margin:.1f}% Net Margin' if margin else '')
    lines.append({'kind': 'net', 'label': nlabel, 'amount': stmt['net_income'],
                  'indent': False, 'rule': 'double_bottom'})
    return lines


def _xlsx_response(wb, filename):
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = _XLSX_MIME
    resp.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp


def build_income_statement_xlsx(stmt, period_label, company, branch_name, filename):
    """Render the Income Statement as a formatted two-column workbook."""
    wb = Workbook()
    ws = wb.active
    ws.title = 'Income Statement'

    right = Alignment(horizontal='right')
    thin, double_s = Side(style='thin'), Side(style='double')
    rules = {
        'bottom': Border(bottom=thin),
        'top_bottom': Border(top=thin, bottom=thin),
        'double_bottom': Border(bottom=double_s),
    }

    def put(particulars='', amount=None):
        ws.append([particulars, amount])
        return ws.max_row

    # ── Header ──────────────────────────────────────────────────────────────
    if company.get('name'):
        r = put(company['name']); ws.cell(r, 1).font = Font(bold=True, size=14)
    meta = []
    if company.get('tin'):
        meta.append('TIN: ' + company['tin'])
    if company.get('address'):
        meta.append(company['address'])
    if meta:
        put(' · '.join(meta))
    if branch_name:
        put('Branch: ' + branch_name)
    r = put('Income Statement (Profit & Loss)'); ws.cell(r, 1).font = Font(bold=True, size=13)
    put(period_label)
    put()

    r = put('Particulars', 'Amount')
    for cell in ws[r]:
        cell.font = Font(bold=True)
        cell.border = Border(bottom=thin)
    ws.cell(r, 2).alignment = right

    # ── Body (from the shared line list) ─────────────────────────────────────
    for ln in income_statement_lines(stmt):
        label = ('        ' + ln['label']) if ln['indent'] else ln['label']
        r = put(label, ln['amount'])
        bold = ln['kind'] in ('header', 'total', 'subtotal', 'net')
        size = 12 if ln['kind'] == 'net' else None
        border = rules.get(ln['rule'])
        font = Font(bold=bold, size=size) if size else (Font(bold=True) if bold else None)
        lc = ws.cell(r, 1)
        if font:
            lc.font = font
        if border:
            lc.border = border
        if ln['amount'] is not None:
            ac = ws.cell(r, 2)
            ac.number_format = _NUM_FMT
            ac.alignment = right
            if font:
                ac.font = font
            if border:
                ac.border = border

    ws.column_dimensions['A'].width = 50
    ws.column_dimensions['B'].width = 22
    ws.sheet_view.showGridLines = False

    return _xlsx_response(wb, filename)
