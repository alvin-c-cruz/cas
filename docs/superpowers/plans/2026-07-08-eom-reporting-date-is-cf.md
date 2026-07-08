# EOM Reporting Date + Two-Column IS & CF — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Default all four financial statements to an end-of-current-month reporting date, and turn the Income Statement and Cash Flow into reporting-date-driven two-column (Current-Month + Year-to-Date) reports.

**Architecture:** Add one pure date util (`end_of_month`). Change the two date-param helpers in `app/reports/views.py` so as-of reports default to month-end and IS/CF derive both column ranges from a single `as_of`. Generate IS/CF twice (month range, YTD range) and merge into a two-column structure via new pure helpers in `app/reports/two_column.py`. Templates, Excel exports, and print views render the second column.

**Tech Stack:** Flask, SQLAlchemy, Jinja2, openpyxl, pytest. Python 3.13. Project venv at `C:/envs/erp-workspace/projects/cas/venv`.

**Spec:** `docs/superpowers/specs/2026-07-08-eom-reporting-date-is-cf-design.md`

## Global Constraints

- Run every command from `projects/cas/`. Use the venv python: `C:/envs/erp-workspace/projects/cas/venv/Scripts/python` (or `pytest` if the venv is active).
- The dev server does **not** hot-reload `.py` — restart before browser-testing view changes.
- SQLAlchemy 2.0 spellings only: `db.session.get(Model, id)` / `db.get_or_404(Model, id)`. Never `Model.query.get(...)`.
- PH time: derive "today" from `ph_now().date()`, never naive `date.today()`, in code you touch.
- Peso sign: literal `₱` (U+20B1) glyph in templates. No `&#8369;`.
- No hardcoded styling — reuse existing report CSS classes (`fs-section-header`, `fs-line-row`, `fs-subtotal-row`, `fs-grand-total-row`, `num-col`).
- No empty-state CTA buttons. No JS `confirm/alert/prompt`.
- Every write path already has audit coverage; this feature is read-only reporting — no audit changes.
- Do NOT change any report's figures/classification — only the default date and the two-column presentation. The YTD `net_income` for a given `as_of` must equal today's single-period result (Balance Sheet + Year-End close consume it).
- Frequent commits: one per task. Branch is `feat/eom-reporting-date-two-col-is-cf` (already created).

---

## File Structure

- `app/utils_helpers.py` — add `end_of_month` (pure); re-export via `app/utils/__init__.py`.
- `app/reports/views.py` — `_tb_params` EOM default; new `_stmt_params`; IS & CF views (page/excel/print) call generator twice + merge; drop `_is_params` usage.
- `app/reports/two_column.py` — **new**: `merge_is_two_column`, `merge_cf_two_column`, and shared `_union_by` helper.
- `app/reports/templates/reports/income_statement.html`, `income_statement_print.html` — second column + single-date picker.
- `app/reports/templates/reports/cash_flow.html`, `cash_flow_print.html` — second column + single-date picker.
- `app/reports/statement_export.py` — two-column `build_income_statement_xlsx`, `build_cash_flow_xlsx` (+ their `*_lines` used by print).
- Tests under `tests/unit/` and `tests/integration/`.

---

### Task 1: `end_of_month` date utility

**Files:**
- Modify: `app/utils_helpers.py` (add function)
- Modify: `app/utils/__init__.py` (re-export)
- Test: `tests/unit/test_date_utils.py` (create)

**Interfaces:**
- Produces: `end_of_month(d: date) -> date` — last calendar day of `d`'s month. Importable as `from app.utils import end_of_month`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_date_utils.py
from datetime import date
import pytest
from app.utils import end_of_month

pytestmark = [pytest.mark.unit]

def test_end_of_month_31_day_month():
    assert end_of_month(date(2026, 7, 8)) == date(2026, 7, 31)

def test_end_of_month_february_non_leap():
    assert end_of_month(date(2026, 2, 10)) == date(2026, 2, 28)

def test_end_of_month_february_leap():
    assert end_of_month(date(2028, 2, 10)) == date(2028, 2, 29)

def test_end_of_month_december():
    assert end_of_month(date(2026, 12, 1)) == date(2026, 12, 31)

def test_end_of_month_idempotent_on_month_end():
    assert end_of_month(date(2026, 7, 31)) == date(2026, 7, 31)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_date_utils.py -v`
Expected: FAIL — `ImportError: cannot import name 'end_of_month'`.

- [ ] **Step 3: Implement the util**

In `app/utils_helpers.py`, add near the top-level imports `import calendar` (if not present) and append:

```python
def end_of_month(d):
    """Return the last calendar day of d's month."""
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])
```

In `app/utils/__init__.py`, extend the import and `__all__`:

```python
from app.utils_helpers import PHT, ph_now, ph_datetime, utc_to_pht, format_ph_datetime, end_of_month

