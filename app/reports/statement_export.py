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

    # ── Body — live SUM/subtotal formulas so edits recalc in Excel ───────────
    def style(r, bold=False, size=None, border=None):
        font = Font(bold=bold, size=size) if size else (Font(bold=True) if bold else None)
        lc = ws.cell(r, 1)
        if font:
            lc.font = font
        if border:
            lc.border = border
        ac = ws.cell(r, 2)
        ac.number_format = _NUM_FMT
        ac.alignment = right
        if font:
            ac.font = font
        if border:
            ac.border = border

    total_row = {}        # section key -> row holding that section's total/amount
    gp_row = oi_row = ibt_row = None

    for sec in stmt['sections']:
        header = ('Less: ' if sec['deduction'] else '') + sec['label']
        accts = sec['accounts']
        if not accts:                                   # empty section: one ruled total line
            r = put(header, sec['total'])
            style(r, bold=True, border=rules['bottom'])
            total_row[sec['key']] = r
        elif len(accts) == 1:                           # single account IS the total
            r = put(header); ws.cell(r, 1).font = Font(bold=True)
            a = accts[0]
            r = put(f"        {a['code']}  {a['name']}", a['amount'])
            style(r, border=rules['bottom'])
            total_row[sec['key']] = r
        else:                                           # children + live SUM total
            r = put(header); ws.cell(r, 1).font = Font(bold=True)
            first = last = None
            for a in accts:
                r = put(f"        {a['code']}  {a['name']}", a['amount'])
                style(r)
                first = first or r
                last = r
            r = put('Total ' + sec['label'])
            ws.cell(r, 2).value = f'=SUM(B{first}:B{last})'
            style(r, bold=True, border=rules['top_bottom'])
            total_row[sec['key']] = r

        if sec['key'] == 'cost_of_sales':
            r = put('Gross Profit')
            ws.cell(r, 2).value = f"=B{total_row['revenue']}-B{total_row['cost_of_sales']}"
            style(r, bold=True, border=rules['bottom']); gp_row = r
        elif sec['key'] == 'operating_expenses':
            r = put('Operating Income (Loss)')
            ws.cell(r, 2).value = f"=B{gp_row}-B{total_row['operating_expenses']}"
            style(r, bold=True, border=rules['bottom']); oi_row = r
        elif sec['key'] == 'financial':
            r = put('Income Before Income Tax')
            ws.cell(r, 2).value = f"=B{oi_row}-B{total_row['financial']}"
            style(r, bold=True, border=rules['bottom']); ibt_row = r

    margin = stmt['net_income_percentage']
    nlabel = 'NET INCOME (LOSS)' + (f'  —  {margin:.1f}% Net Margin' if margin else '')
    r = put(nlabel)
    ws.cell(r, 2).value = f"=B{ibt_row}-B{total_row['income_tax']}"
    style(r, bold=True, size=12, border=rules['double_bottom'])

    ws.column_dimensions['A'].width = 50
    ws.column_dimensions['B'].width = 22
    ws.sheet_view.showGridLines = False

    return _xlsx_response(wb, filename)


_BS_GRAND = {'assets': 'TOTAL ASSETS', 'liabilities': 'TOTAL LIABILITIES', 'equity': 'TOTAL EQUITY'}


def balance_sheet_lines(bs):
    """Flatten the classified balance sheet into render-ready lines (print + Excel).

    Multi-group sections (Assets, Liabilities) show group headers + group subtotals;
    a single-group section (Equity) shows its accounts directly (no redundant
    sub-header). Grand totals (TOTAL ASSETS, TOTAL LIABILITIES AND EQUITY) get a
    double rule; group subtotals top+bottom; TOTAL LIABILITIES / TOTAL EQUITY single.
    """
    lines = []
    for sec in bs['sections']:
        lines.append({'kind': 'section', 'label': sec['label'], 'amount': None,
                      'indent': 0, 'rule': None})
        single = len(sec['groups']) == 1
        for g in sec['groups']:
            if not single:
                lines.append({'kind': 'group', 'label': g['label'], 'amount': None,
                              'indent': 1, 'rule': None})
            for a in g['accounts']:
                nm = a['name'] if not a['code'] else f"{a['code']}  {a['name']}"
                lines.append({'kind': 'account', 'label': nm, 'amount': a['amount'],
                              'indent': (1 if single else 2), 'rule': None})
            if not single:
                lines.append({'kind': 'group_total', 'label': 'Total ' + g['label'],
                              'amount': g['total'], 'indent': 1, 'rule': 'top_bottom'})
        rule = 'double_bottom' if sec['key'] == 'assets' else 'bottom'
        lines.append({'kind': 'section_total', 'label': _BS_GRAND[sec['key']],
                      'amount': sec['total'], 'indent': 0, 'rule': rule})
    lines.append({'kind': 'grand_total', 'label': 'TOTAL LIABILITIES AND EQUITY',
                  'amount': bs['total_liabilities_equity'], 'indent': 0, 'rule': 'double_bottom'})
    return lines


