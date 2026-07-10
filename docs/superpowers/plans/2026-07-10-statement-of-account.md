# Statement of Account Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A per-customer, balance-forward Statement of Account report — opening balance, in-period charges/payments with a running balance, closing balance, and an aging summary — as read-only routes on the existing `reports_bp`.

**Architecture:** A pure data-builder (`app/reports/statement_data.py`) event-sources every AR-moving document (Sales Invoice, debit note, ar-dest credit memo, CRV payment) by its document date, filtered to one customer + the current branch. Thin `reports_bp` views render it on screen, to a print page (cloned from the General Ledger print), and to Excel. No model, no migration, no new blueprint.

**Tech Stack:** Flask blueprint routes, SQLAlchemy 2.0 (`db.session.get`, `Model.query.filter(...)`), Jinja templates, `openpyxl` via `app/utils/export.py`, `pytest`.

## Global Constraints

- **SQLAlchemy 2.0 only** — `db.session.get(Model, id)`, never `Model.query.get(...)`.
- **No new model, no migration, no new blueprint** — routes live on the existing `reports_bp`.
- **Charge amount = document `total_amount`** (net of WHT — the actual receivable).
- **Current selected branch only** (`session['selected_branch_id']`), single customer per run.
- **Exclude** voided/cancelled SIs, voided memos, cancelled/voided CRVs, and credit memos whose `destination != 'ar'`.
- **No currency symbol on screen** (bare numbers, "Amounts in PHP" stated once); the **print** page uses the `₱` glyph like the other BIR books.
- **No JS popups**; **no empty-state CTA button**.
- Access: `accountant_or_admin_required` (same as GL/aging).
- Aging bucket boundaries must match `app/reports/views.py::calculate_age_bucket` exactly: `days_overdue = (as_of - bucket_date).days`; `<=0` current, `<=30` 1-30, `<=60` 31-60, `<=90` 61-90, else 90+.
- Run `/guard cas` before any push (Task 6 touches `module_access.py` + `base.html`). Push/deploy only on explicit user go.

**First execution step:** add this plan to `docs/superpowers/plans/INDEX.md` (memory `reference-plans-index`).

---

## Task 1: Pure data-builder — events, opening, rows, running balance, totals, closing

**Files:**
- Create: `app/reports/statement_data.py`
- Test: `tests/unit/test_statement_data.py`

**Interfaces:**
- Produces: `build_statement_of_account(customer_id, branch_id, period) -> dict` where `period` is a dict with `date_from`/`date_to` (`datetime.date`) — the shape returned by `resolve_period`. Returns `{opening_balance, rows, total_charges, total_credits, closing_balance, aging}` (aging filled in Task 2; return an empty dict for it in this task). Each row: `{date, kind, doc_type, doc_id, doc_number, particulars, charge: Decimal, credit: Decimal, running_balance: Decimal}`.
- Consumes: `SalesInvoice`, `SalesMemo`, `CashReceiptVoucher`, `CRVArLine` models.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_statement_data.py
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.branches.models import Branch
from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice
from app.sales_memos.models import SalesMemo
from app.cash_receipts.models import CashReceiptVoucher, CRVArLine
from app.reports.statement_data import build_statement_of_account

pytestmark = [pytest.mark.unit, pytest.mark.reports]

JULY = {'date_from': date(2026, 7, 1), 'date_to': date(2026, 7, 31),
        'label': 'July 2026'}


def _cust(branch):
    c = Customer(code='C1', name='Acme', is_active=True)
    db.session.add(c); db.session.commit()
    return c


def _si(branch, c, number, d, total, status='posted'):
    si = SalesInvoice(branch_id=branch.id, invoice_number=number, invoice_date=d,
                      due_date=d, customer_id=c.id, customer_name=c.name, notes='',
                      status=status, total_amount=Decimal(total), balance=Decimal(total))
    db.session.add(si); db.session.commit()
    return si


def _debit(branch, c, si, number, d, total):
    m = SalesMemo(memo_type='debit', memo_number=number, memo_date=d,
                  sales_invoice_id=si.id, original_invoice_number=si.invoice_number,
                  branch_id=branch.id, customer_id=c.id, customer_name=c.name,
                  reason='chg', notes='', subtotal=Decimal(total), total_amount=Decimal(total),
                  balance=Decimal(total), amount_paid=Decimal('0.00'),
                  destination='ar', status='posted')
    db.session.add(m); db.session.commit()
    return m


def _credit_ar(branch, c, si, number, d, total):
    m = SalesMemo(memo_type='credit', memo_number=number, memo_date=d,
                  sales_invoice_id=si.id, original_invoice_number=si.invoice_number,
                  branch_id=branch.id, customer_id=c.id, customer_name=c.name,
                  reason='ret', notes='', subtotal=Decimal(total), total_amount=Decimal(total),
                  destination='ar', status='posted')
    db.session.add(m); db.session.commit()
    return m