__all__ = ['PHT', 'ph_now', 'ph_datetime', 'utc_to_pht', 'format_ph_datetime', 'end_of_month']
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_date_utils.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add app/utils_helpers.py app/utils/__init__.py tests/unit/test_date_utils.py
git commit -m "feat(reports): add end_of_month date utility"
```

---

### Task 2: Trial Balance & Balance Sheet default to month-end

**Files:**
- Modify: `app/reports/views.py` — `_tb_params` (around line 513)
- Test: `tests/integration/test_balance_sheet_views.py` (add a test)

**Interfaces:**
- Consumes: `end_of_month` (Task 1), `ph_now`.
- Produces: `_tb_params()` unchanged signature `-> (as_of_date, branch_id)`; default `as_of` is now `end_of_month(ph_now().date())`.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_balance_sheet_views.py` (reuse its existing `_login`/`_select_branch` helpers; add imports if missing):

```python
from datetime import date
from app.utils import end_of_month, ph_now

def test_balance_sheet_defaults_to_month_end(client, admin_user):
    _login(client, admin_user)
    resp = client.get('/reports/balance-sheet')
    assert resp.status_code == 200
    expected = end_of_month(ph_now().date())
    body = resp.get_data(as_text=True)
    assert expected.strftime('%B %d, %Y') in body   # "As of July 31, 2026"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_balance_sheet_views.py::test_balance_sheet_defaults_to_month_end -v`
Expected: FAIL — page shows today's date, not month-end.

- [ ] **Step 3: Update `_tb_params`**

Ensure `from app.utils import ph_now, end_of_month` is imported at the top of `views.py` (the file already imports `ph_now`; add `end_of_month`). Replace `_tb_params`:

```python
def _tb_params():
    """Shared (as_of_date, branch_id) for Trial Balance & Balance Sheet routes.

    Defaults the reporting date to the end of the current month (PH time).
    """
    default = end_of_month(ph_now().date())
    as_of_str = request.args.get('as_of', default.isoformat())
    try:
        as_of_date = date.fromisoformat(as_of_str)
    except (ValueError, TypeError):
        as_of_date = default
    return as_of_date, session.get('selected_branch_id')
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integration/test_balance_sheet_views.py tests/integration/test_trial_balance_views.py -v`
Expected: PASS. If a pre-existing test hard-coded a today-default expectation, update that assertion to `end_of_month(ph_now().date())` (a stale-test fix, not a behavior regression).

- [ ] **Step 5: Commit**

```bash
git add app/reports/views.py tests/integration/test_balance_sheet_views.py
git commit -m "feat(reports): Trial Balance & Balance Sheet default to month-end"
```

---

### Task 3: `_stmt_params` — single reporting-date for IS/CF

**Files:**
- Modify: `app/reports/views.py` — add `_stmt_params`; keep `_is_params` untouched for now (removed in Task 6/9 once IS/CF migrate)
- Test: `tests/integration/test_income_statement_views.py` (add tests)

**Interfaces:**
- Consumes: `end_of_month`, `ph_now`, `date`.
- Produces: `_stmt_params() -> (as_of, mtd_start, ytd_start, branch_id)` where
  `as_of = end_of_month(ph_now().date())` by default (param `as_of`), `mtd_start = as_of.replace(day=1)`,
  `ytd_start = date(as_of.year, 1, 1)`. Legacy `?end_date=` is honored as `as_of`.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_income_statement_views.py`:

```python
from app.utils import end_of_month, ph_now
from app.reports.views import _stmt_params  # will exist after Step 3
```

(Direct unit call needs a request context; test via the view instead in Task 5. Here assert import + derivation with a request context:)

```python
def test_stmt_params_defaults_to_month_end(app):
    with app.test_request_context('/reports/income-statement'):
        as_of, mtd_start, ytd_start, _branch = _stmt_params()
    assert as_of == end_of_month(ph_now().date())
    assert mtd_start == as_of.replace(day=1)
    assert ytd_start == as_of.replace(month=1, day=1)

def test_stmt_params_explicit_as_of(app):
    with app.test_request_context('/reports/income-statement?as_of=2026-06-30'):
        as_of, mtd_start, ytd_start, _branch = _stmt_params()
    assert (as_of, mtd_start, ytd_start) == (date(2026, 6, 30), date(2026, 6, 1), date(2026, 1, 1))

