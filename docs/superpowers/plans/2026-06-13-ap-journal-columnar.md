# Columnar Accounts Payable Journal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `/journals/ap` into a GAAP-compliant columnar special journal (one column per GL account, credits in parentheses, monthly filter, viewable/Excel/print), sourcing "Particulars" from a now-required Notes field.

**Architecture:** A read-only pivot of existing `JournalEntryLine` rows. A new pure-data module `app/journals/ap_journal_data.py` resolves the period and builds the column/row/total matrix; the view stays thin; the template renders the matrix and an Excel export route reuses the same builder. Posting logic is untouched. Notes becomes `NOT NULL` (DB) + `DataRequired` (form).

**Tech Stack:** Flask, SQLAlchemy, Flask-Migrate/Alembic (SQLite batch mode), WTForms, openpyxl, pytest.

**Spec:** `docs/superpowers/specs/2026-06-13-ap-journal-columnar-design.md`

---

## Conventions used in this codebase (read first)

- PHT time only: `from app.utils import ph_now`. Never `datetime.now()`.
- Testing DB builds tables from models via `db.create_all()` (not migrations), so a model-level `nullable=False` is what test assertions exercise. The Alembic migration is for the real SQLite DB.
- `JournalEntry.lines` is `lazy='dynamic'` → iterate with `entry.lines.all()`.
- Signed amount convention for the journal: `value = debit_amount - credit_amount`. Debits positive; credits negative → rendered `(x.xx)`.
- Account groups: AP = code `20101`; WHT = code `20301`; Input VAT = the set of `VATCategory.input_vat_account` ids; everything else = "other".
- Existing fixtures live in `tests/conftest.py` (`client`, `db_session`, `accountant_user`, `main_branch`, etc.).

---

## File Structure

| File | Responsibility |
|---|---|
| `app/journals/ap_journal_data.py` (NEW) | Pure data layer: `resolve_period()`, `build_columnar()`, `build_ap_journal_xlsx()`. No Flask request access. |
| `app/journals/views.py` (MODIFY) | `ap_journal()` thin wrapper; new `ap_journal_export()` route. |
| `app/journals/templates/journals/ap_journal.html` (MODIFY) | Month/custom filter UI, columnar table, print CSS, Print + Excel buttons. |
| `app/purchase_bills/models.py` (MODIFY) | `notes` → `nullable=False`. |
| `app/purchase_bills/forms.py` (MODIFY) | `notes` → `DataRequired`. |
| `migrations/versions/<new>.py` (NEW) | Backfill + `batch_alter_table` set `notes` NOT NULL. |
| `tests/unit/test_ap_journal_data.py` (NEW) | Unit tests for period + matrix builders. |
| `tests/integration/test_ap_journal_columnar.py` (NEW) | View + export route tests. |
| `tests/unit/test_purchase_bill_notes_required.py` (NEW) | Model + form notes-required tests. |

---

## Task 1: Period resolution helper

**Files:**
- Create: `app/journals/ap_journal_data.py`
- Test: `tests/unit/test_ap_journal_data.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_ap_journal_data.py
from datetime import date
from app.journals.ap_journal_data import resolve_period


def test_resolve_period_defaults_to_given_month():
    p = resolve_period({}, today=date(2026, 6, 13))
    assert p['mode'] == 'month'
    assert p['date_from'] == date(2026, 6, 1)
    assert p['date_to'] == date(2026, 6, 30)
    assert p['label'] == 'For the month of June 2026'


def test_resolve_period_explicit_month():
    p = resolve_period({'mode': 'month', 'year': '2026', 'month': '2'}, today=date(2026, 6, 13))
    assert p['date_from'] == date(2026, 2, 1)
    assert p['date_to'] == date(2026, 2, 28)  # 2026 not a leap year
    assert p['label'] == 'For the month of February 2026'


def test_resolve_period_custom_range():
    p = resolve_period(
        {'mode': 'custom', 'date_from': '2026-01-15', 'date_to': '2026-03-10'},
        today=date(2026, 6, 13),
    )
    assert p['mode'] == 'custom'
    assert p['date_from'] == date(2026, 1, 15)
    assert p['date_to'] == date(2026, 3, 10)
    assert p['label'] == 'From January 15, 2026 to March 10, 2026'


def test_resolve_period_custom_with_bad_dates_falls_back_to_month():
    p = resolve_period({'mode': 'custom', 'date_from': 'bad', 'date_to': ''}, today=date(2026, 6, 13))
    assert p['mode'] == 'month'
    assert p['date_from'] == date(2026, 6, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_ap_journal_data.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.journals.ap_journal_data'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/journals/ap_journal_data.py
"""Pure data layer for the columnar Accounts Payable Journal.

No Flask request access here — callers pass plain dicts/values so these
functions are unit-testable in isolation.
"""
import calendar
from datetime import date, datetime


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
        if df and dt:
            return {
                'mode': 'custom',
                'year': df.year,
                'month': df.month,
                'date_from': df,
                'date_to': dt,
                'label': f"From {df.strftime('%B %d, %Y')} to {dt.strftime('%B %d, %Y')}",
            }
        # bad/missing custom dates → fall through to month default

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_ap_journal_data.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add app/journals/ap_journal_data.py tests/unit/test_ap_journal_data.py
git commit -m "feat: add AP journal period-resolution helper"
```

