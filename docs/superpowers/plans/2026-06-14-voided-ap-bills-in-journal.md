# Voided AP Bills in AP Journal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make voided AP bills visible in the AP Journal (columnar view + Excel export) as struck-through rows with a VOIDED badge, mirroring how draft rows are already handled.

**Architecture:** Extend `build_columnar` with a `voided_bills` parameter (list of `PurchaseBill`). The view fetches voided bills by `bill_date` within the period and passes them. The template renders them as `table-danger` rows with strikethrough identity columns and blank amount cells. Excel export gets the same treatment with a red fill.

**Tech Stack:** Flask, SQLAlchemy, Jinja2, openpyxl, pytest

---

## File Map

| File | Change |
|---|---|
| `app/journals/ap_journal_data.py` | Add `voided_bills` param to `build_columnar`; update sort key; update `build_ap_journal_xlsx` |
| `app/journals/views.py` | Query voided bills in `_ap_journal_context`; pass to `build_columnar` |
| `app/journals/templates/journals/ap_journal.html` | Render voided rows with strikethrough + badge |
| `tests/unit/test_ap_journal_data.py` | Unit tests for voided rows in `build_columnar` |
| `tests/integration/test_ap_journal_columnar.py` | Integration tests for voided bills in view + export |

---

## Task 1: Unit tests + `build_columnar` voided_bills support

**Files:**
- Modify: `tests/unit/test_ap_journal_data.py`
- Modify: `app/journals/ap_journal_data.py`

- [ ] **Step 1: Write failing unit tests for voided rows**

Add to `tests/unit/test_ap_journal_data.py`:

```python
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from app.journals.ap_journal_data import build_columnar


def _mock_bill(bill_number, bill_date, vendor_name='Vendor X',
               vendor_invoice_number='INV-1', notes=''):
    b = MagicMock()
    b.bill_number = bill_number
    b.bill_date = bill_date
    b.vendor_name = vendor_name
    b.vendor_invoice_number = vendor_invoice_number
    b.notes = notes
    return b


def test_build_columnar_voided_rows_excluded_from_totals():
    voided = _mock_bill('AP-2026-06-0002', date(2026, 6, 2))
    matrix = build_columnar(
        posted_entries=[], draft_entries=[],
        ap_account_id=1, wt_account_id=2, input_vat_account_ids=set(),
        voided_bills=[voided],
    )
    assert len(matrix['rows']) == 1
    row = matrix['rows'][0]
    assert row['is_voided'] is True
    assert row['cells'] == {}
    assert row['bill'] is voided
    assert matrix['totals'] == {}
    assert matrix['grand_total'] == Decimal('0')


def test_build_columnar_voided_rows_sort_with_posted_by_date():
    # voided bill on June 1, posted JE on June 3 → voided comes first
    voided = _mock_bill('AP-2026-06-0001', date(2026, 6, 1))

    posted_je = MagicMock()
    posted_je.entry_date = date(2026, 6, 3)
    posted_je.entry_number = 'AP-2026-06-0003'
    line = MagicMock()
    acct = MagicMock()
    acct.id = 99
    acct.code = '20101'
    acct.name = 'AP'
    line.account = acct
    line.debit_amount = Decimal('0')
    line.credit_amount = Decimal('5000')
    posted_je.lines.all.return_value = [line]

    matrix = build_columnar(
        posted_entries=[posted_je], draft_entries=[],
        ap_account_id=99, wt_account_id=None, input_vat_account_ids=set(),
        voided_bills=[voided],
    )
    assert matrix['rows'][0]['is_voided'] is True   # June 1 comes before June 3
    assert matrix['rows'][1]['is_voided'] is False


def test_build_columnar_voided_no_column_contribution():
    voided = _mock_bill('AP-2026-06-0005', date(2026, 6, 5))
    matrix = build_columnar(
        posted_entries=[], draft_entries=[],
        ap_account_id=1, wt_account_id=2, input_vat_account_ids=set(),
        voided_bills=[voided],
    )
    # No columns built from voided-only matrix
    assert matrix['columns'] == []
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/unit/test_ap_journal_data.py::test_build_columnar_voided_rows_excluded_from_totals tests/unit/test_ap_journal_data.py::test_build_columnar_voided_rows_sort_with_posted_by_date tests/unit/test_ap_journal_data.py::test_build_columnar_voided_no_column_contribution -v
```

Expected: FAIL — `build_columnar() got an unexpected keyword argument 'voided_bills'`

- [ ] **Step 3: Update `build_columnar` in `app/journals/ap_journal_data.py`**