def test_stmt_params_legacy_end_date_coerced(app):
    with app.test_request_context('/reports/income-statement?end_date=2026-05-31'):
        as_of, mtd_start, ytd_start, _branch = _stmt_params()
    assert (as_of, mtd_start) == (date(2026, 5, 31), date(2026, 5, 1))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_income_statement_views.py -k stmt_params -v`
Expected: FAIL — `ImportError: cannot import name '_stmt_params'`.

- [ ] **Step 3: Add `_stmt_params`**

In `app/reports/views.py`, directly after `_is_params`, add:

```python
def _stmt_params():
    """Single reporting-date parsing for Income Statement & Cash Flow.

    Returns (as_of, mtd_start, ytd_start, branch_id). Reporting date defaults to
    the end of the current month (PH time); param name 'as_of'. A legacy
    'end_date' param is accepted as the reporting date for back-compat.
    """
    default = end_of_month(ph_now().date())
    raw = request.args.get('as_of') or request.args.get('end_date') or default.isoformat()
    try:
        as_of = date.fromisoformat(raw)
    except (ValueError, TypeError):
        as_of = default
    mtd_start = as_of.replace(day=1)
    ytd_start = date(as_of.year, 1, 1)
    return as_of, mtd_start, ytd_start, session.get('selected_branch_id')
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_income_statement_views.py -k stmt_params -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add app/reports/views.py tests/integration/test_income_statement_views.py
git commit -m "feat(reports): add _stmt_params single reporting-date helper for IS/CF"
```

---

### Task 4: Income Statement two-column merge helper

**Files:**
- Create: `app/reports/two_column.py`
- Test: `tests/unit/test_two_column.py` (create)

**Interfaces:**
- Consumes: single-period IS dicts from `generate_income_statement` (shape:
  `{sections:[{key,label,sign,total,lines:[{code,name,account_id,total,children:[{code,name,account_id,amount}]}], subtotal_label?, subtotal?}], net_sales, gross_profit, operating_income, income_before_tax, net_income, period_start, period_end}`).
- Produces:
  - `_union_by(a_items, b_items, key, a_field, b_field) -> list[dict]` — order-preserving union of two lists of dicts by `key`, emitting each item once with both source values (missing side → `0.0`).
  - `merge_is_two_column(mtd: dict, ytd: dict) -> dict` — two-column IS. Each section gains
    `mtd_total`/`ytd_total` (and `mtd_subtotal`/`ytd_subtotal` when `subtotal_label` present); each
    line/child gains `mtd_amount`/`ytd_amount` (replacing `total`/`amount`); top-level summary keys
    (`net_sales`,`gross_profit`,`operating_income`,`income_before_tax`,`net_income`) become
    `{'mtd':float,'ytd':float}` pairs.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_two_column.py
import pytest
from app.reports.two_column import merge_is_two_column, _union_by

pytestmark = [pytest.mark.unit]

def _is(section_total, line_total, net):
    return {
        'period_start': None, 'period_end': None,
        'sections': [{
            'key': 'revenue', 'label': 'Sales', 'sign': 1, 'total': section_total,
            'lines': [{'code': '40001', 'name': 'Sales', 'account_id': 1,
                       'total': line_total, 'children': []}],
        }, {
            'key': 'income_tax', 'label': 'Income Tax Expense', 'sign': -1, 'total': 0.0,
            'lines': [], 'subtotal_label': 'Net Income', 'subtotal': net,
        }],
        'net_sales': section_total, 'gross_profit': section_total,
        'operating_income': net, 'income_before_tax': net, 'net_income': net,
    }

def test_merge_carries_both_column_totals():
    merged = merge_is_two_column(_is(100.0, 100.0, 60.0), _is(700.0, 700.0, 420.0))
    rev = merged['sections'][0]
    assert rev['mtd_total'] == 100.0 and rev['ytd_total'] == 700.0
    line = rev['lines'][0]
    assert line['mtd_amount'] == 100.0 and line['ytd_amount'] == 700.0

def test_merge_carries_subtotal_and_scalar_pairs():
    merged = merge_is_two_column(_is(100.0, 100.0, 60.0), _is(700.0, 700.0, 420.0))
    tax = merged['sections'][1]
    assert tax['mtd_subtotal'] == 60.0 and tax['ytd_subtotal'] == 420.0
    assert merged['net_income'] == {'mtd': 60.0, 'ytd': 420.0}

def test_merge_zero_fills_line_present_in_one_column_only():
    mtd = _is(0.0, 0.0, 0.0); mtd['sections'][0]['lines'] = []      # no line this month
    ytd = _is(700.0, 700.0, 420.0)                                   # line YTD only
    merged = merge_is_two_column(mtd, ytd)
    line = merged['sections'][0]['lines'][0]
    assert line['mtd_amount'] == 0.0 and line['ytd_amount'] == 700.0

def test_union_by_preserves_order_and_zero_fills():
    a = [{'code': 'x', 'total': 1.0}]
    b = [{'code': 'y', 'total': 2.0}]
    out = _union_by(a, b, key='code', a_field='total', b_field='total')
    assert [(o['code'], o['mtd'], o['ytd']) for o in out] == [('x', 1.0, 0.0), ('y', 0.0, 2.0)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_two_column.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.reports.two_column'`.

- [ ] **Step 3: Implement the merge module**

