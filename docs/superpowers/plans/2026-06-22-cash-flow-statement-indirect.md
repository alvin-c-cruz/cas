# Cash Flow Statement (Indirect Method) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Activate the Cash Flow report as a Statement of Cash Flows (indirect method) — Operating/Investing/Financing activities reconciled to the change in cash — matching the activation recipe used for TB/IS/BS.

**Architecture:** A new `generate_cash_flow(start, end, branch_id, method='indirect')` in `app/reports/financial.py` reorganizes every non-cash account's *period movement* (Σ debit−credit) into the three activity buckets by COA code, adds back depreciation, and reconciles to actual cash change. `app/reports/statement_export.py` gets `cash_flow_lines` + `build_cash_flow_xlsx`. The view + excel + print routes, a `cash_flow` module-access key, two templates, a nav swap, and an index card complete the recipe. No CSV.

**Tech Stack:** Flask, SQLAlchemy, SQLite, openpyxl, Jinja2, pytest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-06-22-cash-flow-statement-indirect-design.md`.
- **Indirect method only.** `generate_cash_flow(..., method='indirect')`; any other `method` raises `ValueError`. No direct-method code (deferred).
- **Cash accounts** = active accounts whose **name contains "cash"** (case-insensitive): `_is_cash(account)`.
- **Bucketing by COA code:** Operating = revenue (`4…`) + expense (`5…`) + current assets ex-cash (`10…` non-cash) + current liabilities (`20…`); Investing = non-current asset cost (`11…`) **excluding** Accumulated Depreciation (name contains "depreciation"); Financing = non-current liabilities (`21…`) + equity (`30…`).
- **Depreciation add-back** = period movement of expense accounts whose name contains "depreciation"; Accumulated Depreciation is excluded from Investing so the two offset and the statement still ties.
- Line `amount`s are the **cash effect** (`−Δ` in debit-positive terms): outflow negative, inflow positive. Omit zero-effect lines.
- **No CSV** for this (or any) financial statement. Excel + Print only.
- **Module access:** add a `cash_flow` key (section `'Ledger'`) gating view + export/excel + print endpoints. Staff need an explicit grant; admin/accountant/viewer always allowed.
- Design tokens only (`var(--…)`); literal `₱` (U+20B1), never `&#8369;`.
- Accounting number format in Excel: `#,##0.00;(#,##0.00)` (already `_NUM_FMT`). Gridlines off. Branch hidden when `Branch.query.count() <= 1`.
- This is a **read-only report**: no audit-log writes, consistent with TB/IS/BS view tests.
- Tests: `pytest` (markers `unit` / `integration`); fixtures `client`, `db_session`, `main_branch`, `admin_user`, `staff_user`, `viewer_user` from `tests/conftest.py`.

---

### Task 1: `generate_cash_flow` generator + helpers

**Files:**
- Modify: `app/reports/financial.py` (line 12 import; add helpers + function after `generate_balance_sheet`, which ends at line 319)
- Test: `tests/unit/test_cash_flow_generator.py` (create)

**Interfaces:**
- Consumes: `generate_income_statement(start_date, end_date, branch_id=None)['net_income']` (already in this module); `Account`, `JournalEntry`, `JournalEntryLine`, `db`, `func`, `Decimal` (already imported).
- Produces: `generate_cash_flow(start_date, end_date, branch_id=None, method='indirect') -> dict` with keys: `period_start`, `period_end`, `method`, `operating` (`{net_income, depreciation, working_capital:[{name,amount}], total}`), `investing` (`{lines:[{name,amount}], total}`), `financing` (`{lines:[{name,amount}], total}`), `net_change`, `cash_begin`, `cash_end`, `is_reconciled`, `difference`. Module-level helpers `_is_cash(account)`, `_is_depreciation_name(account)`. All numeric values are floats.

- [ ] **Step 1: Add `timedelta` to the datetime import**

In `app/reports/financial.py` line 12, change:

```python
from datetime import date, datetime
```

to:

```python
from datetime import date, datetime, timedelta
```

- [ ] **Step 2: Write the failing unit tests**

Create `tests/unit/test_cash_flow_generator.py`:

```python
from datetime import date
from decimal import Decimal
import pytest

from app import db
from app.accounts.models import Account
from app.branches.models import Branch
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.reports.financial import generate_cash_flow

pytestmark = [pytest.mark.unit]

START, END = date(2026, 1, 1), date(2026, 6, 30)


def _branch():
    b = Branch(name='Main', code='MAIN')
    db.session.add(b)
    db.session.commit()
    return b


def _acct(code, name, atype, normal='Debit', parent=None):
    a = Account(code=code, name=name, account_type=atype, normal_balance=normal,
                is_active=True, parent_id=parent.id if parent else None)
    db.session.add(a)
    db.session.commit()
    return a


def _je(branch_id, lines, number):
    je = JournalEntry(entry_number=number, entry_date=date(2026, 6, 10), description='d',
                      reference=number, entry_type='adjustment', branch_id=branch_id,
                      status='posted', is_balanced=True, total_debit=Decimal('0'),
                      total_credit=Decimal('0'))
    db.session.add(je)
    db.session.flush()
    n = 1
    for acct, dr, cr in lines:
        db.session.add(JournalEntryLine(entry_id=je.id, line_number=n, account_id=acct.id,
                                        debit_amount=Decimal(str(dr)), credit_amount=Decimal(str(cr))))
        n += 1
    db.session.commit()
    return je


def _build(db_session):
    b = _branch()
    ca = _acct('10000', 'CURRENT ASSETS', 'Asset')
    cash = _acct('10101', 'Cash on Hand', 'Asset', parent=ca)
    ar = _acct('10201', 'Accounts Receivable', 'Asset', parent=ca)
    nca = _acct('11000', 'NON-CURRENT ASSETS', 'Asset')
    equip = _acct('11110', 'Construction Equipment', 'Asset', parent=nca)
    accum = _acct('11111', 'Accumulated Depreciation', 'Asset', 'Credit', parent=nca)
    cl = _acct('20000', 'CURRENT LIABILITIES', 'Liability', 'Credit')
    ap = _acct('20101', 'Accounts Payable', 'Liability', 'Credit', parent=cl)
    eq = _acct('30000', 'EQUITY', 'Equity', 'Credit')
    cap = _acct('30101', 'Capital Stock', 'Equity', 'Credit', parent=eq)
    rev = _acct('40101', 'Sales Revenue', 'Revenue', 'Credit')
    dep = _acct('50260', 'Depreciation Expense', 'Expense')
    sal = _acct('50110', 'Salaries Expense', 'Expense')
    _je(b.id, [(cash, 1000, 0), (cap, 0, 1000)], 'CF1')   # financing inflow 1000, cash +1000
    _je(b.id, [(equip, 500, 0), (cash, 0, 500)], 'CF2')   # investing outflow -500, cash -500
    _je(b.id, [(cash, 200, 0), (rev, 0, 200)], 'CF3')     # NI +200, cash +200
    _je(b.id, [(dep, 50, 0), (accum, 0, 50)], 'CF4')      # NI -50, depreciation add-back +50
    _je(b.id, [(ar, 300, 0), (rev, 0, 300)], 'CF5')       # NI +300, AR up -> WC -300
    _je(b.id, [(sal, 100, 0), (ap, 0, 100)], 'CF6')       # NI -100, AP up -> WC +100
    return b


def test_reconciles(db_session):
    b = _build(db_session)
    cf = generate_cash_flow(START, END, branch_id=b.id)
    assert cf['cash_begin'] == 0.0
    assert cf['cash_end'] == 700.0
    assert cf['net_change'] == 700.0
    assert cf['is_reconciled'] is True
    assert cf['difference'] == 0.0


def test_operating(db_session):
    b = _build(db_session)
    cf = generate_cash_flow(START, END, branch_id=b.id)
    op = cf['operating']
    assert op['net_income'] == 350.0          # (200+300) - (50+100)
    assert op['depreciation'] == 50.0
    assert op['total'] == 200.0               # 350 + 50 - 200
    wc = {w['amount'] for w in op['working_capital']}
    assert -300.0 in wc                        # AR increase consumes cash
    assert 100.0 in wc                         # AP increase frees cash


def test_depreciation_excluded_from_investing(db_session):
    b = _build(db_session)
    cf = generate_cash_flow(START, END, branch_id=b.id)
    assert all('Accumulated Depreciation' not in ln['name'] for ln in cf['investing']['lines'])


def test_investing(db_session):
    b = _build(db_session)
    cf = generate_cash_flow(START, END, branch_id=b.id)
    assert cf['investing']['total'] == -500.0
    assert any(ln['amount'] == -500.0 for ln in cf['investing']['lines'])


def test_financing(db_session):
    b = _build(db_session)
    cf = generate_cash_flow(START, END, branch_id=b.id)
    assert cf['financing']['total'] == 1000.0
    assert any(ln['name'] == 'Capital Stock' and ln['amount'] == 1000.0
               for ln in cf['financing']['lines'])


def test_no_cash_accounts(db_session):
    b = _branch()
    ca = _acct('10000', 'CURRENT ASSETS', 'Asset')
    ar = _acct('10201', 'Accounts Receivable', 'Asset', parent=ca)
    rev = _acct('40101', 'Sales Revenue', 'Revenue', 'Credit')
    _je(b.id, [(ar, 100, 0), (rev, 0, 100)], 'CF1')
    cf = generate_cash_flow(START, END, branch_id=b.id)
    assert cf['cash_begin'] == 0.0
    assert cf['cash_end'] == 0.0
    assert cf['net_change'] == 0.0
    assert cf['is_reconciled'] is True


def test_rejects_direct_method(db_session):
    b = _build(db_session)
    with pytest.raises(ValueError):
        generate_cash_flow(START, END, branch_id=b.id, method='direct')
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest tests/unit/test_cash_flow_generator.py -q`
Expected: FAIL with `ImportError: cannot import name 'generate_cash_flow'`.

- [ ] **Step 4: Implement `generate_cash_flow` + helpers**

In `app/reports/financial.py`, after `generate_balance_sheet` (after line 319), append:

```python
def _is_cash(account):
    """Cash & cash equivalents: an account whose name contains 'cash'."""
    return 'cash' in (account.name or '').lower()


def _is_depreciation_name(account):
    """Depreciation expense or accumulated depreciation (name-based)."""
    return 'depreciation' in (account.name or '').lower()


def generate_cash_flow(start_date, end_date, branch_id=None, method='indirect'):
    """Statement of Cash Flows (indirect method) for a period.

    Reorganizes every non-cash account's period movement (Sigma debit - credit)
    into Operating / Investing / Financing activities, adds back depreciation,
    and reconciles to the actual change in cash. Returns floats for
    template/export consumption.

    Because every journal entry balances, the change in cash equals the negative
    sum of all non-cash account movements; bucketing those movements therefore
    sums exactly to the change in cash. Depreciation is the one special case: it
    is added back in Operating and Accumulated Depreciation is excluded from
    Investing (the two are equal and opposite, so the total still ties).

    NOTE (closing-entries caveat): equity movement feeds Financing. If year-end
    closing entries are ever posted to a Retained Earnings equity account, that
    movement would double-count net income here (same caveat as the Balance
    Sheet). Not an issue on books without closing entries.
    """
    if method != 'indirect':
        raise ValueError("Only the indirect cash-flow method is implemented")

    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    branch_filter = [JournalEntry.branch_id == branch_id] if branch_id else []

    def movement(account_id):
        """Net period movement in debit-positive terms: Sigma(debit) - Sigma(credit)."""
        debit_sum, credit_sum = db.session.query(
            func.coalesce(func.sum(JournalEntryLine.debit_amount), 0),
            func.coalesce(func.sum(JournalEntryLine.credit_amount), 0),
        ).join(JournalEntry).filter(
            JournalEntry.status == 'posted',
            JournalEntry.entry_date >= start_date,
            JournalEntry.entry_date <= end_date,
            JournalEntryLine.account_id == account_id,
            *branch_filter
        ).one()
        return Decimal(str(debit_sum)) - Decimal(str(credit_sum))

    def cash_balance(as_of):
        """Sigma over cash accounts of (debit - credit) posted on/before as_of."""
        total = Decimal('0.00')
        for a in accounts:
            if not _is_cash(a):
                continue
            debit_sum, credit_sum = db.session.query(
                func.coalesce(func.sum(JournalEntryLine.debit_amount), 0),
                func.coalesce(func.sum(JournalEntryLine.credit_amount), 0),
            ).join(JournalEntry).filter(
                JournalEntry.status == 'posted',
                JournalEntry.entry_date <= as_of,
                JournalEntryLine.account_id == a.id,
                *branch_filter
            ).one()
            total += Decimal(str(debit_sum)) - Decimal(str(credit_sum))
        return total

    # Operating
    net_income = Decimal(str(
        generate_income_statement(start_date, end_date, branch_id=branch_id)['net_income']))

    depreciation = Decimal('0.00')
    for a in accounts:
        if (a.account_type == 'Expense' or (a.code or '').startswith('5')) and _is_depreciation_name(a):
            depreciation += movement(a.id)        # debit-positive expense -> positive add-back

    working_capital = []
    wc_total = Decimal('0.00')
    for a in accounts:
        code = a.code or ''
        is_curr_asset = code.startswith('10') and not _is_cash(a)
        is_curr_liab = code.startswith('20')
        if not (is_curr_asset or is_curr_liab):
            continue
        effect = -movement(a.id)                  # asset up uses cash; liability up frees cash
        if effect != 0:
            verb = '(Increase)/decrease in ' if is_curr_asset else 'Increase/(decrease) in '
            working_capital.append({'name': verb + a.name, 'amount': float(effect)})
            wc_total += effect

    operating_total = net_income + depreciation + wc_total

    # Investing: non-current asset cost (11...) excluding accumulated depreciation
    investing_lines = []
    investing_total = Decimal('0.00')
    for a in accounts:
        if not (a.code or '').startswith('11') or _is_depreciation_name(a):
            continue
        effect = -movement(a.id)                  # purchase (debit up) -> outflow (negative)
        if effect != 0:
            investing_lines.append({'name': '(Acquisition)/disposal of ' + a.name,
                                    'amount': float(effect)})
            investing_total += effect

    # Financing: non-current liabilities (21...) + equity (30...)
    financing_lines = []
    financing_total = Decimal('0.00')
    for a in accounts:
        code = a.code or ''
        if not (code.startswith('21') or code.startswith('30')):
            continue
        effect = -movement(a.id)                  # contribution / loan proceeds (credit up) -> inflow
        if effect != 0:
            financing_lines.append({'name': a.name, 'amount': float(effect)})
            financing_total += effect

    net_change = operating_total + investing_total + financing_total
    cash_begin = cash_balance(start_date - timedelta(days=1))
    cash_end = cash_balance(end_date)
    diff = abs(net_change - (cash_end - cash_begin))

    return {
        'period_start': start_date,
        'period_end': end_date,
        'method': 'indirect',
        'operating': {
            'net_income': float(net_income),
            'depreciation': float(depreciation),
            'working_capital': working_capital,
            'total': float(operating_total),
        },
        'investing': {'lines': investing_lines, 'total': float(investing_total)},
        'financing': {'lines': financing_lines, 'total': float(financing_total)},
        'net_change': float(net_change),
        'cash_begin': float(cash_begin),
        'cash_end': float(cash_end),
        'is_reconciled': bool(diff < Decimal('0.01')),
        'difference': float(diff),
    }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/unit/test_cash_flow_generator.py -q`
