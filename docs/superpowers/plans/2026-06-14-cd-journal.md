# Cash Disbursements Journal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `/journals/cd` as a columnar Cash Disbursements Journal, mirroring the AP Journal layout — same period filter, columnar pivot, Print button, and Excel export — but pivoting on `entry_type='disbursement'` JEs.

**Architecture:** Three-layer mirror of the AP Journal: a pure data module (`cd_journal_data.py`) for the columnar pivot and xlsx builder; view functions wired into the existing `journals_bp`; and Jinja2 templates duplicated from the AP Journal equivalents. Cancelled CDVs (whose JEs remain posted) appear as flagged rows with strikethrough + CANCELLED badge, included in column totals. Column groups: debit (blue) = `ap_applied`, `vat`, `expense`; credit (red) = `wht`, `cash`. Credit vs debit is resolved at build time by checking `totals[account_id]` sign for unknown accounts.

**Tech Stack:** Flask blueprint, SQLAlchemy, openpyxl, Jinja2, vanilla JS AJAX (mirror of ap_journal.html pattern)

---

### Task 1: Data layer — `cd_journal_data.py` + unit tests

**Files:**
- Create: `app/journals/cd_journal_data.py`
- Create: `tests/unit/test_cd_journal_data.py`

- [ ] **Step 1: Write the failing unit tests**

Create `tests/unit/test_cd_journal_data.py`:

```python
import io
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from openpyxl import load_workbook
import pytest

from app.journals.cd_journal_data import build_columnar_cd, build_cd_journal_xlsx

pytestmark = [pytest.mark.journals, pytest.mark.unit]


def _mock_line(acct_id, code, name, debit, credit):
    line = MagicMock()
    acct = MagicMock()
    acct.id = acct_id
    acct.code = code
    acct.name = name
    line.account = acct
    line.debit_amount = Decimal(str(debit))
    line.credit_amount = Decimal(str(credit))
    return line


def _mock_entry(date_str, number, lines):
    je = MagicMock()
    je.entry_date = date.fromisoformat(date_str)
    je.entry_number = number
    je.reference = number
    je.lines.all.return_value = lines
    return je


# AP=1, WHT=2, VAT=3, Cash=10, Expense=20
AP_ID = 1
WHT_ID = 2
VAT_ID = 3
CASH_ID = 10
EXPENSE_ID = 20


def _standard_cdv_lines():
    """Dr Expense 10000, Dr Input VAT 1200, Cr WHT 200, Cr AP 0, Cr Cash 11000."""
    return [
        _mock_line(EXPENSE_ID, '60400', 'Rent Expense', 10000, 0),
        _mock_line(VAT_ID,     '10610', 'Input VAT',    1200,  0),
        _mock_line(WHT_ID,     '20301', 'WHT Payable',  0,     200),
        _mock_line(CASH_ID,    '10101', 'Cash on Hand', 0,     11000),
    ]


def test_build_columnar_cd_basic_pivot_and_balance():
    je = _mock_entry('2026-06-01', 'CD-2026-06-0001', _standard_cdv_lines())
    matrix = build_columnar_cd(
        posted_entries=[je], draft_entries=[],
        ap_account_id=AP_ID, wt_account_id=WHT_ID,
        input_vat_account_ids={VAT_ID},
    )
    assert matrix['balanced'] is True
    assert matrix['grand_total'] == Decimal('0')
    assert len(matrix['rows']) == 1
    row = matrix['rows'][0]
    assert row['is_draft'] is False
    assert row['is_cancelled'] is False
    # Expense debit: signed = 10000 - 0 = +10000
    assert row['cells'][EXPENSE_ID] == Decimal('10000')
    # Cash credit: signed = 0 - 11000 = -11000
    assert row['cells'][CASH_ID] == Decimal('-11000')


def test_build_columnar_cd_column_ordering():
    """Column order: ap_applied(0), vat(1), expense(2), wht(3), cash(4)."""
    je = _mock_entry('2026-06-01', 'CD-2026-06-0001', _standard_cdv_lines())
    matrix = build_columnar_cd(
        posted_entries=[je], draft_entries=[],
        ap_account_id=AP_ID, wt_account_id=WHT_ID,
        input_vat_account_ids={VAT_ID},
    )
    groups = [c['group'] for c in matrix['columns']]
    # expense before wht and cash; vat before expense
    assert groups.index('vat') < groups.index('expense')
    assert groups.index('expense') < groups.index('wht')
    assert groups.index('wht') < groups.index('cash')


def test_build_columnar_cd_column_groups():
    je = _mock_entry('2026-06-01', 'CD-2026-06-0001', _standard_cdv_lines())
    matrix = build_columnar_cd(
        posted_entries=[je], draft_entries=[],
        ap_account_id=AP_ID, wt_account_id=WHT_ID,
        input_vat_account_ids={VAT_ID},
    )
    by_id = {c['account_id']: c['group'] for c in matrix['columns']}
    assert by_id[VAT_ID]     == 'vat'
    assert by_id[EXPENSE_ID] == 'expense'
    assert by_id[WHT_ID]     == 'wht'
    assert by_id[CASH_ID]    == 'cash'


def test_build_columnar_cd_cancelled_ref_is_flagged():
    je = _mock_entry('2026-06-01', 'CD-2026-06-0001', _standard_cdv_lines())
    matrix = build_columnar_cd(
        posted_entries=[je], draft_entries=[],
        ap_account_id=AP_ID, wt_account_id=WHT_ID,
        input_vat_account_ids={VAT_ID},
        cancelled_refs={'CD-2026-06-0001'},
    )
    assert matrix['rows'][0]['is_cancelled'] is True
    # Cancelled rows are still included in totals
    assert matrix['totals'][CASH_ID] == Decimal('-11000')


def test_build_columnar_cd_cancelled_ref_not_in_set_is_not_flagged():
    je = _mock_entry('2026-06-01', 'CD-2026-06-0001', _standard_cdv_lines())
    matrix = build_columnar_cd(
        posted_entries=[je], draft_entries=[],
        ap_account_id=AP_ID, wt_account_id=WHT_ID,
        input_vat_account_ids={VAT_ID},
        cancelled_refs={'CD-2026-06-9999'},
    )
    assert matrix['rows'][0]['is_cancelled'] is False


def test_build_columnar_cd_draft_has_no_cells():
    je = _mock_entry('2026-06-01', 'CD-2026-06-0001', _standard_cdv_lines())
    draft = _mock_entry('2026-06-02', 'CD-2026-06-0002', _standard_cdv_lines())
    matrix = build_columnar_cd(
        posted_entries=[je], draft_entries=[draft],
        ap_account_id=AP_ID, wt_account_id=WHT_ID,
        input_vat_account_ids={VAT_ID},
    )
    draft_row = next(r for r in matrix['rows'] if r['is_draft'])
    assert draft_row['cells'] == {}


def test_build_cd_journal_xlsx_has_headers_and_total_row(app):
    columns = [
        {'account_id': EXPENSE_ID, 'code': '60400', 'name': 'Rent Expense', 'group': 'expense'},
        {'account_id': CASH_ID,    'code': '10101', 'name': 'Cash on Hand', 'group': 'cash'},
    ]
    rows = [{
        'entry': _mock_entry('2026-06-01', 'CD-2026-06-0001', []),
        'cells': {EXPENSE_ID: Decimal('10000'), CASH_ID: Decimal('-10000')},
        'is_draft': False,
        'is_cancelled': False,
    }]
    totals = {EXPENSE_ID: Decimal('10000'), CASH_ID: Decimal('-10000')}
    with app.app_context():
        resp = build_cd_journal_xlsx(
            columns=columns, rows=rows, totals=totals,
            period_label='For the month of June 2026',
            company_name='ABC Company', branch_name='Main Branch',
            filename='CD-Journal-2026-06.xlsx',
            identity=lambda e: ('CD-2026-06-0001', '', 'Vendor A', 'Rent'),
        )
    assert resp.headers['Content-Type'].startswith('application/vnd.openxmlformats')
    assert 'CD-Journal-2026-06.xlsx' in resp.headers['Content-Disposition']
    wb = load_workbook(io.BytesIO(resp.get_data()))
    ws = wb.active
    all_text = ' '.join(str(c.value) for row in ws.iter_rows() for c in row if c.value is not None)
    assert 'Cash Disbursements Journal' in all_text
    assert 'Rent Expense' in all_text
    assert 'TOTAL' in all_text


def test_build_cd_journal_xlsx_cancelled_row_has_red_fill(app):
    columns = [
        {'account_id': CASH_ID, 'code': '10101', 'name': 'Cash on Hand', 'group': 'cash'},
    ]
    entry = _mock_entry('2026-06-01', 'CD-2026-06-0001', [])
    rows = [{
        'entry': entry,
        'cells': {CASH_ID: Decimal('-10000')},
        'is_draft': False,
        'is_cancelled': True,
    }]
    with app.app_context():
        resp = build_cd_journal_xlsx(
            columns=columns, rows=rows, totals={CASH_ID: Decimal('-10000')},
            period_label='For the month of June 2026',
            company_name='ABC Co', branch_name=None,
            filename='test.xlsx',
            identity=lambda e: ('CD-2026-06-0001', '', 'Vendor X', '[CANCELLED]'),
        )
    wb = load_workbook(io.BytesIO(resp.get_data()))
    ws = wb.active
    # No branch → header row 5, data row 6
    for col_idx in range(1, 5 + len(columns) + 1):
        cell = ws.cell(row=6, column=col_idx)
        assert cell.fill.fgColor.rgb.endswith('FFCDD2'), \
            f"col {col_idx}: expected FFCDD2, got {cell.fill.fgColor.rgb}"
```