def _crv_pay(branch, c, number, d, doc, amount):
    crv = CashReceiptVoucher(branch_id=branch.id, crv_number=number, crv_date=d,
                             customer_id=c.id, customer_name=c.name, payment_method='cash',
                             cash_account_id=None, notes='', status='posted')
    line = CRVArLine(line_number=1, invoice_number=doc.invoice_number if hasattr(doc, 'invoice_number') else doc.memo_number,
                     original_balance=Decimal(amount), amount_applied=Decimal(amount))
    if isinstance(doc, SalesInvoice):
        line.invoice_id = doc.id
    else:
        line.sales_memo_id = doc.id
    crv.ar_lines.append(line)
    db.session.add(crv); db.session.commit()
    return crv


def test_opening_balance_from_pre_period_events(db_session, main_branch):
    c = _cust(main_branch)
    _si(main_branch, c, 'SI-0001', date(2026, 6, 10), '12000.00')   # pre-period charge
    _crv_pay(main_branch, c, 'CR-1', date(2026, 6, 20),
             SalesInvoice.query.filter_by(invoice_number='SI-0001').first(), '2000.00')
    result = build_statement_of_account(c.id, main_branch.id, JULY)
    assert result['opening_balance'] == Decimal('10000.00')   # 12000 - 2000, both pre-period
    assert result['rows'] == []


def test_running_balance_threads_through_mixed_events(db_session, main_branch):
    c = _cust(main_branch)
    _si(main_branch, c, 'SI-0001', date(2026, 6, 10), '12000.00')            # opening 12000
    si7 = _si(main_branch, c, 'SI-0007', date(2026, 7, 3), '5600.00')        # +5600
    _debit(main_branch, c, si7, 'DM-0001', date(2026, 7, 10), '560.00')      # +560
    _credit_ar(main_branch, c, si7, 'CM-0002', date(2026, 7, 18), '1120.00') # -1120
    _crv_pay(main_branch, c, 'CR-0044', date(2026, 7, 25), si7, '4000.00')   # -4000
    r = build_statement_of_account(c.id, main_branch.id, JULY)
    assert r['opening_balance'] == Decimal('12000.00')
    bals = [row['running_balance'] for row in r['rows']]
    assert bals == [Decimal('17600.00'), Decimal('18160.00'),
                    Decimal('17040.00'), Decimal('13040.00')]
    assert r['total_charges'] == Decimal('6160.00')
    assert r['total_credits'] == Decimal('5120.00')
    assert r['closing_balance'] == Decimal('13040.00')          # opening + charges - credits


def test_excludes_voided_cancelled_and_non_ar_credit(db_session, main_branch):
    c = _cust(main_branch)
    si = _si(main_branch, c, 'SI-0007', date(2026, 7, 3), '5600.00')
    _si(main_branch, c, 'SI-VOID', date(2026, 7, 4), '9999.00', status='voided')
    # non-AR credit memo (cash refund) must not appear
    m = _credit_ar(main_branch, c, si, 'CM-CASH', date(2026, 7, 5), '500.00')
    m.destination = 'cash_refund'; db.session.commit()
    r = build_statement_of_account(c.id, main_branch.id, JULY)
    numbers = [row['doc_number'] for row in r['rows']]
    assert numbers == ['SI-0007']
    assert r['closing_balance'] == Decimal('5600.00')


def test_empty_activity_opening_equals_closing(db_session, main_branch):
    c = _cust(main_branch)
    _si(main_branch, c, 'SI-OLD', date(2026, 6, 1), '3000.00')
    r = build_statement_of_account(c.id, main_branch.id, JULY)
    assert r['rows'] == []
    assert r['opening_balance'] == Decimal('3000.00')
    assert r['closing_balance'] == Decimal('3000.00')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/unit/test_statement_data.py -q -o addopts=`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.reports.statement_data'`.

- [ ] **Step 3: Write minimal implementation**

