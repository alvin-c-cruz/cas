# Cash Flow Statement — Direct Method Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the direct method to the Statement of Cash Flows as a method toggle on the same `/reports/cash-flow` page — actual-cash decomposition into Operating/Investing/Financing, a non-cash transactions disclosure note, and a PAS 7 net-income→operating-cash reconciliation note. The shipped indirect statement is unchanged.

**Architecture:** `generate_cash_flow(..., method='direct')` decomposes the period's actual cash (from cash-touching JEs) into the three activities by contra-account classification, lists non-cash investing/financing transactions in a note, and reuses the indirect Operating computation as the reconciliation note. Export + view + template branch on `method`. Indirect path stays byte-for-byte identical.

**Tech Stack:** Flask, SQLAlchemy, SQLite, openpyxl, Jinja2, pytest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-06-22-cash-flow-statement-direct-design.md`.
- **Indirect path unchanged.** `method='indirect'` returns the exact current dict (no `noncash`/`reconciliation` keys). `method not in ('indirect','direct')` → `ValueError`.
- **Direct = actual cash only.** All three sections computed from cash-touching JEs (`_is_cash` = name contains "cash"). Non-cash transactions excluded from sections, listed in `noncash`. Ties by construction: `net_change = operating+investing+financing = cash_end − cash_begin`.
- **Activity classification** (`_direct_activity`): Investing = `11…` excluding accumulated depreciation (name contains "depreciation"); Financing = `21…`/`30…`; Operating = everything else (catch-all).
- **Operating PFRS sub-lines** (`_direct_operating_subline`, first match wins): Taxes paid (name has `vat`/`withholding`/`wht`/`income tax`) → Cash received from customers (code `4…` or name has `receivable`) → Cash paid to suppliers (code `501…` or name has `payable`/`inventory`/`construction in progress`/`materials`) → Cash paid for operating expenses (code `5…`) → Other operating receipts/(payments).
- **Cash effect** of a contra line = `Σ(credit) − Σ(debit)` (inflow positive). Zero-total lines omitted.
- **UI:** one page, `?method=indirect|direct`; toggle; no new module-access key; Excel/Print carry the method; filename gains the method for direct.
- Design tokens only; literal `₱` (U+20B1); no JS popups; accounting format `#,##0.00;(#,##0.00)`; gridlines off; branch hidden when single branch.
- Read-only report — no audit-log assertions.
- Tests: `pytest`; fixtures `client`, `db_session`, `main_branch`, `admin_user`, `staff_user`, `viewer_user`.

---

### Task 1: Generator — `method='direct'` branch + classification helpers

**Files:**
- Modify: `app/reports/financial.py` (add helpers after line 329; edit `generate_cash_flow` guard at 351-352; rename its `return {` at line 443 to `indirect = {`; append the direct branch after the dict closes at line 460)
- Test: `tests/unit/test_cash_flow_generator.py` (append direct-method tests + a `_build_direct` helper)

**Interfaces:**
- Consumes: existing `_is_cash`, `_is_depreciation_name`, `generate_income_statement`, `Account`, `JournalEntry`, `JournalEntryLine`, `db`, `func`, `Decimal`.
- Produces: `generate_cash_flow(..., method='direct')` returning `{period_start, period_end, method:'direct', operating{lines:[{name,amount}],total}, investing{lines,total}, financing{lines,total}, noncash:[{description,amount}], reconciliation{net_income,depreciation,working_capital:[{name,amount}],total}, net_change, cash_begin, cash_end, is_reconciled, difference}`. Module helpers `_direct_activity(account)`, `_direct_operating_subline(account)`, constant `_DIRECT_SUBLINE_ORDER`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cash_flow_generator.py`:

```python
def _build_direct(db_session):
    b = _branch()
    ca = _acct('10000', 'CURRENT ASSETS', 'Asset')
    cash = _acct('10101', 'Cash on Hand', 'Asset', parent=ca)
    ar = _acct('10201', 'Accounts Receivable', 'Asset', parent=ca)
    nca = _acct('11000', 'NON-CURRENT ASSETS', 'Asset')
    equip = _acct('11110', 'Construction Equipment', 'Asset', parent=nca)
    cl = _acct('20000', 'CURRENT LIABILITIES', 'Liability', 'Credit')
    ap = _acct('20101', 'Accounts Payable', 'Liability', 'Credit', parent=cl)
    eq = _acct('30000', 'EQUITY', 'Equity', 'Credit')
    cap = _acct('30101', 'Capital Stock', 'Equity', 'Credit', parent=eq)
    rev = _acct('40101', 'Sales Revenue', 'Revenue', 'Credit')
    _je(b.id, [(equip, 2000, 0), (cap, 0, 2000)], 'D1')   # NON-CASH equipment-for-stock
    _je(b.id, [(cash, 500, 0), (rev, 0, 500)], 'D2')      # cash sale -> received from customers +500
    _je(b.id, [(ar, 300, 0), (rev, 0, 300)], 'D3')        # credit sale (non-cash) -> excluded
    _je(b.id, [(cash, 200, 0), (ar, 0, 200)], 'D4')       # collection -> received from customers +200
    _je(b.id, [(ap, 150, 0), (cash, 0, 150)], 'D5')       # pay supplier -> paid to suppliers -150
    return b