- [ ] **Step 2: Run tests — expect ImportError**

```
pytest tests/unit/test_cd_journal_data.py -v
```

Expected: `ImportError: cannot import name 'build_columnar_cd'`

- [ ] **Step 3: Implement `cd_journal_data.py`**

Create `app/journals/cd_journal_data.py`:

```python
"""Pure data layer for the columnar Cash Disbursements Journal.

No Flask request access here — callers pass plain dicts/values so these
functions are unit-testable in isolation.
"""
import io
from decimal import Decimal

from flask import make_response
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
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
    """Sort: ap_applied(0) → vat(1) → expense(2) → wht(3) → cash(4), then by code."""
    order = {'ap_applied': 0, 'vat': 1, 'expense': 2, 'wht': 3, 'cash': 4}
    g = _group(account, ap_account_id, wt_account_id, input_vat_account_ids, totals)
    return (order.get(g, 2), account.code)


def build_columnar_cd(posted_entries, draft_entries, ap_account_id,
                      wt_account_id, input_vat_account_ids, cancelled_refs=None):
    """Pivot disbursement journal-entry lines into a columnar matrix.

    Columns are built only from POSTED entries' accounts. Cancelled CDVs
    (whose JEs remain posted) are included in totals but flagged is_cancelled=True
    for visual display (strikethrough + badge). Draft rows carry no amounts.

    cancelled_refs: set of CDV numbers (entry.reference) that are cancelled.

    Returns dict: columns, rows, totals, grand_total, balanced.
    """
    if cancelled_refs is None:
        cancelled_refs = set()

    accounts_by_id = {}
    totals = {}
    rows = []

    for je in posted_entries:
        cells = {}
        for line in je.lines.all():
            acct = line.account
            accounts_by_id[acct.id] = acct
            signed = (line.debit_amount or Decimal('0')) - (line.credit_amount or Decimal('0'))
            cells[acct.id] = cells.get(acct.id, Decimal('0')) + signed
            totals[acct.id] = totals.get(acct.id, Decimal('0')) + signed
        is_cancelled = je.reference in cancelled_refs if cancelled_refs else False
        rows.append({'entry': je, 'cells': cells, 'is_draft': False, 'is_cancelled': is_cancelled})

    for je in draft_entries:
        rows.append({'entry': je, 'cells': {}, 'is_draft': True, 'is_cancelled': False})

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
    if value is None or value == Decimal('0'):
        return ''
    if value < 0:
        return f'({-value:,.2f})'
    return f'{value:,.2f}'


def build_cd_journal_xlsx(columns, rows, totals, period_label, company_name,
                          branch_name, filename, identity):
    """Build the columnar CD Journal as an .xlsx Flask response.

    branch_name=None skips the branch row.
    identity(entry) -> (cd_no, check_no, vendor, particulars)
    """
    wb = Workbook()
    ws = wb.active
    ws.title = 'CD Journal'

    right = Alignment(horizontal='right')
    center_wrap = Alignment(horizontal='center', vertical='center', wrap_text=True)
    num_fmt = '#,##0.00;(#,##0.00)'

    thin = Side(style='thin')
    double_s = Side(style='double')
    cell_border = Border(left=thin, right=thin, top=thin, bottom=thin)
    total_border = Border(bottom=double_s)
    draft_fill     = PatternFill(fill_type='solid', fgColor='FFF9C4')  # light yellow
    cancelled_fill = PatternFill(fill_type='solid', fgColor='FFCDD2')  # light red

    ws.append([company_name])
    ws['A1'].font = Font(bold=True, size=16)
    if branch_name:
        ws.append([branch_name])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True, size=16)
    ws.append(['Cash Disbursements Journal'])
    ws.cell(row=ws.max_row, column=1).font = Font(bold=True, size=14)
    ws.append([period_label])
    ws.append([])

    fixed = ['Date', 'CD No.', 'Check No.', 'Vendor', 'Particulars']
    header = fixed + [c['name'] for c in columns]
    ws.append(header)
    hdr_row = ws.max_row
    ws.row_dimensions[hdr_row].height = 40
    for cell in ws[hdr_row]:
        cell.font = Font(bold=True)
        cell.alignment = center_wrap
        cell.border = cell_border

    first_data_row = hdr_row + 1
    for r in rows:
        e = r['entry']
        no, check_no, vendor, particulars = identity(e)
        if r['is_cancelled']:
            particulars = '[CANCELLED] ' + (particulars or '')
        elif r['is_draft']:
            particulars = '[DRAFT] ' + (particulars or '')
        line = [
            e.entry_date.strftime('%d-%b-%Y'),
            no or '',
            check_no or '',
            vendor or '',
            particulars or '',
        ]
        for c in columns:
            if r['is_draft']:
                line.append(None)
            else:
                val = r['cells'].get(c['account_id'])
                line.append(float(val) if val else None)
        ws.append(line)
        cur = ws.max_row
        fill = cancelled_fill if r['is_cancelled'] else (draft_fill if r['is_draft'] else None)
        for i, cell in enumerate(ws[cur], 1):
            cell.border = cell_border
            if fill:
                cell.fill = fill
            if i > len(fixed):
                cell.number_format = num_fmt
                cell.alignment = right

    last_data_row = ws.max_row
    ws.append([])
    ws.append(['TOTAL', '', '', '', ''])
    tot_row = ws.max_row
    for i in range(1, len(fixed) + 1):
        ws.cell(row=tot_row, column=i).font = Font(bold=True)
        ws.cell(row=tot_row, column=i).border = total_border
    for i, c in enumerate(columns, len(fixed) + 1):
        col_letter = get_column_letter(i)
        cell = ws.cell(row=tot_row, column=i)
        cell.value = f'=SUM({col_letter}{first_data_row}:{col_letter}{last_data_row + 1})'
        cell.font = Font(bold=True)
        cell.number_format = num_fmt
        cell.alignment = right
        cell.border = total_border

    col_widths = [12, 22, 18, 28, 40] + [20] * len(columns)
    for i, width in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = width

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    resp.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp
```