def build_balance_sheet_xlsx(bs, as_of_label, company, branch_name, filename):
    """Classified Balance Sheet as a formatted workbook with live SUM formulas."""
    wb = Workbook()
    ws = wb.active
    ws.title = 'Balance Sheet'

    right = Alignment(horizontal='right')
    thin, double_s = Side(style='thin'), Side(style='double')
    rules = {
        'bottom': Border(bottom=thin),
        'top_bottom': Border(top=thin, bottom=thin),
        'double_bottom': Border(bottom=double_s),
    }

    def put(label='', amount=None):
        ws.append([label, amount])
        return ws.max_row

    def style(r, bold=False, size=None, border=None):
        font = Font(bold=bold, size=size) if size else (Font(bold=True) if bold else None)
        lc = ws.cell(r, 1)
        if font:
            lc.font = font
        if border:
            lc.border = border
        ac = ws.cell(r, 2)
        ac.number_format = _NUM_FMT
        ac.alignment = right
        if font:
            ac.font = font
        if border:
            ac.border = border

    # ── Header ──
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
    r = put('Balance Sheet'); ws.cell(r, 1).font = Font(bold=True, size=13)
    put(as_of_label)
    put()
    r = put('Particulars', 'Amount')
    for cell in ws[r]:
        cell.font = Font(bold=True)
        cell.border = Border(bottom=thin)
    ws.cell(r, 2).alignment = right

    # ── Body — live formulas ──
    section_total_row = {}
    for sec in bs['sections']:
        r = put(sec['label']); ws.cell(r, 1).font = Font(bold=True)      # section header
        single = len(sec['groups']) == 1
        group_total_rows = []
        for g in sec['groups']:
            if not single:
                r = put('    ' + g['label']); ws.cell(r, 1).font = Font(bold=True)
            acct_rows = []
            for a in g['accounts']:
                nm = a['name'] if not a['code'] else f"{a['code']}  {a['name']}"
                indent = '        ' if not single else '    '
                r = put(indent + nm, a['amount']); style(r); acct_rows.append(r)
            if not single:
                r = put('    Total ' + g['label'])
                ws.cell(r, 2).value = f'=SUM(B{acct_rows[0]}:B{acct_rows[-1]})' if acct_rows else 0
                style(r, bold=True, border=rules['top_bottom'])
                group_total_rows.append(r)
            else:
                group_total_rows = acct_rows      # equity: section total sums the accounts
        st = put(_BS_GRAND[sec['key']])
        if group_total_rows:
            if single:
                ws.cell(st, 2).value = f'=SUM(B{group_total_rows[0]}:B{group_total_rows[-1]})'
            else:
                ws.cell(st, 2).value = '=' + '+'.join(f'B{x}' for x in group_total_rows)
        else:
            ws.cell(st, 2).value = 0
        style(st, bold=True, border=rules['double_bottom' if sec['key'] == 'assets' else 'bottom'])
        section_total_row[sec['key']] = st

    gt = put('TOTAL LIABILITIES AND EQUITY')
    ws.cell(gt, 2).value = f"=B{section_total_row['liabilities']}+B{section_total_row['equity']}"
    style(gt, bold=True, size=12, border=rules['double_bottom'])

    ws.column_dimensions['A'].width = 50
    ws.column_dimensions['B'].width = 22
    ws.sheet_view.showGridLines = False

    return _xlsx_response(wb, filename)