Expected: PASS (7 passed).

- [ ] **Step 6: Commit**

```bash
git add app/reports/financial.py tests/unit/test_cash_flow_generator.py
git commit -m "feat(reports): generate_cash_flow indirect-method generator"
```

---

### Task 2: Export — `cash_flow_lines` + `build_cash_flow_xlsx`

**Files:**
- Modify: `app/reports/statement_export.py` (append after line 320)
- Test: `tests/unit/test_cash_flow_export.py` (create)

**Interfaces:**
- Consumes: the `generate_cash_flow(...)` dict from Task 1; existing `_NUM_FMT`, `_xlsx_response`, `Workbook`, `Font`, `Alignment`, `Border`, `Side` (already imported in the file).
- Produces: `cash_flow_lines(cf) -> list[dict]` (each `{kind, label, amount|None, indent: bool, rule: None|'top_bottom'|'double_bottom'}`); `build_cash_flow_xlsx(cf, period_label, company, branch_name, filename) -> flask response`.

- [ ] **Step 1: Write the failing unit test**

Create `tests/unit/test_cash_flow_export.py`:

```python
import pytest
from app.reports.statement_export import cash_flow_lines

pytestmark = [pytest.mark.unit]

CF = {
    'operating': {
        'net_income': 350.0, 'depreciation': 50.0,
        'working_capital': [{'name': '(Increase)/decrease in Accounts Receivable', 'amount': -300.0},
                            {'name': 'Increase/(decrease) in Accounts Payable', 'amount': 100.0}],
        'total': 200.0,
    },
    'investing': {'lines': [{'name': '(Acquisition)/disposal of Construction Equipment', 'amount': -500.0}],
                  'total': -500.0},
    'financing': {'lines': [{'name': 'Capital Stock', 'amount': 1000.0}], 'total': 1000.0},
    'net_change': 700.0, 'cash_begin': 0.0, 'cash_end': 700.0,
}


def test_lines_cover_all_sections_and_reconciliation():
    lines = cash_flow_lines(CF)
    labels = [ln['label'] for ln in lines]
    assert 'CASH FLOWS FROM OPERATING ACTIVITIES' in labels
    assert 'CASH FLOWS FROM INVESTING ACTIVITIES' in labels
    assert 'CASH FLOWS FROM FINANCING ACTIVITIES' in labels
    assert 'NET INCREASE/(DECREASE) IN CASH' in labels
    assert 'Cash at beginning of period' in labels
    assert 'Cash at end of period' in labels
    # net change carries a double-bottom rule
    net = next(ln for ln in lines if ln['label'] == 'NET INCREASE/(DECREASE) IN CASH')
    assert net['amount'] == 700.0 and net['rule'] == 'double_bottom'


def test_depreciation_line_omitted_when_zero():
    cf = {**CF, 'operating': {**CF['operating'], 'depreciation': 0.0}}
    labels = [ln['label'] for ln in cash_flow_lines(cf)]
    assert not any('Depreciation' in lbl for lbl in labels)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/unit/test_cash_flow_export.py -q`
Expected: FAIL with `ImportError: cannot import name 'cash_flow_lines'`.

- [ ] **Step 3: Implement `cash_flow_lines` + `build_cash_flow_xlsx`**

Append to `app/reports/statement_export.py`:

```python
def cash_flow_lines(cf):
    """Flatten the indirect cash flow statement into render-ready lines (print + Excel)."""
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


def build_cash_flow_xlsx(cf, period_label, company, branch_name, filename):
    """Statement of Cash Flows (indirect) as a formatted workbook with live formulas."""
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
    put('Indirect Method')
    put(period_label)
    put()
    r = put('Particulars', 'Amount')
    for cell in ws[r]:
        cell.font = Font(bold=True)
        cell.border = Border(bottom=thin)
    ws.cell(r, 2).alignment = right

    # Operating — live SUM over the operating detail rows
    op = cf['operating']
    r = put('CASH FLOWS FROM OPERATING ACTIVITIES'); ws.cell(r, 1).font = Font(bold=True)
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
    ws.cell(r, 2).value = f'=SUM(B{first}:B{last})'
    style(r, bold=True, border=rules['top_bottom'])
    sec_rows = {'operating': r}

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
    ws.cell(r, 2).value = f"=B{net_row}+B{begin_row}"      # live: net change + beginning = end
    style(r, bold=True, border=rules['double_bottom'])

    ws.column_dimensions['A'].width = 50
    ws.column_dimensions['B'].width = 22
    ws.sheet_view.showGridLines = False

    return _xlsx_response(wb, filename)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/test_cash_flow_export.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add app/reports/statement_export.py tests/unit/test_cash_flow_export.py
git commit -m "feat(reports): cash_flow_lines + professional Excel builder"
```

---

### Task 3: View + Excel/Print routes + module-access key + screen template + nav + index card

