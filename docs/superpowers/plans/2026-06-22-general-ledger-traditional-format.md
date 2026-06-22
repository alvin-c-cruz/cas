# General Ledger — Traditional T-Ledger Format Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-present the existing General Ledger as the traditional two-sided ("T") ledger book — debits left, credits right, totals per side, Balance b/f / c/f, Particulars naming the contra-account — across screen, print, and exports.

**Architecture:** The generator gains one new piece of data (`contra` per line, resolved in one batched query). The screen template, print template, and the export flattener are rebuilt as the bilateral T-ledger. The query logic, branch scoping, access gate, source-doc resolver, routes, and filters are unchanged. No model changes, no migration.

**Tech Stack:** Flask, SQLAlchemy, SQLite, Jinja2, openpyxl (`app/utils/export.py`), Choices.js, pytest.

## Global Constraints

- **No new models / migrations** — read-only over existing data.
- **Money in templates:** literal `₱` (U+20B1) glyph, never `&#8369;`.
- **No hardcoded styling** in the screen template — design tokens / CSS variables (`--text-2`, `--border`, `--bg`, `--card`, `--blue`, `--radius`). The standalone print template may use inline CSS (it can't inherit `style.css`).
- **Responsive** — the two-sided table is wrapped in `overflow-x:auto` so narrow screens scroll rather than break the layout.
- **No JS popups** (`confirm`/`alert`/`prompt`); `window.print()` is allowed.
- **TDD** — failing test first; commit after each green task.
- **Unchanged contracts:** `generate_general_ledger(start, end, branch_id, account_id=None)` keeps every existing return key and adds only `line['contra']`. `running_balance` stays in the data (unused by presentations; keeps Task-1 math tests valid). `_attach_source_links`, `_gl_params`, the four routes, the filter form, and the access registry are untouched.
- **Contra display:** the contra-account **name** only (the Source column already carries the document number). One distinct opposite account → its name; two or more → the literal string `"Various"`; none → `""`.
- **Settings access:** `from app.settings import AppSettings`; read with `AppSettings.get_setting('company_name', '')` (also `company_address`, `company_tin`). Branch: `from app.branches.models import Branch`.

---

### Task 1: Contra-account resolution in the generator

**Files:**
- Modify: `app/reports/financial.py` (`generate_general_ledger` — add a batched contra pass before `return`)
- Test: `tests/unit/test_general_ledger_contra.py` (create)

**Interfaces:**
- Consumes: existing `generate_general_ledger`, `Account`, `JournalEntry`, `JournalEntryLine`, `db` (all already imported in `financial.py`).
- Produces: every line dict in the return value gains `'contra': str` — the opposite-side account name, `"Various"` for multiple distinct, `""` for none.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_general_ledger_contra.py`:

```python
from datetime import date
from decimal import Decimal
import pytest

from app import db
from app.accounts.models import Account
from app.branches.models import Branch
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.reports.financial import generate_general_ledger

pytestmark = [pytest.mark.unit]


def _branch():
    b = Branch(name='Main', code='MAIN')
    db.session.add(b)
    db.session.commit()
    return b


def _acct(code, name, atype='Asset', normal='Debit'):
    a = Account(code=code, name=name, account_type=atype, normal_balance=normal, is_active=True)
    db.session.add(a)
    db.session.commit()
    return a


def _entry(branch_id, when, number, lines):
    """lines: list of (account, debit, credit)."""
    je = JournalEntry(entry_number=number, entry_date=when, description='d', reference=number,
                      entry_type='adjustment', branch_id=branch_id, status='posted',
                      is_balanced=True, total_debit=Decimal('0'), total_credit=Decimal('0'))
    db.session.add(je)
    db.session.flush()
    n = 1
    for acct, dr, cr in lines:
        db.session.add(JournalEntryLine(entry_id=je.id, line_number=n, account_id=acct.id,
                                        debit_amount=Decimal(str(dr)), credit_amount=Decimal(str(cr)),
                                        description=f'{number} l{n}'))
        n += 1
    db.session.commit()
    return je


def _line_for(gl, code):
    sec = next(a for a in gl['accounts'] if a['code'] == code)
    return sec['lines'][0]


def test_two_line_entry_contra_is_other_account_name(db_session):
    b = _branch()
    cash = _acct('1001', 'Cash')
    sales = _acct('4001', 'Sales Revenue', 'Income', 'Credit')
    _entry(b.id, date(2026, 6, 5), 'JE-1', [(cash, 100, 0), (sales, 0, 100)])
    gl = generate_general_ledger(date(2026, 6, 1), date(2026, 6, 30), b.id)
    assert _line_for(gl, '1001')['contra'] == 'Sales Revenue'
    assert _line_for(gl, '4001')['contra'] == 'Cash'


def test_multi_contra_is_various_single_opposite_is_named(db_session):
    b = _branch()
    expense = _acct('5001', 'Office Supplies', 'Expense', 'Debit')
    ap = _acct('2001', 'Accounts Payable', 'Liability', 'Credit')
    wht = _acct('2002', 'WHT Payable', 'Liability', 'Credit')
    # Dr Expense 100 / Cr AP 88 / Cr WHT 12
    _entry(b.id, date(2026, 6, 7), 'JE-2', [(expense, 100, 0), (ap, 0, 88), (wht, 0, 12)])
    gl = generate_general_ledger(date(2026, 6, 1), date(2026, 6, 30), b.id)
    assert _line_for(gl, '5001')['contra'] == 'Various'      # opposite = AP + WHT
    assert _line_for(gl, '2001')['contra'] == 'Office Supplies'  # opposite = Expense only
    assert _line_for(gl, '2002')['contra'] == 'Office Supplies'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_general_ledger_contra.py -v`
Expected: FAIL — `KeyError: 'contra'`.

- [ ] **Step 3: Implement the batched contra pass**

In `app/reports/financial.py`, in `generate_general_ledger`, replace the final `return {...}` block with a contra-resolution pass followed by the same return:

```python
    # Resolve the contra-account (opposite side of each line's own JE) in one batched query.
    entry_ids = {l['entry_id'] for a in result_accounts for l in a['lines']}
    if entry_ids:
        sibling_rows = db.session.query(
            JournalEntryLine.entry_id,
            JournalEntryLine.account_id,
            Account.name,
            JournalEntryLine.debit_amount,
        ).join(Account, JournalEntryLine.account_id == Account.id).filter(
            JournalEntryLine.entry_id.in_(entry_ids)
        ).all()
        by_entry = {}
        for eid, acct_id, name, dr in sibling_rows:
            by_entry.setdefault(eid, []).append((acct_id, name, dr > 0))
        for a in result_accounts:
            for l in a['lines']:
                near_is_debit = l['debit'] > 0
                opposite = {acct_id: name
                            for (acct_id, name, is_debit) in by_entry.get(l['entry_id'], [])
                            if is_debit != near_is_debit}
                if len(opposite) == 1:
                    l['contra'] = next(iter(opposite.values()))
                elif len(opposite) > 1:
                    l['contra'] = 'Various'
                else:
                    l['contra'] = ''

    return {
        'start_date': start_date,
        'end_date': end_date,
        'accounts': result_accounts,
        'grand_total_debit': float(grand_debit),
        'grand_total_credit': float(grand_credit),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_general_ledger_contra.py -v`
Expected: 2 passed. Also run the existing generator suite to confirm no regression:
Run: `pytest tests/unit/test_general_ledger.py -v` → still all green.

- [ ] **Step 5: Commit**

```bash
git add app/reports/financial.py tests/unit/test_general_ledger_contra.py
git commit -m "feat(reports): resolve contra-account per general-ledger line"
```

---

### Task 2: Screen template — two-sided T-ledger

**Files:**
- Modify: `app/reports/templates/reports/general_ledger.html` (replace the per-account table)
- Modify: `tests/integration/test_general_ledger_views.py` (update label-dependent assertions; add a T-ledger render test)

**Interfaces:**
- Consumes: `line.contra` (Task 1); existing `acct.opening_balance/total_debit/total_credit/closing_balance`, `acct.lines[].{entry_id,entry_number,entry_date,source,debit,credit}`, `balance_dr_cr` macro.
- Produces: no new endpoints; the screen renders the bilateral layout.

- [ ] **Step 1: Update the broken assertion + add the render test (write first, expect fail)**

In `tests/integration/test_general_ledger_views.py`:

(a) `test_general_ledger_account_filter` currently asserts `resp.data.count(b'Opening balance') == 1`. The label is going away. Change that line to:
```python
    assert resp.data.count(b'Balance b/f') == 1
```

(b) Add a new test asserting the T-ledger renders with contra + the new wording:
```python
def test_general_ledger_renders_t_ledger(client, db_session, main_branch, admin_user,
                                         cash_account, revenue_account):
    _post_je(main_branch.id, cash_account, revenue_account, date.today(), 'JE-TL')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/general-ledger')
    assert resp.status_code == 200
    body = resp.data
    assert b'Balance b/f' in body
    assert b'Total Debit' in body
    assert b'Total Credit' in body
    assert b'Balance c/f' in body
    # Particulars shows the contra-account name (cash debit's contra = revenue account name)
    assert revenue_account.name.encode() in body
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/integration/test_general_ledger_views.py -k "account_filter or renders_t_ledger" -v`
Expected: `renders_t_ledger` FAILs (old template lacks "Balance b/f"/"Total Debit"); `account_filter` FAILs on the new marker until the template changes.

- [ ] **Step 3: Replace the per-account table in `general_ledger.html`**

Replace the block from `{% if ledger.accounts %}` through its matching `{% endif %}` (the account loop + empty state, currently lines ~52–110) with the two-sided layout below. The macro, filter form, header actions, and the Choices.js script stay as they are.

```html
        {% if ledger.accounts %}
        {% for acct in ledger.accounts %}
        {% set debit_lines = acct.lines | selectattr('debit') | list %}
        {% set credit_lines = acct.lines | selectattr('credit') | list %}
        {% set rowcount = [debit_lines|length, credit_lines|length] | max %}
        <div style="margin-bottom:24px;border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;">
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;background:var(--bg);padding:10px 14px;font-weight:600;">
                <span>{{ acct.code }} &mdash; {{ acct.name }}</span>
                <span style="color:var(--text-2);">Balance b/f: {{ balance_dr_cr(acct.opening_balance) }}</span>
            </div>
            <div style="overflow-x:auto;">
            <table class="table" style="margin:0;font-size:0.9rem;">
                <thead>
                    <tr style="background:var(--bg);">
                        <th>Date</th><th>JE #</th><th>Source</th><th>Particulars</th><th style="text-align:right;">Debit</th>
                        <th style="border-left:2px solid var(--border);">Date</th><th>JE #</th><th>Source</th><th>Particulars</th><th style="text-align:right;">Credit</th>
                    </tr>
                </thead>
                <tbody>
                    {% for i in range(rowcount) %}
                    <tr>
                        {% set d = debit_lines[i] if i < debit_lines|length else None %}
                        {% if d %}
                        <td>{{ d.entry_date.strftime('%Y-%m-%d') }}</td>
                        <td><a href="{{ url_for('journal_entries.view', id=d.entry_id) }}" style="color:var(--blue)">{{ d.entry_number }}</a></td>
                        <td>{% if d.source.url %}<a href="{{ d.source.url }}" style="color:var(--blue)">{{ d.source.label }}</a>{% else %}{{ d.source.label }}{% endif %}</td>
                        <td>{{ d.contra }}</td>
                        <td style="text-align:right;">₱{{ "{:,.2f}".format(d.debit) }}</td>
                        {% else %}<td></td><td></td><td></td><td></td><td></td>{% endif %}
                        {% set c = credit_lines[i] if i < credit_lines|length else None %}
                        {% if c %}
                        <td style="border-left:2px solid var(--border);">{{ c.entry_date.strftime('%Y-%m-%d') }}</td>
                        <td><a href="{{ url_for('journal_entries.view', id=c.entry_id) }}" style="color:var(--blue)">{{ c.entry_number }}</a></td>
                        <td>{% if c.source.url %}<a href="{{ c.source.url }}" style="color:var(--blue)">{{ c.source.label }}</a>{% else %}{{ c.source.label }}{% endif %}</td>
                        <td>{{ c.contra }}</td>
                        <td style="text-align:right;">₱{{ "{:,.2f}".format(c.credit) }}</td>
                        {% else %}<td style="border-left:2px solid var(--border);"></td><td></td><td></td><td></td><td></td>{% endif %}
                    </tr>
                    {% endfor %}
                </tbody>
                <tfoot style="border-top:2px solid var(--border);font-weight:600;">
                    <tr style="background:var(--bg);">
                        <td colspan="4">Total Debit</td>
                        <td style="text-align:right;">₱{{ "{:,.2f}".format(acct.total_debit) }}</td>
                        <td colspan="4" style="border-left:2px solid var(--border);">Total Credit</td>
                        <td style="text-align:right;">₱{{ "{:,.2f}".format(acct.total_credit) }}</td>
                    </tr>
                    <tr style="background:var(--bg);">
                        <td colspan="10" style="text-align:right;">Balance c/f: {{ balance_dr_cr(acct.closing_balance) }}</td>
                    </tr>
                </tfoot>
            </table>
            </div>
        </div>
        {% endfor %}
        {% else %}
        <div class="empty-state">
            <p>No ledger activity for {{ start_date.strftime('%b %d, %Y') }} &ndash; {{ end_date.strftime('%b %d, %Y') }}.</p>
        </div>
        {% endif %}
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/integration/test_general_ledger_views.py -v`
Expected: all pass (the updated `account_filter`, the new `renders_t_ledger`, and the rest).

- [ ] **Step 5: Commit**

```bash
git add app/reports/templates/reports/general_ledger.html tests/integration/test_general_ledger_views.py
git commit -m "feat(reports): two-sided T-ledger screen layout with contra-account particulars"
```

---

### Task 3: Print template — T-ledger + BIR-book header

**Files:**
- Modify: `app/reports/views.py` (`general_ledger_print` — pass company + branch context)
- Modify: `app/reports/templates/reports/general_ledger_print.html` (rebuild as T-ledger + header)
- Modify: `tests/integration/test_general_ledger_views.py` (print test asserts company header + T-ledger)

**Interfaces:**
- Consumes: `line.contra`; `AppSettings.get_setting`; `Branch`; existing ledger dict.
- Produces: the print view passes `company` (dict with `name`/`address`/`tin`) and `branch_name` to the template.

- [ ] **Step 1: Update the print test (write first)**

In `tests/integration/test_general_ledger_views.py`, replace `test_general_ledger_print_renders` body so it seeds a company name and asserts the header + T-ledger wording. First inspect `app/settings.py` for the setter (e.g. `AppSettings.set_setting(key, value)` or constructing a row) and use the real mechanism:

```python
def test_general_ledger_print_renders(client, db_session, main_branch, admin_user,
                                      cash_account, revenue_account):
    from app.settings import AppSettings
    AppSettings.set_setting('company_name', 'ACME Trading Corp')   # use the real setter; see app/settings.py
    _post_je(main_branch.id, cash_account, revenue_account, date.today(), 'JE-P1')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/general-ledger/print')
    assert resp.status_code == 200
    body = resp.data
    assert b'General Ledger' in body
    assert b'ACME Trading Corp' in body          # BIR-book company header
    assert b'Total Debit' in body                 # T-ledger footer
```

> If `app/settings.py` has no `set_setting`, create the setting row directly the way other tests/seeds do (inspect `AppSettings` model fields) — the point is a persisted `company_name`.

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/integration/test_general_ledger_views.py::test_general_ledger_print_renders -v`
Expected: FAIL (company name not in output; "Total Debit" not in old running-balance print template).

- [ ] **Step 3: Pass company + branch context from the view**

In `app/reports/views.py`, replace the `general_ledger_print` view with:

```python
@reports_bp.route('/reports/general-ledger/print')
@login_required
def general_ledger_print():
    from app.settings import AppSettings
    from app.branches.models import Branch
    start_date, end_date, account_id, branch_id = _gl_params()
    ledger = generate_general_ledger(start_date, end_date, branch_id, account_id=account_id)
    _attach_source_links(ledger, branch_id)
    company = {
        'name': AppSettings.get_setting('company_name', ''),
        'address': AppSettings.get_setting('company_address', ''),
        'tin': AppSettings.get_setting('company_tin', ''),
    }
    branch = Branch.query.get(branch_id) if branch_id else None
    return render_template('reports/general_ledger_print.html',
                           ledger=ledger, start_date=start_date, end_date=end_date,
                           company=company, branch_name=branch.name if branch else '')
```

- [ ] **Step 4: Rebuild `general_ledger_print.html`**

Replace the whole file with the T-ledger + BIR header (standalone doc; inline CSS is allowed here; literal `₱`):

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>General Ledger</title>
    <style>
        body { font-family: Arial, sans-serif; font-size: 12px; color: #000; margin: 24px; }
        h1 { font-size: 18px; margin: 0; }
        .company { font-size: 14px; font-weight: bold; }
        .meta { color: #333; margin: 2px 0 14px 0; }
        .acct { page-break-inside: avoid; margin-bottom: 18px; }
        .acct + .acct { page-break-before: always; }
        .acct-head { display:flex; justify-content:space-between; font-weight: bold; border-bottom: 1px solid #000; padding-bottom: 4px; margin-bottom: 6px; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 3px 6px; border-bottom: 1px solid #ccc; text-align: left; }
        .num { text-align: right; }
        .mid { border-left: 2px solid #000; }
        tfoot td { font-weight: bold; border-top: 1px solid #000; }
    </style>
</head>
<body onload="window.print()">
    {% if company.name %}<div class="company">{{ company.name }}</div>{% endif %}
    <div class="meta">
        {% if company.tin %}TIN: {{ company.tin }} &nbsp; {% endif %}
        {% if company.address %}{{ company.address }}<br>{% endif %}
        {% if branch_name %}Branch: {{ branch_name }} &nbsp; {% endif %}
        General Ledger &nbsp; | &nbsp; {{ start_date.strftime('%B %d, %Y') }} &ndash; {{ end_date.strftime('%B %d, %Y') }}
    </div>
    {% macro bal(value) %}{% if value >= 0 %}₱{{ "{:,.2f}".format(value) }} Dr{% else %}₱{{ "{:,.2f}".format(-value) }} Cr{% endif %}{% endmacro %}
    {% for acct in ledger.accounts %}
    {% set debit_lines = acct.lines | selectattr('debit') | list %}
    {% set credit_lines = acct.lines | selectattr('credit') | list %}
    {% set rowcount = [debit_lines|length, credit_lines|length] | max %}
    <div class="acct">
        <div class="acct-head"><span>{{ acct.code }} &mdash; {{ acct.name }}</span><span>Balance b/f: {{ bal(acct.opening_balance) }}</span></div>
        <table>
            <thead>
                <tr>
                    <th>Date</th><th>JE #</th><th>Source</th><th>Particulars</th><th class="num">Debit</th>
                    <th class="mid">Date</th><th>JE #</th><th>Source</th><th>Particulars</th><th class="num">Credit</th>
                </tr>
            </thead>
            <tbody>
                {% for i in range(rowcount) %}
                <tr>
                    {% set d = debit_lines[i] if i < debit_lines|length else None %}
                    {% if d %}
                    <td>{{ d.entry_date.strftime('%Y-%m-%d') }}</td><td>{{ d.entry_number }}</td><td>{{ d.source.label }}</td><td>{{ d.contra }}</td><td class="num">₱{{ "{:,.2f}".format(d.debit) }}</td>
                    {% else %}<td></td><td></td><td></td><td></td><td></td>{% endif %}
                    {% set c = credit_lines[i] if i < credit_lines|length else None %}
                    {% if c %}
                    <td class="mid">{{ c.entry_date.strftime('%Y-%m-%d') }}</td><td>{{ c.entry_number }}</td><td>{{ c.source.label }}</td><td>{{ c.contra }}</td><td class="num">₱{{ "{:,.2f}".format(c.credit) }}</td>
                    {% else %}<td class="mid"></td><td></td><td></td><td></td><td></td>{% endif %}
                </tr>
                {% endfor %}
            </tbody>
            <tfoot>
                <tr>
                    <td colspan="4">Total Debit</td><td class="num">₱{{ "{:,.2f}".format(acct.total_debit) }}</td>
                    <td class="mid" colspan="4">Total Credit</td><td class="num">₱{{ "{:,.2f}".format(acct.total_credit) }}</td>
                </tr>
                <tr><td colspan="10" class="num">Balance c/f: {{ bal(acct.closing_balance) }}</td></tr>
            </tfoot>
        </table>
    </div>
    {% endfor %}
</body>
</html>
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/integration/test_general_ledger_views.py::test_general_ledger_print_renders -v`
Expected: PASS. Then the whole file: `pytest tests/integration/test_general_ledger_views.py -v` → all green.

- [ ] **Step 6: Commit**

```bash
git add app/reports/views.py app/reports/templates/reports/general_ledger_print.html tests/integration/test_general_ledger_views.py
git commit -m "feat(reports): T-ledger print layout with BIR company/branch/period header"
```

---

### Task 4: Exports — T-shape Excel/CSV

**Files:**
- Modify: `app/reports/views.py` (`_flatten_ledger`, `_GL_COLUMNS`, `_GL_HEADERS`)
- Modify: `tests/integration/test_general_ledger_views.py` (update the CSV-content test)

**Interfaces:**
- Consumes: `line.contra`; the ledger dict.
- Produces: `_flatten_ledger` returns 10-column paired rows; `_GL_COLUMNS`/`_GL_HEADERS` describe them.

- [ ] **Step 1: Update the CSV-content test (write first)**

In `tests/integration/test_general_ledger_views.py`, `test_general_ledger_csv_export_contains_data` asserts on the old labels. Replace its assertions so they match the T-shape — assert the account code, a `Balance b/f` marker, and a `Total Debit` marker appear, plus the known cash debit amount string `export_to_csv` emits (check `app/utils/export.py format_value`: a `float` like `100.0` is written via `str(...)`; if the generator stores the amount as a float `100.0`, assert `b'100.0'`; verify against `format_value` and adjust the exact string if needed):

```python
def test_general_ledger_csv_export_contains_data(client, db_session, main_branch, admin_user,
                                                 cash_account, revenue_account):
    _post_je(main_branch.id, cash_account, revenue_account, date.today(), 'JE-CSV')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/general-ledger/export/csv')
    assert resp.status_code == 200
    body = resp.data
    assert cash_account.code.encode() in body          # account header row
    assert b'Balance b/f' in body
    assert b'Total Debit' in body
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/integration/test_general_ledger_views.py::test_general_ledger_csv_export_contains_data -v`
Expected: FAIL (old flatten emits "Opening balance"/"Closing balance", not "Balance b/f"/"Total Debit").

- [ ] **Step 3: Reshape `_flatten_ledger` + columns/headers**

In `app/reports/views.py`, replace `_flatten_ledger`, `_GL_COLUMNS`, and `_GL_HEADERS` with:

```python
def _flatten_ledger(ledger):
    """Flatten the book into two-sided T-ledger export rows: per account a header row,
    paired debit/credit rows, a totals row, and a closing-balance row."""
    def _bal(v):
        return f"₱{abs(v):,.2f} {'Dr' if v >= 0 else 'Cr'}"

    rows = []
    for acct in ledger['accounts']:
        debit_lines = [l for l in acct['lines'] if l['debit']]
        credit_lines = [l for l in acct['lines'] if l['credit']]
        rows.append({'d_date': f"{acct['code']} - {acct['name']}", 'd_je': '', 'd_source': '',
                     'd_particulars': '', 'debit': '', 'c_date': 'Balance b/f', 'c_je': '',
                     'c_source': '', 'c_particulars': '', 'credit': _bal(acct['opening_balance'])})
        for i in range(max(len(debit_lines), len(credit_lines))):
            d = debit_lines[i] if i < len(debit_lines) else None
            c = credit_lines[i] if i < len(credit_lines) else None
            rows.append({
                'd_date': d['entry_date'] if d else '', 'd_je': d['entry_number'] if d else '',
                'd_source': d['source']['label'] if d else '', 'd_particulars': d['contra'] if d else '',
                'debit': d['debit'] if d else '',
                'c_date': c['entry_date'] if c else '', 'c_je': c['entry_number'] if c else '',
                'c_source': c['source']['label'] if c else '', 'c_particulars': c['contra'] if c else '',
                'credit': c['credit'] if c else '',
            })
        rows.append({'d_date': 'Total Debit', 'd_je': '', 'd_source': '', 'd_particulars': '',
                     'debit': acct['total_debit'], 'c_date': 'Total Credit', 'c_je': '',
                     'c_source': '', 'c_particulars': '', 'credit': acct['total_credit']})
        rows.append({'d_date': '', 'd_je': '', 'd_source': '', 'd_particulars': '', 'debit': '',
                     'c_date': 'Balance c/f', 'c_je': '', 'c_source': '', 'c_particulars': '',
                     'credit': _bal(acct['closing_balance'])})
    return rows


_GL_COLUMNS = ['d_date', 'd_je', 'd_source', 'd_particulars', 'debit',
               'c_date', 'c_je', 'c_source', 'c_particulars', 'credit']
_GL_HEADERS = ['Date', 'JE #', 'Source', 'Particulars', 'Debit',
               'Date', 'JE #', 'Source', 'Particulars', 'Credit']
```

> The `export_to_excel`/`export_to_csv` calls in the three routes are unchanged — they already pass `_GL_COLUMNS`/`_GL_HEADERS`. The `Balance b/f`/`c/f` markers land in the `c_date`/`credit` cells, which is why the test asserts `b'Balance b/f'` and `b'Total Debit'`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/integration/test_general_ledger_views.py -v`
Expected: all pass (the updated CSV-content test, the Excel/print tests, and the rest).

- [ ] **Step 5: Commit**

```bash
git add app/reports/views.py tests/integration/test_general_ledger_views.py
git commit -m "feat(reports): two-sided T-ledger Excel/CSV export"
```

---

## Self-Review

**Spec coverage:**
- Contra-account resolution (batched, name / "Various" / "") → Task 1. ✅
- Two-sided screen T-ledger (b/f header, side split, totals, c/f, overflow-x, contra particulars) → Task 2. ✅
- Print T-ledger + BIR company/TIN/address/branch/period header → Task 3. ✅
- Exports mirror the T-shape (10 columns) → Task 4. ✅
- `running_balance` retained but unused; generator keys otherwise unchanged → Global Constraints + Task 1 (additive only). ✅
- Label-change ripple (account_filter, csv-content, print tests) → Tasks 2/3/4. ✅
- Unchanged: query/scoping/access/source-resolver/routes/filters → not touched by any task. ✅

**Placeholder scan:** No TBD/TODO. Two real-codebase verification notes (the `AppSettings` setter mechanism in Task 3 Step 1; the exact CSV float string in Task 4 Step 1) are checks against existing code, not placeholders — surrounding code is complete.

**Type consistency:** `line['contra']` (str) defined in Task 1 is consumed identically in Tasks 2/3/4. `selectattr('debit')`/`selectattr('credit')` split used in both templates and mirrored by the `if l['debit']` / `if l['credit']` split in `_flatten_ledger`. `balance_dr_cr` (screen) and `bal` (print) and `_bal` (export) all encode the same debit-positive → Dr/Cr convention. `_GL_COLUMNS` keys exactly match the dict keys `_flatten_ledger` emits.