- [ ] **Step 4: Run tests — expect all pass**

```
pytest tests/unit/test_cd_journal_data.py -v
```

Expected: 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/journals/cd_journal_data.py tests/unit/test_cd_journal_data.py
git commit -m "feat: cd_journal_data — build_columnar_cd + build_cd_journal_xlsx + unit tests"
```

---

### Task 2: View routes + templates (main view + print)

**Files:**
- Modify: `app/journals/views.py` (add import, `_cd_journal_context`, `_cd_entry_identity`, replace `cd_journal()`, add `cd_journal_print()`)
- Create: `app/journals/templates/journals/cd_journal.html`
- Create: `app/journals/templates/journals/cd_journal_print.html`
- Modify: `app/templates/base.html` (remove `nav-item--soon` from CD Journal nav link, lines 1169–1173)

- [ ] **Step 1: Update `views.py` — add import and helper functions**

At the top of `app/journals/views.py`, update the import line:

```python
from app.journals.ap_journal_data import resolve_period, build_columnar, build_ap_journal_xlsx
```

Change to:

```python
from app.journals.ap_journal_data import resolve_period, build_columnar, build_ap_journal_xlsx
from app.journals.cd_journal_data import build_columnar_cd
```

Then add these two functions after `_entry_identity` (after line 86):

```python
def _cd_journal_context(branch_id):
    """Build the columnar CD journal data for a branch + period from request.args."""
    from app.cash_disbursements.models import CashDisbursementVoucher
    period = resolve_period(request.args, today=ph_now().date())

    entries = JournalEntry.query.filter(
        JournalEntry.entry_type == 'disbursement',
        JournalEntry.branch_id == branch_id,
        JournalEntry.entry_date >= period['date_from'],
        JournalEntry.entry_date <= period['date_to'],
    ).order_by(JournalEntry.entry_date).all()
    posted = [e for e in entries if e.status == 'posted']
    drafts = [e for e in entries if e.status == 'draft']

    refs = [e.reference for e in entries if e.reference]
    cdvs = CashDisbursementVoucher.query.filter(
        CashDisbursementVoucher.cdv_number.in_(refs)
    ).all() if refs else []
    cdv_map = {c.cdv_number: c for c in cdvs}
    cancelled_refs = {c.cdv_number for c in cdvs if c.status == 'cancelled'}

    ap_id, wt_id, vat_ids = _gl_account_ids()
    matrix = build_columnar_cd(posted, drafts, ap_id, wt_id, vat_ids,
                               cancelled_refs=cancelled_refs)
    return period, matrix, cdv_map


def _cd_entry_identity(entry, cdv_map):
    """Return (cd_no, check_no, vendor, particulars) for the left identifier columns."""
    cdv = cdv_map.get(entry.reference)
    return (
        entry.reference or '—',
        (cdv.check_number if cdv and cdv.check_number else '') or '',
        (cdv.vendor_name if cdv else '') or '—',
        (cdv.notes if cdv else '') or '',
    )