```python
# app/reports/two_column.py
"""Merge two single-period statement dicts into a two-column (MTD + YTD) shape.

Both inputs come from the same generator with the same section spec, so sections
align by index. Lines are unioned by account code (IS) or line name (CF); a value
present in only one column is zero-filled on the other.
"""


def _union_by(a_items, b_items, key, a_field, b_field):
    """Order-preserving union of two dict lists by `key`.

    Emits one row per distinct key (a's order first, then b-only keys), each as
    {**identity from whichever side has it, 'mtd': a_val, 'ytd': b_val}.
    """
    a_by = {i[key]: i for i in a_items}
    b_by = {i[key]: i for i in b_items}
    out, seen = [], set()
    for i in a_items:
        k = i[key]; seen.add(k)
        b = b_by.get(k)
        row = dict(i)
        row['mtd'] = i.get(a_field, 0.0)
        row['ytd'] = (b.get(b_field, 0.0) if b else 0.0)
        out.append(row)
    for i in b_items:
        k = i[key]
        if k in seen:
            continue
        row = dict(i)
        row['mtd'] = 0.0
        row['ytd'] = i.get(b_field, 0.0)
        out.append(row)
    return out


def _merge_children(a_children, b_children):
    rows = _union_by(a_children, b_children, key='code', a_field='amount', b_field='amount')
    for r in rows:
        r['mtd_amount'] = r.pop('mtd')
        r['ytd_amount'] = r.pop('ytd')
        r.pop('amount', None)
    return rows


def _merge_lines(a_lines, b_lines):
    a_by = {l['account_id']: l for l in a_lines}
    b_by = {l['account_id']: l for l in b_lines}
    order = list(a_by.keys()) + [k for k in b_by.keys() if k not in a_by]
    merged = []
    for aid in order:
        a = a_by.get(aid); b = b_by.get(aid)
        base = dict(a or b)
        base['mtd_amount'] = (a['total'] if a else 0.0)
        base['ytd_amount'] = (b['total'] if b else 0.0)
        base.pop('total', None)
        base['children'] = _merge_children((a or {}).get('children', []),
                                           (b or {}).get('children', []))
        merged.append(base)
    return merged


_IS_SCALARS = ('net_sales', 'gross_profit', 'operating_income', 'income_before_tax', 'net_income')


def merge_is_two_column(mtd, ytd):
    """Two-column Income Statement. See module docstring."""
    sections = []
    for sm, sy in zip(mtd['sections'], ytd['sections']):
        sec = {'key': sm['key'], 'label': sm['label'], 'sign': sm['sign'],
               'mtd_total': sm['total'], 'ytd_total': sy['total'],
               'lines': _merge_lines(sm['lines'], sy['lines'])}
        if sm.get('subtotal_label'):
            sec['subtotal_label'] = sm['subtotal_label']
            sec['mtd_subtotal'] = sm.get('subtotal', 0.0)
            sec['ytd_subtotal'] = sy.get('subtotal', 0.0)
        sections.append(sec)
    out = {'sections': sections,
           'mtd_start': mtd.get('period_start'), 'mtd_end': mtd.get('period_end'),
           'ytd_start': ytd.get('period_start'), 'as_of': ytd.get('period_end')}
    for k in _IS_SCALARS:
        out[k] = {'mtd': mtd.get(k, 0.0), 'ytd': ytd.get(k, 0.0)}
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_two_column.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add app/reports/two_column.py tests/unit/test_two_column.py
git commit -m "feat(reports): add Income Statement two-column merge helper"
```

---

### Task 5: Income Statement view + template render two columns

**Files:**
- Modify: `app/reports/views.py` — `income_statement()` (lines ~585-593)
- Modify: `app/reports/templates/reports/income_statement.html`
- Test: `tests/integration/test_income_statement_views.py`

**Interfaces:**
- Consumes: `_stmt_params` (Task 3), `merge_is_two_column` (Task 4), `generate_income_statement`.
- Produces: template context `income_statement` = two-column dict; `as_of`, `mtd_end`, `ytd_start` for headers.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_income_statement_views.py` (uses the file's `_login`/`_seed_pl`/`_select_branch` helpers):

```python
def test_income_statement_page_two_columns(client, admin_user, branch_manila):
    _seed_pl(branch_manila.id)          # revenue 100 / admin 40 -> net 60, dated today
    _login(client, admin_user); _select_branch(client, branch_manila.id)
    resp = client.get(f'/reports/income-statement?as_of={date.today().isoformat()}')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # both column headers present
    assert date.today().strftime('%b %Y') in body        # "Jul 2026" current-month header
    assert f'YTD {date.today().year}' in body
    # net income appears (both columns equal here since all activity is this month)
    assert '60.00' in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_income_statement_views.py::test_income_statement_page_two_columns -v`
Expected: FAIL — single-column template lacks `YTD <year>` header.

- [ ] **Step 3: Update the view**

Replace `income_statement()`:

```python
@reports_bp.route('/reports/income-statement')
@login_required
def income_statement():
    as_of, mtd_start, ytd_start, branch_id = _stmt_params()
    mtd = generate_income_statement(mtd_start, as_of, branch_id=branch_id)
    ytd = generate_income_statement(ytd_start, as_of, branch_id=branch_id)
    data = merge_is_two_column(mtd, ytd)
    return render_template('reports/income_statement.html',
                           income_statement=data, as_of=as_of,
                           mtd_start=mtd_start, ytd_start=ytd_start)
```

Add `from app.reports.two_column import merge_is_two_column` to the imports at the top of `views.py`.

- [ ] **Step 4: Update the template**

Edit `income_statement.html`. Key changes (mirror the existing structure for anything not shown):

1. Sub-header + action links use `as_of`:

```html
<div class="card-sub">As of {{ as_of.strftime('%B %d, %Y') }} — Current month vs. Year to date</div>
```
```html
<a href="{{ url_for('reports.income_statement_export_excel', as_of=as_of.isoformat()) }}" class="btn btn-secondary">📊 Excel</a>
<a href="{{ url_for('reports.income_statement_print', as_of=as_of.isoformat()) }}" target="_blank" class="btn btn-secondary">Print</a>
<button class="btn btn-secondary" onclick="showPeriodPicker()">📅 Change Date</button>
```

2. Add a two-column header row as the first `<tr>` in `<tbody>`:

```html
<tr class="fs-section-header">
    <td style="width:30px;"></td>
    <td></td>
    <td class="num-col" style="width:160px;">{{ as_of.strftime('%b %Y') }}</td>
    <td class="num-col" style="width:160px;">YTD {{ as_of.year }}</td>
