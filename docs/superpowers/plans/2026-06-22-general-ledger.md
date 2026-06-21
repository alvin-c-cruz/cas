# General Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Activate the General Ledger nav stub as a read-only, branch-scoped all-accounts ledger book (per-account opening + running balance, source-doc drill-down, date/account filters, Excel/CSV/print).

**Architecture:** Extend the existing `reports` blueprint and `app/reports/financial.py`, mirroring the Trial Balance / AR-AP-aging patterns. A pure data generator reads posted `JournalEntry`/`JournalEntryLine` rows; the view enriches each line with a source-document link, renders the book, and serves exports. Access is gated by adding a `general_ledger` key to the existing `book_permissions` module registry (staff-only gating; admin/accountant/viewer always allowed) — no new model, no migration.

**Tech Stack:** Flask, SQLAlchemy, SQLite, Jinja2, openpyxl (via `app/utils/export.py`), Choices.js (`initSearchSelect`), pytest.

## Global Constraints

- **No new models / migrations** — this feature is read-only over existing data. (If any model change is ever proposed, it needs explicit user approval first; none is needed here.)
- **Time:** use PHT helpers from `app.utils` if a timestamp is ever needed; never naive `datetime.now()`. Dates here are plain `date` objects from request params.
- **Money in templates:** use the literal `₱` (U+20B1) glyph, never `&#8369;`.
- **No hardcoded styling** in templates — use design tokens / CSS variables already in `style.css` (`--text-2`, `--border`, `--bg`, `--card`, `--blue`, `--red`, `--radius`, etc.).
- **Responsive** on desktop/tablet/mobile.
- **No JavaScript popups** (`confirm`/`alert`/`prompt`) — not needed here anyway (read-only).
- **Static cache-buster:** if any file under `app/static/` is edited, bump `?v=N` on every template `<link>`/`<script>` that loads it. (This plan adds no new static file; the account picker reuses existing `cas-ui.js`/`initSearchSelect`.)
- **TDD:** write the failing test first for every task; commit after each green task.
- **Audit:** the GL performs no writes, so the audit-in-tests rule does not apply (nothing to audit).
- **Access consistency:** GL routes use `@login_required` only and rely on the global `before_request` module gate (same as `reports.ar_aging`/`reports.ap_aging`). Do **not** add `accountant_or_admin_required` — that would wrongly block viewers.

---

### Task 1: General Ledger data generator

**Files:**
- Modify: `app/reports/financial.py` (add `generate_general_ledger`)
- Test: `tests/unit/test_general_ledger.py` (create)

**Interfaces:**
- Consumes: `Account` (`app.accounts.models`), `JournalEntry`, `JournalEntryLine` (`app.journal_entries.models`), `db` (`app`).
- Produces:
  ```
  generate_general_ledger(start_date: date, end_date: date, branch_id: int,
                          account_id: int | None = None) -> dict
  ```
  Return dict:
  ```
  {
    'start_date': date, 'end_date': date,
    'accounts': [
      {'code': str, 'name': str, 'account_type': str,
       'opening_balance': float,          # debit-positive (debit − credit)
       'lines': [
         {'entry_id': int, 'entry_number': str, 'entry_date': date,
          'entry_type': str, 'reference': str|None, 'description': str,
          'debit': float, 'credit': float, 'running_balance': float},  # debit-positive
       ],
       'total_debit': float, 'total_credit': float, 'closing_balance': float},
    ],
    'grand_total_debit': float, 'grand_total_credit': float,
  }
  ```
  Rules: posted entries only; branch-scoped; opening = Σ(debit−credit) for entry_date < start_date; in-range lines ordered by (entry_date, entry_number, line_number) with a running balance; an account with `opening_balance == 0` and no in-range lines is omitted (this naturally drops non-postable parent accounts). `description` is the line's own description, falling back to the entry description.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_general_ledger.py`:

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


def _branch(name='Main', code='MAIN'):
    b = Branch(name=name, code=code)
    db.session.add(b)
    db.session.commit()
    return b


def _acct(code, name, atype='Asset', normal='Debit'):
    a = Account(code=code, name=name, account_type=atype,
                normal_balance=normal, is_active=True)
    db.session.add(a)
    db.session.commit()
    return a


def _entry(branch_id, entry_date, number, lines, status='posted',
           entry_type='adjustment', reference=None):
    """lines: list of (account, debit, credit)."""
    je = JournalEntry(entry_number=number, entry_date=entry_date,
                      description='desc ' + number, reference=reference or number,
                      entry_type=entry_type, branch_id=branch_id, status=status,
                      is_balanced=True, total_debit=Decimal('0'), total_credit=Decimal('0'))
    db.session.add(je)
    db.session.flush()
    n = 1
    for acct, dr, cr in lines:
        db.session.add(JournalEntryLine(
            entry_id=je.id, line_number=n, account_id=acct.id,
            debit_amount=Decimal(str(dr)), credit_amount=Decimal(str(cr)),
            description=f'{number} line {n}'))
        n += 1
    je.total_debit = sum((Decimal(str(d)) for _, d, _ in lines), Decimal('0'))
    je.total_credit = sum((Decimal(str(c)) for _, _, c in lines), Decimal('0'))
    db.session.commit()
    return je