```python
# app/reports/statement_data.py
"""Pure builder for the customer Statement of Account (SOA).

Event-sources every AR-moving document by its document date so the running balance
reconstructs any historical period (the live `balance` fields are as-of-now, not
as-of-a-past-date). No Flask/request access here — callers pass ids + a resolved period.
"""
from decimal import Decimal

from app.sales_invoices.models import SalesInvoice
from app.sales_memos.models import SalesMemo
from app.cash_receipts.models import CashReceiptVoucher, CRVArLine

# Same-date ordering: charges before credits; SI, then DN, then CM, then payment.
_KIND_RANK = {'invoice': 0, 'debit_note': 1, 'credit_memo': 2, 'payment': 3}

_ACTIVE_SI = ['posted', 'partially_paid', 'paid']


def _collect_events(customer_id, branch_id):
    """Every AR-moving event for a customer+branch (no date filter), as row dicts."""
    events = []

    for i in SalesInvoice.query.filter(
            SalesInvoice.customer_id == customer_id,
            SalesInvoice.branch_id == branch_id,
            SalesInvoice.status.in_(_ACTIVE_SI)).all():
        events.append({'date': i.invoice_date, 'kind': 'invoice', 'doc_type': 'invoice',
                       'doc_id': i.id, 'doc_number': i.invoice_number,
                       'particulars': 'Sales Invoice',
                       'charge': Decimal(str(i.total_amount)), 'credit': Decimal('0.00')})

    for m in SalesMemo.query.filter(
            SalesMemo.customer_id == customer_id, SalesMemo.branch_id == branch_id,
            SalesMemo.memo_type == 'debit', SalesMemo.status == 'posted').all():
        events.append({'date': m.memo_date, 'kind': 'debit_note', 'doc_type': 'debit_note',
                       'doc_id': m.id, 'doc_number': m.memo_number,
                       'particulars': 'Debit Note',
                       'charge': Decimal(str(m.total_amount)), 'credit': Decimal('0.00')})

    for m in SalesMemo.query.filter(
            SalesMemo.customer_id == customer_id, SalesMemo.branch_id == branch_id,
            SalesMemo.memo_type == 'credit', SalesMemo.destination == 'ar',
            SalesMemo.status == 'posted').all():
        events.append({'date': m.memo_date, 'kind': 'credit_memo', 'doc_type': 'credit_memo',
                       'doc_id': m.id, 'doc_number': m.memo_number,
                       'particulars': 'Credit Memo',
                       'charge': Decimal('0.00'), 'credit': Decimal(str(m.total_amount))})

    for line in CRVArLine.query.join(
            CashReceiptVoucher, CRVArLine.crv_id == CashReceiptVoucher.id).filter(
            CashReceiptVoucher.customer_id == customer_id,
            CashReceiptVoucher.branch_id == branch_id,
            CashReceiptVoucher.status == 'posted').all():
        crv = line.crv
        events.append({'date': crv.crv_date, 'kind': 'payment', 'doc_type': 'crv',
                       'doc_id': crv.id, 'doc_number': crv.crv_number,
                       'particulars': f'Collection ({line.invoice_number})',
                       'charge': Decimal('0.00'), 'credit': Decimal(str(line.amount_applied))})

    return events


def build_statement_of_account(customer_id, branch_id, period):
    d_from, d_to = period['date_from'], period['date_to']
    events = _collect_events(customer_id, branch_id)

    opening = sum((e['charge'] - e['credit'] for e in events if e['date'] < d_from),
                  Decimal('0.00'))

    in_period = [e for e in events if d_from <= e['date'] <= d_to]
    in_period.sort(key=lambda e: (e['date'], _KIND_RANK[e['kind']], e['doc_number']))

    running = opening
    total_charges = Decimal('0.00')
    total_credits = Decimal('0.00')
    rows = []
    for e in in_period:
        running += e['charge'] - e['credit']
        total_charges += e['charge']
        total_credits += e['credit']
        rows.append({**e, 'running_balance': running})

    closing = opening + total_charges - total_credits
    return {'opening_balance': opening, 'rows': rows,
            'total_charges': total_charges, 'total_credits': total_credits,
            'closing_balance': closing, 'aging': {}}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/unit/test_statement_data.py -q -o addopts=`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add app/reports/statement_data.py tests/unit/test_statement_data.py
git commit -m "feat(soa): T1 - SOA data-builder (events, opening, running balance, closing)"
```

---

## Task 2: Aging summary — as-of-period-end reconstruction with tie-out invariant

**Files:**
- Modify: `app/reports/statement_data.py`
- Test: `tests/unit/test_statement_data.py` (add cases)

**Interfaces:**
- Produces: `build_statement_of_account(...)['aging']` = `{'current','1-30','31-60','61-90','90+','total'}` of `Decimal`. `total` equals `closing_balance`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_statement_data.py

def test_aging_buckets_tie_to_closing_balance(db_session, main_branch):
    c = _cust(main_branch)
    # SI dated 2026-05-01, due 2026-05-31 -> 61 days overdue as of 07-31 -> 61-90 bucket
    si_old = _si(main_branch, c, 'SI-OLD', date(2026, 5, 1), '7000.00')
    si_old.due_date = date(2026, 5, 31); db.session.commit()
    # SI dated + due 2026-07-20 -> current as of 07-31
    _si(main_branch, c, 'SI-NEW', date(2026, 7, 20), '3000.00')
    r = build_statement_of_account(c.id, main_branch.id, JULY)
    ag = r['aging']
    assert ag['61-90'] == Decimal('7000.00')
    assert ag['current'] == Decimal('3000.00')
    assert ag['total'] == r['closing_balance'] == Decimal('10000.00')


def test_aging_nets_payments_and_credits_as_of_date_to(db_session, main_branch):
    c = _cust(main_branch)
    si = _si(main_branch, c, 'SI-0007', date(2026, 7, 3), '5600.00')
    si.due_date = date(2026, 7, 3); db.session.commit()          # current on 07-31? 28 days -> 1-30
    _credit_ar(main_branch, c, si, 'CM-0002', date(2026, 7, 18), '1120.00')
    _crv_pay(main_branch, c, 'CR-0044', date(2026, 7, 25), si, '2000.00')
    r = build_statement_of_account(c.id, main_branch.id, JULY)
    # remaining on SI-0007 = 5600 - 1120 - 2000 = 2480, bucket 1-30
    assert r['aging']['1-30'] == Decimal('2480.00')
    assert r['aging']['total'] == r['closing_balance'] == Decimal('2480.00')


def test_debit_note_aged_by_memo_date(db_session, main_branch):
    c = _cust(main_branch)
    si = _si(main_branch, c, 'SI-0007', date(2026, 7, 20), '1000.00')
    si.due_date = date(2026, 7, 20); db.session.commit()
    _debit(main_branch, c, si, 'DM-0001', date(2026, 7, 25), '560.00')  # current (memo_date basis)
    r = build_statement_of_account(c.id, main_branch.id, JULY)
    assert r['aging']['current'] == Decimal('1560.00')
    assert r['aging']['total'] == r['closing_balance']
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/unit/test_statement_data.py -k aging -q -o addopts=`
Expected: FAIL (aging is `{}`, so `ag['61-90']` raises `KeyError`).