```

- [ ] **Step 2: Replace `cd_journal()` and add `cd_journal_print()` in `views.py`**

Replace the stub `cd_journal()` route (lines 188–191):

```python
@journals_bp.route('/journals/cd')
@login_required
def cd_journal():
    branch_id = _branch_id()
    if not branch_id:
        flash('Please select a branch to view journal entries.', 'warning')
        return redirect(url_for('users.select_branch', next=request.url))

    period, matrix, cdv_map = _cd_journal_context(branch_id)
    return render_template('journals/cd_journal.html',
                           period=period, matrix=matrix, cdv_map=cdv_map)


@journals_bp.route('/journals/cd/print')
@login_required
def cd_journal_print():
    branch_id = _branch_id()
    if not branch_id:
        flash('Please select a branch.', 'warning')
        return redirect(url_for('users.select_branch', next=request.url))

    from app.branches.models import Branch
    from app.settings import AppSettings
    period, matrix, cdv_map = _cd_journal_context(branch_id)

    branch = db.session.get(Branch, branch_id)
    branch_count = Branch.query.count()
    branch_name = branch.name if (branch and branch_count > 1) else None
    company_name = AppSettings.get_setting('company_name') or ''

    return render_template('journals/cd_journal_print.html',
                           period=period, matrix=matrix, cdv_map=cdv_map,
                           company_name=company_name, branch_name=branch_name,
                           printed_at=ph_now())
```

- [ ] **Step 3: Remove `nav-item--soon` from base.html**

In `app/templates/base.html` at lines 1169–1173, replace:

```html
                    <a href="{{ url_for('journals.cd_journal') }}" class="nav-item nav-item--soon {% if request.endpoint == 'journals.cd_journal' %}active{% endif %}">
                        <span class="nav-icon">💸</span>
                        <span class="nav-text">Cash Disbursements Journal</span>
                        <span class="nav-coming-soon">Soon</span>
```

With:

```html
                    <a href="{{ url_for('journals.cd_journal') }}" class="nav-item {% if request.endpoint == 'journals.cd_journal' %}active{% endif %}">
                        <span class="nav-icon">💸</span>
                        <span class="nav-text">Cash Disbursements Journal</span>
```

(Remove the `nav-item--soon` class and the `<span class="nav-coming-soon">Soon</span>` line.)

- [ ] **Step 4: Create `cd_journal.html`**

Create `app/journals/templates/journals/cd_journal.html`:

```html
{% extends "base.html" %}
{% block title %}Cash Disbursements Journal{% endblock %}
{% block page_title %}Cash Disbursements Journal{% endblock %}