Replace the function signature and body (lines 98–148) with:

```python
def build_columnar(posted_entries, draft_entries, ap_account_id,
                   wt_account_id, input_vat_account_ids, voided_bills=None):
    """Pivot journal-entry lines into a columnar matrix.

    Columns are built only from POSTED entries' accounts, ordered
    credits-first (AP, WHT, Input VAT, then other accounts by code).
    Posted rows carry signed amounts (debit - credit) per account and
    contribute to per-column totals. Draft and voided rows are listed
    with a flag and no amounts, excluded from totals.

    Returns dict: columns, rows, totals, grand_total, balanced.
    """
    if voided_bills is None:
        voided_bills = []

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
        rows.append({'entry': je, 'cells': cells, 'is_draft': False, 'is_voided': False})

    for je in draft_entries:
        rows.append({'entry': je, 'cells': {}, 'is_draft': True, 'is_voided': False})

    for bill in voided_bills:
        rows.append({'bill': bill, 'entry': None, 'cells': {}, 'is_draft': False, 'is_voided': True})

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

    def _row_sort_key(r):
        if r['is_voided']:
            return (r['bill'].bill_date, r['bill'].bill_number)
        return (r['entry'].entry_date, r['entry'].entry_number)

    rows.sort(key=_row_sort_key)

    grand_total = sum(totals.values(), Decimal('0'))
    return {
        'columns': columns,
        'rows': rows,
        'totals': totals,
        'grand_total': grand_total,
        'balanced': grand_total == Decimal('0'),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/unit/test_ap_journal_data.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```
git add app/journals/ap_journal_data.py tests/unit/test_ap_journal_data.py
git commit -m "feat: build_columnar — voided_bills third row type with sort support"
```

---

## Task 2: Update `build_ap_journal_xlsx` for voided rows

**Files:**
- Modify: `app/journals/ap_journal_data.py`
- Modify: `tests/unit/test_ap_journal_data.py`

- [ ] **Step 1: Write a failing test for voided rows in Excel**

Add to `tests/unit/test_ap_journal_data.py`:

```python
def test_build_ap_journal_xlsx_voided_row_has_red_fill_and_no_amounts(app):
    from openpyxl import load_workbook
    from app.journals.ap_journal_data import build_ap_journal_xlsx
    from unittest.mock import MagicMock
    from datetime import date
    from decimal import Decimal

    columns = [
        {'account_id': 1, 'code': '20101', 'name': 'Accounts Payable - Trade', 'group': 'ap'},
    ]
    bill = MagicMock()
    bill.bill_date = date(2026, 6, 3)
    bill.bill_number = 'AP-2026-06-0002'
    bill.vendor_invoice_number = 'INV-99'
    bill.vendor_name = 'Voided Vendor'
    bill.notes = 'Test void'

    rows = [{
        'entry': None,
        'bill': bill,
        'cells': {},
        'is_draft': False,
        'is_voided': True,
    }]
    with app.app_context():
        resp = build_ap_journal_xlsx(
            columns=columns, rows=rows, totals={},
            period_label='For the month of June 2026',
            company_name='ABC Co', branch_name=None,
            filename='test.xlsx',
            identity=lambda e: ('', '', '', ''))

    wb = load_workbook(io.BytesIO(resp.get_data()))
    ws = wb.active
    all_text = ' '.join(str(c.value) for row in ws.iter_rows() for c in row if c.value is not None)
    assert 'AP-2026-06-0002' in all_text
    assert 'Voided Vendor' in all_text
    assert '[VOIDED]' in all_text

    # Amount cell for the voided row must be blank
    # Header is row 5 (no branch), data is row 6
    data_row_vals = [ws.cell(row=6, column=i).value for i in range(1, len(columns) + 6)]
    assert all(v is None or str(v).strip() == '' for v in data_row_vals[5:])
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/unit/test_ap_journal_data.py::test_build_ap_journal_xlsx_voided_row_has_red_fill_and_no_amounts -v
```

Expected: FAIL

- [ ] **Step 3: Update `build_ap_journal_xlsx` in `app/journals/ap_journal_data.py`**

In `build_ap_journal_xlsx`, add a `voided_fill` variable alongside `draft_fill`, then update the data-row loop to handle `is_voided`. Replace the existing `draft_fill` line and data-row loop (approximately lines 179 and 207–231):

```python
    draft_fill = PatternFill(fill_type='solid', fgColor='FFF9C4')   # light yellow
    voided_fill = PatternFill(fill_type='solid', fgColor='FFCDD2')  # light red

    # ... (preamble + header unchanged) ...

    # Data rows
    first_data_row = hdr_row + 1
    for r in rows:
        if r.get('is_voided'):
            b = r['bill']
            line = [
                b.bill_date.strftime('%d-%b-%Y'),
                b.bill_number or '',
                b.vendor_invoice_number or '',
                b.vendor_name or '',
                '[VOIDED] ' + (b.notes or ''),
            ] + [None] * len(columns)
            ws.append(line)
            cur = ws.max_row
            for cell in ws[cur]:
                cell.border = cell_border
                cell.fill = voided_fill
            continue

        e = r['entry']
        no, invoice, vendor, particulars = identity(e)
        line = [
            e.entry_date.strftime('%d-%b-%Y'),
            no or '',
            invoice or '',
            vendor or '',
            ('[DRAFT] ' + (particulars or '')) if r['is_draft'] else (particulars or ''),
        ]
        for c in columns:
            if r['is_draft']:
                line.append(None)
            else:
                val = r['cells'].get(c['account_id'])
                line.append(float(val) if val else None)
        ws.append(line)
        cur = ws.max_row
        for i, cell in enumerate(ws[cur], 1):
            cell.border = cell_border
            if r['is_draft']:
                cell.fill = draft_fill
            if i > len(fixed):
                cell.number_format = num_fmt
                cell.alignment = right
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/unit/test_ap_journal_data.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```
git add app/journals/ap_journal_data.py tests/unit/test_ap_journal_data.py
git commit -m "feat: ap journal Excel — voided rows with red fill, no amounts"
```