---

## Task 2: Columnar matrix builder

**Files:**
- Modify: `app/journals/ap_journal_data.py`
- Test: `tests/integration/test_ap_journal_columnar.py` (uses DB for real JournalEntry/lines)

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_ap_journal_columnar.py
from decimal import Decimal
from datetime import date
import pytest

from app import db
from app.accounts.models import Account
from app.branches.models import Branch
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.journals.ap_journal_data import build_columnar


def _acct(code, name, atype, normal):
    a = Account.query.filter_by(code=code).first()
    if not a:
        a = Account(code=code, name=name, account_type=atype,
                    normal_balance=normal, is_active=True)
        db.session.add(a)
        db.session.commit()
    return a


def _entry(branch_id, status, entry_date, number, lines):
    """lines: list of (account, debit, credit)."""
    je = JournalEntry(entry_number=number, entry_date=entry_date,
                      description='x', reference=number, entry_type='purchase',
                      branch_id=branch_id, status=status, is_balanced=True,
                      total_debit=Decimal('0'), total_credit=Decimal('0'))
    db.session.add(je)
    db.session.flush()
    n = 1
    for acct, dr, cr in lines:
        db.session.add(JournalEntryLine(
            entry_id=je.id, line_number=n, account_id=acct.id,
            debit_amount=Decimal(str(dr)), credit_amount=Decimal(str(cr))))
        n += 1
    db.session.commit()
    return je


def test_build_columnar_posted_pivot_and_balance(db_session):
    branch = Branch(name='Main', code='MAIN'); db.session.add(branch); db.session.commit()
    ap = _acct('20101', 'Accounts Payable - Trade', 'Liability', 'credit')
    wt = _acct('20301', 'WHT Payable - Expanded', 'Liability', 'credit')
    vat = _acct('10610', 'Input VAT', 'Asset', 'debit')
    rent = _acct('60400', 'Rent Expense', 'Expense', 'debit')

    # Bill: Dr Rent 10,000 + Dr Input VAT 1,200 ; Cr WHT 200 + Cr AP 11,000
    je = _entry(branch.id, 'posted', date(2026, 6, 1), 'JE-1',
                [(rent, 10000, 0), (vat, 1200, 0), (wt, 0, 200), (ap, 0, 11000)])

    matrix = build_columnar(
        posted_entries=[je], draft_entries=[],
        ap_account_id=ap.id, wt_account_id=wt.id, input_vat_account_ids={vat.id})

    codes = [c['code'] for c in matrix['columns']]
    assert codes == ['20101', '20301', '10610', '60400']  # AP, WHT, VAT, other
    row = matrix['rows'][0]
    assert row['is_draft'] is False
    assert row['cells'][ap.id] == Decimal('-11000')   # credit → negative
    assert row['cells'][rent.id] == Decimal('10000')
    assert matrix['totals'][ap.id] == Decimal('-11000')
    assert matrix['grand_total'] == Decimal('0')
    assert matrix['balanced'] is True


def test_build_columnar_draft_excluded_from_totals_and_columns(db_session):
    branch = Branch(name='B2', code='B2'); db.session.add(branch); db.session.commit()
    ap = _acct('20101', 'Accounts Payable - Trade', 'Liability', 'credit')
    rent = _acct('60400', 'Rent Expense', 'Expense', 'debit')
    util = _acct('60500', 'Utilities Expense', 'Expense', 'debit')

    posted = _entry(branch.id, 'posted', date(2026, 6, 2), 'JE-P',
                    [(rent, 5000, 0), (ap, 0, 5000)])
    draft = _entry(branch.id, 'draft', date(2026, 6, 3), 'JE-D',
                   [(util, 999, 0), (ap, 0, 999)])

    matrix = build_columnar([posted], [draft], ap.id, None, set())

    codes = [c['code'] for c in matrix['columns']]
    assert '60500' not in codes               # draft-only account makes no column
    assert matrix['totals'].get(rent.id) == Decimal('5000')
    # draft row present, flagged, no cells
    draft_rows = [r for r in matrix['rows'] if r['is_draft']]
    assert len(draft_rows) == 1
    assert draft_rows[0]['cells'] == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_ap_journal_columnar.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_columnar'`