def test_opening_balance_sums_only_prior_posted_lines(db_session):
    b = _branch()
    cash = _acct('1001', 'Cash')
    rev = _acct('4001', 'Revenue', 'Income', 'Credit')
    # prior: cash +1000
    _entry(b.id, date(2026, 5, 31), 'JE-1', [(cash, 1000, 0), (rev, 0, 1000)])
    gl = generate_general_ledger(date(2026, 6, 1), date(2026, 6, 30), b.id)
    cash_sec = next(a for a in gl['accounts'] if a['code'] == '1001')
    assert cash_sec['opening_balance'] == 1000.0
    assert cash_sec['lines'] == []  # no in-range movement


def test_running_balance_accumulates_and_equals_closing(db_session):
    b = _branch()
    cash = _acct('1001', 'Cash')
    rev = _acct('4001', 'Revenue', 'Income', 'Credit')
    _entry(b.id, date(2026, 6, 5), 'JE-1', [(cash, 500, 0), (rev, 0, 500)])
    _entry(b.id, date(2026, 6, 9), 'JE-2', [(cash, 0, 200), (rev, 200, 0)])
    gl = generate_general_ledger(date(2026, 6, 1), date(2026, 6, 30), b.id)
    cash_sec = next(a for a in gl['accounts'] if a['code'] == '1001')
    assert [l['running_balance'] for l in cash_sec['lines']] == [500.0, 300.0]
    assert cash_sec['closing_balance'] == 300.0
    assert cash_sec['total_debit'] == 500.0
    assert cash_sec['total_credit'] == 200.0


def test_hide_empty_skips_zero_no_movement_keeps_opening_only(db_session):
    b = _branch()
    cash = _acct('1001', 'Cash')
    rev = _acct('4001', 'Revenue', 'Income', 'Credit')
    _acct('1002', 'Unused Bank')  # never touched -> omitted
    _entry(b.id, date(2026, 5, 1), 'JE-1', [(cash, 1000, 0), (rev, 0, 1000)])
    gl = generate_general_ledger(date(2026, 6, 1), date(2026, 6, 30), b.id)
    codes = [a['code'] for a in gl['accounts']]
    assert '1002' not in codes      # zero opening + no movement -> skipped
    assert '1001' in codes          # opening-only account is kept


def test_account_id_filter_returns_single_account(db_session):
    b = _branch()
    cash = _acct('1001', 'Cash')
    rev = _acct('4001', 'Revenue', 'Income', 'Credit')
    _entry(b.id, date(2026, 6, 5), 'JE-1', [(cash, 500, 0), (rev, 0, 500)])
    gl = generate_general_ledger(date(2026, 6, 1), date(2026, 6, 30), b.id, account_id=cash.id)
    assert [a['code'] for a in gl['accounts']] == ['1001']


def test_branch_scope_excludes_other_branch(db_session):
    b1 = _branch('B1', 'B1')
    b2 = _branch('B2', 'B2')
    cash = _acct('1001', 'Cash')
    rev = _acct('4001', 'Revenue', 'Income', 'Credit')
    _entry(b2.id, date(2026, 6, 5), 'JE-X', [(cash, 999, 0), (rev, 0, 999)])
    gl = generate_general_ledger(date(2026, 6, 1), date(2026, 6, 30), b1.id)
    assert gl['accounts'] == []


