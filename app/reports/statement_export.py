"""Professional .xlsx builders for the financial statements (formatted workbooks,
not the generic export_to_excel dump)."""
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


def _xlsx_response(wb, filename):
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = _XLSX_MIME
    resp.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp


def build_income_statement_xlsx(stmt, period_label, company, branch_name, filename):
    """Render the hierarchical Income Statement as a formatted two-column
    (Particulars | Amount) workbook: company header, sections with indented child
    accounts, bold subtotals, and an emphasised Net Income line."""
    wb = Workbook()
    ws = wb.active
    ws.title = 'Income Statement'

    right = Alignment(horizontal='right')
    thin, double_s = Side(style='thin'), Side(style='double')
    top_rule = Border(top=thin)
    single_bottom = Border(bottom=thin)
    double_bottom = Border(bottom=double_s)

    def row(particulars='', amount=None):
        ws.append([particulars, amount])
        return ws.max_row

    def amount_cell(r, bold=False, border=None, size=None):
        c = ws.cell(r, 2)
        c.number_format = _NUM_FMT
        c.alignment = right
        if bold or size:
            c.font = Font(bold=bold, size=size) if size else Font(bold=bold)
        if border:
            c.border = border
        return c

    # ── Header ──────────────────────────────────────────────────────────────
    if company.get('name'):
        r = row(company['name']); ws.cell(r, 1).font = Font(bold=True, size=14)
    meta = []
    if company.get('tin'):
        meta.append('TIN: ' + company['tin'])
    if company.get('address'):
        meta.append(company['address'])
    if meta:
        row(' · '.join(meta))
    if branch_name:
        row('Branch: ' + branch_name)
    r = row('Income Statement (Profit & Loss)'); ws.cell(r, 1).font = Font(bold=True, size=13)
    row(period_label)
    row()

    r = row('Particulars', 'Amount')
    for cell in ws[r]:
        cell.font = Font(bold=True)
        cell.border = Border(bottom=thin)
    ws.cell(r, 2).alignment = right

    # ── Body ────────────────────────────────────────────────────────────────
    for sec in stmt['sections']:
        label = ('Less: ' if sec['deduction'] else '') + sec['label']
        r = row(label, sec['total'])
        ws.cell(r, 1).font = Font(bold=True)
        # Single rule under the last line before the total (Less: Income Tax Expense).
        sec_border = single_bottom if sec['key'] == 'income_tax' else None
        if sec_border:
            ws.cell(r, 1).border = sec_border
        amount_cell(r, bold=True, border=sec_border)
        for a in sec['accounts']:
            r = row(f"        {a['code']}  {a['name']}", a['amount'])
            amount_cell(r)
        if sec['key'] in _IS_SUBTOTALS:
            lbl, key = _IS_SUBTOTALS[sec['key']]
            r = row(lbl, stmt[key])
            ws.cell(r, 1).font = Font(bold=True)
            ws.cell(r, 1).border = top_rule
            amount_cell(r, bold=True, border=top_rule)

    margin = stmt['net_income_percentage']
    net_label = 'NET INCOME (LOSS)' + (f'  —  {margin:.1f}% Net Margin' if margin else '')
    r = row(net_label, stmt['net_income'])
    ws.cell(r, 1).font = Font(bold=True, size=12)
    ws.cell(r, 1).border = double_bottom
    amount_cell(r, bold=True, border=double_bottom, size=12)

    ws.column_dimensions['A'].width = 50
    ws.column_dimensions['B'].width = 22
    ws.sheet_view.showGridLines = False

    return _xlsx_response(wb, filename)