- [ ] **Step 3: Write minimal implementation**

Append to `app/journals/ap_journal_data.py`:

```python
from decimal import Decimal


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_ap_journal_columnar.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add app/journals/ap_journal_data.py tests/integration/test_ap_journal_columnar.py
git commit -m "feat: add AP journal columnar matrix builder"
```

---

## Task 3: Excel workbook builder

**Files:**
- Modify: `app/journals/ap_journal_data.py`
- Test: `tests/unit/test_ap_journal_data.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_ap_journal_data.py
from decimal import Decimal
from openpyxl import load_workbook
import io
from app.journals.ap_journal_data import build_ap_journal_xlsx


def _fake_entry(date_str, number, invoice, vendor, notes):
    class E: pass
    from datetime import datetime
    e = E()
    e.entry_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    e.reference = number
    e._invoice = invoice
    e._vendor = vendor
    e._notes = notes
    return e


def test_build_ap_journal_xlsx_has_headers_and_total_row():
    columns = [
        {'account_id': 1, 'code': '20101', 'name': 'Accounts Payable - Trade', 'group': 'ap'},
        {'account_id': 2, 'code': '60400', 'name': 'Rent Expense', 'group': 'other'},
    ]
    rows = [{
        'entry': _fake_entry('2026-06-01', 'AP-2026-06-0001', 'SI-1', 'Vendor A', 'Rent'),
        'cells': {1: Decimal('-5000'), 2: Decimal('5000')},
        'is_draft': False,
    }]
    totals = {1: Decimal('-5000'), 2: Decimal('5000')}
    resp = build_ap_journal_xlsx(
        columns=columns, rows=rows, totals=totals,
        period_label='For the month of June 2026',
        company_name='ABC Company', branch_name='Main Branch',
        filename='AP-Journal-2026-06.xlsx',
        identity=lambda e: (e.reference, e._invoice, e._vendor, e._notes))
    assert resp.headers['Content-Type'].startswith('application/vnd.openxmlformats')
    assert 'AP-Journal-2026-06.xlsx' in resp.headers['Content-Disposition']

    wb = load_workbook(io.BytesIO(resp.get_data()))
    ws = wb.active
    all_text = ' '.join(str(c.value) for row in ws.iter_rows() for c in row if c.value is not None)
    assert 'Accounts Payable Journal' in all_text
    assert 'Accounts Payable - Trade' in all_text
    assert 'Rent Expense' in all_text
    assert 'TOTAL' in all_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_ap_journal_data.py::test_build_ap_journal_xlsx_has_headers_and_total_row -v`
Expected: FAIL — `ImportError: cannot import name 'build_ap_journal_xlsx'`

- [ ] **Step 3: Write minimal implementation**

Append to `app/journals/ap_journal_data.py`:

```python
import io
from flask import make_response
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment


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
    resp.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return resp
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_ap_journal_data.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add app/journals/ap_journal_data.py tests/unit/test_ap_journal_data.py
git commit -m "feat: add AP journal Excel workbook builder"
```

---

## Task 4: Rewrite the ap_journal view + add export route