def test_draft_entries_excluded(db_session):
    b = _branch()
    cash = _acct('1001', 'Cash')
    rev = _acct('4001', 'Revenue', 'Income', 'Credit')
    _entry(b.id, date(2026, 6, 5), 'JE-D', [(cash, 700, 0), (rev, 0, 700)], status='draft')
    gl = generate_general_ledger(date(2026, 6, 1), date(2026, 6, 30), b.id)
    assert gl['accounts'] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_general_ledger.py -v`
Expected: FAIL with `ImportError: cannot import name 'generate_general_ledger'`.

- [ ] **Step 3: Implement the generator**

Add to `app/reports/financial.py` (the `func`, `Decimal`, `db`, `Account`, `JournalEntry`, `JournalEntryLine`, `date` imports already exist at the top of the file):

```python
def generate_general_ledger(start_date, end_date, branch_id, account_id=None):
    """All-accounts General Ledger book over posted journal entries.

    Per account: opening balance (debit-positive) carried from before start_date,
    each in-range posted line with a running balance, and a closing subtotal.
    Accounts with no opening balance and no in-range activity are omitted.
    """
    accounts_q = Account.query.filter_by(is_active=True)
    if account_id:
        accounts_q = accounts_q.filter(Account.id == account_id)
    accounts = accounts_q.order_by(Account.code).all()

    result_accounts = []
    grand_debit = Decimal('0.00')
    grand_credit = Decimal('0.00')

    for account in accounts:
        opening = db.session.query(
            func.coalesce(
                func.sum(JournalEntryLine.debit_amount - JournalEntryLine.credit_amount),
                0)
        ).join(JournalEntry).filter(
            JournalEntry.status == 'posted',
            JournalEntry.branch_id == branch_id,
            JournalEntry.entry_date < start_date,
            JournalEntryLine.account_id == account.id,
        ).scalar()
        opening = Decimal(str(opening or '0.00'))

        rows = db.session.query(JournalEntryLine, JournalEntry).join(JournalEntry).filter(
            JournalEntry.status == 'posted',
            JournalEntry.branch_id == branch_id,
            JournalEntry.entry_date >= start_date,
            JournalEntry.entry_date <= end_date,
            JournalEntryLine.account_id == account.id,
        ).order_by(
            JournalEntry.entry_date,
            JournalEntry.entry_number,
            JournalEntryLine.line_number,
        ).all()

        if opening == 0 and not rows:
            continue

        running = opening
        total_debit = Decimal('0.00')
        total_credit = Decimal('0.00')
        line_dicts = []
        for line, entry in rows:
            running += (line.debit_amount - line.credit_amount)
            total_debit += line.debit_amount
            total_credit += line.credit_amount
            line_dicts.append({
                'entry_id': entry.id,
                'entry_number': entry.entry_number,
                'entry_date': entry.entry_date,
                'entry_type': entry.entry_type,
                'reference': entry.reference,
                'description': line.description or entry.description,
                'debit': float(line.debit_amount),
                'credit': float(line.credit_amount),
                'running_balance': float(running),
            })

        closing = opening + (total_debit - total_credit)
        grand_debit += total_debit
        grand_credit += total_credit
        result_accounts.append({
            'code': account.code,
            'name': account.name,
            'account_type': account.account_type,
            'opening_balance': float(opening),
            'lines': line_dicts,
            'total_debit': float(total_debit),
            'total_credit': float(total_credit),
            'closing_balance': float(closing),
        })

    return {
        'start_date': start_date,
        'end_date': end_date,
        'accounts': result_accounts,
        'grand_total_debit': float(grand_debit),
        'grand_total_credit': float(grand_credit),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_general_ledger.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add app/reports/financial.py tests/unit/test_general_ledger.py
git commit -m "feat(reports): general ledger data generator"
```

---

### Task 2: Source-document link resolver

**Files:**
- Modify: `app/reports/views.py` (add `_attach_source_links` helper + imports)
- Test: `tests/integration/test_general_ledger_views.py` (create — resolver test only in this task)

**Interfaces:**
- Consumes: the generator output from Task 1; models `SalesInvoice`, `AccountsPayable`, `CashReceiptVoucher`, `CashDisbursementVoucher`, `JournalEntry`; `url_for`.
- Produces:
  ```
  _attach_source_links(ledger: dict, branch_id: int) -> None   # mutates in place
  ```
  After the call, every line gains `line['source'] = {'url': str|None, 'label': str}`.
  Mapping by `entry_type`: `sale`→Sales Invoice, `purchase`→Accounts Payable, `receipt`→CRV, `disbursement`→CDV (deep-linked by document number → row id); any other type (`adjustment`/`opening`/`closing`/`reclassification`/`reversal`) → the Journal Entry view by `entry_id`. `url` is `None` only when a referenced source doc cannot be resolved by number, in which case `label` is the JE number.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_general_ledger_views.py` with the resolver test:

```python
from datetime import date
from decimal import Decimal
import pytest

from app import db
from app.accounts.models import Account
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.reports.views import _attach_source_links
from app.sales_invoices.models import SalesInvoice

pytestmark = [pytest.mark.integration]


def test_attach_source_links_sale_links_to_invoice(db_session, main_branch, admin_user):
    inv = SalesInvoice(invoice_number='SI-2026-06-0001', customer_name='ACME',
                       invoice_date=date(2026, 6, 5), branch_id=main_branch.id,
                       status='posted', subtotal=Decimal('100'), total_amount=Decimal('100'),
                       balance=Decimal('0'))
    db.session.add(inv)
    db.session.commit()
    ledger = {'accounts': [{'lines': [
        {'entry_id': 1, 'entry_number': 'SI-0001', 'entry_type': 'sale',
         'reference': 'SI-2026-06-0001'},
        {'entry_id': 2, 'entry_number': 'JV-0007', 'entry_type': 'adjustment',
         'reference': 'JV-0007'},
    ]}]}
    _attach_source_links(ledger, main_branch.id)
    lines = ledger['accounts'][0]['lines']
    assert f'/sales-invoices/{inv.id}' in lines[0]['source']['url']
    assert lines[0]['source']['label'] == 'SI SI-2026-06-0001'
    # manual voucher falls back to the JE view
    assert '/journal-entries/2' in lines[1]['source']['url']
    assert lines[1]['source']['label'] == 'JV-0007'
```

> Note: confirm `SalesInvoice`'s required columns at implementation time; adjust the constructor kwargs to satisfy NOT NULL fields if the model has more required columns. The assertion on the URL substring is resilient to the exact route prefix.

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/integration/test_general_ledger_views.py::test_attach_source_links_sale_links_to_invoice -v`
Expected: FAIL with `ImportError: cannot import name '_attach_source_links'`.

- [ ] **Step 3: Implement the resolver**

Add to `app/reports/views.py` (extend the existing imports at the top):

```python
from app.cash_receipts.models import CashReceiptVoucher
from app.cash_disbursements.models import CashDisbursementVoucher
from app.journal_entries.models import JournalEntry
# SalesInvoice and AccountsPayable are already imported at the top of this file.

# entry_type -> (Model, number column, view endpoint, short label prefix)
_SOURCE_MAP = {
    'sale':         (SalesInvoice,             'invoice_number', 'sales_invoices.view',     'SI'),
    'purchase':     (AccountsPayable,          'ap_number',      'accounts_payable.view',   'AP'),
    'receipt':      (CashReceiptVoucher,       'crv_number',     'cash_receipts.view',      'CR'),
    'disbursement': (CashDisbursementVoucher,  'cdv_number',     'cash_disbursements.view', 'CD'),
}


def _attach_source_links(ledger, branch_id):
    """Mutate each line, adding line['source'] = {'url', 'label'}.

    Resolves the four auto-posted transaction types to their source document by
    number (one IN-query per type); everything else links to the Journal Entry view.
    """
    # Gather the distinct references actually present, grouped by entry_type.
    refs_by_type = {}
    for account in ledger['accounts']:
        for line in account['lines']:
            et = line.get('entry_type')
            if et in _SOURCE_MAP and line.get('reference'):
                refs_by_type.setdefault(et, set()).add(line['reference'])

    # Build {number: id} maps with one query per source type.
    id_maps = {}
    for et, refs in refs_by_type.items():
        model, numcol, _endpoint, _prefix = _SOURCE_MAP[et]
        col = getattr(model, numcol)
        rows = model.query.filter(model.branch_id == branch_id, col.in_(refs)).all()
        id_maps[et] = {getattr(r, numcol): r.id for r in rows}

    for account in ledger['accounts']:
        for line in account['lines']:
            et = line.get('entry_type')
            ref = line.get('reference')
            mapped = _SOURCE_MAP.get(et)
            doc_id = id_maps.get(et, {}).get(ref) if mapped else None
            if mapped and doc_id is not None:
                _model, _numcol, endpoint, prefix = mapped
                line['source'] = {'url': url_for(endpoint, id=doc_id),
                                  'label': f'{prefix} {ref}'}
            else:
                line['source'] = {'url': url_for('journal_entries.view', id=line['entry_id']),
                                  'label': line['entry_number']}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/integration/test_general_ledger_views.py::test_attach_source_links_sale_links_to_invoice -v`
Expected: PASS. (If it errors on a missing NOT NULL column in the `SalesInvoice(...)` constructor, add the required kwargs and re-run — the resolver code itself is unchanged.)

- [ ] **Step 5: Commit**

```bash
git add app/reports/views.py tests/integration/test_general_ledger_views.py
git commit -m "feat(reports): general ledger source-document link resolver"
```

---

### Task 3: General Ledger view + template + reports index card

**Files:**
- Modify: `app/reports/views.py` (add `general_ledger` route)
- Create: `app/reports/templates/reports/general_ledger.html`
- Modify: `app/reports/templates/reports/index.html` (add a GL card)
- Test: `tests/integration/test_general_ledger_views.py` (add view tests)

**Interfaces:**
- Consumes: `generate_general_ledger` (Task 1), `_attach_source_links` (Task 2), `session['selected_branch_id']`.
- Produces: endpoint `reports.general_ledger` at `GET /reports/general-ledger`. Query params: `start_date`, `end_date` (ISO; default = 1st of current month → today), `account_id` (optional int). Renders `reports/general_ledger.html` with context `ledger`, `start_date`, `end_date`, `accounts` (the active-account list for the picker), `selected_account_id`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_general_ledger_views.py`:

```python
from app.reports.financial import generate_general_ledger  # noqa: E402


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def _post_je(branch_id, account, contra, when, number):
    je = JournalEntry(entry_number=number, entry_date=when, description='d',
                      reference=number, entry_type='adjustment', branch_id=branch_id,
                      status='posted', is_balanced=True,
                      total_debit=Decimal('100'), total_credit=Decimal('100'))
    db.session.add(je)
    db.session.flush()
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=1, account_id=account.id,
                                    debit_amount=Decimal('100'), credit_amount=Decimal('0'),
                                    description='dr'))
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=2, account_id=contra.id,
                                    debit_amount=Decimal('0'), credit_amount=Decimal('100'),
                                    description='cr'))
    db.session.commit()
    return je


def test_general_ledger_requires_login(client):
    resp = client.get('/reports/general-ledger')
    assert resp.status_code in (302, 401)


def test_general_ledger_admin_renders(client, db_session, main_branch, admin_user,
                                      cash_account, revenue_account):
    _post_je(main_branch.id, cash_account, revenue_account, date.today(), 'JE-T1')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/general-ledger')
    assert resp.status_code == 200
    assert b'General Ledger' in resp.data
    assert cash_account.code.encode() in resp.data


def test_general_ledger_account_filter(client, db_session, main_branch, admin_user,
                                       cash_account, revenue_account):
    _post_je(main_branch.id, cash_account, revenue_account, date.today(), 'JE-T2')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get(f'/reports/general-ledger?account_id={cash_account.id}')
    assert resp.status_code == 200
    assert cash_account.code.encode() in resp.data
    assert revenue_account.code.encode() not in resp.data


def test_general_ledger_staff_without_grant_denied(client, db_session, main_branch,
                                                   staff_user):
    _login(client, staff_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/general-ledger', follow_redirects=False)
    assert resp.status_code == 302  # global module gate redirects ungranted staff
```

> The `staff_user` fixture has no `general_ledger` book permission, so the global `before_request` gate (Task 5 registry entry) redirects it. This test will only pass once Task 5 is complete; if running tasks strictly in order, expect it to fail until then — note it and move on, or reorder to run it after Task 5. The other three tests pass within this task.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/integration/test_general_ledger_views.py -v`
Expected: the new view tests FAIL with 404 (route not yet defined).

- [ ] **Step 3: Implement the view**

Add to `app/reports/views.py`. `Account` import is needed for the picker list — add `from app.accounts.models import Account` to the imports if not present:

```python
@reports_bp.route('/reports/general-ledger')
@login_required
def general_ledger():
    """All-accounts General Ledger book for the selected branch."""
    today = date.today()
    start_default = date(today.year, today.month, 1)

    def _parse(param, fallback):
        try:
            return date.fromisoformat(request.args.get(param, ''))
        except (ValueError, TypeError):
            return fallback

    start_date = _parse('start_date', start_default)
    end_date = _parse('end_date', today)
    account_id = request.args.get('account_id', type=int)

    branch_id = session.get('selected_branch_id')
    ledger = generate_general_ledger(start_date, end_date, branch_id, account_id=account_id)
    _attach_source_links(ledger, branch_id)

    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    return render_template('reports/general_ledger.html',
                           ledger=ledger,
                           start_date=start_date,
                           end_date=end_date,
                           accounts=accounts,
                           selected_account_id=account_id)
```

- [ ] **Step 4: Create the template**

Create `app/reports/templates/reports/general_ledger.html`:

```html
{% extends "base.html" %}

{% block title %}General Ledger{% endblock %}
{% block page_title %}General Ledger{% endblock %}

{% block content %}
{% set q = 'start_date=' ~ start_date.isoformat() ~ '&end_date=' ~ end_date.isoformat() ~ ('&account_id=' ~ selected_account_id if selected_account_id else '') %}
<div class="card">
    <div class="card-header">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
            <div>
                <h2 style="margin:0;">General Ledger</h2>
                <p style="margin:4px 0 0 0;color:var(--text-2);">
                    {{ start_date.strftime('%B %d, %Y') }} &ndash; {{ end_date.strftime('%B %d, %Y') }}
                </p>
            </div>
            <div class="card-header-actions" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
                <a href="{{ url_for('reports.general_ledger_export_excel') }}?{{ q }}" class="btn btn-secondary">&#11015; Excel</a>
                <a href="{{ url_for('reports.general_ledger_export_csv') }}?{{ q }}" class="btn btn-secondary">&#11015; CSV</a>
                <a href="{{ url_for('reports.general_ledger_print') }}?{{ q }}" target="_blank" class="btn btn-secondary">Print</a>
                <a href="{{ url_for('reports.index') }}" class="btn btn-secondary">Back to Reports</a>
            </div>
        </div>
    </div>

    <div class="card-body">
        <form method="GET" style="margin-bottom:20px;">
            <div style="display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap;">
                <div class="form-group" style="margin:0;">
                    <label>From</label>
                    <input type="date" name="start_date" value="{{ start_date.isoformat() }}" class="form-control" style="width:180px;">
                </div>
                <div class="form-group" style="margin:0;">
                    <label>To</label>
                    <input type="date" name="end_date" value="{{ end_date.isoformat() }}" class="form-control" style="width:180px;">
                </div>
                <div class="form-group" style="margin:0;min-width:280px;">
                    <label>Account (optional)</label>
                    <select name="account_id" class="form-control search-select" data-placeholder="All accounts">
                        <option value="">All accounts</option>
                        {% for a in accounts %}
                        <option value="{{ a.id }}" {{ 'selected' if selected_account_id == a.id else '' }}>{{ a.code }} &mdash; {{ a.name }}</option>
                        {% endfor %}
                    </select>
                </div>
                <button type="submit" class="btn btn-primary">Generate</button>
            </div>
        </form>

        {% if ledger.accounts %}
        {% for acct in ledger.accounts %}
        <div style="margin-bottom:24px;border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;">
            <div style="background:var(--bg);padding:10px 14px;font-weight:600;">
                {{ acct.code }} &mdash; {{ acct.name }}
            </div>
            <table class="table" style="margin:0;font-size:0.9rem;">
                <thead>
                    <tr style="background:var(--bg);">
                        <th>Date</th>
                        <th>JE #</th>
                        <th>Source</th>
                        <th>Particulars</th>
                        <th style="text-align:right;">Debit</th>
                        <th style="text-align:right;">Credit</th>
                        <th style="text-align:right;">Balance</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td colspan="6"><em>Opening balance</em></td>
                        <td style="text-align:right;">{{ balance_dr_cr(acct.opening_balance) }}</td>
                    </tr>
                    {% for line in acct.lines %}
                    <tr>
                        <td>{{ line.entry_date.strftime('%Y-%m-%d') }}</td>
                        <td><a href="{{ url_for('journal_entries.view', id=line.entry_id) }}" style="color:var(--blue)">{{ line.entry_number }}</a></td>
                        <td>
                            {% if line.source.url %}
                            <a href="{{ line.source.url }}" style="color:var(--blue)">{{ line.source.label }}</a>
                            {% else %}{{ line.source.label }}{% endif %}
                        </td>
                        <td>{{ line.description }}</td>
                        <td style="text-align:right;">{% if line.debit %}₱{{ "{:,.2f}".format(line.debit) }}{% endif %}</td>
                        <td style="text-align:right;">{% if line.credit %}₱{{ "{:,.2f}".format(line.credit) }}{% endif %}</td>
                        <td style="text-align:right;">{{ balance_dr_cr(line.running_balance) }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
                <tfoot style="border-top:2px solid var(--border);font-weight:600;">
                    <tr style="background:var(--bg);">
                        <td colspan="4">Closing balance</td>
                        <td style="text-align:right;">₱{{ "{:,.2f}".format(acct.total_debit) }}</td>
                        <td style="text-align:right;">₱{{ "{:,.2f}".format(acct.total_credit) }}</td>
                        <td style="text-align:right;">{{ balance_dr_cr(acct.closing_balance) }}</td>
                    </tr>
                </tfoot>
            </table>
        </div>
        {% endfor %}
        {% else %}
        <div class="empty-state">
            <p>No ledger activity for {{ start_date.strftime('%b %d, %Y') }} &ndash; {{ end_date.strftime('%b %d, %Y') }}.</p>
        </div>
        {% endif %}
    </div>
</div>

{% macro balance_dr_cr(value) %}{% if value >= 0 %}₱{{ "{:,.2f}".format(value) }} Dr{% else %}₱{{ "{:,.2f}".format(-value) }} Cr{% endif %}{% endmacro %}

{% block scripts %}
{{ super() }}
<script>
  document.addEventListener('DOMContentLoaded', function () {
    if (window.initSearchSelect) { initSearchSelect('.search-select'); }
  });
</script>
{% endblock %}
{% endblock %}
```

> **Macro placement note:** Jinja resolves `{% macro %}` at compile time regardless of source order, so calling `balance_dr_cr(...)` above its definition works. If the project's Jinja config disallows that, move the `{% macro %}` block to the top of `{% block content %}`. Verify the exact `initSearchSelect` invocation against `app/static/js/cas-ui.js` and an existing caller (see the search-select skill) and match it.

- [ ] **Step 5: Add a card to the reports index**

In `app/reports/templates/reports/index.html`, add a third card after the AP Aging card (inside the same `.row`):

```html
            <!-- General Ledger Card -->
            <div class="col" style="flex: 1; min-width: 300px;">
                <div class="content-card" style="height: 100%;">
                    <div class="card-body">
                        <h3 style="margin-top: 0; color: var(--primary);">
                            <span style="font-size: 2rem;">📖</span>
                            General Ledger
                        </h3>
                        <p class="text-muted" style="margin-bottom: 20px;">
                            The full ledger book: every account with its posted entries, opening and running balances. Filter by date range or a single account.
                        </p>
                        <a href="{{ url_for('reports.general_ledger') }}" class="btn btn-primary">
                            View General Ledger
                        </a>
                    </div>
                </div>
            </div>
```

- [ ] **Step 6: Run the tests**

Run: `pytest tests/integration/test_general_ledger_views.py -v -k "admin_renders or account_filter or requires_login"`
Expected: PASS. (The `staff_without_grant_denied` test passes after Task 5.)

- [ ] **Step 7: Commit**

```bash
git add app/reports/views.py app/reports/templates/reports/general_ledger.html app/reports/templates/reports/index.html tests/integration/test_general_ledger_views.py
git commit -m "feat(reports): general ledger view, template, and reports-index card"
```

---

### Task 4: Exports (Excel + CSV) and print layout

**Files:**
- Modify: `app/reports/views.py` (add 3 routes + a shared flatten helper)
- Create: `app/reports/templates/reports/general_ledger_print.html`
- Test: `tests/integration/test_general_ledger_views.py` (add export/print tests)

**Interfaces:**
- Consumes: `generate_general_ledger`, `_attach_source_links`, `export_to_excel`, `export_to_csv` (all already importable in `views.py`).
- Produces: endpoints `reports.general_ledger_export_excel` (`/reports/general-ledger/export/excel`), `reports.general_ledger_export_csv` (`/reports/general-ledger/export/csv`), `reports.general_ledger_print` (`/reports/general-ledger/print`). All honour `start_date`/`end_date`/`account_id`. A module-level `_flatten_ledger(ledger)` returns flat row dicts (account-header, line, and subtotal rows) for the spreadsheet exports.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_general_ledger_views.py`:

```python
def test_general_ledger_excel_export(client, db_session, main_branch, admin_user,
                                     cash_account, revenue_account):
    _post_je(main_branch.id, cash_account, revenue_account, date.today(), 'JE-E1')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/general-ledger/export/excel?start_date=2026-06-01&end_date=2026-06-30')
    assert resp.status_code == 200
    assert 'spreadsheetml' in resp.headers['Content-Type']


def test_general_ledger_csv_export(client, db_session, main_branch, admin_user,
                                   cash_account, revenue_account):
    _post_je(main_branch.id, cash_account, revenue_account, date.today(), 'JE-E2')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/general-ledger/export/csv')
    assert resp.status_code == 200
    assert 'text/csv' in resp.headers['Content-Type']


def test_general_ledger_print_renders(client, db_session, main_branch, admin_user,
                                      cash_account, revenue_account):
    _post_je(main_branch.id, cash_account, revenue_account, date.today(), 'JE-P1')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/general-ledger/print')
    assert resp.status_code == 200
    assert b'General Ledger' in resp.data
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/integration/test_general_ledger_views.py -v -k "excel_export or csv_export or print_renders"`
Expected: FAIL with 404.

- [ ] **Step 3: Implement the routes**

Add to `app/reports/views.py` (factor the param-parsing into a small helper to stay DRY with Task 3):

```python
def _gl_params():
    """Shared (start_date, end_date, account_id, branch_id) parsing for GL routes."""
    today = date.today()
    start_default = date(today.year, today.month, 1)

    def _parse(param, fallback):
        try:
            return date.fromisoformat(request.args.get(param, ''))
        except (ValueError, TypeError):
            return fallback

    return (_parse('start_date', start_default),
            _parse('end_date', today),
            request.args.get('account_id', type=int),
            session.get('selected_branch_id'))


def _flatten_ledger(ledger):
    """Flatten the book into export rows: a header row per account, its lines, a subtotal."""
    rows = []
    for acct in ledger['accounts']:
        rows.append({'date': f"{acct['code']} - {acct['name']}", 'je': '', 'source': '',
                     'particulars': 'Opening balance', 'debit': '', 'credit': '',
                     'balance': acct['opening_balance']})
        for line in acct['lines']:
            rows.append({
                'date': line['entry_date'], 'je': line['entry_number'],
                'source': line['source']['label'], 'particulars': line['description'],
                'debit': line['debit'] or '', 'credit': line['credit'] or '',
                'balance': line['running_balance'],
            })
        rows.append({'date': '', 'je': '', 'source': '', 'particulars': 'Closing balance',
                     'debit': acct['total_debit'], 'credit': acct['total_credit'],
                     'balance': acct['closing_balance']})
    return rows


_GL_COLUMNS = ['date', 'je', 'source', 'particulars', 'debit', 'credit', 'balance']
_GL_HEADERS = ['Date', 'JE #', 'Source', 'Particulars', 'Debit', 'Credit', 'Balance']


@reports_bp.route('/reports/general-ledger/export/excel')
@login_required
def general_ledger_export_excel():
    start_date, end_date, account_id, branch_id = _gl_params()
    ledger = generate_general_ledger(start_date, end_date, branch_id, account_id=account_id)
    _attach_source_links(ledger, branch_id)
    rows = _flatten_ledger(ledger)
    return export_to_excel(
        rows, _GL_COLUMNS, _GL_HEADERS,
        filename=f'general_ledger_{start_date.isoformat()}_to_{end_date.isoformat()}.xlsx',
        title=f'General Ledger - {start_date.isoformat()} to {end_date.isoformat()}')


@reports_bp.route('/reports/general-ledger/export/csv')
@login_required
def general_ledger_export_csv():
    start_date, end_date, account_id, branch_id = _gl_params()
    ledger = generate_general_ledger(start_date, end_date, branch_id, account_id=account_id)
    _attach_source_links(ledger, branch_id)
    rows = _flatten_ledger(ledger)
    return export_to_csv(
        rows, _GL_COLUMNS, _GL_HEADERS,
        filename=f'general_ledger_{start_date.isoformat()}_to_{end_date.isoformat()}.csv')


@reports_bp.route('/reports/general-ledger/print')
@login_required
def general_ledger_print():
    start_date, end_date, account_id, branch_id = _gl_params()
    ledger = generate_general_ledger(start_date, end_date, branch_id, account_id=account_id)
    _attach_source_links(ledger, branch_id)
    return render_template('reports/general_ledger_print.html',
                           ledger=ledger, start_date=start_date, end_date=end_date)
```

> Refactor note: update the `general_ledger` view from Task 3 to call `_gl_params()` instead of repeating the inline parsing (DRY). Keep its extra `accounts`/`selected_account_id` context.

- [ ] **Step 4: Create the print template**

Create `app/reports/templates/reports/general_ledger_print.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>General Ledger</title>
    <style>
        body { font-family: Arial, sans-serif; font-size: 12px; color: #000; margin: 24px; }
        h1 { font-size: 18px; margin: 0 0 4px 0; }
        .period { color: #444; margin: 0 0 16px 0; }
        .acct { page-break-inside: avoid; margin-bottom: 18px; }
        .acct + .acct { page-break-before: always; }
        .acct-title { font-weight: bold; border-bottom: 1px solid #000; padding-bottom: 4px; margin-bottom: 6px; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 4px 6px; border-bottom: 1px solid #ccc; text-align: left; }
        .num { text-align: right; }
        tfoot td { font-weight: bold; border-top: 1px solid #000; }
        @media print { .noprint { display: none; } }
    </style>
</head>
<body onload="window.print()">
    <h1>General Ledger</h1>
    <p class="period">{{ start_date.strftime('%B %d, %Y') }} &ndash; {{ end_date.strftime('%B %d, %Y') }}</p>
    {% macro bal(value) %}{% if value >= 0 %}₱{{ "{:,.2f}".format(value) }} Dr{% else %}₱{{ "{:,.2f}".format(-value) }} Cr{% endif %}{% endmacro %}
    {% for acct in ledger.accounts %}
    <div class="acct">
        <div class="acct-title">{{ acct.code }} &mdash; {{ acct.name }}</div>
        <table>
            <thead>
                <tr><th>Date</th><th>JE #</th><th>Source</th><th>Particulars</th>
                    <th class="num">Debit</th><th class="num">Credit</th><th class="num">Balance</th></tr>
            </thead>
            <tbody>
                <tr><td colspan="6"><em>Opening balance</em></td><td class="num">{{ bal(acct.opening_balance) }}</td></tr>
                {% for line in acct.lines %}
                <tr>
                    <td>{{ line.entry_date.strftime('%Y-%m-%d') }}</td>
                    <td>{{ line.entry_number }}</td>
                    <td>{{ line.source.label }}</td>
                    <td>{{ line.description }}</td>
                    <td class="num">{% if line.debit %}₱{{ "{:,.2f}".format(line.debit) }}{% endif %}</td>
                    <td class="num">{% if line.credit %}₱{{ "{:,.2f}".format(line.credit) }}{% endif %}</td>
                    <td class="num">{{ bal(line.running_balance) }}</td>
                </tr>
                {% endfor %}
            </tbody>
            <tfoot>
                <tr><td colspan="4">Closing balance</td>
                    <td class="num">₱{{ "{:,.2f}".format(acct.total_debit) }}</td>
                    <td class="num">₱{{ "{:,.2f}".format(acct.total_credit) }}</td>
                    <td class="num">{{ bal(acct.closing_balance) }}</td></tr>
            </tfoot>
        </table>
    </div>
    {% endfor %}
</body>
</html>
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/integration/test_general_ledger_views.py -v -k "excel_export or csv_export or print_renders"`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/reports/views.py app/reports/templates/reports/general_ledger_print.html tests/integration/test_general_ledger_views.py
git commit -m "feat(reports): general ledger Excel/CSV export and print layout"
```

---

### Task 5: Access wiring, nav link, and existing-test updates

**Files:**
- Modify: `app/users/module_access.py` (register `general_ledger`)
- Modify: `app/templates/base.html` (swap the nav link)
- Modify: `tests/integration/test_under_development.py` (GL no longer redirects)
- Modify: `tests/integration/test_sidebar_roles.py` (GL is a real gated link)
- Test: re-run `tests/integration/test_general_ledger_views.py::test_general_ledger_staff_without_grant_denied`

**Interfaces:**
- Consumes: `MODULE_REGISTRY` shape from `app/users/module_access.py`; `can_access_module` Jinja global.
- Produces: the `general_ledger` book key gating four endpoints; a real sidebar link to `reports.general_ledger`.

- [ ] **Step 1: Register the module**

In `app/users/module_access.py`, add to `MODULE_REGISTRY` in the `'Ledger'` section (after the `ar_aging` entry):

```python
    {'key': 'general_ledger', 'label': 'General Ledger', 'section': 'Ledger',
     'endpoints': ('reports.general_ledger', 'reports.general_ledger_export_excel',
                   'reports.general_ledger_export_csv', 'reports.general_ledger_print')},
```

- [ ] **Step 2: Verify the staff-denial test now passes**

Run: `pytest tests/integration/test_general_ledger_views.py::test_general_ledger_staff_without_grant_denied -v`
Expected: PASS (the global `before_request` hook now recognises the endpoint and redirects ungranted staff).

- [ ] **Step 3: Swap the nav link**

In `app/templates/base.html` (~lines 1141-1145), replace the under-development stub:

```html
                    <a href="{{ url_for('dashboard.under_development', feature='General Ledger') }}" class="nav-item nav-item--soon {% if request.endpoint == 'dashboard.under_development' and request.args.get('feature') == 'General Ledger' %}active{% endif %}">
                        <span class="nav-icon">📖</span>
                        <span class="nav-text">General Ledger</span>
                        <span class="nav-coming-soon">Soon</span>
                    </a>
```

with a real, module-gated link (matching the surrounding Ledger items):

```html
                    {% if can_access_module(current_user, 'general_ledger') %}
                    <a href="{{ url_for('reports.general_ledger') }}" class="nav-item {% if request.endpoint == 'reports.general_ledger' %}active{% endif %}">
                        <span class="nav-icon">📖</span>
                        <span class="nav-text">General Ledger</span>
                    </a>
                    {% endif %}
```

- [ ] **Step 4: Update the under-development test**

In `tests/integration/test_under_development.py`, find the assertion that General Ledger redirects to / renders the under-development page and remove or invert it (GL now renders its own page). Search the file:

Run: `pytest tests/integration/test_under_development.py -v`
Then edit any failing GL-specific assertion. If the test parametrizes a list of "Soon" features including `'General Ledger'`, remove `'General Ledger'` from that list. (Do not weaken assertions for the *other* still-stubbed features — Trial Balance, Income Statement, Balance Sheet, BIR remain under development.)

- [ ] **Step 5: Update the sidebar-roles test**

In `tests/integration/test_sidebar_roles.py`, GL changes from a `nav-item--soon` "Soon" stub to a real link gated by `can_access_module`. Update expectations: for admin/accountant/viewer the GL link is present and points at `/reports/general-ledger`; for staff without the grant it is absent. Run and fix:

Run: `pytest tests/integration/test_sidebar_roles.py -v`

- [ ] **Step 6: Run the full GL + touched suites**

Run: `pytest tests/unit/test_general_ledger.py tests/integration/test_general_ledger_views.py tests/integration/test_under_development.py tests/integration/test_sidebar_roles.py -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add app/users/module_access.py app/templates/base.html tests/integration/test_under_development.py tests/integration/test_sidebar_roles.py
git commit -m "feat(reports): gate general ledger via book_permissions and activate nav link"
```

---

## Self-Review

**Spec coverage:**
- All-accounts GL book with opening + running balance + subtotal → Task 1. ✅
- Date range (default current month), single-account filter, hide-empty, branch auto-scope → Task 1 (data) + Task 3 (form/route). ✅
- Source-doc drill-down (4 types + JE fallback) → Task 2. ✅
- Excel + CSV + print → Task 4. ✅
- `book_permissions` gating + nav swap + reports-index discoverability → Task 3 (card) + Task 5 (registry/nav). ✅
- Deferred items (per-account access; un-stubbing TB/IS/BS) → explicitly out of scope, no tasks. ✅
- Ripple-effect test updates (`test_under_development`, `test_sidebar_roles`) → Task 5. ✅

**Placeholder scan:** No TBD/TODO; every code step shows complete code. Two flagged verification notes (SalesInvoice required columns in Task 2; exact `initSearchSelect` call + macro ordering in Task 3) are real-codebase checks, not placeholders — the surrounding code is complete.

**Type consistency:** `generate_general_ledger(start_date, end_date, branch_id, account_id=None)` and its return keys are used identically across Tasks 3–4. `_attach_source_links(ledger, branch_id)` mutates `line['source'] = {'url','label'}`, consumed by both templates and `_flatten_ledger`. Endpoint names (`reports.general_ledger`, `…_export_excel`, `…_export_csv`, `…_print`) match between routes, templates, the export-link querystring, and the registry entry in Task 5.

**Known ordering caveat:** `test_general_ledger_staff_without_grant_denied` (written in Task 3) only goes green after Task 5 registers the module. This is called out in Task 3 Step 1 and verified in Task 5 Step 2.