- [ ] **Step 3: Write minimal implementation**

Add to `app/reports/statement_data.py`:

```python
from datetime import date as _date

_BUCKETS = ['current', '1-30', '31-60', '61-90', '90+']


def _age_bucket(bucket_date, as_of):
    """Mirror of app/reports/views.py::calculate_age_bucket (kept local so the pure
    builder does not import the Flask views module)."""
    if not bucket_date:
        return 'current'
    days_overdue = (as_of - bucket_date).days
    if days_overdue <= 0:
        return 'current'
    if days_overdue <= 30:
        return '1-30'
    if days_overdue <= 60:
        return '31-60'
    if days_overdue <= 90:
        return '61-90'
    return '90+'


def _crv_applied_to(as_of, invoice_id=None, sales_memo_id=None):
    """Sum of posted-CRV amounts applied to one document on or before `as_of`."""
    q = CRVArLine.query.join(
        CashReceiptVoucher, CRVArLine.crv_id == CashReceiptVoucher.id).filter(
        CashReceiptVoucher.status == 'posted',
        CashReceiptVoucher.crv_date <= as_of)
    if invoice_id is not None:
        q = q.filter(CRVArLine.invoice_id == invoice_id)
    else:
        q = q.filter(CRVArLine.sales_memo_id == sales_memo_id)
    return sum((Decimal(str(l.amount_applied)) for l in q.all()), Decimal('0.00'))


def _cm_applied_to_si(si_id, as_of):
    """Sum of ar-dest credit memos against one SI on or before `as_of`."""
    q = SalesMemo.query.filter(
        SalesMemo.memo_type == 'credit', SalesMemo.destination == 'ar',
        SalesMemo.status == 'posted', SalesMemo.sales_invoice_id == si_id,
        SalesMemo.memo_date <= as_of)
    return sum((Decimal(str(m.total_amount)) for m in q.all()), Decimal('0.00'))


def _age_open_items(customer_id, branch_id, as_of):
    buckets = {b: Decimal('0.00') for b in _BUCKETS}

    for i in SalesInvoice.query.filter(
            SalesInvoice.customer_id == customer_id, SalesInvoice.branch_id == branch_id,
            SalesInvoice.status.in_(_ACTIVE_SI), SalesInvoice.invoice_date <= as_of).all():
        paid = _crv_applied_to(as_of, invoice_id=i.id) + _cm_applied_to_si(i.id, as_of)
        remaining = Decimal(str(i.total_amount)) - paid
        if remaining > 0:
            buckets[_age_bucket(i.due_date or i.invoice_date, as_of)] += remaining

    for m in SalesMemo.query.filter(
            SalesMemo.customer_id == customer_id, SalesMemo.branch_id == branch_id,
            SalesMemo.memo_type == 'debit', SalesMemo.status == 'posted',
            SalesMemo.memo_date <= as_of).all():
        paid = _crv_applied_to(as_of, sales_memo_id=m.id)
        remaining = Decimal(str(m.total_amount)) - paid
        if remaining > 0:
            buckets[_age_bucket(m.memo_date, as_of)] += remaining

    buckets['total'] = sum(buckets.values(), Decimal('0.00'))
    return buckets
```

Then in `build_statement_of_account`, replace `'aging': {}` with:

```python
    aging = _age_open_items(customer_id, branch_id, d_to)
    return {'opening_balance': opening, 'rows': rows,
            'total_charges': total_charges, 'total_credits': total_credits,
            'closing_balance': closing, 'aging': aging}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/unit/test_statement_data.py -q -o addopts=`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add app/reports/statement_data.py tests/unit/test_statement_data.py