{% block extra_css %}
<style>
.cd-jrnl-toolbar { display:flex; gap:16px; align-items:flex-end; flex-wrap:wrap;
    padding:20px; background:var(--surface-2, #f8fafc); border-bottom:1px solid var(--border, #e2e8f0); }
.cd-jrnl-field label { display:block; font-size:12px; font-weight:600; color:var(--text-2,#64748b);
    margin-bottom:6px; text-transform:uppercase; }
.cd-jrnl-table { width:100%; border-collapse:collapse; font-size:12px; white-space:nowrap; }
.cd-jrnl-table th, .cd-jrnl-table td { padding:6px 8px; border-bottom:1px solid var(--border,#e2e8f0); }
.cd-jrnl-table th { text-align:left; border-bottom:2px solid var(--text-1,#334155); }
.cd-jrnl-num { text-align:right; font-family:var(--mono, monospace); }
.cd-jrnl-total td { border-top:2px solid var(--text-1,#334155); font-weight:700; }
.cd-jrnl-head--credit { background:#fef2f2; }
.cd-jrnl-head--debit { background:#eff6ff; }
.cd-jrnl-draft-badge { font-size:10px; font-weight:600; color:#c2410c; background:#fff7ed;
    border:1px solid #fed7aa; padding:1px 6px; border-radius:8px; text-transform:uppercase; }
.cd-jrnl-cancelled-badge { font-size:10px; font-weight:600; color:#b91c1c; background:#fef2f2;
    border:1px solid #fecaca; padding:1px 6px; border-radius:8px; text-transform:uppercase; }
.cd-jrnl-cancelled td { text-decoration:line-through; background:var(--red-50, #fef2f2); }
.cd-jrnl-cancelled .cd-jrnl-no-strike { text-decoration:none !important; }
.cd-jrnl-scroll { overflow-x:auto; }
.cd-jrnl-balance-warning { color:var(--red,#dc2626); font-weight:600; margin-top:10px; }
.cd-jrnl-meta { padding:8px 20px 0; }
.cd-jrnl-meta h3 { margin:0; font-size:14px; }
.cd-jrnl-meta p { margin:2px 0 0; font-size:12px; color:var(--text-2,#64748b); }
@media print {
    .sidebar, .topbar, .cd-jrnl-toolbar, .cd-jrnl-actions { display:none !important; }
    .main-content { margin-left:0 !important; }
    @page { size: landscape; }
    .cd-jrnl-table { font-size:9px; }
}
</style>
{% endblock %}

{% block content %}
<div class="card">
    <div class="card-header">
        <div class="cd-jrnl-actions" style="display:flex; gap:8px; justify-content:flex-end;">
            <a id="cdPrintLink" href="{{ url_for('journals.cd_journal_print', **request.args) }}" class="btn btn-secondary btn-sm">Print</a>
            <a id="cdExportLink" href="{{ url_for('journals.cd_journal_export', **request.args) }}" class="btn btn-primary btn-sm">Download Excel</a>
        </div>
    </div>

    <form method="GET" action="{{ url_for('journals.cd_journal') }}" class="cd-jrnl-toolbar" id="cdFilter">
        <input type="hidden" name="mode" id="cdMode" value="{{ period.mode }}">
        <div class="cd-jrnl-field" id="cdMonthFields" {% if period.mode == 'custom' %}style="display:none"{% endif %}>
            <label>Month</label>
            <select name="month" class="form-control form-control-sm">
                {% for m in range(1, 13) %}
                <option value="{{ m }}" {% if m == period.month %}selected{% endif %}>
                    {{ ['January','February','March','April','May','June','July','August','September','October','November','December'][m-1] }}
                </option>
                {% endfor %}
            </select>
        </div>
        <div class="cd-jrnl-field" id="cdYearField" {% if period.mode == 'custom' %}style="display:none"{% endif %}>
            <label>Year</label>
            <input type="number" name="year" value="{{ period.year }}" class="form-control form-control-sm" style="width:100px;">
        </div>
        <div class="cd-jrnl-field" id="cdFromField" {% if period.mode != 'custom' %}style="display:none"{% endif %}>
            <label>From</label>
            <input type="date" name="date_from" value="{{ period.date_from.isoformat() }}" class="form-control form-control-sm">
        </div>
        <div class="cd-jrnl-field" id="cdToField" {% if period.mode != 'custom' %}style="display:none"{% endif %}>
            <label>To</label>
            <input type="date" name="date_to" value="{{ period.date_to.isoformat() }}" class="form-control form-control-sm">
        </div>
        <div class="cd-jrnl-field">
            <button type="submit" class="btn btn-primary btn-sm">Filter</button>
            <button type="button" id="cdToggleCustom" class="btn btn-secondary btn-sm">
                {% if period.mode == 'custom' %}Use month{% else %}Custom range{% endif %}
            </button>
        </div>
    </form>

    <div id="cd-journal-content">
    <div class="cd-jrnl-meta">
        <h3>Cash Disbursements Journal</h3>
        <p>{{ period.label }} &mdash; {{ current_branch.name if current_branch else 'All Branches' }}</p>
    </div>

    <div class="card-body">
        {% if matrix.rows %}
        <div class="cd-jrnl-scroll">
        <table class="cd-jrnl-table">
            <thead>
                <tr>
                    <th>Date</th>
                    <th>CD No.</th>
                    <th>Check No.</th>
                    <th>Vendor</th>
                    <th>Particulars</th>
                    {% for col in matrix.columns %}
                    <th class="cd-jrnl-num {% if col.group in ['wht','cash'] %}cd-jrnl-head--credit{% else %}cd-jrnl-head--debit{% endif %}">{{ col.name }}</th>
                    {% endfor %}
                </tr>
            </thead>
            <tbody>
                {% for row in matrix.rows %}
                {% set cdv = cdv_map.get(row.entry.reference) %}
                <tr {% if row.is_cancelled %}class="cd-jrnl-cancelled"{% endif %}>
                    <td>{{ row.entry.entry_date.strftime('%b %d, %Y') }}</td>
                    <td class="cd-jrnl-no-strike">
                        {% if cdv %}
                        <a href="{{ url_for('cash_disbursements.view', id=cdv.id) }}" style="font-weight:600;color:var(--blue);">{{ row.entry.reference }}</a>
                        {% else %}{{ row.entry.reference or '&mdash;' }}{% endif %}
                        {% if row.is_draft %}<span class="cd-jrnl-draft-badge">Draft</span>{% endif %}
                        {% if row.is_cancelled %}<span class="cd-jrnl-cancelled-badge cd-jrnl-no-strike">Cancelled</span>{% endif %}
                    </td>
                    <td>{{ cdv.check_number if cdv and cdv.check_number else '' }}</td>
                    <td>{{ cdv.vendor_name if cdv else '&mdash;' }}</td>
                    <td>{{ (cdv.notes if cdv else '') or '' }}</td>
                    {% for col in matrix.columns %}
                    <td class="cd-jrnl-num">
                        {%- if row.is_draft -%}
                        {%- elif col.account_id in row.cells and row.cells[col.account_id] != 0 -%}
                            {%- set v = row.cells[col.account_id] -%}
                            {%- if v < 0 -%}({{ '{:,.2f}'.format(-v) }}){%- else -%}{{ '{:,.2f}'.format(v) }}{%- endif -%}
                        {%- endif -%}
                    </td>
                    {% endfor %}
                </tr>
                {% endfor %}
                <tr class="cd-jrnl-total">
                    <td colspan="5">TOTAL</td>
                    {% for col in matrix.columns %}
                    <td class="cd-jrnl-num">
                        {%- set t = matrix.totals.get(col.account_id) -%}
                        {%- if t and t != 0 -%}
                            {%- if t < 0 -%}({{ '{:,.2f}'.format(-t) }}){%- else -%}{{ '{:,.2f}'.format(t) }}{%- endif -%}
                        {%- endif -%}
                    </td>
                    {% endfor %}
                </tr>
            </tbody>
        </table>
        </div>
        {% if not matrix.balanced %}
        <p class="cd-jrnl-balance-warning">
            Warning: Column totals do not net to zero &mdash; debits and credits are out of balance. Review the underlying entries.
        </p>
        {% endif %}
        {% else %}
        <div class="empty-state">
            <p>No CD entries found for {{ period.label | lower }}.</p>
            <p style="font-size:13px; color:var(--text-3);">CD journal entries are created automatically when a CDV is posted.</p>
        </div>
        {% endif %}
    </div>{# card-body #}
    </div>{# cd-journal-content #}
</div>{# card #}

<script>
(function () {
    var form   = document.getElementById('cdFilter');
    var toggle = document.getElementById('cdToggleCustom');
    var mode   = document.getElementById('cdMode');
    if (!form || !toggle || !mode) return;

    function showFields(isCustom) {
        document.getElementById('cdMonthFields').style.display = isCustom ? 'none' : '';
        document.getElementById('cdYearField').style.display   = isCustom ? 'none' : '';
        document.getElementById('cdFromField').style.display   = isCustom ? '' : 'none';
        document.getElementById('cdToField').style.display     = isCustom ? '' : 'none';
        toggle.textContent = isCustom ? 'Use month' : 'Custom range';
    }

    function fetchAndSwap(params) {
        var url = '/journals/cd?' + params.toString();
        fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.text();
            })
            .then(function (html) {
                var doc   = new DOMParser().parseFromString(html, 'text/html');
                var fresh = doc.getElementById('cd-journal-content');
                if (!fresh) throw new Error('no content');
                document.getElementById('cd-journal-content').replaceWith(fresh);
                var exportLink = document.getElementById('cdExportLink');
                if (exportLink) exportLink.href = '/journals/cd/export?' + params.toString();
                var printLink = document.getElementById('cdPrintLink');
                if (printLink) printLink.href = '/journals/cd/print?' + params.toString();
                history.pushState({}, '', url);
            })
            .catch(function () {
                window.location.href = url;
            });
    }

    form.addEventListener('submit', function (e) {
        e.preventDefault();
        fetchAndSwap(new URLSearchParams(new FormData(form)));
    });

    toggle.addEventListener('click', function () {
        var isCustom = mode.value !== 'custom';
        mode.value = isCustom ? 'custom' : 'month';
        showFields(isCustom);
        fetchAndSwap(new URLSearchParams(new FormData(form)));
    });

    window.addEventListener('popstate', function () {
        var params = new URLSearchParams(window.location.search);
        var isCustom = params.get('mode') === 'custom';
        mode.value = isCustom ? 'custom' : 'month';
        showFields(isCustom);
        fetchAndSwap(params);
    });
})();
</script>
{% endblock %}
```

- [ ] **Step 5: Create `cd_journal_print.html`**

Create `app/journals/templates/journals/cd_journal_print.html`:

```html
{% extends "base.html" %}
{% block title %}CD Journal Print — {{ period.label }}{% endblock %}
{% block page_title %}CD Journal — Print Preview{% endblock %}

{% block extra_css %}
<style>
  .cdj-print-actions { display: flex; gap: 8px; justify-content: flex-end; }
  .cdj-header { text-align: center; border-bottom: 2px solid #111; padding-bottom: 10px; margin-bottom: 14px; }
  .cdj-header .company-name { font-size: 16px; font-weight: 700; letter-spacing: .5px; }
  .cdj-header .branch-name  { font-size: 13px; font-weight: 700; color: #444; margin-top: 2px; }
  .cdj-header .doc-title    { font-size: 14px; font-weight: 700; letter-spacing: 1px; margin-top: 6px; }
  .cdj-header .period-label { font-size: 11px; color: #555; margin-top: 3px; }
  .cdj-scroll { overflow-x: auto; }
  .cdj-table { width: 100%; border-collapse: collapse; font-size: 10px; }
  .cdj-table th, .cdj-table td { border: 1px solid #aaa; padding: 3px 6px; white-space: nowrap; }
  .cdj-table th { background: #222; color: #fff; font-weight: 700; text-align: left; }
  .cdj-table th.num { text-align: center; width: 120px; min-width: 120px;
    white-space: normal; word-break: break-word; vertical-align: bottom; }
  .cdj-table td.num { text-align: right; font-family: monospace; width: 120px; min-width: 120px; max-width: 120px; }
  .cdj-table th.credit-col { background: #b71c1c; }
  .cdj-table th.debit-col  { background: #1565c0; }
  .cdj-row-draft td { background: #fffde7; }
  .cdj-row-cancelled td { background: #ffebee; text-decoration: line-through; }
  .cdj-row-cancelled td.no-strike { text-decoration: none; }
  .cdj-total td { border-top: 2px solid #111; font-weight: 700; background: #f0f0f0; }
  .balance-warning { margin-top: 10px; font-size: 11px; font-weight: 700; color: #b91c1c; }
  .audit-footer { margin-top: 8px; font-size: 9px; color: #888; text-align: right;
                  border-top: 1px solid #ddd; padding-top: 4px; }
  @media print {
    nav.sidebar, header.topbar, .cdj-print-actions, .card-header { display: none !important; }
    .main { margin-left: 0 !important; padding: 0 !important; }
    .content-wrapper, .card { box-shadow: none !important; border: none !important; }
    .cdj-scroll { overflow: visible !important; }
    @page { size: A4 landscape; margin: 10mm; }
    .cdj-table { font-size: 8px; }
    .cdj-table th.num { width: 90px; min-width: 90px; white-space: normal; }
    .cdj-table td.num { width: 90px; min-width: 90px; max-width: 90px; }
    .cdj-table thead { display: table-header-group; }
    .cdj-table tbody tr { break-inside: avoid; page-break-inside: avoid; }
    .cdj-header { page-break-after: avoid; }
  }
</style>
{% endblock %}

{% block content %}
<div class="card">
  <div class="card-header">
    <div class="cdj-print-actions">
      <button onclick="window.print()" class="btn btn-secondary btn-sm">Print</button>
      <a href="{{ url_for('journals.cd_journal') }}" class="btn btn-secondary btn-sm">Back</a>
    </div>
  </div>
  <div class="card-body">

    <div class="cdj-header">
      {% if company_name %}<div class="company-name">{{ company_name | upper }}</div>{% endif %}
      {% if branch_name %}<div class="branch-name">{{ branch_name }}</div>{% endif %}
      <div class="doc-title">CASH DISBURSEMENTS JOURNAL</div>
      <div class="period-label">{{ period.label }}</div>
    </div>

    {% if matrix.rows %}
    <div class="cdj-scroll">
    <table class="cdj-table">
      <thead>
        <tr>
          <th>Date</th>
          <th>CD No.</th>
          <th>Check No.</th>
          <th>Vendor</th>
          <th>Particulars</th>
          {% for col in matrix.columns %}
          <th class="num {% if col.group in ['wht','cash'] %}credit-col{% else %}debit-col{% endif %}">
            {{ col.name }}
          </th>
          {% endfor %}
        </tr>
      </thead>
      <tbody>
        {% for row in matrix.rows %}
        {% set cdv = cdv_map.get(row.entry.reference) %}
        <tr {% if row.is_cancelled %}class="cdj-row-cancelled"{% elif row.is_draft %}class="cdj-row-draft"{% endif %}>
          <td>{{ row.entry.entry_date.strftime('%d-%b-%Y') }}</td>
          <td class="no-strike">{{ row.entry.reference or '—' }}</td>
          <td>{{ cdv.check_number if cdv and cdv.check_number else '' }}</td>
          <td>{{ cdv.vendor_name if cdv else '—' }}</td>
          <td>
            {%- if row.is_cancelled -%}[CANCELLED] {% endif -%}
            {%- if row.is_draft -%}[DRAFT] {% endif -%}
            {{ (cdv.notes if cdv else '') or '' }}
          </td>
          {% for col in matrix.columns %}
          <td class="num">
            {%- if not row.is_draft and col.account_id in row.cells and row.cells[col.account_id] != 0 -%}
              {%- set v = row.cells[col.account_id] -%}
              {%- if v < 0 -%}({{ '{:,.2f}'.format(-v) }}){%- else -%}{{ '{:,.2f}'.format(v) }}{%- endif -%}
            {%- endif -%}
          </td>
          {% endfor %}
        </tr>
        {% endfor %}

        <tr class="cdj-total">
          <td colspan="5">TOTAL</td>
          {% for col in matrix.columns %}
          <td class="num">
            {%- set t = matrix.totals.get(col.account_id) -%}
            {%- if t and t != 0 -%}
              {%- if t < 0 -%}({{ '{:,.2f}'.format(-t) }}){%- else -%}{{ '{:,.2f}'.format(t) }}{%- endif -%}
            {%- endif -%}
          </td>
          {% endfor %}
        </tr>
      </tbody>
    </table>
    </div>

    {% if not matrix.balanced %}
    <p class="balance-warning">Warning: Column totals do not net to zero — debits and credits are out of balance.</p>
    {% endif %}

    {% else %}
    <p style="margin-top:16px; color:#555;">No CD entries found for {{ period.label | lower }}.</p>
    {% endif %}

    <div class="audit-footer">
      Printed: {{ printed_at.strftime('%d %b %Y %I:%M %p') }}
    </div>

  </div>
</div>
{% endblock %}
```

- [ ] **Step 6: Start Flask and verify `/journals/cd` loads**

```powershell
python flask_app.py
```

Navigate to `http://127.0.0.1:5000/journals/cd` (logged in, branch selected). Verify:
- No "Under Development" redirect
- Nav shows "Cash Disbursements Journal" active without "Soon" badge
- Empty state renders (no CDV JEs yet unless branch has data)
- Period filter renders with month/year dropdowns
- Print and Download Excel buttons visible in header

- [ ] **Step 7: Commit**

```bash
git add app/journals/views.py app/journals/cd_journal_data.py
git add app/journals/templates/journals/cd_journal.html
git add app/journals/templates/journals/cd_journal_print.html
git add app/templates/base.html
git commit -m "feat: cd journal — view routes, templates, nav link activated"
```

---

### Task 3: Export route + integration tests

**Files:**
- Modify: `app/journals/views.py` (add `cd_journal_export()`)
- Create: `tests/integration/test_cd_journal_views.py`

- [ ] **Step 1: Write the failing integration tests**

Create `tests/integration/test_cd_journal_views.py`:

```python
"""Integration tests for the Cash Disbursements Journal view and export."""
from datetime import date
from decimal import Decimal
import pytest

from app import db
from app.accounts.models import Account
from app.branches.models import Branch
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.users.models import User

pytestmark = [pytest.mark.journals, pytest.mark.integration]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def branch(db_session):
    b = Branch(name='Test Branch', code='TST')
    db.session.add(b)
    db.session.commit()
    return b


@pytest.fixture()
def accountant(db_session):
    u = User(username='acc_cd', email='acc_cd@test.com', role='accountant', is_active=True)
    u.set_password('pass')
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture()
def cash_acct(db_session):
    a = Account.query.filter_by(code='10101').first()
    if not a:
        a = Account(code='10101', name='Cash on Hand', account_type='Asset',
                    normal_balance='debit', is_active=True)
        db.session.add(a)
        db.session.commit()
    return a


@pytest.fixture()
def expense_acct(db_session):
    a = Account.query.filter_by(code='60400').first()
    if not a:
        a = Account(code='60400', name='Rent Expense', account_type='Expense',
                    normal_balance='debit', is_active=True)
        db.session.add(a)
        db.session.commit()
    return a


def _login(client, username, password='pass'):
    client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)
    with client.session_transaction() as s:
        from app.branches.models import Branch
        branch = Branch.query.first()
        if branch:
            s['selected_branch_id'] = branch.id


def _disbursement_je(branch_id, entry_date, number, cash_acct, expense_acct, amount):
    """Post a disbursement JE: Dr Expense, Cr Cash."""
    je = JournalEntry(
        entry_number=number, entry_date=entry_date,
        description='Test disbursement', reference=number,
        entry_type='disbursement',
        branch_id=branch_id, status='posted', is_balanced=True,
        total_debit=Decimal(str(amount)), total_credit=Decimal(str(amount)),
    )
    db.session.add(je)
    db.session.flush()
    db.session.add(JournalEntryLine(
        entry_id=je.id, line_number=1, account_id=expense_acct.id,
        debit_amount=Decimal(str(amount)), credit_amount=Decimal('0')))
    db.session.add(JournalEntryLine(
        entry_id=je.id, line_number=2, account_id=cash_acct.id,
        debit_amount=Decimal('0'), credit_amount=Decimal(str(amount))))
    db.session.commit()
    return je


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCDJournalView:
    def test_redirects_to_login_when_unauthenticated(self, client):
        resp = client.get('/journals/cd', follow_redirects=False)
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']

    def test_returns_200_when_authenticated(self, client, accountant, branch):
        _login(client, 'acc_cd')
        resp = client.get('/journals/cd')
        assert resp.status_code == 200
        assert b'Cash Disbursements Journal' in resp.data

    def test_empty_state_when_no_entries(self, client, accountant, branch):
        _login(client, 'acc_cd')
        resp = client.get('/journals/cd?month=1&year=2020')
        assert resp.status_code == 200
        assert b'No CD entries found' in resp.data

    def test_shows_period_label(self, client, accountant, branch):
        _login(client, 'acc_cd')
        resp = client.get('/journals/cd?mode=month&year=2026&month=6')
        assert resp.status_code == 200
        assert b'June 2026' in resp.data

    def test_shows_disbursement_entry(self, client, accountant, branch, cash_acct, expense_acct, db_session):
        je = _disbursement_je(branch.id, date(2026, 6, 10), 'CD-2026-06-0001',
                              cash_acct, expense_acct, 5000)
        _login(client, 'acc_cd')
        resp = client.get('/journals/cd?mode=month&year=2026&month=6')
        assert resp.status_code == 200
        assert b'CD-2026-06-0001' in resp.data
        assert b'5,000.00' in resp.data

    def test_custom_range_filter(self, client, accountant, branch, cash_acct, expense_acct, db_session):
        _disbursement_je(branch.id, date(2026, 5, 15), 'CD-2026-05-0001',
                         cash_acct, expense_acct, 3000)
        _login(client, 'acc_cd')
        resp = client.get('/journals/cd?mode=custom&date_from=2026-05-01&date_to=2026-05-31')
        assert resp.status_code == 200
        assert b'CD-2026-05-0001' in resp.data

    def test_entry_outside_period_not_shown(self, client, accountant, branch, cash_acct, expense_acct, db_session):
        _disbursement_je(branch.id, date(2026, 4, 1), 'CD-2026-04-0001',
                         cash_acct, expense_acct, 1000)
        _login(client, 'acc_cd')
        resp = client.get('/journals/cd?mode=month&year=2026&month=6')
        assert b'CD-2026-04-0001' not in resp.data

    def test_shows_download_and_print_buttons(self, client, accountant, branch):
        _login(client, 'acc_cd')
        resp = client.get('/journals/cd')
        assert b'Download Excel' in resp.data
        assert b'Print' in resp.data

    def test_print_route_returns_200(self, client, accountant, branch):
        _login(client, 'acc_cd')
        resp = client.get('/journals/cd/print')
        assert resp.status_code == 200
        assert b'CASH DISBURSEMENTS JOURNAL' in resp.data


class TestCDJournalExport:
    def test_export_redirects_unauthenticated(self, client):
        resp = client.get('/journals/cd/export', follow_redirects=False)
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']

    def test_export_returns_xlsx(self, client, accountant, branch):
        _login(client, 'acc_cd')
        resp = client.get('/journals/cd/export?mode=month&year=2026&month=6')
        assert resp.status_code == 200
        assert 'spreadsheetml' in resp.headers['Content-Type']
        assert 'CD-Journal-' in resp.headers['Content-Disposition']

    def test_export_filename_uses_year_month(self, client, accountant, branch):
        _login(client, 'acc_cd')
        resp = client.get('/journals/cd/export?mode=month&year=2026&month=3')
        assert '2026-03' in resp.headers['Content-Disposition']

    def test_export_filename_custom_range(self, client, accountant, branch):
        _login(client, 'acc_cd')
        resp = client.get('/journals/cd/export?mode=custom&date_from=2026-01-01&date_to=2026-03-31')
        assert '2026-01-01' in resp.headers['Content-Disposition']

    def test_export_contains_entry_data(self, client, accountant, branch, cash_acct, expense_acct, db_session):
        from openpyxl import load_workbook
        import io
        _disbursement_je(branch.id, date(2026, 6, 5), 'CD-2026-06-0001',
                         cash_acct, expense_acct, 8000)
        _login(client, 'acc_cd')
        resp = client.get('/journals/cd/export?mode=month&year=2026&month=6')
        wb = load_workbook(io.BytesIO(resp.data))
        ws = wb.active
        all_text = ' '.join(str(c.value) for row in ws.iter_rows() for c in row if c.value is not None)
        assert 'Cash Disbursements Journal' in all_text
        assert 'CD-2026-06-0001' in all_text

    def test_export_empty_period_still_returns_xlsx(self, client, accountant, branch):
        _login(client, 'acc_cd')
        resp = client.get('/journals/cd/export?mode=month&year=2020&month=1')
        assert resp.status_code == 200
        assert 'spreadsheetml' in resp.headers['Content-Type']
```

- [ ] **Step 2: Run tests — expect failures on export route**

```
pytest tests/integration/test_cd_journal_views.py -v
```

Expected: `test_export_*` tests fail with 302/404 (export route doesn't exist yet); view tests pass.

- [ ] **Step 3: Add `cd_journal_export()` to `views.py`**

Add after `cd_journal_print()` in `app/journals/views.py`:

```python
@journals_bp.route('/journals/cd/export')
@login_required
def cd_journal_export():
    branch_id = _branch_id()
    if not branch_id:
        flash('Please select a branch to export journal entries.', 'warning')
        return redirect(url_for('users.select_branch', next=request.url))

    from app.branches.models import Branch
    from app.settings import AppSettings
    from app.journals.cd_journal_data import build_cd_journal_xlsx
    period, matrix, cdv_map = _cd_journal_context(branch_id)

    branch = db.session.get(Branch, branch_id)
    branch_count = Branch.query.count()
    branch_name = branch.name if (branch and branch_count > 1) else None
    company_name = AppSettings.get_setting('company_name') or 'Company'

    if period['mode'] == 'month':
        filename = f"CD-Journal-{period['year']}-{period['month']:02d}.xlsx"
    else:
        filename = f"CD-Journal-{period['date_from'].isoformat()}_{period['date_to'].isoformat()}.xlsx"

    return build_cd_journal_xlsx(
        columns=matrix['columns'], rows=matrix['rows'], totals=matrix['totals'],
        period_label=period['label'], company_name=company_name,
        branch_name=branch_name, filename=filename,
        identity=lambda e: _cd_entry_identity(e, cdv_map))
```

- [ ] **Step 4: Run all tests — expect full pass**

```
pytest tests/unit/test_cd_journal_data.py tests/integration/test_cd_journal_views.py -v
```

Expected: 8 unit tests + 15 integration tests pass (23 total).

Also run the full journals suite to guard for regressions:

```
pytest -m journals -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/journals/views.py tests/integration/test_cd_journal_views.py
git commit -m "feat: cd journal export route + integration tests (23 tests pass)"
```

---

## Self-Review

**Spec coverage:**
- ✅ Columnar pivot mirroring AP Journal — `build_columnar_cd` in Task 1
- ✅ Column groups (debit/credit coloring) — `_group()` in Task 1
- ✅ Column ordering ap_applied → vat → expense → wht → cash — `_col_key()` in Task 1
- ✅ Period filter (month/year + custom range) — reuses `resolve_period` in Task 2
- ✅ AJAX filter with content swap — JavaScript in `cd_journal.html` Task 2
- ✅ Cancelled CDVs flagged in view — `cancelled_refs` in `_cd_journal_context` Task 2
- ✅ Print route and template — `cd_journal_print()` + `cd_journal_print.html` Task 2
- ✅ Nav link activated (no "Soon" badge) — `base.html` edit Task 2
- ✅ Excel export — `build_cd_journal_xlsx` Task 1, `cd_journal_export()` Task 3
- ✅ Integration tests — Task 3

**No placeholders, no TBDs.** All code is complete and runnable.

**Type/name consistency:** `cdv_map` passed as third return value from `_cd_journal_context` and used in both view and template. `build_columnar_cd` imported in views.py and from cd_journal_data.py in export route. `build_cd_journal_xlsx` lazy-imported in export route (same pattern as AP journal).