**Files:**
- Modify: `app/journals/views.py`
- Test: `tests/integration/test_ap_journal_columnar.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/integration/test_ap_journal_columnar.py
from app.users.models import User


def _login(client, db_session, branch):
    u = User(username='acc', email='acc@t.com', full_name='Acc', role='accountant', is_active=True)
    u.set_password('pass'); u.branches.append(branch)
    db.session.add(u); db.session.commit()
    client.post('/login', data={'username': 'acc', 'password': 'pass'}, follow_redirects=True)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id


def test_ap_journal_view_renders_account_columns(client, db_session):
    branch = Branch(name='Main', code='MAIN'); db.session.add(branch); db.session.commit()
    ap = _acct('20101', 'Accounts Payable - Trade', 'Liability', 'credit')
    rent = _acct('60400', 'Rent Expense', 'Expense', 'debit')
    _entry(branch.id, 'posted', date(2026, 6, 1), 'AP-2026-06-0001',
           [(rent, 5000, 0), (ap, 0, 5000)])
    _login(client, db_session, branch)

    res = client.get('/journals/ap?mode=month&year=2026&month=6')
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert 'Rent Expense' in body
    assert 'Accounts Payable - Trade' in body
    assert 'For the month of June 2026' in body


def test_ap_journal_export_returns_xlsx(client, db_session):
    branch = Branch(name='Main', code='MAIN'); db.session.add(branch); db.session.commit()
    ap = _acct('20101', 'Accounts Payable - Trade', 'Liability', 'credit')
    rent = _acct('60400', 'Rent Expense', 'Expense', 'debit')
    _entry(branch.id, 'posted', date(2026, 6, 1), 'AP-2026-06-0001',
           [(rent, 5000, 0), (ap, 0, 5000)])
    _login(client, db_session, branch)

    res = client.get('/journals/ap/export?mode=month&year=2026&month=6')
    assert res.status_code == 200
    assert res.headers['Content-Type'].startswith('application/vnd.openxmlformats')
    assert 'AP-Journal-2026-06.xlsx' in res.headers['Content-Disposition']
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_ap_journal_columnar.py -k "view_renders or export_returns" -v`
Expected: FAIL — export route 404; view body lacks account columns (old template).

- [ ] **Step 3: Write minimal implementation**

Replace the `ap_journal()` function in `app/journals/views.py` (lines 37–64) and add an export route. First update imports at the top of the file:

```python
"""Journals — filtered list views over JournalEntry for each journal type."""
from flask import Blueprint, render_template, redirect, url_for, request, session, flash
from flask_login import login_required
from app import db
from app.journal_entries.models import JournalEntry
from app.utils import ph_now
from app.journals.ap_journal_data import resolve_period, build_columnar, build_ap_journal_xlsx
from datetime import datetime
```

> Do NOT `selectinload(JournalEntry.lines)` — `lines` is `lazy='dynamic'` and SQLAlchemy raises if you eager-load a dynamic relationship. `build_columnar` calls `entry.lines.all()` per entry; for a single month's volume the per-entry queries are acceptable.

Then replace `ap_journal()` and add `_ap_journal_context()` + `ap_journal_export()`:

```python
def _gl_account_ids():
    """Return (ap_id, wt_id, input_vat_ids) for column grouping."""
    from app.accounts.models import Account
    from app.vat_categories.models import VATCategory
    ap = Account.query.filter_by(code='20101').first()
    wt = Account.query.filter_by(code='20301').first()
    vat_ids = {c.input_vat_account.id for c in VATCategory.query.all() if c.input_vat_account}
    return (ap.id if ap else None, wt.id if wt else None, vat_ids)


def _ap_journal_context(branch_id):
    """Build everything the columnar AP journal needs for a branch + period."""
    period = resolve_period(request.args, today=ph_now().date())

    entries = JournalEntry.query.filter(
        JournalEntry.entry_type == 'purchase',
        JournalEntry.branch_id == branch_id,
        JournalEntry.entry_date >= period['date_from'],
        JournalEntry.entry_date <= period['date_to'],
    ).order_by(JournalEntry.entry_date).all()
    posted = [e for e in entries if e.status == 'posted']
    drafts = [e for e in entries if e.status == 'draft']

    ap_id, wt_id, vat_ids = _gl_account_ids()
    matrix = build_columnar(posted, drafts, ap_id, wt_id, vat_ids)

    from app.purchase_bills.models import PurchaseBill
    refs = [e.reference for e in entries if e.reference]
    bills = PurchaseBill.query.filter(PurchaseBill.bill_number.in_(refs)).all() if refs else []
    bill_map = {b.bill_number: b for b in bills}
    return period, matrix, bill_map


def _entry_identity(entry, bill_map):
    """(no, invoice_no, vendor, particulars) for the left identifier columns."""
    bill = bill_map.get(entry.reference)
    return (
        entry.reference or '—',
        (bill.vendor_invoice_number if bill else '') or '',
        (bill.vendor_name if bill else '') or '—',
        (bill.notes if bill else '') or '',
    )


@journals_bp.route('/journals/ap')
@login_required
def ap_journal():
    branch_id = _branch_id()
    if not branch_id:
        flash('Please select a branch to view journal entries.', 'warning')
        return redirect(url_for('users.select_branch', next=request.url))

    period, matrix, bill_map = _ap_journal_context(branch_id)
    return render_template('journals/ap_journal.html',
                           period=period, matrix=matrix, bill_map=bill_map)


@journals_bp.route('/journals/ap/export')
@login_required
def ap_journal_export():
    branch_id = _branch_id()
    if not branch_id:
        flash('Please select a branch to export journal entries.', 'warning')
        return redirect(url_for('users.select_branch', next=request.url))

    from app.branches.models import Branch
    from app.company_settings.models import CompanySettings
    period, matrix, bill_map = _ap_journal_context(branch_id)

    branch = db.session.get(Branch, branch_id)
    branch_name = branch.name if branch else 'All Branches'
    settings = CompanySettings.query.first()
    company_name = settings.company_name if settings and settings.company_name else 'Company'

    if period['mode'] == 'month':
        filename = f"AP-Journal-{period['year']}-{period['month']:02d}.xlsx"
    else:
        filename = f"AP-Journal-{period['date_from'].isoformat()}_{period['date_to'].isoformat()}.xlsx"

    return build_ap_journal_xlsx(
        columns=matrix['columns'], rows=matrix['rows'], totals=matrix['totals'],
        period_label=period['label'], company_name=company_name,
        branch_name=branch_name, filename=filename,
        identity=lambda e: _entry_identity(e, bill_map))
```