git commit -m "feat(soa): T2 - as-of-period-end aging reconstruction, buckets tie to closing"
```

---

## Task 3: On-screen route + template

**Files:**
- Modify: `app/reports/views.py` (add `statement_of_account` view + a customer/period context helper)
- Create: `app/reports/templates/reports/statement_of_account.html`
- Create: `app/reports/templates/reports/_soa_table.html` (shared `soa_body` macro, reused by the print page in Task 4)
- Test: `tests/integration/test_statement_of_account.py`

**Interfaces:**
- Consumes: `build_statement_of_account` (T1/T2), `resolve_period` (already imported in `reports/views.py`), `get_company_identity` (`app/utils/bir_books.py`), `accountant_or_admin_required` (in `reports/views.py`).
- Produces: endpoint `reports.statement_of_account` at `/reports/statement-of-account`; the `soa_body(statement, currency)` Jinja macro (consumed by Task 4's print page).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_statement_of_account.py
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice

pytestmark = [pytest.mark.integration, pytest.mark.reports]


def _login(client, u):
    with client.session_transaction() as s:
        s['_user_id'] = str(u.id); s['_fresh'] = True


def _setup(client, admin_user, main_branch):
    c = Customer(code='C1', name='Acme', is_active=True)
    db.session.add(c); db.session.commit()
    si = SalesInvoice(branch_id=main_branch.id, invoice_number='SI-0007',
                      invoice_date=date(2026, 7, 3), due_date=date(2026, 7, 3),
                      customer_id=c.id, customer_name=c.name, notes='', status='posted',
                      total_amount=Decimal('5600.00'), balance=Decimal('5600.00'))
    db.session.add(si); db.session.commit()
    _login(client, admin_user)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    return c


def test_statement_screen_renders(client, db_session, admin_user, main_branch):
    c = _setup(client, admin_user, main_branch)
    resp = client.get(
        f'/reports/statement-of-account?customer_id={c.id}&mode=custom'
        '&date_from=2026-07-01&date_to=2026-07-31')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Statement of Account' in body
    assert 'Balance forward' in body
    assert 'SI-0007' in body
    assert '5,600.00' in body


def test_statement_no_customer_shows_picker(client, db_session, admin_user, main_branch):
    _setup(client, admin_user, main_branch)
    resp = client.get('/reports/statement-of-account')
    assert resp.status_code == 200
    assert 'customer_id' in resp.get_data(as_text=True)   # picker present, no statement yet
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_statement_of_account.py -q -o addopts=`
Expected: FAIL with 404 (route not registered).

- [ ] **Step 3: Write minimal implementation**

In `app/reports/views.py` (near the `ar_aging` view), add:

```python
from app.reports.statement_data import build_statement_of_account


@reports_bp.route('/reports/statement-of-account')
@login_required
@accountant_or_admin_required
def statement_of_account():
    from app.utils.bir_books import get_company_identity
    branch_id = session.get('selected_branch_id')
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    customer_id = request.args.get('customer_id', type=int)
    period = resolve_period(request.args, ph_now().date())

    statement = None
    customer = None
    if customer_id:
        customer = db.session.get(Customer, customer_id)
        if customer:
            statement = build_statement_of_account(customer_id, branch_id, period)

    return render_template('reports/statement_of_account.html',
                           customers=customers, customer=customer,
                           customer_id=customer_id, period=period,
                           statement=statement, company=get_company_identity())
```

(Ensure `Customer`, `session`, `request`, `ph_now`, `resolve_period`, `render_template`,
`login_required` are already imported at the top of `reports/views.py` — they are used by
`ar_aging`/`general_journal`; add `Customer` import if missing.)

Create `app/reports/templates/reports/statement_of_account.html`:

```jinja
{% extends "base.html" %}
{% block title %}Statement of Account{% endblock %}
{% block page_title %}Statement of Account{% endblock %}
{% block content %}
{% from "reports/_soa_table.html" import soa_body %}

<div class="card">
  <div class="card-body">
    <form method="GET" class="filter-bar" style="display:flex;gap:12px;align-items:end;flex-wrap:wrap;">
      <div class="form-group">
        <label class="form-label" for="customer_id">Customer</label>
        <select name="customer_id" id="customer_id" class="form-control" required>
          <option value="">Select customer…</option>
          {% for c in customers %}
          <option value="{{ c.id }}" {% if customer_id == c.id %}selected{% endif %}>{{ c.code }} — {{ c.name }}</option>
          {% endfor %}
        </select>
      </div>
      <div class="form-group">
        <label class="form-label" for="date_from">From</label>
        <input type="date" name="date_from" id="date_from" class="form-control"
               value="{{ period.date_from }}">
      </div>
      <div class="form-group">
        <label class="form-label" for="date_to">To</label>
        <input type="date" name="date_to" id="date_to" class="form-control"
               value="{{ period.date_to }}">
      </div>
      <input type="hidden" name="mode" value="custom">
      <button type="submit" class="btn btn-primary">View</button>
      {% if statement %}
      <a class="btn btn-secondary" target="_blank" rel="noopener noreferrer"
         href="{{ url_for('reports.statement_of_account_print', customer_id=customer_id, mode='custom', date_from=period.date_from, date_to=period.date_to) }}">Print</a>
      <a class="btn btn-secondary"
         href="{{ url_for('reports.statement_of_account_export_excel', customer_id=customer_id, mode='custom', date_from=period.date_from, date_to=period.date_to) }}">Excel</a>
      {% endif %}
    </form>
  </div>
</div>

{% if statement and customer %}
<div class="card" style="margin-top:16px;">
  <div class="card-body">
    <div style="margin-bottom:12px;">
      <div style="font-size:18px;font-weight:700;">Statement of Account</div>
      <div>{{ customer.name }}{% if customer.tin %} · TIN {{ customer.tin }}{% endif %}</div>
      {% if customer.address %}<div style="color:var(--text-2);">{{ customer.address }}</div>{% endif %}
      <div style="color:var(--text-2);">Period: {{ period.label }} · Amounts in PHP</div>
    </div>
    {{ soa_body(statement, currency='') }}
  </div>
</div>
{% elif customer_id %}
<div class="card" style="margin-top:16px;"><div class="card-body">Customer not found.</div></div>
{% endif %}
{% endblock %}
```

Create the shared table macro `app/reports/templates/reports/_soa_table.html`:

```jinja
{% macro soa_body(s, currency='') %}
{% set cur = currency %}
<table class="table">
  <thead><tr><th>Date</th><th>Document</th><th>Particulars</th>
    <th style="text-align:right;">Charge</th><th style="text-align:right;">Credit</th>
    <th style="text-align:right;">Balance</th></tr></thead>
  <tbody>
    <tr><td colspan="5"><em>Balance forward</em></td>
        <td style="text-align:right;font-family:var(--mono);">{{ cur }}{{ '{:,.2f}'.format(s.opening_balance) }}</td></tr>
    {% for row in s.rows %}
    <tr>
      <td>{{ row.date.strftime('%b %d, %Y') }}</td>
      <td style="font-family:var(--mono);">{{ row.doc_number }}</td>
      <td>{{ row.particulars }}</td>
      <td style="text-align:right;font-family:var(--mono);">{% if row.charge %}{{ cur }}{{ '{:,.2f}'.format(row.charge) }}{% endif %}</td>
      <td style="text-align:right;font-family:var(--mono);">{% if row.credit %}({{ cur }}{{ '{:,.2f}'.format(row.credit) }}){% endif %}</td>
      <td style="text-align:right;font-family:var(--mono);">{{ cur }}{{ '{:,.2f}'.format(row.running_balance) }}</td>
    </tr>
    {% else %}
    <tr><td colspan="6"><em>No activity in this period.</em></td></tr>
    {% endfor %}
    <tr style="font-weight:700;border-top:2px solid var(--text-3);">
      <td colspan="5">Closing balance</td>
      <td style="text-align:right;font-family:var(--mono);">{{ cur }}{{ '{:,.2f}'.format(s.closing_balance) }}</td></tr>
  </tbody>
</table>
<div style="margin-top:12px;">
  <strong>Aging of closing balance:</strong>
  Current {{ cur }}{{ '{:,.2f}'.format(s.aging['current']) }} ·
  1-30 {{ cur }}{{ '{:,.2f}'.format(s.aging['1-30']) }} ·
  31-60 {{ cur }}{{ '{:,.2f}'.format(s.aging['31-60']) }} ·
  61-90 {{ cur }}{{ '{:,.2f}'.format(s.aging['61-90']) }} ·
  90+ {{ cur }}{{ '{:,.2f}'.format(s.aging['90+']) }}
</div>
{% endmacro %}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_statement_of_account.py -q -o addopts=`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add app/reports/views.py app/reports/templates/reports/statement_of_account.html app/reports/templates/reports/_soa_table.html tests/integration/test_statement_of_account.py
git commit -m "feat(soa): T3 - on-screen Statement of Account route + template"
```

---

## Task 4: Print route + template (clone of General Ledger print)

**Files:**
- Modify: `app/reports/views.py`
- Create: `app/reports/templates/reports/statement_of_account_print.html`
- Test: `tests/integration/test_statement_of_account.py` (add a case)

**Interfaces:**
- Produces: endpoint `reports.statement_of_account_print` at `/reports/statement-of-account/print`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/integration/test_statement_of_account.py

def test_statement_print_renders_bir_header(client, db_session, admin_user, main_branch):
    c = _setup(client, admin_user, main_branch)
    resp = client.get(
        f'/reports/statement-of-account/print?customer_id={c.id}&mode=custom'
        '&date_from=2026-07-01&date_to=2026-07-31')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'STATEMENT OF ACCOUNT' in body     # bir_book_header title (upper-case)
    assert 'window.print()' in body
    assert 'SI-0007' in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_statement_of_account.py -k print -q -o addopts=`