</tr>
```

3. Section header row — two amount cells (mind the sign):

```html
<tr class="fs-section-header">
    <td style="width:30px;"></td>
    <td{% if sec.key in ['selling', 'admin'] %} style="padding-left:18px;"{% endif %}>{{ sec.label }}</td>
    <td class="num-col">{% if sec.sign == -1 %}(₱{{ '{:,.2f}'.format(sec.mtd_total) }}){% else %}₱{{ '{:,.2f}'.format(sec.mtd_total) }}{% endif %}</td>
    <td class="num-col">{% if sec.sign == -1 %}(₱{{ '{:,.2f}'.format(sec.ytd_total) }}){% else %}₱{{ '{:,.2f}'.format(sec.ytd_total) }}{% endif %}</td>
</tr>
```

4. Line row and child row — two amount cells; keep the drilldown data-attrs pointing at the YTD range (`data-start="{{ ytd_start.isoformat() }}" data-end="{{ as_of.isoformat() }}"`):

```html
<td class="num-col">₱{{ '{:,.2f}'.format(line.mtd_amount) }}</td>
<td class="num-col">₱{{ '{:,.2f}'.format(line.ytd_amount) }}</td>
```
```html
<td class="num-col">₱{{ '{:,.2f}'.format(child.mtd_amount) }}</td>
<td class="num-col">₱{{ '{:,.2f}'.format(child.ytd_amount) }}</td>
```

5. Subtotal row — two cells:

```html
<tr class="fs-subtotal-row">
    <td></td>
    <td style="color:var(--blue);">{{ sec.subtotal_label }}</td>
    <td class="num-col" style="color:var(--blue);">₱{{ '{:,.2f}'.format(sec.mtd_subtotal) }}</td>
    <td class="num-col" style="color:var(--blue);">₱{{ '{:,.2f}'.format(sec.ytd_subtotal) }}</td>
</tr>
```

6. Grand total — two cells using the scalar pairs (drop the net-margin `net_sales` division or compute per column; keep it simple — show both amounts, no margin):

```html
<tr class="fs-grand-total-row">
    <td></td>
    <td>NET INCOME (LOSS)</td>
    <td class="num-col" style="color:{% if income_statement.net_income.mtd >= 0 %}var(--green){% else %}var(--red){% endif %};">₱{{ '{:,.2f}'.format(income_statement.net_income.mtd) }}</td>
    <td class="num-col" style="color:{% if income_statement.net_income.ytd >= 0 %}var(--green){% else %}var(--red){% endif %};">₱{{ '{:,.2f}'.format(income_statement.net_income.ytd) }}</td>
</tr>
```

7. The "OPERATING EXPENSES" umbrella caption row: add a fourth empty `<td class="num-col">`.

8. Replace the Period Picker modal with a single reporting-date form:

```html
<div id="periodPicker" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:var(--backdrop);z-index:1000;align-items:center;justify-content:center;">
  <div style="background:var(--card);padding:30px;border-radius:8px;max-width:420px;width:90%;">
    <h3 style="margin-top:0;">Reporting Date</h3>
    <form action="{{ url_for('reports.income_statement') }}" method="get">
      <label for="as_of" style="display:block;margin-bottom:8px;font-weight:600;">As of (month-end):</label>
      <input type="date" id="as_of" name="as_of" value="{{ as_of.isoformat() }}"
             style="width:100%;padding:10px;border:1px solid var(--border);border-radius:4px;font-family:inherit;">
      <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:24px;">
        <button type="button" class="btn btn-secondary" onclick="hidePeriodPicker()">Cancel</button>
        <button type="submit" class="btn btn-primary">Generate Report</button>
      </div>
    </form>
  </div>
</div>
```

Delete the now-unused `setCurrentMonth/setLastMonth/setYTD/setLastYear` JS and the `start_date`/`end_date` inputs. Keep `showPeriodPicker`/`hidePeriodPicker` and the backdrop-click handler. Bump the `fs-drilldown.js?v=` query string (e.g. `?v=3`) since the template changed. Verify `fs-drilldown.js` reads `data-start`/`data-end` (unchanged names) — it does; no JS change needed.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/integration/test_income_statement_views.py -v`
Expected: PASS. Fix any stale single-column assertions in the file (update to the two-column headers / `net_income.ytd`).

- [ ] **Step 6: Commit**

```bash
git add app/reports/views.py app/reports/templates/reports/income_statement.html tests/integration/test_income_statement_views.py
git commit -m "feat(reports): Income Statement two-column reporting-date view"
```

---

### Task 6: Income Statement Excel export + print (two columns)

**Files:**
- Modify: `app/reports/views.py` — `income_statement_export_excel()` and `income_statement_print()`
- Modify: `app/reports/statement_export.py` — `build_income_statement_xlsx`, `income_statement_lines`
- Modify: `app/reports/templates/reports/income_statement_print.html`
- Test: `tests/unit/test_income_statement_export.py`