def test_direct_reconciles(db_session):
    b = _build_direct(db_session)
    cf = generate_cash_flow(START, END, branch_id=b.id, method='direct')
    assert cf['method'] == 'direct'
    assert cf['cash_end'] == 550.0 and cf['cash_begin'] == 0.0
    assert cf['net_change'] == 550.0
    assert cf['is_reconciled'] is True


def test_direct_sections_are_cash_only(db_session):
    b = _build_direct(db_session)
    cf = generate_cash_flow(START, END, branch_id=b.id, method='direct')
    # non-cash equipment-for-stock is excluded from the sections, shown in the note
    assert cf['investing']['lines'] == []
    assert cf['investing']['total'] == 0.0
    assert cf['financing']['lines'] == []
    assert cf['financing']['total'] == 0.0
    assert any(n['amount'] == 2000.0 for n in cf['noncash'])


def test_direct_operating_sublines(db_session):
    b = _build_direct(db_session)
    cf = generate_cash_flow(START, END, branch_id=b.id, method='direct')
    lines = {l['name']: l['amount'] for l in cf['operating']['lines']}
    assert lines['Cash received from customers'] == 700.0     # 500 sale + 200 collection
    assert lines['Cash paid to suppliers'] == -150.0
    assert cf['operating']['total'] == 550.0


def test_direct_reconciliation_note(db_session):
    b = _build_direct(db_session)
    cf = generate_cash_flow(START, END, branch_id=b.id, method='direct')
    rec = cf['reconciliation']
    assert rec['net_income'] == 800.0                          # revenue 500 + 300, no expense
    assert rec['total'] == cf['operating']['total']            # foots to operating cash (550)


def test_direct_guard_and_indirect_unchanged(db_session):
    b = _build_direct(db_session)
    with pytest.raises(ValueError):
        generate_cash_flow(START, END, branch_id=b.id, method='xyz')
    ind = generate_cash_flow(START, END, branch_id=b.id, method='indirect')
    assert ind['method'] == 'indirect'
    assert 'noncash' not in ind and 'reconciliation' not in ind
    assert set(ind['operating'].keys()) == {'net_income', 'depreciation', 'working_capital', 'total'}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/unit/test_cash_flow_generator.py -k direct -q`
Expected: FAIL — `ValueError: Only the indirect cash-flow method is implemented` (the current guard rejects `method='direct'`).

- [ ] **Step 3: Add the classification helpers**

In `app/reports/financial.py`, after `_is_depreciation_name` (line 329), add:

```python
_DIRECT_SUBLINE_ORDER = [
    'Cash received from customers',
    'Cash paid to suppliers',
    'Cash paid for operating expenses',
    'Taxes paid',
    'Other operating receipts/(payments)',
]


def _direct_activity(account):
    """Activity bucket for a non-cash contra account in the direct method."""
    code = account.code or ''
    if code.startswith('11') and not _is_depreciation_name(account):
        return 'investing'
    if code.startswith('21') or code.startswith('30'):
        return 'financing'
    return 'operating'   # 4x / 5x / 10x-ex-cash / 20x + any stray (catch-all)


def _direct_operating_subline(account):
    """PFRS operating sub-line for an operating contra account (first match wins)."""
    code = account.code or ''
    name = (account.name or '').lower()
    if any(t in name for t in ('vat', 'withholding', 'wht', 'income tax')):
        return 'Taxes paid'
    if code.startswith('4') or 'receivable' in name:
        return 'Cash received from customers'
    if code.startswith('501') or any(t in name for t in
                                      ('payable', 'inventory', 'construction in progress', 'materials')):
        return 'Cash paid to suppliers'
    if code.startswith('5'):
        return 'Cash paid for operating expenses'
    return 'Other operating receipts/(payments)'