Expected: FAIL with 404.

- [ ] **Step 3: Write minimal implementation**

In `app/reports/views.py` add:

```python
@reports_bp.route('/reports/statement-of-account/print')
@login_required
@accountant_or_admin_required
def statement_of_account_print():
    from app.utils.bir_books import get_company_identity
    branch_id = session.get('selected_branch_id')
    customer_id = request.args.get('customer_id', type=int)
    customer = db.session.get(Customer, customer_id) if customer_id else None
    if not customer:
        flash('Select a customer to print a statement.', 'error')
        return redirect(url_for('reports.statement_of_account'))
    period = resolve_period(request.args, ph_now().date())
    statement = build_statement_of_account(customer_id, branch_id, period)
    return render_template('reports/statement_of_account_print.html',
                           customer=customer, period=period, statement=statement,
                           company=get_company_identity())
```

Create `app/reports/templates/reports/statement_of_account_print.html` — clone the structure of
`app/reports/templates/reports/general_ledger_print.html`:

```jinja
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Statement of Account — {{ customer.name }}</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='css/bir-books.css') }}">
</head>
{% from "reports/_bir_book_header.html" import bir_book_header %}
{% from "reports/_soa_table.html" import soa_body %}
<body onload="window.print()">
  {{ bir_book_header(company, 'STATEMENT OF ACCOUNT', period.label) }}
  <div style="margin:8px 0;">
    <strong>{{ customer.name }}</strong>{% if customer.tin %} · TIN {{ customer.tin }}{% endif %}
    {% if customer.address %}<br>{{ customer.address }}{% endif %}
  </div>
  {{ soa_body(statement, currency='₱') }}
</body>
</html>
```

(Verify against the real `general_ledger_print.html` that `_bir_book_header.html` macro path and
the `bir-books.css` link are exactly as that file uses them.)

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_statement_of_account.py -k print -q -o addopts=`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/reports/views.py app/reports/templates/reports/statement_of_account_print.html
git commit -m "feat(soa): T4 - printable Statement of Account (BIR header + running balance)"
```

---

## Task 5: Excel export route

**Files:**
- Modify: `app/reports/views.py`
- Test: `tests/integration/test_statement_of_account.py` (add a case)

**Interfaces:**
- Consumes: `export_to_excel(data, columns, headers, filename, title=None)` from `app/utils/export.py`.
- Produces: endpoint `reports.statement_of_account_export_excel` at `/reports/statement-of-account/export/excel`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/integration/test_statement_of_account.py

def test_statement_excel_export(client, db_session, admin_user, main_branch):
    c = _setup(client, admin_user, main_branch)
    resp = client.get(
        f'/reports/statement-of-account/export/excel?customer_id={c.id}&mode=custom'
        '&date_from=2026-07-01&date_to=2026-07-31')
    assert resp.status_code == 200
    assert resp.headers['Content-Type'].startswith(
        'application/vnd.openxmlformats-officedocument.spreadsheetml')
    assert len(resp.data) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_statement_of_account.py -k excel -q -o addopts=`
Expected: FAIL with 404.

- [ ] **Step 3: Write minimal implementation**

In `app/reports/views.py` add (mirror the existing `ar_aging_export_excel`/GL export pattern):

```python
@reports_bp.route('/reports/statement-of-account/export/excel')
@login_required
@accountant_or_admin_required
def statement_of_account_export_excel():
    branch_id = session.get('selected_branch_id')
    customer_id = request.args.get('customer_id', type=int)
    customer = db.session.get(Customer, customer_id) if customer_id else None
    if not customer:
        flash('Select a customer to export a statement.', 'error')
        return redirect(url_for('reports.statement_of_account'))
    period = resolve_period(request.args, ph_now().date())
    s = build_statement_of_account(customer_id, branch_id, period)

    rows = [{'date': '', 'doc_number': 'Balance forward', 'particulars': '',
             'charge': '', 'credit': '',
             'balance': float(s['opening_balance'])}]
    for r in s['rows']:
        rows.append({'date': r['date'].isoformat(), 'doc_number': r['doc_number'],
                     'particulars': r['particulars'],
                     'charge': float(r['charge']) if r['charge'] else '',
                     'credit': float(r['credit']) if r['credit'] else '',
                     'balance': float(r['running_balance'])})
    rows.append({'date': '', 'doc_number': 'Closing balance', 'particulars': '',
                 'charge': '', 'credit': '', 'balance': float(s['closing_balance'])})

    columns = ['date', 'doc_number', 'particulars', 'charge', 'credit', 'balance']
    headers = ['Date', 'Document', 'Particulars', 'Charge', 'Credit', 'Balance']
    return export_to_excel(
        rows, columns, headers,
        filename=f'SOA_{customer.code}_{period["date_from"]}_{period["date_to"]}.xlsx',
        title=f'Statement of Account — {customer.name} — {period["label"]}')