**Files:**
- Modify: `app/reports/views.py` (the `generate_…` import near the top; add the `cash_flow` view + excel + print routes after `balance_sheet_print`, which ends at line 669)
- Modify: `app/users/module_access.py` (after the `balance_sheet` entry at lines 46-48)
- Create: `app/reports/templates/reports/cash_flow.html`
- Modify: `app/templates/base.html` (lines 1181-1185 — the under-development Cash Flow nav link)
- Modify: `app/reports/templates/reports/index.html` (add a card before line 119 `</div>` closing `.row`)
- Test: `tests/integration/test_cash_flow_views.py` (create)

**Interfaces:**
- Consumes: `generate_cash_flow` (Task 1); `build_cash_flow_xlsx`, `cash_flow_lines` (Task 2); `_is_params()` and `_bs_company_branch(branch_id)` (existing in `views.py`); `can_access_module` Jinja global; `MODULE_REGISTRY` gating via the global `before_request` hook.
- Produces: endpoints `reports.cash_flow`, `reports.cash_flow_export_excel`, `reports.cash_flow_print`; module key `cash_flow`.

> **Why all three routes here:** the screen template (`cash_flow.html`) builds Excel/Print links with `url_for('reports.cash_flow_export_excel')` / `reports.cash_flow_print`. If those endpoints did not exist, rendering the screen would raise `BuildError`. All three routes are registered in this task so the render test is green; the print route's template is created in Task 4 but is exercised only by Task 4's test.

- [ ] **Step 1: Write the failing integration tests**

Create `tests/integration/test_cash_flow_views.py`:

```python
from datetime import date
from decimal import Decimal
import pytest

from app import db
from app.accounts.models import Account
from app.journal_entries.models import JournalEntry, JournalEntryLine

pytestmark = [pytest.mark.integration]


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def _acct(code, name, atype, normal='Debit', parent=None):
    a = Account(code=code, name=name, account_type=atype, normal_balance=normal,
                is_active=True, parent_id=parent.id if parent else None)
    db.session.add(a)
    db.session.commit()
    return a


def _je(branch_id, lines, number):
    je = JournalEntry(entry_number=number, entry_date=date.today(), description='d',
                      reference=number, entry_type='adjustment', branch_id=branch_id,
                      status='posted', is_balanced=True, total_debit=Decimal('0'),
                      total_credit=Decimal('0'))
    db.session.add(je)
    db.session.flush()
    n = 1
    for acct, dr, cr in lines:
        db.session.add(JournalEntryLine(entry_id=je.id, line_number=n, account_id=acct.id,
                                        debit_amount=Decimal(str(dr)), credit_amount=Decimal(str(cr))))
        n += 1
    db.session.commit()
    return je


def _seed_cf(branch_id):
    ca = _acct('10000', 'CURRENT ASSETS', 'Asset')
    cash = _acct('10101', 'Cash on Hand', 'Asset', parent=ca)
    eq = _acct('30000', 'EQUITY', 'Equity', 'Credit')
    cap = _acct('30101', 'Capital Stock', 'Equity', 'Credit', parent=eq)
    _je(branch_id, [(cash, 1000, 0), (cap, 0, 1000)], 'CF1')


def test_cash_flow_requires_login(client):
    resp = client.get('/reports/cash-flow')
    assert resp.status_code in (302, 401)


def test_cash_flow_admin_renders(client, db_session, main_branch, admin_user):
    _seed_cf(main_branch.id)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/cash-flow')
    assert resp.status_code == 200
    body = resp.data
    assert b'CASH FLOWS FROM OPERATING ACTIVITIES' in body
    assert b'INVESTING' in body
    assert b'FINANCING' in body
    assert b'NET INCREASE' in body
    assert b'Reconciled' in body


def test_cash_flow_staff_without_grant_denied(client, db_session, main_branch, staff_user):
    staff_user.branches.append(main_branch)
    db_session.commit()
    _login(client, staff_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/cash-flow', follow_redirects=False)
    assert resp.status_code == 302


def test_cash_flow_staff_with_grant_allowed(client, db_session, main_branch, staff_user):
    perms = staff_user.get_book_permissions()
    perms['cash_flow'] = True
    staff_user.set_book_permissions(perms)
    staff_user.branches.append(main_branch)
    db_session.commit()
    _login(client, staff_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/cash-flow', follow_redirects=False)
    assert resp.status_code == 200


def test_cash_flow_viewer_allowed(client, db_session, main_branch, viewer_user):
    viewer_user.branches.append(main_branch)
    db_session.commit()
    _login(client, viewer_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/cash-flow', follow_redirects=False)
    assert resp.status_code == 200
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/integration/test_cash_flow_views.py -q`
Expected: FAIL (404 on `/reports/cash-flow` — route not yet registered).

- [ ] **Step 3: Add the `cash_flow` module-access key**

In `app/users/module_access.py`, after the `balance_sheet` entry (lines 46-48), insert:

```python
    {'key': 'cash_flow', 'label': 'Cash Flow', 'section': 'Ledger',
     'endpoints': ('reports.cash_flow', 'reports.cash_flow_export_excel',
                   'reports.cash_flow_print')},
```

- [ ] **Step 4: Import `generate_cash_flow` and add the view + Excel + Print routes**

In `app/reports/views.py`, add `generate_cash_flow` to the existing `from app.reports.financial import (...)` import (alongside `generate_balance_sheet`).

Then after `balance_sheet_print` (after line 669), add all three routes:

```python
@reports_bp.route('/reports/cash-flow')
@login_required
def cash_flow():
    start_date, end_date, branch_id = _is_params()
    cf = generate_cash_flow(start_date, end_date, branch_id=branch_id)
    return render_template('reports/cash_flow.html', cash_flow=cf,
                           start_date=start_date, end_date=end_date)


@reports_bp.route('/reports/cash-flow/export/excel')
@login_required
def cash_flow_export_excel():
    """Export the Statement of Cash Flows to a formatted Excel workbook."""
    from app.reports.statement_export import build_cash_flow_xlsx
    start_date, end_date, branch_id = _is_params()
    cf = generate_cash_flow(start_date, end_date, branch_id=branch_id)
    company, branch_name = _bs_company_branch(branch_id)
    period_label = f"{start_date.strftime('%B %d, %Y')} to {end_date.strftime('%B %d, %Y')}"
    filename = f'Cash_Flow_{start_date.isoformat()}_to_{end_date.isoformat()}.xlsx'
    return build_cash_flow_xlsx(cf, period_label, company, branch_name, filename)


@reports_bp.route('/reports/cash-flow/print')
@login_required
def cash_flow_print():
    from app.reports.statement_export import cash_flow_lines
    start_date, end_date, branch_id = _is_params()
    cf = generate_cash_flow(start_date, end_date, branch_id=branch_id)
    company, branch_name = _bs_company_branch(branch_id)
    return render_template('reports/cash_flow_print.html',
                           lines=cash_flow_lines(cf), start_date=start_date,
                           end_date=end_date, company=company, branch_name=branch_name)
```

- [ ] **Step 5: Create the screen template**

Create `app/reports/templates/reports/cash_flow.html`:

```html
{% extends "base.html" %}

{% block title %}Cash Flow{% endblock %}
{% block page_title %}Statement of Cash Flows{% endblock %}

{% block content %}
{% macro amt(v) %}<td style="text-align:right;font-family:var(--mono);">{% if v < 0 %}(₱{{ '{:,.2f}'.format(-v) }}){% else %}₱{{ '{:,.2f}'.format(v) }}{% endif %}</td>{% endmacro %}
<div class="card">
    <div class="card-header">
        <div>
            <div class="card-title">Statement of Cash Flows</div>
            <div class="card-sub">Indirect Method · {{ start_date.strftime('%B %d, %Y') }} to {{ end_date.strftime('%B %d, %Y') }}</div>
        </div>
        <div class="card-header-actions" style="display:flex;gap:8px;">
            <a href="{{ url_for('reports.cash_flow_export_excel', start_date=start_date.isoformat(), end_date=end_date.isoformat()) }}"
               class="btn btn-secondary">📊 Excel</a>
            <a href="{{ url_for('reports.cash_flow_print', start_date=start_date.isoformat(), end_date=end_date.isoformat()) }}"
               target="_blank" class="btn btn-secondary">Print</a>
            <button class="btn btn-secondary" onclick="showPeriodPicker()">📅 Change Period</button>
        </div>
    </div>

    <div class="card-body">
        <table class="table" style="margin:0;">
            <tbody>
                {% set op = cash_flow.operating %}
                <tr style="background:var(--bg);font-weight:700;"><td>CASH FLOWS FROM OPERATING ACTIVITIES</td><td></td></tr>
                <tr><td style="padding-left:24px;">Net Income (period)</td>{{ amt(op.net_income) }}</tr>
                {% if op.depreciation %}<tr><td style="padding-left:24px;">Add: Depreciation</td>{{ amt(op.depreciation) }}</tr>{% endif %}
                {% if op.working_capital %}
                <tr><td style="padding-left:24px;font-style:italic;color:var(--text-2);">Changes in operating assets and liabilities:</td><td></td></tr>
                {% for w in op.working_capital %}<tr><td style="padding-left:40px;">{{ w.name }}</td>{{ amt(w.amount) }}</tr>{% endfor %}
                {% endif %}
                <tr style="font-weight:700;border-top:1px solid var(--border);"><td>Net cash provided by/(used in) operating activities</td>{{ amt(op.total) }}</tr>

                {% for sec, label in [(cash_flow.investing, 'INVESTING'), (cash_flow.financing, 'FINANCING')] %}
                <tr style="background:var(--bg);font-weight:700;"><td>CASH FLOWS FROM {{ label }} ACTIVITIES</td><td></td></tr>
                {% for ln in sec.lines %}<tr><td style="padding-left:24px;">{{ ln.name }}</td>{{ amt(ln.amount) }}</tr>{% endfor %}
                <tr style="font-weight:700;border-top:1px solid var(--border);"><td>Net cash provided by/(used in) {{ label|lower }} activities</td>{{ amt(sec.total) }}</tr>
                {% endfor %}

                <tr style="font-weight:800;border-top:3px double var(--border);background:var(--bg);"><td>NET INCREASE/(DECREASE) IN CASH</td>{{ amt(cash_flow.net_change) }}</tr>
                <tr><td>Cash at beginning of period</td>{{ amt(cash_flow.cash_begin) }}</tr>
                <tr style="font-weight:700;border-bottom:3px double var(--border);"><td>Cash at end of period</td>{{ amt(cash_flow.cash_end) }}</tr>
            </tbody>
        </table>

        <div class="alert {% if cash_flow.is_reconciled %}alert-success{% else %}alert-danger{% endif %}"
             style="margin-top:24px;border-radius:8px;padding:16px;">
            {% if cash_flow.is_reconciled %}
            <strong>✅ Reconciled</strong> — net change in cash ties to ending minus beginning cash.
            {% else %}
            <strong>⚠️ Not Reconciled</strong> — difference of ₱{{ '{:,.2f}'.format(cash_flow.difference) }}. Please review journal entries.
            {% endif %}
        </div>
    </div>
</div>

<!-- Period Picker Modal -->
<div id="periodPicker" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:1000;align-items:center;justify-content:center;">
    <div style="background:var(--card);padding:30px;border-radius:8px;max-width:500px;width:90%;">
        <h3 style="margin-top:0;">Select Period</h3>
        <form action="{{ url_for('reports.cash_flow') }}" method="get">
            <div style="margin-bottom:20px;">
                <label for="start_date" style="display:block;margin-bottom:8px;font-weight:600;">Start Date:</label>
                <input type="date" id="start_date" name="start_date" value="{{ start_date.isoformat() }}"
                       style="width:100%;padding:10px;border:1px solid var(--border);border-radius:4px;font-family:inherit;">
            </div>
            <div style="margin-bottom:30px;">
                <label for="end_date" style="display:block;margin-bottom:8px;font-weight:600;">End Date:</label>
                <input type="date" id="end_date" name="end_date" value="{{ end_date.isoformat() }}"
                       style="width:100%;padding:10px;border:1px solid var(--border);border-radius:4px;font-family:inherit;">
            </div>
            <div style="display:flex;gap:10px;justify-content:flex-end;">
                <button type="button" class="btn btn-secondary" onclick="hidePeriodPicker()">Cancel</button>
                <button type="submit" class="btn btn-primary">Generate Report</button>
            </div>
        </form>
    </div>
</div>

<script>
function showPeriodPicker() { document.getElementById('periodPicker').style.display = 'flex'; }
function hidePeriodPicker() { document.getElementById('periodPicker').style.display = 'none'; }
document.getElementById('periodPicker').addEventListener('click', function (e) { if (e.target === this) hidePeriodPicker(); });
</script>
{% endblock %}
```