> NOTE: confirm `CompanySettings` model path/attribute names. If `app.company_settings.models.CompanySettings` or `company_name` differs, adjust the two lines that read it; the rest is independent. Grep: `grep -rn "class CompanySettings" app/` and `grep -rn "company_name" app/company_settings/`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_ap_journal_columnar.py -v`
Expected: PASS (all). The view test needs the new template (Task 5) to render columns; if it fails only on the body-content asserts, proceed to Task 5 then re-run. The export test should pass now.

- [ ] **Step 5: Commit**

```bash
git add app/journals/views.py tests/integration/test_ap_journal_columnar.py
git commit -m "feat: columnar AP journal view + Excel export route"
```

---

## Task 5: Columnar template with month/custom filter, print CSS, buttons

**Files:**
- Modify: `app/journals/templates/journals/ap_journal.html` (full replace)

- [ ] **Step 1: Write the failing test**

(Already covered by `test_ap_journal_view_renders_account_columns` and a new draft-indicator test.)

```python
# append to tests/integration/test_ap_journal_columnar.py
def test_ap_journal_view_shows_draft_indicator(client, db_session):
    branch = Branch(name='Main', code='MAIN'); db.session.add(branch); db.session.commit()
    ap = _acct('20101', 'Accounts Payable - Trade', 'Liability', 'credit')
    rent = _acct('60400', 'Rent Expense', 'Expense', 'debit')
    _entry(branch.id, 'draft', date(2026, 6, 5), 'AP-2026-06-0009',
           [(rent, 700, 0), (ap, 0, 700)])
    _login(client, db_session, branch)
    res = client.get('/journals/ap?mode=month&year=2026&month=6')
    body = res.get_data(as_text=True)
    assert 'Draft' in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_ap_journal_columnar.py::test_ap_journal_view_shows_draft_indicator -v`
Expected: FAIL — old template renders nothing matching the new structure.

- [ ] **Step 3: Write minimal implementation**

Replace the entire contents of `app/journals/templates/journals/ap_journal.html` with:

```html
{% extends "base.html" %}
{% block title %}Accounts Payable Journal{% endblock %}
{% block page_title %}Accounts Payable Journal{% endblock %}