```

(Ensure `export_to_excel` is imported at the top of `reports/views.py` — the aging/GL exports
already import it; add if missing.)

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_statement_of_account.py -k excel -q -o addopts=`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/reports/views.py
git commit -m "feat(soa): T5 - Excel export of the Statement of Account"
```

---

## Task 6: Registry + sidebar wiring + customer-detail button + access gate

**Files:**
- Modify: `app/users/module_access.py` (MODULE_REGISTRY entry)
- Modify: `app/templates/base.html` (`_nav_ep` + `_nav_icon`)
- Modify: `app/customers/templates/customers/detail.html` (a "Statement" button)
- Test: `tests/integration/test_statement_of_account.py` (add gate + nav cases)

**Interfaces:**
- Consumes: the routes from T3–T5. Adds registry key `statement_of_account`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/integration/test_statement_of_account.py

def test_statement_in_registry_and_sidebar(client, db_session, admin_user, main_branch):
    from app.users.module_access import MODULE_REGISTRY, module_key_for_endpoint
    keys = [m['key'] for m in MODULE_REGISTRY]
    assert 'statement_of_account' in keys
    assert module_key_for_endpoint('reports.statement_of_account') == 'statement_of_account'
    # sidebar renders without KeyError for an admin (who sees every module)
    _setup(client, admin_user, main_branch)
    resp = client.get('/dashboard')
    assert resp.status_code == 200


def test_statement_blocked_for_viewer(client, db_session, admin_user, viewer_user, main_branch):
    _setup(client, admin_user, main_branch)          # seed as admin
    with client.session_transaction() as s:
        s['_user_id'] = str(viewer_user.id); s['_fresh'] = True
    resp = client.get('/reports/statement-of-account', follow_redirects=False)
    assert resp.status_code in (302, 403)            # accountant_or_admin_required blocks viewer
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_statement_of_account.py -k "registry or blocked" -q -o addopts=`
Expected: FAIL (`statement_of_account` not in `MODULE_REGISTRY`).

- [ ] **Step 3: Write minimal implementation**

In `app/users/module_access.py`, add next to the `ar_aging` entry:

```python
    {'key': 'statement_of_account', 'label': 'Statement of Account', 'section': 'Ledger',
     'area': 'Sales', 'group': 'Reports',
     'endpoints': ('reports.statement_of_account', 'reports.statement_of_account_print',
                   'reports.statement_of_account_export_excel')},
```

In `app/templates/base.html`, add to the `_nav_ep` map (near the `ar_aging` entry):

```jinja
      'statement_of_account': 'reports.statement_of_account',
```

and to the `_nav_icon` map:

```jinja
      'statement_of_account': '🧾',
```

(Read the real `_nav_ep`/`_nav_icon` blocks first and match their exact literal syntax — a key
present in `MODULE_REGISTRY` but missing from `_nav_ep` raises `KeyError` on every page.)

In `app/customers/templates/customers/detail.html`, add a button in the detail header actions
(where "Edit"/"Back" live), scoped to accountant/admin like other report links:

```jinja
      {% if current_user.role in ['accountant', 'admin', 'chief_accountant'] %}
      <a class="btn btn-secondary"
         href="{{ url_for('reports.statement_of_account', customer_id=customer.id) }}">Statement</a>
      {% endif %}
```

(Confirm the loop variable is `customer` on that page; adjust if it is `c`/`cust`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_statement_of_account.py -q -o addopts=`
Expected: PASS (all cases).

- [ ] **Step 5: Commit**

```bash
git add app/users/module_access.py app/templates/base.html app/customers/templates/customers/detail.html tests/integration/test_statement_of_account.py
git commit -m "feat(soa): T6 - registry + sidebar + customer-detail Statement button + gate"
```

---

## Verification (after all tasks)

- **Full SOA suite:** `venv/Scripts/python.exe -m pytest tests/unit/test_statement_data.py tests/integration/test_statement_of_account.py -q -o addopts=` — builder math, both tie-out invariants, routes, export, gate.
- **Regression on the aging sibling:** `venv/Scripts/python.exe -m pytest -m reports -o addopts= -q` — the SOA shares no code with `ar_aging` but lives in the same views module; confirm the reports suite stays green.
- **Manual/MCP:** for a customer with a posted SI + debit note + ar-dest credit memo + a CRV collection, open the SOA for the month → confirm the balance-forward number, the four row types with a correct running balance, the closing balance, and that the aging strip sums to the closing balance (and matches the AR aging report when the period ends today). Print and Excel render.
- **Guard:** `/guard cas` before any push (Task 6 edits `module_access.py` + `base.html` — high blast radius). Push/deploy only on explicit user go.