- [ ] **Step 6: Swap the Cash Flow nav link**

In `app/templates/base.html`, replace lines 1181-1185 (the `nav-item--soon` Cash Flow link) with:

```html
                    {% if can_access_module(current_user, 'cash_flow') %}
                    <a href="{{ url_for('reports.cash_flow') }}" class="nav-item {% if request.endpoint and request.endpoint.startswith('reports.cash_flow') %}active{% endif %}">
                        <span class="nav-icon">💸</span>
                        <span class="nav-text">Cash Flow</span>
                    </a>
                    {% endif %}
```

- [ ] **Step 7: Add the reports-index card**

In `app/reports/templates/reports/index.html`, immediately before the `</div>` on line 119 that closes `.row` (i.e. after the Balance Sheet card's closing `</div>` on line 118), insert:

```html
            <!-- Cash Flow Card -->
            <div class="col" style="flex: 1; min-width: 300px;">
                <div class="content-card" style="height: 100%;">
                    <div class="card-body">
                        <h3 style="margin-top: 0; color: var(--primary);">
                            <span style="font-size: 2rem;">💸</span>
                            Cash Flow
                        </h3>
                        <p class="text-muted" style="margin-bottom: 20px;">
                            Statement of Cash Flows (indirect method): operating, investing, and financing activities, reconciled to the change in cash. Export to Excel or print.
                        </p>
                        <a href="{{ url_for('reports.cash_flow') }}" class="btn btn-primary">
                            View Cash Flow
                        </a>
                    </div>
                </div>
            </div>
```

- [ ] **Step 8: Add the Excel-export integration test**

Append to `tests/integration/test_cash_flow_views.py`:

```python
def test_cash_flow_excel_export(client, db_session, main_branch, admin_user):
    _seed_cf(main_branch.id)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/cash-flow/export/excel')
    assert resp.status_code == 200
    assert 'spreadsheetml' in resp.headers['Content-Type']
```

- [ ] **Step 9: Run the integration tests to verify they pass**

Run: `pytest tests/integration/test_cash_flow_views.py -q`
Expected: PASS (6 passed). All routes resolve, the screen renders, and the Excel export returns a spreadsheet. (The `/reports/cash-flow/print` route exists but its template arrives in Task 4 — it is not exercised here.)

- [ ] **Step 10: Commit**

```bash
git add app/reports/views.py app/users/module_access.py app/reports/templates/reports/cash_flow.html app/templates/base.html app/reports/templates/reports/index.html tests/integration/test_cash_flow_views.py
git commit -m "feat(reports): activate Cash Flow view + Excel/Print routes + nav + index card"
```

---

### Task 4: Print template

**Files:**
- Create: `app/reports/templates/reports/cash_flow_print.html`
- Test: `tests/integration/test_cash_flow_views.py` (extend with one test)

**Interfaces:**
- Consumes: the `reports.cash_flow_print` route + `cash_flow_lines` (added in Tasks 2-3); renders from the `lines` list (`{kind, label, amount|None, indent, rule}`).
- Produces: the printable HTML for the Statement of Cash Flows.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_cash_flow_views.py`:

```python
def test_cash_flow_print_renders(client, db_session, main_branch, admin_user):
    from app.settings import AppSettings
    AppSettings.set_setting('company_name', 'ACME Trading Corp')
    _seed_cf(main_branch.id)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/cash-flow/print')
    assert resp.status_code == 200
    assert b'Statement of Cash Flows' in resp.data
    assert b'ACME Trading Corp' in resp.data
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/integration/test_cash_flow_views.py -k print -q`
Expected: FAIL (the `cash_flow_print` route raises `TemplateNotFound: reports/cash_flow_print.html`).

- [ ] **Step 3: Create the print template**

Create `app/reports/templates/reports/cash_flow_print.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Cash Flow</title>
    <style>
        body { font-family: Arial, sans-serif; font-size: 12px; color: #000; margin: 24px; }
        .company { font-size: 14px; font-weight: bold; }
        .meta { color: #333; margin: 2px 0 14px 0; }
        h1 { font-size: 16px; margin: 0 0 2px 0; }
        table { width: 100%; border-collapse: collapse; }
        td { padding: 3px 8px; }
        .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .colhead td { font-weight: bold; border-bottom: 1px solid #000; }
        .header td, .subtotal td, .net td, .total td { font-weight: bold; }
        .net td { font-size: 14px; }
        .subheader td { font-style: italic; }
        .indent td:first-child { padding-left: 28px; }
        .rule-bottom td { border-bottom: 1px solid #000; }
        .rule-top_bottom td { border-top: 1px solid #000; border-bottom: 1px solid #000; }
        .rule-double_bottom td { border-bottom: 3px double #000; }
    </style>
</head>
<body onload="window.print()">
    {% if company.name %}<div class="company">{{ company.name }}</div>{% endif %}
    <div class="meta">
        {% if company.tin %}TIN: {{ company.tin }} &nbsp; {% endif %}
        {% if company.address %}{{ company.address }}<br>{% endif %}
        {% if branch_name %}Branch: {{ branch_name }} &nbsp; {% endif %}
    </div>
    <h1>Statement of Cash Flows</h1>
    <div class="meta">Indirect Method &nbsp;·&nbsp; {{ start_date.strftime('%B %d, %Y') }} to {{ end_date.strftime('%B %d, %Y') }}</div>

    <table>
        <tbody>
            <tr class="colhead"><td>Particulars</td><td class="num">Amount</td></tr>
            {% for ln in lines %}
            <tr class="{{ ln.kind }}{% if ln.indent %} indent{% endif %}{% if ln.rule %} rule-{{ ln.rule }}{% endif %}">
                <td>{{ ln.label }}</td>
                <td class="num">{% if ln.amount is not none %}{% if ln.amount < 0 %}(₱{{ '{:,.2f}'.format(-ln.amount) }}){% else %}₱{{ '{:,.2f}'.format(ln.amount) }}{% endif %}{% endif %}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</body>
</html>
```

- [ ] **Step 4: Run the full Cash Flow view suite**

Run: `pytest tests/integration/test_cash_flow_views.py -q`
Expected: PASS (7 passed — the 6 from Task 3 plus the print test).

- [ ] **Step 5: Commit**

```bash
git add app/reports/templates/reports/cash_flow_print.html tests/integration/test_cash_flow_views.py
git commit -m "feat(reports): Cash Flow printable statement template"
```

---

## Final verification (after all tasks)

- [ ] Run the whole Cash Flow suite + the existing statement suites for regressions:

```bash
pytest tests/unit/test_cash_flow_generator.py tests/unit/test_cash_flow_export.py tests/integration/test_cash_flow_views.py tests/unit/test_balance_sheet_generator.py tests/integration/test_balance_sheet_views.py -q
```

- [ ] Manual (dev server on :5050, logged in): open `/reports/cash-flow` — three activity sections render with line items + subtotals, NET INCREASE/(DECREASE) IN CASH, beginning/ending cash, and a green ✅ Reconciled banner; the **Excel** download opens with live formulas and the **Print** view shows the BIR company header; the **Cash Flow** nav item (no longer "Soon") and the reports-index card both link through. Confirm the banner stays ✅ Reconciled on the real `cas_demo.db` data.

## Self-Review notes

- **Spec coverage:** generator + helpers (Task 1), `cash_flow_lines` + `build_cash_flow_xlsx` (Task 2), view + access key + screen + nav + index card (Task 3), excel + print routes + print template (Task 4). Reconciliation banner, depreciation add-back, `method='indirect'`-only guard, no-CSV, branch-hidden-when-single, design tokens, literal ₱ — all covered.
- **Type consistency:** `generate_cash_flow` return shape (Task 1) is consumed verbatim by `cash_flow_lines`/`build_cash_flow_xlsx` (Task 2) and the templates (Tasks 3-4). Endpoint names (`reports.cash_flow`, `reports.cash_flow_export_excel`, `reports.cash_flow_print`) match across the view, module-access key, nav link, and templates.
- **Cross-task render dependency** is called out explicitly in Task 3 Step 8 (the screen template references the Task 4 endpoints via `url_for`).