---

## Task 3: View layer — fetch voided bills and pass to `build_columnar`

**Files:**
- Modify: `app/journals/views.py`
- Modify: `tests/integration/test_ap_journal_columnar.py`

- [ ] **Step 1: Write failing integration tests**

Add to `tests/integration/test_ap_journal_columnar.py`:

```python
from app.purchase_bills.models import PurchaseBill
from app.vendors.models import Vendor


def _voided_bill(branch_id, bill_number, bill_date, vendor_name='Vendor V'):
    b = PurchaseBill(
        bill_number=bill_number,
        bill_date=bill_date,
        due_date=bill_date,
        vendor_name=vendor_name,
        vendor_id=None,
        status='voided',
        subtotal=Decimal('0'),
        vat_amount=Decimal('0'),
        withholding_tax_amount=Decimal('0'),
        total_amount=Decimal('0'),
        branch_id=branch_id,
    )
    db.session.add(b)
    db.session.commit()
    return b


def test_ap_journal_view_shows_voided_bill(client, db_session):
    branch = Branch(name='Main', code='MAIN')
    db.session.add(branch)
    db.session.commit()
    _voided_bill(branch.id, 'AP-2026-06-0003', date(2026, 6, 3))
    _login(client, db_session, branch)

    res = client.get('/journals/ap?mode=month&year=2026&month=6')
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert 'AP-2026-06-0003' in body
    assert 'VOIDED' in body


def test_ap_journal_export_includes_voided_bill(client, db_session):
    import io
    from openpyxl import load_workbook

    branch = Branch(name='Main', code='MAIN')
    db.session.add(branch)
    db.session.commit()
    _voided_bill(branch.id, 'AP-2026-06-0007', date(2026, 6, 7), vendor_name='Void Co')
    _login(client, db_session, branch)

    res = client.get('/journals/ap/export?mode=month&year=2026&month=6')
    assert res.status_code == 200
    wb = load_workbook(io.BytesIO(res.get_data()))
    ws = wb.active
    all_text = ' '.join(str(c.value) for row in ws.iter_rows() for c in row if c.value is not None)
    assert 'AP-2026-06-0007' in all_text
    assert '[VOIDED]' in all_text
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/integration/test_ap_journal_columnar.py::test_ap_journal_view_shows_voided_bill tests/integration/test_ap_journal_columnar.py::test_ap_journal_export_includes_voided_bill -v
```

Expected: FAIL — voided bill not in response body

- [ ] **Step 3: Update `_ap_journal_context` in `app/journals/views.py`**

Replace the existing `_ap_journal_context` function (lines 48–68):