def _cf_invfin_net_cash_lines(cf):
    """Investing + Financing sections + NET INCREASE + begin/end cash.

    Shared by both methods so the tail is emitted identically.
    """
    lines = []
    for key, label, short in (('investing', 'CASH FLOWS FROM INVESTING ACTIVITIES', 'investing'),
                              ('financing', 'CASH FLOWS FROM FINANCING ACTIVITIES', 'financing')):
        sec = cf[key]
        lines.append({'kind': 'header', 'label': label, 'amount': None, 'indent': False, 'rule': None})
        for ln in sec['lines']:
            lines.append({'kind': 'account', 'label': ln['name'], 'amount': ln['amount'],
                          'indent': True, 'rule': None})
        lines.append({'kind': 'subtotal',
                      'label': 'Net cash provided by/(used in) %s activities' % short,
                      'amount': sec['total'], 'indent': False, 'rule': 'top_bottom'})
    lines.append({'kind': 'net', 'label': 'NET INCREASE/(DECREASE) IN CASH',
                  'amount': cf['net_change'], 'indent': False, 'rule': 'double_bottom'})
    lines.append({'kind': 'total', 'label': 'Cash at beginning of period',
                  'amount': cf['cash_begin'], 'indent': False, 'rule': None})
    lines.append({'kind': 'total', 'label': 'Cash at end of period',
                  'amount': cf['cash_end'], 'indent': False, 'rule': 'double_bottom'})
    return lines


def _reconciliation_lines(rec):
    """The PAS 7 net-income -> operating-cash reconciliation note."""
    lines = [{'kind': 'subheader',
              'label': 'Reconciliation of net income to net cash from operating activities',
              'amount': None, 'indent': False, 'rule': None},
             {'kind': 'account', 'label': 'Net Income (period)',
              'amount': rec['net_income'], 'indent': True, 'rule': None}]
    if rec['depreciation']:
        lines.append({'kind': 'account', 'label': 'Add: Depreciation',
                      'amount': rec['depreciation'], 'indent': True, 'rule': None})
    for w in rec['working_capital']:
        lines.append({'kind': 'account', 'label': w['name'], 'amount': w['amount'],
                      'indent': True, 'rule': None})
    lines.append({'kind': 'subtotal', 'label': 'Net cash from operating activities',
                  'amount': rec['total'], 'indent': False, 'rule': 'top_bottom'})
    return lines


def cash_flow_lines(cf):
    """Flatten the cash flow statement into render-ready lines (print + Excel)."""
    if cf.get('method') == 'direct':
        lines = [{'kind': 'header', 'label': 'CASH FLOWS FROM OPERATING ACTIVITIES',
                  'amount': None, 'indent': False, 'rule': None}]
        for ln in cf['operating']['lines']:
            lines.append({'kind': 'account', 'label': ln['name'], 'amount': ln['amount'],
                          'indent': True, 'rule': None})
        lines.append({'kind': 'subtotal',
                      'label': 'Net cash provided by/(used in) operating activities',
                      'amount': cf['operating']['total'], 'indent': False, 'rule': 'top_bottom'})
        lines += _cf_invfin_net_cash_lines(cf)
        if cf.get('noncash'):
            lines.append({'kind': 'subheader',
                          'label': 'Non-cash investing and financing transactions',
                          'amount': None, 'indent': False, 'rule': None})
            for n in cf['noncash']:
                lines.append({'kind': 'account', 'label': n['description'],
                              'amount': n['amount'], 'indent': True, 'rule': None})
        lines += _reconciliation_lines(cf['reconciliation'])
        return lines

    # Indirect (unchanged output)
    lines = []
    op = cf['operating']
    lines.append({'kind': 'header', 'label': 'CASH FLOWS FROM OPERATING ACTIVITIES',
                  'amount': None, 'indent': False, 'rule': None})
    lines.append({'kind': 'account', 'label': 'Net Income (period)',
                  'amount': op['net_income'], 'indent': True, 'rule': None})
    if op['depreciation']:
        lines.append({'kind': 'account', 'label': 'Add: Depreciation',
                      'amount': op['depreciation'], 'indent': True, 'rule': None})
    if op['working_capital']:
        lines.append({'kind': 'subheader', 'label': 'Changes in operating assets and liabilities:',
                      'amount': None, 'indent': True, 'rule': None})
        for w in op['working_capital']:
            lines.append({'kind': 'account', 'label': w['name'], 'amount': w['amount'],
                          'indent': True, 'rule': None})
    lines.append({'kind': 'subtotal', 'label': 'Net cash provided by/(used in) operating activities',
                  'amount': op['total'], 'indent': False, 'rule': 'top_bottom'})
    lines += _cf_invfin_net_cash_lines(cf)
    return lines