**Interfaces:**
- Consumes: two-column IS dict (Task 4), `_stmt_params`.
- Produces: `income_statement_lines(data)` returns rows carrying `mtd_amount`/`ytd_amount`; `build_income_statement_xlsx(stmt, as_of_label, company, branch_name, filename)` writes a `<Mon YYYY>` and `YTD <year>` amount column.

- [ ] **Step 1: Write the failing test**

Read `tests/unit/test_income_statement_export.py` and `app/reports/statement_export.py::income_statement_lines` first to match their current row shape. Add:

```python
def test_income_statement_lines_two_column():
    from app.reports.two_column import merge_is_two_column
    from app.reports.statement_export import income_statement_lines
    # build a minimal two-column dict (reuse the _is builder pattern from test_two_column)
    ...
    rows = income_statement_lines(merged)
    # every amount row exposes both columns
    assert all(('mtd_amount' in r and 'ytd_amount' in r) for r in rows if r.get('kind') == 'line')
```

(Match the assertion to the actual `income_statement_lines` row schema you read.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_income_statement_export.py -k two_column -v`
Expected: FAIL.

- [ ] **Step 3: Update export + views + print template**

- In `statement_export.py`: change `income_statement_lines` to read `mtd_amount`/`ytd_amount`/`mtd_total`/`ytd_total`/`mtd_subtotal`/`ytd_subtotal` and the `{'mtd','ytd'}` scalar pairs (instead of `amount`/`total`/`subtotal`). Update `build_income_statement_xlsx` to write two numeric columns with headers `stmt['as_of'].strftime('%b %Y')` and `f"YTD {stmt['as_of'].year}"`.
- In `views.py`, update both routes to the two-call + merge pattern and pass `as_of`:

```python
@reports_bp.route('/reports/income-statement/export/excel')
@login_required
def income_statement_export_excel():
    from app.reports.statement_export import build_income_statement_xlsx
    as_of, mtd_start, ytd_start, branch_id = _stmt_params()
    stmt = merge_is_two_column(
        generate_income_statement(mtd_start, as_of, branch_id=branch_id),
        generate_income_statement(ytd_start, as_of, branch_id=branch_id))
    company, branch_name = _bs_company_branch(branch_id)
    as_of_label = f'As of {as_of.strftime("%B %d, %Y")}'
    filename = f'Income_Statement_{as_of.isoformat()}.xlsx'
    return build_income_statement_xlsx(stmt, as_of_label, company, branch_name, filename)
```
```python
@reports_bp.route('/reports/income-statement/print')
@login_required
def income_statement_print():
    from app.reports.statement_export import income_statement_lines
    as_of, mtd_start, ytd_start, branch_id = _stmt_params()
    stmt = merge_is_two_column(
        generate_income_statement(mtd_start, as_of, branch_id=branch_id),
        generate_income_statement(ytd_start, as_of, branch_id=branch_id))
    company, branch_name = _bs_company_branch(branch_id)
    return render_template('reports/income_statement_print.html',
                           lines=income_statement_lines(stmt), as_of=as_of,
                           company=company, branch_name=branch_name)
```

- In `income_statement_print.html`: add the second amount column and a two-column header (`{{ as_of.strftime('%b %Y') }}` / `YTD {{ as_of.year }}`), reading `mtd_amount`/`ytd_amount` per line. Replace any `start_date`/`end_date` header text with `As of {{ as_of.strftime('%B %d, %Y') }}`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_income_statement_export.py tests/integration/test_income_statement_views.py -v`
Expected: PASS. Also open the running app and export/print once to eyeball alignment.

- [ ] **Step 5: Commit**

```bash
git add app/reports/views.py app/reports/statement_export.py app/reports/templates/reports/income_statement_print.html tests/unit/test_income_statement_export.py
git commit -m "feat(reports): Income Statement two-column Excel + print"
```

---

### Task 7: Cash Flow two-column merge helper

**Files:**
- Modify: `app/reports/two_column.py` — add `merge_cf_two_column`
- Test: `tests/unit/test_two_column.py`

**Interfaces:**
- Consumes: single-period CF dict from `generate_cash_flow` (shape:
  `{operating:{net_income,depreciation,working_capital:[{name,amount}],total}, investing:{lines:[{name,amount}],total}, financing:{lines:[{name,amount}],total}, net_change, cash_begin, cash_end, period_start, period_end, method, is_reconciled, difference}`).
- Produces: `merge_cf_two_column(mtd, ytd) -> dict` where every scalar (`net_income`, `depreciation`,
  activity `total`s, `net_change`, `cash_begin`, `cash_end`) becomes `{'mtd','ytd'}`, and each activity
  line list is unioned by `name` with `mtd_amount`/`ytd_amount`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_two_column.py`:

```python
from app.reports.two_column import merge_cf_two_column

def _cf(op_total, wc_amt, net_change, cash_begin, cash_end):
    return {
        'period_start': None, 'period_end': None, 'method': 'indirect',
        'operating': {'net_income': op_total, 'depreciation': 0.0,
                      'working_capital': [{'name': 'Increase in AR', 'amount': wc_amt}],
                      'total': op_total},
        'investing': {'lines': [], 'total': 0.0},
        'financing': {'lines': [], 'total': 0.0},
        'net_change': net_change, 'cash_begin': cash_begin, 'cash_end': cash_end,
        'is_reconciled': True, 'difference': 0.0,
    }

def test_merge_cf_pairs_scalars_and_unions_lines():
    merged = merge_cf_two_column(_cf(60.0, -10.0, 60.0, 0.0, 60.0),
                                 _cf(420.0, -70.0, 420.0, 0.0, 420.0))
    assert merged['net_change'] == {'mtd': 60.0, 'ytd': 420.0}
    assert merged['cash_end'] == {'mtd': 60.0, 'ytd': 420.0}
    assert merged['operating']['total'] == {'mtd': 60.0, 'ytd': 420.0}
    wc = merged['operating']['working_capital'][0]
    assert wc['name'] == 'Increase in AR' and wc['mtd_amount'] == -10.0 and wc['ytd_amount'] == -70.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_two_column.py -k cf -v`
Expected: FAIL — `cannot import name 'merge_cf_two_column'`.

- [ ] **Step 3: Implement `merge_cf_two_column`**

Append to `app/reports/two_column.py`:

```python
def _pair(a, b):
    return {'mtd': a, 'ytd': b}


def _merge_named_lines(a_lines, b_lines):
    rows = _union_by(a_lines, b_lines, key='name', a_field='amount', b_field='amount')
    for r in rows:
        r['mtd_amount'] = r.pop('mtd')
        r['ytd_amount'] = r.pop('ytd')
        r.pop('amount', None)
    return rows


def merge_cf_two_column(mtd, ytd):
    """Two-column Statement of Cash Flows. See module docstring."""
    return {
        'method': mtd.get('method', 'indirect'),
        'mtd_start': mtd.get('period_start'), 'mtd_end': mtd.get('period_end'),
        'ytd_start': ytd.get('period_start'), 'as_of': ytd.get('period_end'),
        'operating': {
            'net_income': _pair(mtd['operating']['net_income'], ytd['operating']['net_income']),
            'depreciation': _pair(mtd['operating']['depreciation'], ytd['operating']['depreciation']),
            'working_capital': _merge_named_lines(mtd['operating']['working_capital'],
                                                  ytd['operating']['working_capital']),
            'total': _pair(mtd['operating']['total'], ytd['operating']['total']),
        },
        'investing': {
            'lines': _merge_named_lines(mtd['investing']['lines'], ytd['investing']['lines']),
            'total': _pair(mtd['investing']['total'], ytd['investing']['total']),
        },
        'financing': {
            'lines': _merge_named_lines(mtd['financing']['lines'], ytd['financing']['lines']),
            'total': _pair(mtd['financing']['total'], ytd['financing']['total']),
        },
        'net_change': _pair(mtd['net_change'], ytd['net_change']),
        'cash_begin': _pair(mtd['cash_begin'], ytd['cash_begin']),
        'cash_end': _pair(mtd['cash_end'], ytd['cash_end']),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_two_column.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add app/reports/two_column.py tests/unit/test_two_column.py
git commit -m "feat(reports): add Cash Flow two-column merge helper"
```

---

### Task 8: Cash Flow view + template (two columns)

**Files:**
- Modify: `app/reports/views.py` — `cash_flow()` (lines ~686-692)
- Modify: `app/reports/templates/reports/cash_flow.html`
- Test: `tests/integration/test_cash_flow_views.py`

**Interfaces:**
- Consumes: `_stmt_params`, `merge_cf_two_column`, `generate_cash_flow`.
- Produces: template context `cash_flow` = two-column dict; `as_of`, `mtd_start`, `ytd_start`.

- [ ] **Step 1: Write the failing test**

Read `tests/integration/test_cash_flow_views.py` for its seed/login helpers, then add:

```python
def test_cash_flow_page_two_columns(client, admin_user, branch_manila):
    # seed a cash-affecting posted JE (see existing helpers in this file)
    ...
    _login(client, admin_user); _select_branch(client, branch_manila.id)
    resp = client.get(f'/reports/cash-flow?as_of={date.today().isoformat()}')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert date.today().strftime('%b %Y') in body
    assert f'YTD {date.today().year}' in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_cash_flow_views.py::test_cash_flow_page_two_columns -v`
Expected: FAIL.

- [ ] **Step 3: Update the view**

```python
@reports_bp.route('/reports/cash-flow')
@login_required
def cash_flow():
    as_of, mtd_start, ytd_start, branch_id = _stmt_params()
    data = merge_cf_two_column(
        generate_cash_flow(mtd_start, as_of, branch_id=branch_id),
        generate_cash_flow(ytd_start, as_of, branch_id=branch_id))
    return render_template('reports/cash_flow.html', cash_flow=data, as_of=as_of,
                           mtd_start=mtd_start, ytd_start=ytd_start)
```

Add `from app.reports.two_column import merge_cf_two_column` to the imports (or extend the existing two_column import line).

- [ ] **Step 4: Update the template**

Edit `cash_flow.html`: add a `<Mon YYYY>` / `YTD <year>` two-column header; render every amount from the `{'mtd','ytd'}` pairs and `mtd_amount`/`ytd_amount` line fields; replace the start/end period picker with the single `as_of` reporting-date form (copy the modal from Task 5 Step 4.8, pointing its `action` at `url_for('reports.cash_flow')`); update the Excel/Print links to pass `as_of=as_of.isoformat()`; update the sub-header to `As of {{ as_of.strftime('%B %d, %Y') }}`. Mirror the report's existing operating/investing/financing row structure, adding the second amount `<td class="num-col">` to each row.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/integration/test_cash_flow_views.py -v`
Expected: PASS. Fix any stale single-column assertions.

- [ ] **Step 6: Commit**

```bash
git add app/reports/views.py app/reports/templates/reports/cash_flow.html tests/integration/test_cash_flow_views.py
git commit -m "feat(reports): Cash Flow two-column reporting-date view"
```

---

### Task 9: Cash Flow Excel export + print + retire `_is_params`

**Files:**
- Modify: `app/reports/views.py` — `cash_flow_export_excel()`, `cash_flow_print()`; delete `_is_params`
- Modify: `app/reports/statement_export.py` — `build_cash_flow_xlsx`, `cash_flow_lines`
- Modify: `app/reports/templates/reports/cash_flow_print.html`
- Test: `tests/unit/test_cash_flow_export.py`

**Interfaces:**
- Consumes: two-column CF dict (Task 7), `_stmt_params`.
- Produces: `cash_flow_lines`/`build_cash_flow_xlsx` emit two amount columns headed `<Mon YYYY>` / `YTD <year>`.

- [ ] **Step 1: Write the failing test**

Read `tests/unit/test_cash_flow_export.py` + `cash_flow_lines` first; add a two-column assertion mirroring Task 6 Step 1.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_cash_flow_export.py -k two_column -v`
Expected: FAIL.

- [ ] **Step 3: Update export, views, print, and delete `_is_params`**

- Update `cash_flow_lines` + `build_cash_flow_xlsx` in `statement_export.py` for the two-column pairs (headers from `cf['as_of']`).
- Update both CF routes to the two-call + merge pattern, passing `as_of` (mirror Task 6 Step 3).
- Update `cash_flow_print.html` with the second amount column + `As of` header.
- Grep confirms `_is_params` now has zero callers (`grep -rn "_is_params" app/`); delete its definition.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_cash_flow_export.py tests/integration/test_cash_flow_views.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/reports/views.py app/reports/statement_export.py app/reports/templates/reports/cash_flow_print.html tests/unit/test_cash_flow_export.py
git commit -m "feat(reports): Cash Flow two-column Excel + print; retire _is_params"
```

---

### Task 10: Ripple — cross-links + full regression

**Files:**
- Modify: any template linking to IS/CF with `start_date`/`end_date` (dashboard, report index)
- Verify: full report suite

- [ ] **Step 1: Find stale links**

Run: `grep -rnE "income-statement|cash-flow|income_statement|cash_flow" app/**/templates app/templates | grep -E "start_date|end_date"`
Expected: a short list (report index / dashboard quick-links). If none, note it and skip to Step 3.

- [ ] **Step 2: Update links**

Change each `income_statement`/`cash_flow` `url_for(...)` that passes `start_date=`/`end_date=` to pass `as_of=` (or nothing — the EOM default applies). Bump any `?v=` on edited templates' shared assets if applicable.

- [ ] **Step 3: Run the full report test surface**

Run:
```bash
pytest tests/unit/test_date_utils.py tests/unit/test_two_column.py \
       tests/unit/test_income_statement_export.py tests/unit/test_cash_flow_export.py \
       tests/integration/test_income_statement_views.py tests/integration/test_cash_flow_views.py \
       tests/integration/test_balance_sheet_views.py tests/integration/test_trial_balance_views.py \
       tests/integration/test_year_end_close.py -v
```
Expected: all PASS. `test_year_end_close.py` proves the YTD `net_income` consumer is unaffected.

- [ ] **Step 4: Manual smoke (running server)**

Restart the dev server. Visit `/reports/income-statement`, `/reports/cash-flow`, `/reports/balance-sheet`, `/reports/trial-balance` with no params → each defaults to month-end; IS/CF show two columns. Change the reporting date to a prior month-end and confirm both columns recompute. Export Excel + Print for IS and CF.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore(reports): update IS/CF cross-links to as_of; regression pass"
```

---

## Self-Review

- **Spec coverage:** `end_of_month` (T1); EOM default for TB/BS (T2) and IS/CF (T3); two-column IS merge (T4) + view/template (T5) + export/print (T6); two-column CF merge (T7) + view/template (T8) + export/print (T9); `as_of` param unification + legacy `end_date` coercion (T3); ripple links + `_is_params` removal (T9/T10); consumer-safety via `test_year_end_close` (T10). All spec sections mapped.
- **Placeholder scan:** Tasks 6 and 9 Step 1 intentionally say "read the current row shape first" because `income_statement_lines`/`cash_flow_lines`/the xlsx builders and CF print template were not read during planning; the implementer must match their exact schema. This is a deliberate read-then-adapt instruction, not a code placeholder — the data contract (which keys to consume) is fully specified.
- **Type consistency:** Merge outputs use consistent names throughout — sections carry `mtd_total`/`ytd_total`/`mtd_subtotal`/`ytd_subtotal`; lines/children carry `mtd_amount`/`ytd_amount`; scalars are `{'mtd','ytd'}` pairs; `as_of` is the merged dict's reporting date. Templates/exports in T5/T6/T8/T9 consume exactly these.