```python
def _ap_journal_context(branch_id):
    """Build the columnar AP journal data for a branch + period from request.args."""
    from app.purchase_bills.models import PurchaseBill
    period = resolve_period(request.args, today=ph_now().date())

    entries = JournalEntry.query.filter(
        JournalEntry.entry_type == 'purchase',
        JournalEntry.branch_id == branch_id,
        JournalEntry.entry_date >= period['date_from'],
        JournalEntry.entry_date <= period['date_to'],
    ).order_by(JournalEntry.entry_date).all()
    posted = [e for e in entries if e.status == 'posted']
    drafts = [e for e in entries if e.status == 'draft']

    voided_bills = PurchaseBill.query.filter(
        PurchaseBill.branch_id == branch_id,
        PurchaseBill.status == 'voided',
        PurchaseBill.bill_date >= period['date_from'],
        PurchaseBill.bill_date <= period['date_to'],
    ).order_by(PurchaseBill.bill_date, PurchaseBill.bill_number).all()

    ap_id, wt_id, vat_ids = _gl_account_ids()
    matrix = build_columnar(posted, drafts, ap_id, wt_id, vat_ids, voided_bills=voided_bills)

    refs = [e.reference for e in entries if e.reference]
    bills = PurchaseBill.query.filter(PurchaseBill.bill_number.in_(refs)).all() if refs else []
    bill_map = {b.bill_number: b for b in bills}
    return period, matrix, bill_map
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/integration/test_ap_journal_columnar.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```
git add app/journals/views.py tests/integration/test_ap_journal_columnar.py
git commit -m "feat: ap journal view — fetch and pass voided bills to build_columnar"
```

---

## Task 4: Template — render voided rows

**Files:**
- Modify: `app/journals/templates/journals/ap_journal.html`

No new tests needed — the integration test in Task 3 already asserts `VOIDED` appears in the HTML body.

- [ ] **Step 1: Add CSS for voided badge and strikethrough**

In the `<style>` block of `app/journals/templates/journals/ap_journal.html`, add after the `.ap-jrnl-draft-badge` rule (line 19):

```css
.ap-jrnl-voided-badge { font-size:10px; font-weight:600; color:#dc2626; background:#fee2e2;
    border:1px solid #fca5a5; padding:1px 6px; border-radius:8px; text-transform:uppercase; }
.ap-jrnl-voided td { background:#fff5f5; text-decoration:line-through; color:var(--text-2,#64748b); }
.ap-jrnl-voided .ap-jrnl-no-strike { text-decoration:none; }
```

- [ ] **Step 2: Update the row loop in the template**

Replace the `{% for row in matrix.rows %}` block (lines 98–121) with:

```html
{% for row in matrix.rows %}
{% if row.is_voided %}
<tr class="ap-jrnl-voided">
    <td>{{ row.bill.bill_date.strftime('%b %d, %Y') }}</td>
    <td>
        <a href="{{ url_for('purchase_bills.view', id=row.bill.id) }}" style="font-weight:600;">{{ row.bill.bill_number }}</a>
        <span class="ap-jrnl-voided-badge ap-jrnl-no-strike">VOIDED</span>
    </td>
    <td>{{ row.bill.vendor_invoice_number or '' }}</td>
    <td>{{ row.bill.vendor_name or '&mdash;' }}</td>
    <td>{{ row.bill.notes or '' }}</td>
    {% for col in matrix.columns %}<td class="ap-jrnl-num"></td>{% endfor %}
</tr>
{% else %}
{% set bill = bill_map.get(row.entry.reference) %}
<tr>
    <td>{{ row.entry.entry_date.strftime('%b %d, %Y') }}</td>
    <td>
        {% if bill %}
        <a href="{{ url_for('purchase_bills.view', id=bill.id) }}" style="font-weight:600;">{{ row.entry.reference }}</a>
        {% else %}{{ row.entry.reference or '&mdash;' }}{% endif %}
        {% if row.is_draft %}<span class="ap-jrnl-draft-badge">Draft</span>{% endif %}
    </td>
    <td>{{ bill.vendor_invoice_number if bill else '' }}</td>
    <td>{{ bill.vendor_name if bill else '&mdash;' }}</td>
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
{% endif %}
{% endfor %}
```

- [ ] **Step 3: Run the full integration test suite to verify**

```
pytest tests/integration/test_ap_journal_columnar.py -v
```

Expected: all tests PASS, including `test_ap_journal_view_shows_voided_bill`

- [ ] **Step 4: Run the full test suite to check for regressions**

```
pytest -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```
git add app/journals/templates/journals/ap_journal.html
git commit -m "feat: ap journal template — voided rows with strikethrough and VOIDED badge"
```

---

## Task 5: Push

- [ ] **Step 1: Push to remote**

```
git push
```