def build_cash_flow_xlsx(cf, period_label, company, branch_name, filename):
    """Statement of Cash Flows as a formatted workbook with live formulas."""
    wb = Workbook()
    ws = wb.active
    ws.title = 'Cash Flow'

    right = Alignment(horizontal='right')
    thin, double_s = Side(style='thin'), Side(style='double')
    rules = {
        'bottom': Border(bottom=thin),
        'top_bottom': Border(top=thin, bottom=thin),
        'double_bottom': Border(bottom=double_s),
    }

    def put(label='', amount=None):
        ws.append([label, amount])
        return ws.max_row

    def style(r, bold=False, size=None, border=None):
        font = Font(bold=bold, size=size) if size else (Font(bold=True) if bold else None)
        lc = ws.cell(r, 1)
        if font:
            lc.font = font
        if border:
            lc.border = border
        ac = ws.cell(r, 2)
        ac.number_format = _NUM_FMT
        ac.alignment = right
        if font:
            ac.font = font
        if border:
            ac.border = border

    is_direct = cf.get('method') == 'direct'

    # Header
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
    r = put('Statement of Cash Flows'); ws.cell(r, 1).font = Font(bold=True, size=13)
    put('Direct Method' if is_direct else 'Indirect Method')
    put(period_label)
    put()
    r = put('Particulars', 'Amount')
    for cell in ws[r]:
        cell.font = Font(bold=True)
        cell.border = Border(bottom=thin)
    ws.cell(r, 2).alignment = right

    # Operating section (live SUM over its detail rows)
    r = put('CASH FLOWS FROM OPERATING ACTIVITIES'); ws.cell(r, 1).font = Font(bold=True)
    if is_direct:
        first = last = None
        for ln in cf['operating']['lines']:
            r = put('        ' + ln['name'], ln['amount']); style(r)
            first = first or r
            last = r
    else:
        op = cf['operating']
        r = put('        Net Income (period)', op['net_income']); style(r)
        first = last = r
        if op['depreciation']:
            r = put('        Add: Depreciation', op['depreciation']); style(r); last = r
        if op['working_capital']:
            r = put('        Changes in operating assets and liabilities:')
            ws.cell(r, 1).font = Font(italic=True)
            for w in op['working_capital']:
                r = put('            ' + w['name'], w['amount']); style(r); last = r
    r = put('Net cash provided by/(used in) operating activities')
    ws.cell(r, 2).value = f'=SUM(B{first}:B{last})' if first else 0
    style(r, bold=True, border=rules['top_bottom'])
    sec_rows = {'operating': r}

    # Investing + Financing (shared)
    for key, short in (('investing', 'investing'), ('financing', 'financing')):
        sec = cf[key]
        r = put('CASH FLOWS FROM %s ACTIVITIES' % short.upper()); ws.cell(r, 1).font = Font(bold=True)
        rows = []
        for ln in sec['lines']:
            r = put('        ' + ln['name'], ln['amount']); style(r); rows.append(r)
        r = put('Net cash provided by/(used in) %s activities' % short)
        ws.cell(r, 2).value = f'=SUM(B{rows[0]}:B{rows[-1]})' if rows else 0
        style(r, bold=True, border=rules['top_bottom'])
        sec_rows[key] = r

    r = put('NET INCREASE/(DECREASE) IN CASH')
    ws.cell(r, 2).value = f"=B{sec_rows['operating']}+B{sec_rows['investing']}+B{sec_rows['financing']}"
    style(r, bold=True, size=12, border=rules['double_bottom'])
    net_row = r
    r = put('Cash at beginning of period', cf['cash_begin']); style(r)
    begin_row = r
    r = put('Cash at end of period')
    ws.cell(r, 2).value = f"=B{net_row}+B{begin_row}"
    style(r, bold=True, border=rules['double_bottom'])

    # Direct extras: non-cash note + reconciliation note
    if is_direct:
        if cf.get('noncash'):
            put()
            r = put('Non-cash investing and financing transactions'); ws.cell(r, 1).font = Font(italic=True)
            for n in cf['noncash']:
                r = put('        ' + n['description'], n['amount']); style(r)
        put()
        r = put('Reconciliation of net income to net cash from operating activities')
        ws.cell(r, 1).font = Font(italic=True)
        rec = cf['reconciliation']
        r = put('        Net Income (period)', rec['net_income']); style(r)
        rfirst = rlast = r
        if rec['depreciation']:
            r = put('        Add: Depreciation', rec['depreciation']); style(r); rlast = r
        for w in rec['working_capital']:
            r = put('        ' + w['name'], w['amount']); style(r); rlast = r
        r = put('Net cash from operating activities')
        ws.cell(r, 2).value = f'=SUM(B{rfirst}:B{rlast})'
        style(r, bold=True, border=rules['top_bottom'])

    ws.column_dimensions['A'].width = 50
    ws.column_dimensions['B'].width = 22
    ws.sheet_view.showGridLines = False

    return _xlsx_response(wb, filename)