```

- [ ] **Step 4: Widen the method guard**

In `generate_cash_flow`, replace lines 351-352:

```python
    if method != 'indirect':
        raise ValueError("Only the indirect cash-flow method is implemented")
```

with:

```python
    if method not in ('indirect', 'direct'):
        raise ValueError("Cash-flow method must be 'indirect' or 'direct'")
```

- [ ] **Step 5: Capture the indirect dict and add the direct branch**

In `generate_cash_flow`, change the final return (line 443) from `return {` to `indirect = {` (leave the dict body lines 444-460 exactly as they are). Then, immediately after the dict's closing `}` (line 460), append:

```python
    if method == 'indirect':
        return indirect

    # method == 'direct': decompose the period's ACTUAL cash into the three
    # activities from cash-touching JEs. Non-cash transactions (no cash line) are
    # excluded and listed in `noncash`. Ties to the cash movement by construction.
    acct_by_id = {a.id: a for a in accounts}
    cash_ids = [a.id for a in accounts if _is_cash(a)]

    op_buckets = {k: Decimal('0.00') for k in _DIRECT_SUBLINE_ORDER}
    inv_by_acct, fin_by_acct = {}, {}
    if cash_ids:
        cash_je_ids = db.session.query(JournalEntryLine.entry_id).join(JournalEntry).filter(
            JournalEntry.status == 'posted',
            JournalEntry.entry_date >= start_date,
            JournalEntry.entry_date <= end_date,
            JournalEntryLine.account_id.in_(cash_ids),
            *branch_filter
        ).distinct()
        contra = db.session.query(
            JournalEntryLine.account_id,
            (func.coalesce(func.sum(JournalEntryLine.credit_amount), 0)
             - func.coalesce(func.sum(JournalEntryLine.debit_amount), 0)).label('eff'),
        ).filter(
            JournalEntryLine.entry_id.in_(cash_je_ids),
            ~JournalEntryLine.account_id.in_(cash_ids),
        ).group_by(JournalEntryLine.account_id).all()
        for account_id, eff in contra:
            a = acct_by_id.get(account_id)
            if a is None:
                continue
            effect = Decimal(str(eff))
            activity = _direct_activity(a)
            if activity == 'investing':
                inv_by_acct[a.id] = (a, effect)
            elif activity == 'financing':
                fin_by_acct[a.id] = (a, effect)
            else:
                op_buckets[_direct_operating_subline(a)] += effect

    operating_lines = [{'name': k, 'amount': float(op_buckets[k])}
                       for k in _DIRECT_SUBLINE_ORDER if op_buckets[k] != 0]
    operating_dtotal = sum(op_buckets.values(), Decimal('0.00'))

    investing_dlines, investing_dtotal = [], Decimal('0.00')
    for a, eff in sorted(inv_by_acct.values(), key=lambda x: x[0].code or ''):
        if eff != 0:
            investing_dlines.append({'name': '(Acquisition)/disposal of ' + a.name,
                                     'amount': float(eff)})
            investing_dtotal += eff
    financing_dlines, financing_dtotal = [], Decimal('0.00')
    for a, eff in sorted(fin_by_acct.values(), key=lambda x: x[0].code or ''):
        if eff != 0:
            financing_dlines.append({'name': a.name, 'amount': float(eff)})
            financing_dtotal += eff

    # Non-cash investing & financing transactions: posted in-period branch JEs
    # not touching cash that hit a real investing (11x non-accum-depr) or
    # financing (21x/30x) account. (Depreciation entries hit only accumulated
    # depreciation among 11x accounts, so they do not qualify.)
    noncash = []
    invfin_ids = [a.id for a in accounts
                  if ((a.code or '').startswith('11') and not _is_depreciation_name(a))
                  or (a.code or '').startswith('21') or (a.code or '').startswith('30')]
    if invfin_ids:
        cash_je_set = set()
        if cash_ids:
            cash_je_set = {r[0] for r in db.session.query(JournalEntryLine.entry_id).filter(
                JournalEntryLine.account_id.in_(cash_ids)).distinct()}
        cand = db.session.query(JournalEntry).join(JournalEntryLine).filter(
            JournalEntry.status == 'posted',
            JournalEntry.entry_date >= start_date,
            JournalEntry.entry_date <= end_date,
            JournalEntryLine.account_id.in_(invfin_ids),
            *branch_filter
        ).distinct().all()
        for je in sorted(cand, key=lambda j: j.id):
            if je.id in cash_je_set:
                continue
            gross = db.session.query(
                func.coalesce(func.sum(JournalEntryLine.debit_amount), 0)
            ).filter(JournalEntryLine.entry_id == je.id).scalar()
            noncash.append({'description': je.description or je.reference or f'JE {je.id}',
                            'amount': float(gross or 0)})

    net_change_d = operating_dtotal + investing_dtotal + financing_dtotal
    diff_d = abs(net_change_d - (cash_end - cash_begin))
    return {
        'period_start': start_date,
        'period_end': end_date,
        'method': 'direct',
        'operating': {'lines': operating_lines, 'total': float(operating_dtotal)},
        'investing': {'lines': investing_dlines, 'total': float(investing_dtotal)},
        'financing': {'lines': financing_dlines, 'total': float(financing_dtotal)},
        'noncash': noncash,
        'reconciliation': indirect['operating'],
        'net_change': float(net_change_d),
        'cash_begin': float(cash_begin),
        'cash_end': float(cash_end),
        'is_reconciled': bool(diff_d < Decimal('0.01')),
        'difference': float(diff_d),
    }
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/unit/test_cash_flow_generator.py -q`
Expected: PASS — the original indirect tests plus the 5 new direct tests (12 passed).

- [ ] **Step 7: Commit**

```bash
git add app/reports/financial.py tests/unit/test_cash_flow_generator.py
git commit -m "feat(reports): direct-method cash-flow generator (actual-cash decomposition + non-cash note)"
```

---

### Task 2: Export — direct branch in `cash_flow_lines` + `build_cash_flow_xlsx`

**Files:**
- Modify: `app/reports/statement_export.py` (refactor `cash_flow_lines` to share an investing/financing/net/cash tail helper; add the direct branch; branch `build_cash_flow_xlsx` on method)
- Test: `tests/unit/test_cash_flow_export.py` (append direct tests)

**Interfaces:**
- Consumes: the `method='direct'` dict from Task 1; existing `_NUM_FMT`, `_xlsx_response`, `Workbook`, `Font`, `Alignment`, `Border`, `Side`.
- Produces: `cash_flow_lines(cf)` (method-aware) + a private `_cf_invfin_net_cash_lines(cf)` helper; `build_cash_flow_xlsx(...)` (method-aware). Direct line kinds reuse the existing set (`header`/`account`/`subheader`/`subtotal`/`net`/`total`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cash_flow_export.py`:

```python
DIRECT_CF = {
    'method': 'direct',
    'operating': {'lines': [{'name': 'Cash received from customers', 'amount': 700.0},
                            {'name': 'Cash paid to suppliers', 'amount': -150.0}],
                  'total': 550.0},
    'investing': {'lines': [], 'total': 0.0},
    'financing': {'lines': [], 'total': 0.0},
    'noncash': [{'description': 'Equipment acquired via capital stock', 'amount': 2000.0}],
    'reconciliation': {'net_income': 800.0, 'depreciation': 0.0,
                       'working_capital': [{'name': '(Increase)/decrease in Accounts Receivable',
                                            'amount': -100.0}],
                       'total': 550.0},
    'net_change': 550.0, 'cash_begin': 0.0, 'cash_end': 550.0,
}


def test_direct_lines_cover_sections_note_and_reconciliation():
    labels = [ln['label'] for ln in cash_flow_lines(DIRECT_CF)]
    assert 'CASH FLOWS FROM OPERATING ACTIVITIES' in labels
    assert 'Cash received from customers' in labels
    assert 'CASH FLOWS FROM INVESTING ACTIVITIES' in labels
    assert 'CASH FLOWS FROM FINANCING ACTIVITIES' in labels
    assert 'NET INCREASE/(DECREASE) IN CASH' in labels
    assert 'Non-cash investing and financing transactions' in labels
    assert 'Equipment acquired via capital stock' in labels
    assert 'Reconciliation of net income to net cash from operating activities' in labels
    assert 'Net Income (period)' in labels


def test_direct_omits_noncash_block_when_empty():
    cf = {**DIRECT_CF, 'noncash': []}
    labels = [ln['label'] for ln in cash_flow_lines(cf)]
    assert 'Non-cash investing and financing transactions' not in labels
    # reconciliation note still present
    assert 'Reconciliation of net income to net cash from operating activities' in labels
```

(The existing indirect `cash_flow_lines` tests stay and must still pass — the refactor must not change indirect output.)

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/unit/test_cash_flow_export.py -k direct -q`
Expected: FAIL — `cash_flow_lines` currently assumes the indirect shape and emits no `Reconciliation…`/`Non-cash…` rows (KeyError on `op['net_income']` or missing labels).

- [ ] **Step 3: Refactor `cash_flow_lines` + add the direct branch**

In `app/reports/statement_export.py`, replace the whole `cash_flow_lines` function (lines 323-360) with:

```python
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
```

- [ ] **Step 4: Run the export tests to verify they pass**

Run: `pytest tests/unit/test_cash_flow_export.py -q`
Expected: PASS — the existing indirect tests (unchanged output via the shared tail helper) + the 2 new direct tests.

- [ ] **Step 5: Branch `build_cash_flow_xlsx` on method**

In `app/reports/statement_export.py`, replace the whole `build_cash_flow_xlsx` function (lines 363-460) with:

```python
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
```

- [ ] **Step 6: Run the export tests again (full file)**

Run: `pytest tests/unit/test_cash_flow_export.py -q`
Expected: PASS (indirect + direct line tests; the xlsx builder is exercised end-to-end by the integration test in Task 3).

- [ ] **Step 7: Commit**

```bash
git add app/reports/statement_export.py tests/unit/test_cash_flow_export.py
git commit -m "feat(reports): direct-method cash-flow lines + Excel (non-cash + reconciliation notes)"
```

---

### Task 3: Views + templates — method toggle, direct render, notes

**Files:**
- Modify: `app/reports/views.py` (add `_cf_method()`; pass method through `cash_flow`, `cash_flow_export_excel`, `cash_flow_print`; method in filename)
- Modify: `app/reports/templates/reports/cash_flow.html` (toggle + method branch + notes)
- Modify: `app/reports/templates/reports/cash_flow_print.html` (method label)
- Test: `tests/integration/test_cash_flow_views.py` (append direct tests)

**Interfaces:**
- Consumes: `generate_cash_flow(..., method=...)` (Task 1); `cash_flow_lines` / `build_cash_flow_xlsx` (Task 2); existing `_is_params()`, `_bs_company_branch()`, `request`.
- Produces: `?method=` handling on the three endpoints; method-aware screen + print.

- [ ] **Step 1: Write the failing integration tests**

Append to `tests/integration/test_cash_flow_views.py` (reuse the existing `_login`, `_select_branch`, `_acct`, `_je`, `_seed_cf` helpers):

```python
def _seed_cf_direct(branch_id):
    ca = _acct('10000', 'CURRENT ASSETS', 'Asset')
    cash = _acct('10101', 'Cash on Hand', 'Asset', parent=ca)
    nca = _acct('11000', 'NON-CURRENT ASSETS', 'Asset')
    equip = _acct('11110', 'Construction Equipment', 'Asset', parent=nca)
    eq = _acct('30000', 'EQUITY', 'Equity', 'Credit')
    cap = _acct('30101', 'Capital Stock', 'Equity', 'Credit', parent=eq)
    rev = _acct('40101', 'Sales Revenue', 'Revenue', 'Credit')
    _je(branch_id, [(equip, 2000, 0), (cap, 0, 2000)], 'DC1')   # non-cash -> note
    _je(branch_id, [(cash, 500, 0), (rev, 0, 500)], 'DC2')      # cash sale


def test_cash_flow_direct_renders(client, db_session, main_branch, admin_user):
    _seed_cf_direct(main_branch.id)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/cash-flow?method=direct')
    assert resp.status_code == 200
    body = resp.data
    assert b'Direct Method' in body
    assert b'Cash received from customers' in body
    assert b'Non-cash' in body
    assert b'Reconciliation of net income' in body


def test_cash_flow_toggle_links_present(client, db_session, main_branch, admin_user):
    _seed_cf_direct(main_branch.id)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/cash-flow?method=direct')
    assert b'method=indirect' in resp.data and b'method=direct' in resp.data


def test_cash_flow_direct_excel(client, db_session, main_branch, admin_user):
    _seed_cf_direct(main_branch.id)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/cash-flow/export/excel?method=direct')
    assert resp.status_code == 200
    assert 'spreadsheetml' in resp.headers['Content-Type']
    assert 'Direct' in resp.headers['Content-Disposition']


def test_cash_flow_direct_print(client, db_session, main_branch, admin_user):
    from app.settings import AppSettings
    AppSettings.set_setting('company_name', 'ACME Trading Corp')
    _seed_cf_direct(main_branch.id)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/cash-flow/print?method=direct')
    assert resp.status_code == 200
    assert b'Direct Method' in resp.data


def test_cash_flow_default_is_indirect(client, db_session, main_branch, admin_user):
    _seed_cf_direct(main_branch.id)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/cash-flow')
    assert resp.status_code == 200
    assert b'Indirect Method' in resp.data
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/integration/test_cash_flow_views.py -k "direct or toggle or default_is_indirect" -q`
Expected: FAIL — the view ignores `method`, always renders indirect (no `Direct Method` / toggle / notes).

- [ ] **Step 3: Add `_cf_method()` and thread it through the three routes**

In `app/reports/views.py`, add a helper just above the `cash_flow` view (before line 673):

```python
def _cf_method():
    """Validated cash-flow method from the query string (default 'indirect')."""
    m = request.args.get('method', 'indirect')
    return m if m in ('indirect', 'direct') else 'indirect'
```

Replace the three cash-flow routes (lines 673-704) with:

```python
@reports_bp.route('/reports/cash-flow')
@login_required
def cash_flow():
    start_date, end_date, branch_id = _is_params()
    method = _cf_method()
    cf = generate_cash_flow(start_date, end_date, branch_id=branch_id, method=method)
    return render_template('reports/cash_flow.html', cash_flow=cf, method=method,
                           start_date=start_date, end_date=end_date)


@reports_bp.route('/reports/cash-flow/export/excel')
@login_required
def cash_flow_export_excel():
    """Export the Statement of Cash Flows to a formatted Excel workbook."""
    from app.reports.statement_export import build_cash_flow_xlsx
    start_date, end_date, branch_id = _is_params()
    method = _cf_method()
    cf = generate_cash_flow(start_date, end_date, branch_id=branch_id, method=method)
    company, branch_name = _bs_company_branch(branch_id)
    period_label = f"{start_date.strftime('%B %d, %Y')} to {end_date.strftime('%B %d, %Y')}"
    tag = 'Direct' if method == 'direct' else 'Indirect'
    filename = f'Cash_Flow_{tag}_{start_date.isoformat()}_to_{end_date.isoformat()}.xlsx'
    return build_cash_flow_xlsx(cf, period_label, company, branch_name, filename)


@reports_bp.route('/reports/cash-flow/print')
@login_required
def cash_flow_print():
    from app.reports.statement_export import cash_flow_lines
    start_date, end_date, branch_id = _is_params()
    method = _cf_method()
    cf = generate_cash_flow(start_date, end_date, branch_id=branch_id, method=method)
    company, branch_name = _bs_company_branch(branch_id)
    return render_template('reports/cash_flow_print.html',
                           lines=cash_flow_lines(cf), method=method, start_date=start_date,
                           end_date=end_date, company=company, branch_name=branch_name)
```

- [ ] **Step 4: Rewrite the screen template with the toggle + method branch**

Replace `app/reports/templates/reports/cash_flow.html` entirely with:

```html
{% extends "base.html" %}

{% block title %}Cash Flow{% endblock %}
{% block page_title %}Statement of Cash Flows{% endblock %}

{% block content %}
{% macro amt(v) %}<td style="text-align:right;font-family:var(--mono);">{% if v < 0 %}(₱{{ '{:,.2f}'.format(-v) }}){% else %}₱{{ '{:,.2f}'.format(v) }}{% endif %}</td>{% endmacro %}
{% macro section(title, sec) %}
<tr style="background:var(--bg);font-weight:700;"><td>{{ title }}</td><td></td></tr>
{% for ln in sec.lines %}<tr><td style="padding-left:24px;">{{ ln.name }}</td>{{ amt(ln.amount) }}</tr>{% endfor %}
<tr style="font-weight:700;border-top:1px solid var(--border);"><td>Net cash provided by/(used in) {{ title.split(' ')[-2]|lower }} activities</td>{{ amt(sec.total) }}</tr>
{% endmacro %}
<div class="card">
    <div class="card-header">
        <div>
            <div class="card-title">Statement of Cash Flows</div>
            <div class="card-sub">{{ 'Direct' if method == 'direct' else 'Indirect' }} Method · {{ start_date.strftime('%B %d, %Y') }} to {{ end_date.strftime('%B %d, %Y') }}</div>
        </div>
        <div class="card-header-actions" style="display:flex;gap:8px;">
            <a href="{{ url_for('reports.cash_flow_export_excel', method=method, start_date=start_date.isoformat(), end_date=end_date.isoformat()) }}"
               class="btn btn-secondary">📊 Excel</a>
            <a href="{{ url_for('reports.cash_flow_print', method=method, start_date=start_date.isoformat(), end_date=end_date.isoformat()) }}"
               target="_blank" class="btn btn-secondary">Print</a>
            <button class="btn btn-secondary" onclick="showPeriodPicker()">📅 Change Period</button>
        </div>
    </div>

    <div class="card-body">
        <div style="display:inline-flex;border:1px solid var(--border);border-radius:8px;overflow:hidden;margin-bottom:16px;">
            <a href="{{ url_for('reports.cash_flow', method='indirect', start_date=start_date.isoformat(), end_date=end_date.isoformat()) }}"
               class="btn {{ 'btn-primary' if method != 'direct' else 'btn-secondary' }}" style="border-radius:0;">Indirect</a>
            <a href="{{ url_for('reports.cash_flow', method='direct', start_date=start_date.isoformat(), end_date=end_date.isoformat()) }}"
               class="btn {{ 'btn-primary' if method == 'direct' else 'btn-secondary' }}" style="border-radius:0;">Direct</a>
        </div>

        <table class="table" style="margin:0;">
            <tbody>
                {% if method == 'direct' %}
                {{ section('CASH FLOWS FROM OPERATING ACTIVITIES', cash_flow.operating) }}
                {{ section('CASH FLOWS FROM INVESTING ACTIVITIES', cash_flow.investing) }}
                {{ section('CASH FLOWS FROM FINANCING ACTIVITIES', cash_flow.financing) }}
                {% else %}
                {% set op = cash_flow.operating %}
                <tr style="background:var(--bg);font-weight:700;"><td>CASH FLOWS FROM OPERATING ACTIVITIES</td><td></td></tr>
                <tr><td style="padding-left:24px;">Net Income (period)</td>{{ amt(op.net_income) }}</tr>
                {% if op.depreciation %}<tr><td style="padding-left:24px;">Add: Depreciation</td>{{ amt(op.depreciation) }}</tr>{% endif %}
                {% if op.working_capital %}
                <tr><td style="padding-left:24px;font-style:italic;color:var(--text-2);">Changes in operating assets and liabilities:</td><td></td></tr>
                {% for w in op.working_capital %}<tr><td style="padding-left:40px;">{{ w.name }}</td>{{ amt(w.amount) }}</tr>{% endfor %}
                {% endif %}
                <tr style="font-weight:700;border-top:1px solid var(--border);"><td>Net cash provided by/(used in) operating activities</td>{{ amt(op.total) }}</tr>
                {{ section('CASH FLOWS FROM INVESTING ACTIVITIES', cash_flow.investing) }}
                {{ section('CASH FLOWS FROM FINANCING ACTIVITIES', cash_flow.financing) }}
                {% endif %}

                <tr style="font-weight:800;border-top:3px double var(--border);background:var(--bg);"><td>NET INCREASE/(DECREASE) IN CASH</td>{{ amt(cash_flow.net_change) }}</tr>
                <tr><td>Cash at beginning of period</td>{{ amt(cash_flow.cash_begin) }}</tr>
                <tr style="font-weight:700;border-bottom:3px double var(--border);"><td>Cash at end of period</td>{{ amt(cash_flow.cash_end) }}</tr>
            </tbody>
        </table>

        {% if method == 'direct' and cash_flow.noncash %}
        <table class="table" style="margin:24px 0 0 0;">
            <tbody>
                <tr style="font-weight:700;"><td colspan="2">Non-cash investing and financing transactions</td></tr>
                {% for n in cash_flow.noncash %}<tr><td style="padding-left:24px;">{{ n.description }}</td>{{ amt(n.amount) }}</tr>{% endfor %}
            </tbody>
        </table>
        {% endif %}

        {% if method == 'direct' %}
        {% set rec = cash_flow.reconciliation %}
        <table class="table" style="margin:24px 0 0 0;">
            <tbody>
                <tr style="font-weight:700;"><td colspan="2">Reconciliation of net income to net cash from operating activities</td></tr>
                <tr><td style="padding-left:24px;">Net Income (period)</td>{{ amt(rec.net_income) }}</tr>
                {% if rec.depreciation %}<tr><td style="padding-left:24px;">Add: Depreciation</td>{{ amt(rec.depreciation) }}</tr>{% endif %}
                {% for w in rec.working_capital %}<tr><td style="padding-left:24px;">{{ w.name }}</td>{{ amt(w.amount) }}</tr>{% endfor %}
                <tr style="font-weight:700;border-top:1px solid var(--border);"><td>Net cash from operating activities</td>{{ amt(rec.total) }}</tr>
            </tbody>
        </table>
        {% endif %}

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
            <input type="hidden" name="method" value="{{ method }}">
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

Note: the `section()` macro's subtotal label derives the activity word from the title (`'CASH FLOWS FROM INVESTING ACTIVITIES'.split(' ')[-2]` → `INVESTING` → lower → "investing"). This matches the indirect template's wording exactly.

- [ ] **Step 5: Add the method label to the print template**

In `app/reports/templates/reports/cash_flow_print.html`, find the line:

```html
    <div class="meta">Indirect Method &nbsp;·&nbsp; {{ start_date.strftime('%B %d, %Y') }} to {{ end_date.strftime('%B %d, %Y') }}</div>
```

and replace `Indirect Method` with `{{ 'Direct' if method == 'direct' else 'Indirect' }} Method`:

```html
    <div class="meta">{{ 'Direct' if method == 'direct' else 'Indirect' }} Method &nbsp;·&nbsp; {{ start_date.strftime('%B %d, %Y') }} to {{ end_date.strftime('%B %d, %Y') }}</div>
```

- [ ] **Step 6: Run the integration tests to verify they pass**

Run: `pytest tests/integration/test_cash_flow_views.py -q`
Expected: PASS — the existing indirect view tests + the 5 new direct tests.

- [ ] **Step 7: Commit**

```bash
git add app/reports/views.py app/reports/templates/reports/cash_flow.html app/reports/templates/reports/cash_flow_print.html tests/integration/test_cash_flow_views.py
git commit -m "feat(reports): Cash Flow direct/indirect method toggle + direct render + notes"
```

---

## Final verification (after all tasks)

- [ ] Run the whole Cash Flow suite + a regression check on the other statements:

```bash
pytest tests/unit/test_cash_flow_generator.py tests/unit/test_cash_flow_export.py tests/integration/test_cash_flow_views.py tests/unit/test_balance_sheet_generator.py tests/integration/test_balance_sheet_views.py -q
```

- [ ] Manual (dev server on :5050, logged in): open `/reports/cash-flow`, click the **Direct** toggle. Operating shows "Cash received from customers / paid to suppliers / …"; Investing & Financing show only cash lines (the ₱2,000,000 equipment-for-stock is NOT in them); a **Non-cash investing and financing transactions** note lists the ₱2,000,000; a **Reconciliation of net income** note foots to the operating cash subtotal; the banner is green. The **Excel** download (filename contains `Direct`) opens with live formulas and both notes; **Print** shows "Direct Method". Toggling back to **Indirect** shows the original statement unchanged.

## Self-Review notes

- **Spec coverage:** generator direct branch + helpers + non-cash note (Task 1); export direct lines + Excel + reconciliation/non-cash blocks (Task 2); `_cf_method()` + 3 routes + toggle + direct render + notes + print label (Task 3). Indirect-unchanged regression guarded in Task 1 (`test_direct_guard_and_indirect_unchanged`) and Task 2 (existing indirect line tests).
- **Type consistency:** the `method='direct'` dict shape from Task 1 (`operating/investing/financing.lines`, `noncash`, `reconciliation`) is consumed verbatim by Task 2's `cash_flow_lines`/`build_cash_flow_xlsx` and Task 3's template. Endpoint names and the `method` query param are consistent across views, templates, and tests.
- **No duplication:** the investing/financing/net/cash tail is factored into `_cf_invfin_net_cash_lines` (shared by both `cash_flow_lines` branches); the xlsx builder keeps one function with a method branch only where the operating section genuinely differs.
- **Ties by construction:** direct `net_change = operating+investing+financing`, all from the same cash decomposition = cash movement = `cash_end − cash_begin`; `test_direct_reconciles` asserts it.