{% block extra_css %}
<style>
.ap-jrnl-toolbar { display:flex; gap:16px; align-items:flex-end; flex-wrap:wrap;
    padding:20px; background:var(--surface-2, #f8fafc); border-bottom:1px solid var(--border, #e2e8f0); }
.ap-jrnl-field label { display:block; font-size:12px; font-weight:600; color:var(--text-2,#64748b);
    margin-bottom:6px; text-transform:uppercase; }
.ap-jrnl-table { width:100%; border-collapse:collapse; font-size:12px; white-space:nowrap; }
.ap-jrnl-table th, .ap-jrnl-table td { padding:6px 8px; border-bottom:1px solid var(--border,#e2e8f0); }
.ap-jrnl-table th { text-align:left; border-bottom:2px solid var(--text-1,#334155); }
.ap-jrnl-num { text-align:right; font-family:var(--mono, monospace); }
.ap-jrnl-total td { border-top:2px solid var(--text-1,#334155); font-weight:700; }
.ap-jrnl-head--credit { background:#fef2f2; }
.ap-jrnl-head--debit { background:#eff6ff; }
.ap-jrnl-draft-badge { font-size:10px; font-weight:600; color:#c2410c; background:#fff7ed;
    border:1px solid #fed7aa; padding:1px 6px; border-radius:8px; text-transform:uppercase; }
.ap-jrnl-scroll { overflow-x:auto; }
.ap-jrnl-meta { padding:8px 20px 0; }
.ap-jrnl-meta h3 { margin:0; font-size:14px; }
.ap-jrnl-meta p { margin:2px 0 0; font-size:12px; color:var(--text-2,#64748b); }
@media print {
    .sidebar, .topbar, .ap-jrnl-toolbar, .ap-jrnl-actions { display:none !important; }
    .main-content { margin-left:0 !important; }
    @page { size: landscape; }
    .ap-jrnl-table { font-size:9px; }
}
</style>
{% endblock %}

{% block content %}
<div class="card">
    <div class="card-header">
        <div class="ap-jrnl-actions" style="display:flex; gap:8px; justify-content:flex-end;">
            <button onclick="window.print()" class="btn btn-secondary btn-sm">🖨 Print</button>
            <a href="{{ url_for('journals.ap_journal_export', **request.args) }}" class="btn btn-primary btn-sm">⬇ Excel</a>
        </div>
    </div>

    <form method="GET" action="{{ url_for('journals.ap_journal') }}" class="ap-jrnl-toolbar" id="apFilter">
        <input type="hidden" name="mode" id="apMode" value="{{ period.mode }}">
        <div class="ap-jrnl-field" id="monthFields" {% if period.mode == 'custom' %}style="display:none"{% endif %}>
            <label>Month</label>
            <select name="month" class="form-control form-control-sm">
                {% for m in range(1, 13) %}
                <option value="{{ m }}" {% if m == period.month %}selected{% endif %}>
                    {{ ['January','February','March','April','May','June','July','August','September','October','November','December'][m-1] }}
                </option>
                {% endfor %}
            </select>
        </div>
        <div class="ap-jrnl-field" id="yearField" {% if period.mode == 'custom' %}style="display:none"{% endif %}>
            <label>Year</label>
            <input type="number" name="year" value="{{ period.year }}" class="form-control form-control-sm" style="width:100px;">
        </div>
        <div class="ap-jrnl-field" id="fromField" {% if period.mode != 'custom' %}style="display:none"{% endif %}>
            <label>From</label>
            <input type="date" name="date_from" value="{{ period.date_from.isoformat() }}" class="form-control form-control-sm">
        </div>
        <div class="ap-jrnl-field" id="toField" {% if period.mode != 'custom' %}style="display:none"{% endif %}>
            <label>To</label>
            <input type="date" name="date_to" value="{{ period.date_to.isoformat() }}" class="form-control form-control-sm">
        </div>
        <div class="ap-jrnl-field">
            <button type="submit" class="btn btn-primary btn-sm">🔍 Filter</button>
            <button type="button" id="toggleCustom" class="btn btn-secondary btn-sm">
                {% if period.mode == 'custom' %}Use month{% else %}Custom range{% endif %}
            </button>
        </div>
    </form>

    <div class="ap-jrnl-meta">
        <h3>Accounts Payable Journal</h3>
        <p>{{ period.label }} — {{ current_branch.name if current_branch else 'All Branches' }}</p>
    </div>

    <div class="card-body">
        {% if matrix.rows %}
        <div class="ap-jrnl-scroll">
        <table class="ap-jrnl-table">
            <thead>
                <tr>
                    <th>Date</th>
                    <th>No.</th>
                    <th>Invoice No.</th>
                    <th>Vendor</th>
                    <th>Particulars</th>
                    {% for col in matrix.columns %}
                    <th class="ap-jrnl-num {% if col.group in ['ap','wht'] %}ap-jrnl-head--credit{% else %}ap-jrnl-head--debit{% endif %}">{{ col.name }}</th>
                    {% endfor %}
                </tr>
            </thead>
            <tbody>
                {% for row in matrix.rows %}
                {% set bill = bill_map.get(row.entry.reference) %}
                <tr>
                    <td>{{ row.entry.entry_date.strftime('%b %d, %Y') }}</td>
                    <td>
                        {% if bill %}
                        <a href="{{ url_for('purchase_bills.view', id=bill.id) }}" style="font-weight:600; color:var(--blue);">{{ row.entry.reference }}</a>
                        {% else %}{{ row.entry.reference or '—' }}{% endif %}
                        {% if row.is_draft %}<span class="ap-jrnl-draft-badge">Draft</span>{% endif %}
                    </td>
                    <td>{{ bill.vendor_invoice_number if bill else '' }}</td>
                    <td>{{ bill.vendor_name if bill else '—' }}</td>
                    <td>{{ (bill.notes if bill else '') or '' }}</td>
                    {% for col in matrix.columns %}
                    <td class="ap-jrnl-num">
                        {%- if row.is_draft -%}
                        {%- elif col.account_id in row.cells and row.cells[col.account_id] != 0 -%}
                            {%- set v = row.cells[col.account_id] -%}
                            {%- if v < 0 -%}({{ '{:,.2f}'.format(-v) }}){%- else -%}{{ '{:,.2f}'.format(v) }}{%- endif -%}
                        {%- endif -%}
                    </td>
                    {% endfor %}
                </tr>
                {% endfor %}
                <tr class="ap-jrnl-total">
                    <td colspan="5">TOTAL</td>
                    {% for col in matrix.columns %}
                    <td class="ap-jrnl-num">
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
        <p style="color:var(--red,#dc2626); font-weight:600; margin-top:10px;">
            ⚠ Column totals do not net to zero — debits and credits are out of balance. Review the underlying entries.
        </p>
        {% endif %}
        {% else %}
        <div class="empty-state">
            <p>No AP entries found for {{ period.label | lower }}.</p>
            <p style="font-size:13px; color:var(--text-3);">AP journal entries are created automatically when an AP voucher is posted.</p>
        </div>
        {% endif %}
    </div>
</div>

<script>
(function () {
    var toggle = document.getElementById('toggleCustom');
    var mode = document.getElementById('apMode');
    if (!toggle) return;
    toggle.addEventListener('click', function () {
        mode.value = (mode.value === 'custom') ? 'month' : 'custom';
        document.getElementById('apFilter').submit();
    });
})();
</script>
{% endblock %}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_ap_journal_columnar.py -v`
Expected: PASS (all, including draft-indicator and view-renders-columns).

- [ ] **Step 5: Commit**

```bash
git add app/journals/templates/journals/ap_journal.html tests/integration/test_ap_journal_columnar.py
git commit -m "feat: columnar AP journal template with month/custom filter, print, Excel"
```

---

## Task 6: Make Notes required — model + migration

**Files:**
- Modify: `app/purchase_bills/models.py:60`
- Create: `migrations/versions/<new>.py`
- Test: `tests/unit/test_purchase_bill_notes_required.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_purchase_bill_notes_required.py
import pytest
from datetime import date
from decimal import Decimal
from app import db
from app.purchase_bills.models import PurchaseBill
from app.branches.models import Branch
from app.vendors.models import Vendor


def test_bill_without_notes_violates_not_null(db_session):
    branch = Branch(name='Main', code='MAIN'); db.session.add(branch)
    vendor = Vendor(code='V1', name='V', check_payee_name='V', is_active=True, payment_terms='Net 30')
    db.session.add(vendor); db.session.commit()
    bill = PurchaseBill(
        branch_id=branch.id, bill_number='AP-X-1', bill_date=date(2026, 6, 1),
        due_date=date(2026, 6, 30), vendor_id=vendor.id, vendor_name='V',
        total_amount=Decimal('100.00'))  # notes omitted
    db.session.add(bill)
    with pytest.raises(Exception):  # IntegrityError (NOT NULL)
        db.session.commit()
    db.session.rollback()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_purchase_bill_notes_required.py -v`
Expected: FAIL — commit succeeds (notes currently nullable), so `pytest.raises` does not trigger.

- [ ] **Step 3: Write minimal implementation**

In `app/purchase_bills/models.py` line 60, change:

```python
    notes = db.Column(db.Text)
```
to:
```python
    notes = db.Column(db.Text, nullable=False, default='')
```

Then create the migration. Generate a revision file:

```bash
flask db revision -m "make purchase_bills.notes required"
```

Edit the new file in `migrations/versions/` so its `upgrade`/`downgrade` read:

```python
import sqlalchemy as sa
from alembic import op

# keep the auto-generated revision / down_revision lines as written

def upgrade():
    op.execute("UPDATE purchase_bills SET notes = '(No particulars recorded)' WHERE notes IS NULL OR notes = ''")
    with op.batch_alter_table('purchase_bills', schema=None) as batch_op:
        batch_op.alter_column('notes', existing_type=sa.Text(), nullable=False)


def downgrade():
    with op.batch_alter_table('purchase_bills', schema=None) as batch_op:
        batch_op.alter_column('notes', existing_type=sa.Text(), nullable=True)
```

> Use `flask db revision` (empty revision) — NOT `flask db migrate` — so autogenerate doesn't add unrelated diffs. The new file's `down_revision` is set automatically to the current head.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_purchase_bill_notes_required.py -v`
Expected: PASS. Then apply the migration to the dev DB: `flask db upgrade` (expected: "Running upgrade ... ").

- [ ] **Step 5: Commit**

```bash
git add app/purchase_bills/models.py migrations/versions/ tests/unit/test_purchase_bill_notes_required.py
git commit -m "feat: require purchase_bills.notes (DB NOT NULL) with backfill migration"
```

---

## Task 7: Make Notes required — form validator + fix fixtures

**Files:**
- Modify: `app/purchase_bills/forms.py:57`
- Modify: any test/seed that creates bills without notes (search below)
- Test: `tests/unit/test_purchase_bill_notes_required.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_purchase_bill_notes_required.py
from app.purchase_bills.forms import PurchaseBillForm


def test_form_requires_notes(app):
    with app.test_request_context():
        form = PurchaseBillForm(formdata=None, meta={'csrf': False})
        form.notes.data = ''
        form.validate()
        assert 'notes' in form.errors


def test_form_accepts_notes(app):
    with app.test_request_context():
        form = PurchaseBillForm(formdata=None, meta={'csrf': False})
        form.notes.data = 'To record office supplies'
        form.validate()
        assert 'notes' not in form.errors
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_purchase_bill_notes_required.py -k form -v`
Expected: FAIL — `test_form_requires_notes` fails because notes is currently `Optional()`.

- [ ] **Step 3: Write minimal implementation**

In `app/purchase_bills/forms.py`, change line 57:

```python
    notes = TextAreaField('Notes', validators=[Optional()])
```
to:
```python
    notes = TextAreaField('Notes (Particulars)', validators=[
        DataRequired(message='Notes are required — this becomes the Particulars in the AP Journal.')
    ])
```

(`DataRequired` is already imported on line 6.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_purchase_bill_notes_required.py -v`
Expected: PASS (all 3).

- [ ] **Step 5: Fix any fixtures/tests that create bills without notes**

Run this to find creators that may now break:

```bash
grep -rln "PurchaseBill(" tests/ app/ | xargs grep -Ln "notes" 2>/dev/null
grep -rn "PurchaseBillForm\|/purchase-bills/create" tests/ | head
```

For each test that builds a `PurchaseBill(...)` or posts to the create route without `notes`, add `notes='Test particulars'` (model) or `'notes': 'Test particulars'` (form POST). Re-run the affected files until green.

- [ ] **Step 6: Run the full purchase-bill + journals suites**

Run: `pytest tests/integration/test_purchase_bill_je.py tests/integration/test_purchase_bill_views.py tests/integration/test_ap_journal_columnar.py tests/integration/test_journals.py -v`
Expected: PASS. Fix any fixture that fails on the new NOT NULL / DataRequired.

- [ ] **Step 7: Commit**

```bash
git add app/purchase_bills/forms.py tests/
git commit -m "feat: require Notes on AP voucher form; update fixtures"
```

---

## Task 8: Full regression + manual smoke

**Files:** none (verification only)

- [ ] **Step 1: Run the full suite**

Run: `pytest -m "not slow" -q`
Expected: all pass. Investigate and fix any fixture that relied on empty notes.

- [ ] **Step 2: Manual smoke (dev server)**

```bash
flask db upgrade        # ensure migration applied
python flask_app.py
```
Visit `/journals/ap` (logged in, branch selected):
- Month selector defaults to current month; header says "For the month of <Month> <Year>".
- Account-title columns appear; AP-Trade and WHT show parenthesised; TOTAL row present.
- "Custom range" button swaps to From/To date inputs and back.
- "Excel" downloads `AP-Journal-YYYY-MM.xlsx` matching the screen.
- "Print" (Ctrl+P) shows landscape, no sidebar/toolbar.
- Create an APV without Notes → form blocks with the required message.

- [ ] **Step 3: Commit (if any fixture/docs touched)**

```bash
git add -A
git commit -m "test: AP journal columnar regression green"
```

---

## Notes for the executor

- Work on `main` (this repo commits directly to main; auto-commit + push is the established workflow). Push after each task: `git push`.
- If `CompanySettings`/`company_name` attribute names differ (Task 4 NOTE), grep and adjust only those two lines.
- Do NOT change `_post_bill_je()` or any posting logic — the journal is read-only over existing data.
- Keep credits-in-parentheses and the single WHT column (we deliberately do not follow the RIC per-rate format).
