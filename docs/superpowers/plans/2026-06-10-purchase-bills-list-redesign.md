# Purchase Bills List Page Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign `/purchase-bills` into Layout A — four summary KPI cards, a working filter bar (search, status, vendor, date range), a richer table (checkboxes, Balance column, all 6 status badges, WT em-dash, red overdue dates), and selection-aware exports.

**Architecture:** New helper module `app/purchase_bills/utils.py` computes branch-scoped summary metrics (mirrors `app/vendors/utils.py`). A private `_filtered_bills_query()` in `views.py` centralizes filter logic shared by `list_bills` and both export routes. Template rewritten with design tokens and the global badge classes from `style.css`. No model changes.

**Tech Stack:** Flask + SQLAlchemy + SQLite, Jinja2, pytest. PH time via `app.utils.ph_now`.

**Spec:** `docs/superpowers/specs/2026-06-10-purchase-bills-list-redesign-design.md`

---

## Context for implementers (read first)

- **Branch scoping:** `list_bills` filters by `session['selected_branch_id']`. At login, a user with exactly one accessible branch gets it auto-selected (`app/users/views.py:174`). In tests: inject `main_branch` fixture, create data with `branch_id=main_branch.id`, then login — the session picks up the branch automatically. Staff users additionally need `staff_user.set_branches([main_branch]); db_session.commit()` BEFORE login.
- **Test credentials** (from `tests/conftest.py`): admin = `admin`/`admin123`, staff = `staff`/`staff123`.
- **`PurchaseBill` key fields:** `bill_number` (unique), `vendor_id`, `vendor_name` (snapshot), `vendor_tin`, `vendor_address`, `branch_id`, `bill_date`, `due_date`, `status` (`draft|posted|partially_paid|paid|cancelled|voided`), `subtotal`, `vat_amount`, `total_before_wt`, `withholding_tax_rate`, `withholding_tax_amount`, `total_amount`, `amount_paid`, `balance`, `payment_terms`. `balance = total_amount - amount_paid` is the outstanding amount.
- **Global badge classes already in `app/static/css/style.css:346-365`:** `.badge`, `.badge-draft`, `.badge-posted`, `.badge-partial`, `.badge-paid`, `.badge-void`, `.badge-cancelled`. Use these; do NOT redefine `.badge*` locally.
- **Design tokens** (`style.css:5-28`): `--bg`, `--card`, `--border`, `--text`, `--text-2`, `--text-3`, `--blue`, `--green`, `--red`, `--amber`, `--radius`, `--shadow`, `--mono`. Never hardcode these colors.
- **No JS popups** — no `confirm()`/`alert()`/`prompt()`. The selection JS below only toggles checkboxes and rewrites export hrefs.
- **PH time** — `from app.utils import ph_now`; never `datetime.now()`.
- Run tests with `python -m pytest <path> -v` from repo root `C:\envs\cas`.

---

### Task 1: Failing unit tests for `compute_bills_summary`

**Files:**
- Create: `tests/unit/test_purchase_bills_utils.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for purchase bills summary helper."""
import pytest
from datetime import timedelta
from decimal import Decimal

from app.branches.models import Branch
from app.vendors.models import Vendor
from app.purchase_bills.models import PurchaseBill
from app.utils import ph_now


def make_vendor(db_session, code='SV001', name='Summary Vendor'):
    v = Vendor(code=code, name=name, check_payee_name=name, is_active=True)
    db_session.add(v)
    db_session.flush()
    return v


def make_branch(db_session, code='BR2', name='Branch Two'):
    b = Branch(code=code, name=name, address='456 Side St',
               phone='000-000-0000', email='br2@test.com', is_active=True)
    db_session.add(b)
    db_session.flush()
    return b


def make_bill(db_session, vendor, branch, bill_number, due_date, status='posted',
              total_amount=Decimal('1000.00'), balance=None):
    today = ph_now().date()
    b = PurchaseBill(
        bill_number=bill_number,
        vendor_id=vendor.id,
        vendor_name=vendor.name,
        vendor_tin='',
        vendor_address='',
        branch_id=branch.id,
        bill_date=today,
        due_date=due_date,
        status=status,
        subtotal=total_amount,
        vat_amount=Decimal('0.00'),
        total_before_wt=total_amount,
        withholding_tax_rate=Decimal('0.00'),
        withholding_tax_amount=Decimal('0.00'),
        total_amount=total_amount,
        amount_paid=Decimal('0.00'),
        balance=balance if balance is not None else total_amount,
        payment_terms='Net 30',
    )
    db_session.add(b)
    db_session.flush()
    return b


@pytest.mark.usefixtures('app')
class TestBillsSummary:
    def test_summary_buckets(self, db_session, main_branch):
        from app.purchase_bills.utils import compute_bills_summary
        vendor = make_vendor(db_session)
        today = ph_now().date()

        # Overdue (posted, due 10 days ago)
        make_bill(db_session, vendor, main_branch, 'S001',
                  due_date=today - timedelta(days=10),
                  total_amount=Decimal('100.00'))
        # Due soon (posted, due in 3 days)
        make_bill(db_session, vendor, main_branch, 'S002',
                  due_date=today + timedelta(days=3),
                  total_amount=Decimal('200.00'))
        # Outstanding but not overdue/due-soon (due in 30 days)
        make_bill(db_session, vendor, main_branch, 'S003',
                  due_date=today + timedelta(days=30),
                  total_amount=Decimal('400.00'))
        # Draft (not in outstanding)
        make_bill(db_session, vendor, main_branch, 'S004',
                  due_date=today, status='draft',
                  total_amount=Decimal('999.00'))
        # Due today (boundary: inclusive lower bound of due-soon window)
        make_bill(db_session, vendor, main_branch, 'S005',
                  due_date=today,
                  total_amount=Decimal('50.00'))
        db_session.commit()

        s = compute_bills_summary(main_branch.id)
        assert s['outstanding_total'] == Decimal('750.00')
        assert s['outstanding_count'] == 4
        assert s['overdue_total'] == Decimal('100.00')
        assert s['overdue_count'] == 1
        assert s['due_soon_total'] == Decimal('250.00')
        assert s['due_soon_count'] == 2
        assert s['draft_count'] == 1

    def test_partially_paid_included_with_balance(self, db_session, main_branch):
        from app.purchase_bills.utils import compute_bills_summary
        vendor = make_vendor(db_session, code='SV002')
        today = ph_now().date()

        make_bill(db_session, vendor, main_branch, 'S010',
                  due_date=today - timedelta(days=5), status='partially_paid',
                  total_amount=Decimal('1000.00'), balance=Decimal('400.00'))
        db_session.commit()

        s = compute_bills_summary(main_branch.id)
        assert s['outstanding_total'] == Decimal('400.00')
        assert s['overdue_total'] == Decimal('400.00')
        assert s['outstanding_count'] == 1

    def test_closed_statuses_excluded(self, db_session, main_branch):
        from app.purchase_bills.utils import compute_bills_summary
        vendor = make_vendor(db_session, code='SV003')
        today = ph_now().date()

        for i, status in enumerate(['paid', 'voided', 'cancelled']):
            make_bill(db_session, vendor, main_branch, f'S02{i}',
                      due_date=today - timedelta(days=5), status=status,
                      total_amount=Decimal('500.00'))
        db_session.commit()

        s = compute_bills_summary(main_branch.id)
        assert s['outstanding_total'] == Decimal('0.00')
        assert s['outstanding_count'] == 0
        assert s['overdue_count'] == 0

    def test_branch_scoping(self, db_session, main_branch):
        from app.purchase_bills.utils import compute_bills_summary
        vendor = make_vendor(db_session, code='SV004')
        other = make_branch(db_session)
        today = ph_now().date()

        make_bill(db_session, vendor, main_branch, 'S030',
                  due_date=today, total_amount=Decimal('100.00'))
        make_bill(db_session, vendor, other, 'S031',
                  due_date=today, total_amount=Decimal('900.00'))
        db_session.commit()

        s = compute_bills_summary(main_branch.id)
        assert s['outstanding_total'] == Decimal('100.00')
        assert s['outstanding_count'] == 1

    def test_empty_branch_returns_zeros(self, db_session, main_branch):
        from app.purchase_bills.utils import compute_bills_summary
        s = compute_bills_summary(main_branch.id)
        assert s['outstanding_total'] == Decimal('0.00')
        assert s['outstanding_count'] == 0
        assert s['overdue_total'] == Decimal('0.00')
        assert s['due_soon_total'] == Decimal('0.00')
        assert s['draft_count'] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_purchase_bills_utils.py -v`
Expected: All 5 tests FAIL with `ModuleNotFoundError: No module named 'app.purchase_bills.utils'` (or ImportError).

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_purchase_bills_utils.py
git commit -m "test: add failing unit tests for purchase bills summary helper"
```

---

### Task 2: Implement `compute_bills_summary`

**Files:**
- Create: `app/purchase_bills/utils.py`
- Test: `tests/unit/test_purchase_bills_utils.py` (from Task 1)

- [ ] **Step 1: Write the implementation**

```python
from decimal import Decimal
from datetime import timedelta
from app.utils import ph_now

# Statuses that carry an outstanding payable balance
OPEN_STATUSES = ('posted', 'partially_paid')


def compute_bills_summary(branch_id):
    """Return summary metrics for the purchase bills list page cards.

    Keys: outstanding_total/_count, overdue_total/_count,
    due_soon_total/_count (due within 7 days), draft_count.
    Amounts are Decimal sums of bill.balance over open bills in the branch.
    """
    from app import db
    from app.purchase_bills.models import PurchaseBill
    today = ph_now().date()

    def _agg(*extra_filters):
        total, count = (
            db.session.query(
                db.func.coalesce(db.func.sum(PurchaseBill.balance), 0),
                db.func.count(PurchaseBill.id),
            )
            .filter(
                PurchaseBill.branch_id == branch_id,
                PurchaseBill.status.in_(OPEN_STATUSES),
                *extra_filters,
            )
            .one()
        )
        return Decimal(str(total)).quantize(Decimal('0.01')), count

    outstanding_total, outstanding_count = _agg()
    overdue_total, overdue_count = _agg(
        PurchaseBill.due_date.isnot(None),
        PurchaseBill.due_date < today,
    )
    due_soon_total, due_soon_count = _agg(
        PurchaseBill.due_date.isnot(None),
        PurchaseBill.due_date >= today,
        PurchaseBill.due_date <= today + timedelta(days=7),
    )
    draft_count = PurchaseBill.query.filter_by(
        branch_id=branch_id, status='draft').count()

    return {
        'outstanding_total': outstanding_total,
        'outstanding_count': outstanding_count,
        'overdue_total': overdue_total,
        'overdue_count': overdue_count,
        'due_soon_total': due_soon_total,
        'due_soon_count': due_soon_count,
        'draft_count': draft_count,
    }
```

- [ ] **Step 2: Run unit tests to verify they pass**

Run: `python -m pytest tests/unit/test_purchase_bills_utils.py -v`
Expected: 5 passed.

- [ ] **Step 3: Commit**

```bash
git add app/purchase_bills/utils.py
git commit -m "feat: add compute_bills_summary helper for purchase bills list cards"
```

---

### Task 3: PH-time cleanups in `views.py`

**Files:**
- Modify: `app/purchase_bills/views.py` (lines ~45, ~160, ~227)

- [ ] **Step 1: Replace the three `datetime.now()` calls with `ph_now()`**

In `generate_bill_number()` (line ~45):
```python
# Before:
    current_year = datetime.now().year
# After:
    current_year = ph_now().year
```

In `export_excel()` (line ~160) and `export_csv_route()` (line ~227):
```python
# Before:
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
# After:
    timestamp = ph_now().strftime('%Y%m%d_%H%M%S')
```

`ph_now` is already imported (line 16). Then check whether `datetime` is still used anywhere in the file:

Run: `grep -n "datetime\." app/purchase_bills/views.py`

If no `datetime.` usages remain, change the import on line 20 from
`from datetime import datetime, date, timedelta` to `from datetime import date, timedelta`.
If other usages remain, leave the import as is.

- [ ] **Step 2: Run existing test suite to confirm nothing broke**

Run: `python -m pytest tests/unit/test_wht_per_line_item.py tests/unit/test_vendor_model.py -v`
Expected: All pass (these exercise bill creation paths).

- [ ] **Step 3: Commit**

```bash
git add app/purchase_bills/views.py
git commit -m "fix: use ph_now() instead of datetime.now() in purchase bills views"
```

---

### Task 4: Failing integration tests for the redesigned list page

**Files:**
- Create: `tests/integration/test_purchase_bill_views.py`

- [ ] **Step 1: Write the tests**

```python
"""Integration tests for the purchase bills list page redesign."""
import pytest
from datetime import timedelta
from decimal import Decimal

from app.vendors.models import Vendor
from app.purchase_bills.models import PurchaseBill
from app.utils import ph_now


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def make_vendor(db_session, code='PV001', name='Page Vendor'):
    v = Vendor(code=code, name=name, check_payee_name=name, is_active=True,
               payment_terms='Net 30')
    db_session.add(v)
    db_session.commit()
    return v


def make_bill(db_session, vendor, branch, bill_number, status='posted',
              days_until_due=30, total_amount=Decimal('1000.00'), balance=None,
              bill_date=None):
    today = ph_now().date()
    b = PurchaseBill(
        bill_number=bill_number, vendor_id=vendor.id,
        vendor_name=vendor.name, vendor_tin='', vendor_address='',
        branch_id=branch.id,
        bill_date=bill_date or today,
        due_date=today + timedelta(days=days_until_due),
        status=status, subtotal=total_amount,
        vat_amount=Decimal('0.00'), total_before_wt=total_amount,
        withholding_tax_rate=Decimal('0.00'),
        withholding_tax_amount=Decimal('0.00'),
        total_amount=total_amount,
        amount_paid=Decimal('0.00'),
        balance=balance if balance is not None else total_amount,
        payment_terms='Net 30',
    )
    db_session.add(b)
    db_session.commit()
    return b


class TestSummaryCards:
    def test_cards_render_with_totals(self, client, db_session, admin_user, main_branch):
        vendor = make_vendor(db_session)
        make_bill(db_session, vendor, main_branch, 'PBT-001',
                  days_until_due=-10, total_amount=Decimal('100.00'))   # overdue
        make_bill(db_session, vendor, main_branch, 'PBT-002',
                  days_until_due=3, total_amount=Decimal('200.00'))     # due soon
        make_bill(db_session, vendor, main_branch, 'PBT-003',
                  status='draft', total_amount=Decimal('999.00'))       # draft
        login(client)
        resp = client.get('/purchase-bills')
        assert resp.status_code == 200
        assert b'Outstanding AP' in resp.data
        assert b'Overdue' in resp.data
        assert b'Due in 7 Days' in resp.data
        assert b'Drafts' in resp.data
        assert b'300.00' in resp.data   # outstanding = 100 + 200
        assert b'100.00' in resp.data   # overdue


class TestFilters:
    def test_status_filter(self, client, db_session, admin_user, main_branch):
        vendor = make_vendor(db_session)
        make_bill(db_session, vendor, main_branch, 'PBF-001', status='posted')
        make_bill(db_session, vendor, main_branch, 'PBF-002', status='draft')
        login(client)
        resp = client.get('/purchase-bills?status=draft')
        assert b'PBF-002' in resp.data
        assert b'PBF-001' not in resp.data

    def test_vendor_filter(self, client, db_session, admin_user, main_branch):
        v1 = make_vendor(db_session, code='PV010', name='Vendor Ten')
        v2 = make_vendor(db_session, code='PV011', name='Vendor Eleven')
        make_bill(db_session, v1, main_branch, 'PBF-010')
        make_bill(db_session, v2, main_branch, 'PBF-011')
        login(client)
        resp = client.get(f'/purchase-bills?vendor={v1.id}')
        assert b'PBF-010' in resp.data
        assert b'PBF-011' not in resp.data

    def test_date_range_filter(self, client, db_session, admin_user, main_branch):
        vendor = make_vendor(db_session)
        today = ph_now().date()
        old_date = today - timedelta(days=60)
        make_bill(db_session, vendor, main_branch, 'PBF-020', bill_date=old_date)
        make_bill(db_session, vendor, main_branch, 'PBF-021')
        login(client)
        cutoff = (today - timedelta(days=30)).isoformat()
        resp = client.get(f'/purchase-bills?date_from={cutoff}')
        assert b'PBF-021' in resp.data
        assert b'PBF-020' not in resp.data

    def test_invalid_date_ignored(self, client, db_session, admin_user, main_branch):
        vendor = make_vendor(db_session)
        make_bill(db_session, vendor, main_branch, 'PBF-030')
        login(client)
        resp = client.get('/purchase-bills?date_from=not-a-date')
        assert resp.status_code == 200
        assert b'PBF-030' in resp.data

    def test_search_by_bill_number(self, client, db_session, admin_user, main_branch):
        vendor = make_vendor(db_session)
        make_bill(db_session, vendor, main_branch, 'PBQ-777')
        make_bill(db_session, vendor, main_branch, 'PBQ-888')
        login(client)
        resp = client.get('/purchase-bills?q=777')
        assert b'PBQ-777' in resp.data
        assert b'PBQ-888' not in resp.data

    def test_search_by_vendor_name(self, client, db_session, admin_user, main_branch):
        v1 = make_vendor(db_session, code='PV020', name='Acme Hardware')
        v2 = make_vendor(db_session, code='PV021', name='Bravo Foods')
        make_bill(db_session, v1, main_branch, 'PBQ-100')
        make_bill(db_session, v2, main_branch, 'PBQ-200')
        login(client)
        resp = client.get('/purchase-bills?q=acme')
        assert b'PBQ-100' in resp.data
        assert b'PBQ-200' not in resp.data


class TestTable:
    def test_balance_column_and_wt_dash(self, client, db_session, admin_user, main_branch):
        vendor = make_vendor(db_session)
        make_bill(db_session, vendor, main_branch, 'PBB-001',
                  status='partially_paid', total_amount=Decimal('1000.00'),
                  balance=Decimal('400.00'))
        login(client)
        resp = client.get('/purchase-bills')
        assert b'400.00' in resp.data           # balance column
        assert b'-\xe2\x82\xb10.00' not in resp.data  # no "-₱0.00" for zero WT

    def test_all_six_status_badges(self, client, db_session, admin_user, main_branch):
        vendor = make_vendor(db_session)
        statuses = ['draft', 'posted', 'partially_paid', 'paid', 'voided', 'cancelled']
        for i, status in enumerate(statuses):
            make_bill(db_session, vendor, main_branch, f'PBS-00{i}', status=status)
        login(client)
        resp = client.get('/purchase-bills')
        for cls in [b'badge-draft', b'badge-posted', b'badge-partial',
                    b'badge-paid', b'badge-void', b'badge-cancelled']:
            assert cls in resp.data

    def test_no_confirm_js(self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.get('/purchase-bills')
        assert b'confirm(' not in resp.data

    def test_pagination_preserves_filters(self, client, db_session, admin_user, main_branch):
        vendor = make_vendor(db_session)
        for i in range(51):  # per_page is 50
            make_bill(db_session, vendor, main_branch, f'PBP-{i:03d}')
        login(client)
        resp = client.get('/purchase-bills?status=posted')
        assert resp.status_code == 200
        assert b'status=posted' in resp.data  # filter param in pagination link


class TestExportSelection:
    def test_export_csv_with_ids_returns_only_selected(self, client, db_session,
                                                       admin_user, main_branch):
        vendor = make_vendor(db_session)
        b1 = make_bill(db_session, vendor, main_branch, 'PBX-001')
        b2 = make_bill(db_session, vendor, main_branch, 'PBX-002')
        login(client)
        resp = client.get(f'/purchase-bills/export/csv?ids={b1.id}')
        assert resp.status_code == 200
        assert b'PBX-001' in resp.data
        assert b'PBX-002' not in resp.data

    def test_export_csv_invalid_ids_ignored(self, client, db_session,
                                            admin_user, main_branch):
        vendor = make_vendor(db_session)
        make_bill(db_session, vendor, main_branch, 'PBX-010')
        login(client)
        resp = client.get('/purchase-bills/export/csv?ids=abc')
        assert resp.status_code == 200
        assert b'PBX-010' in resp.data  # falls back to unfiltered export


class TestAccess:
    def test_staff_can_view_list(self, client, db_session, staff_user, main_branch):
        staff_user.set_branches([main_branch])
        db_session.commit()
        login(client, username='staff', password='staff123')
        resp = client.get('/purchase-bills')
        assert resp.status_code == 200
```

- [ ] **Step 2: Run tests — feature tests must fail, pre-existing behavior may pass**

Run: `python -m pytest tests/integration/test_purchase_bill_views.py -v`
Expected: FAILures on `test_cards_render_with_totals` (no cards), `test_status_filter`-class tests for `q`/`date_from` (params ignored), `test_balance_column_and_wt_dash`, `test_all_six_status_badges`, `test_export_csv_with_ids_returns_only_selected`. `test_no_confirm_js` and `test_staff_can_view_list` may already pass — that is fine.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_purchase_bill_views.py
git commit -m "test: add failing integration tests for purchase bills list redesign"
```

---

### Task 5: Backend — shared filter query, list_bills update, export `ids`

**Files:**
- Modify: `app/purchase_bills/views.py` (`list_bills` at ~line 65, `export_excel` at ~107, `export_csv_route` at ~174)

- [ ] **Step 1: Add `_filtered_bills_query` helper directly above `list_bills`**

```python
def _filtered_bills_query(include_ids=False):
    """Build a branch-scoped PurchaseBill query from request filter args.

    Args read: status, vendor, q, date_from, date_to — and ids when
    include_ids=True (exports only); a valid ids list overrides all
    other filters but stays branch-scoped. Invalid values are ignored.
    """
    current_branch_id = session.get('selected_branch_id')
    query = PurchaseBill.query.filter_by(branch_id=current_branch_id)

    if include_ids:
        ids_param = request.args.get('ids', '')
        if ids_param:
            try:
                ids = [int(x) for x in ids_param.split(',') if x.strip()]
            except ValueError:
                ids = []
            if ids:
                return query.filter(PurchaseBill.id.in_(ids))

    status_filter = request.args.get('status', 'all')
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)

    vendor_filter = request.args.get('vendor', 'all')
    if vendor_filter != 'all':
        try:
            query = query.filter_by(vendor_id=int(vendor_filter))
        except ValueError:
            pass

    q = request.args.get('q', '').strip()
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(PurchaseBill.bill_number.ilike(like),
                                    PurchaseBill.vendor_name.ilike(like)))

    date_from = request.args.get('date_from', '')
    if date_from:
        try:
            query = query.filter(PurchaseBill.bill_date >= date.fromisoformat(date_from))
        except ValueError:
            pass

    date_to = request.args.get('date_to', '')
    if date_to:
        try:
            query = query.filter(PurchaseBill.bill_date <= date.fromisoformat(date_to))
        except ValueError:
            pass

    return query
```

Note: `date` and `db` are already imported at the top of the file.

- [ ] **Step 2: Replace the body of `list_bills`**

```python
@purchase_bills_bp.route('/purchase-bills')
@login_required
def list_bills():
    """List purchase bills with summary cards, filters, search, pagination."""
    from app.purchase_bills.utils import compute_bills_summary

    page = request.args.get('page', 1, type=int)
    per_page = 50

    query = (_filtered_bills_query()
             .options(selectinload(PurchaseBill.line_items))
             .order_by(PurchaseBill.bill_date.desc()))
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    summary = compute_bills_summary(session.get('selected_branch_id'))
    vendors = Vendor.query.filter_by(is_active=True).order_by(Vendor.name).all()

    return render_template('purchase_bills/list.html',
                           bills=pagination.items,
                           pagination=pagination,
                           vendors=vendors,
                           summary=summary,
                           today=ph_now().date(),
                           status_filter=request.args.get('status', 'all'),
                           vendor_filter=request.args.get('vendor', 'all'),
                           q=request.args.get('q', ''),
                           date_from=request.args.get('date_from', ''),
                           date_to=request.args.get('date_to', ''))
```

- [ ] **Step 3: Update both export routes to use the helper**

In `export_excel()` AND `export_csv_route()`, replace everything from
`status_filter = request.args.get('status', 'all')` down to the `vendor_filter` `except ValueError: pass` block (the filter-building section ending just before `bills = query...`) with:

```python
    query = _filtered_bills_query(include_ids=True)
```

and change the subsequent line to use that query (it already reads `bills = query.options(...)...all()` — keep it).

The `columns`/`headers`/`filename`/return sections stay unchanged.

- [ ] **Step 4: Run the backend-dependent integration tests**

Run: `python -m pytest tests/integration/test_purchase_bill_views.py::TestFilters tests/integration/test_purchase_bill_views.py::TestExportSelection -v`
Expected: All pass. (`TestSummaryCards`/`TestTable` still fail — template work is Task 6.)

- [ ] **Step 5: Commit**

```bash
git add app/purchase_bills/views.py
git commit -m "feat: filters, search, date range, summary, export ids for purchase bills list"
```

---

### Task 6: Template rewrite — cards, filter bar, table, selection

**Files:**
- Rewrite: `app/purchase_bills/templates/purchase_bills/list.html`

- [ ] **Step 1: Replace the entire file with:**

```html
{% extends "base.html" %}
{% block title %}Purchase Bills{% endblock %}
{% block page_title %}Purchase Bills{% endblock %}
{% block content %}
{% from "macros.html" import render_flash_messages %}
{{ render_flash_messages() }}

<!-- Summary cards -->
<div class="pb-summary-grid">
    <div class="pb-card">
        <div class="pb-card-label">Outstanding AP</div>
        <div class="pb-card-value">₱{{ '{:,.2f}'.format(summary.outstanding_total) }}</div>
        <div class="pb-card-detail">{{ summary.outstanding_count }} open bill{{ 's' if summary.outstanding_count != 1 else '' }}</div>
    </div>
    <div class="pb-card">
        <div class="pb-card-label" style="color:var(--red);">Overdue</div>
        <div class="pb-card-value" style="color:var(--red);">₱{{ '{:,.2f}'.format(summary.overdue_total) }}</div>
        <div class="pb-card-detail">{{ summary.overdue_count }} bill{{ 's' if summary.overdue_count != 1 else '' }}</div>
    </div>
    <div class="pb-card">
        <div class="pb-card-label" style="color:var(--amber);">Due in 7 Days</div>
        <div class="pb-card-value">₱{{ '{:,.2f}'.format(summary.due_soon_total) }}</div>
        <div class="pb-card-detail">{{ summary.due_soon_count }} bill{{ 's' if summary.due_soon_count != 1 else '' }}</div>
    </div>
    <div class="pb-card">
        <div class="pb-card-label">Drafts</div>
        <div class="pb-card-value">{{ summary.draft_count }}</div>
        <div class="pb-card-detail">to finish</div>
    </div>
</div>

<!-- Filter bar -->
<form method="GET" action="{{ url_for('purchase_bills.list_bills') }}" class="pb-filter-bar">
    <input type="text" name="q" value="{{ q }}" placeholder="Search bill # or vendor"
           class="form-control form-control-sm pb-filter-search">
    <select name="status" class="form-control form-control-sm">
        <option value="all" {% if status_filter == 'all' %}selected{% endif %}>All Statuses</option>
        <option value="draft" {% if status_filter == 'draft' %}selected{% endif %}>Draft</option>
        <option value="posted" {% if status_filter == 'posted' %}selected{% endif %}>Posted</option>
        <option value="partially_paid" {% if status_filter == 'partially_paid' %}selected{% endif %}>Partially Paid</option>
        <option value="paid" {% if status_filter == 'paid' %}selected{% endif %}>Paid</option>
        <option value="voided" {% if status_filter == 'voided' %}selected{% endif %}>Voided</option>
        <option value="cancelled" {% if status_filter == 'cancelled' %}selected{% endif %}>Cancelled</option>
    </select>
    <select name="vendor" class="form-control form-control-sm">
        <option value="all">All Vendors</option>
        {% for v in vendors %}
        <option value="{{ v.id }}" {% if vendor_filter == v.id|string %}selected{% endif %}>{{ v.name }}</option>
        {% endfor %}
    </select>
    <input type="date" name="date_from" value="{{ date_from }}" class="form-control form-control-sm">
    <input type="date" name="date_to" value="{{ date_to }}" class="form-control form-control-sm">
    <button type="submit" class="btn btn-primary btn-sm">Filter</button>
    <a href="{{ url_for('purchase_bills.list_bills') }}" class="btn btn-secondary btn-sm">Clear</a>
</form>

<div class="card">
    <div class="card-header">
        <div class="card-header-actions" style="display:flex; gap:8px; align-items:center;">
            <span id="pb-selected-count" class="pb-selected-count"></span>
            <!-- Future: "Pay selected" button (payment voucher project) renders here -->
            <a href="{{ url_for('purchase_bills.export_excel', status=status_filter, vendor=vendor_filter, q=q, date_from=date_from, date_to=date_to) }}"
               class="btn btn-secondary pb-export-link">📊 Export Excel</a>
            <a href="{{ url_for('purchase_bills.export_csv_route', status=status_filter, vendor=vendor_filter, q=q, date_from=date_from, date_to=date_to) }}"
               class="btn btn-secondary pb-export-link">📄 Export CSV</a>
            <a href="{{ url_for('purchase_bills.create') }}" class="btn btn-primary">➕ Create Bill</a>
        </div>
    </div>
    <div class="card-body">
        {% if bills %}
        {% set badge_map = {'draft':'draft','posted':'posted','partially_paid':'partial','paid':'paid','voided':'void','cancelled':'cancelled'} %}
        <table class="table">
            <thead>
                <tr>
                    <th style="width:28px;"><input type="checkbox" id="pb-check-all" aria-label="Select all bills"></th>
                    <th>Bill #</th><th>Date</th><th>Vendor</th><th>Due Date</th>
                    <th style="text-align:right;">Subtotal</th>
                    <th style="text-align:right;">VAT</th>
                    <th style="text-align:right;">WT</th>
                    <th style="text-align:right;">Net Payable</th>
                    <th style="text-align:right;">Balance</th>
                    <th>Status</th><th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {% for bill in bills %}
                <tr>
                    <td><input type="checkbox" class="pb-row-check" value="{{ bill.id }}" aria-label="Select {{ bill.bill_number }}"></td>
                    <td><a href="{{ url_for('purchase_bills.view', id=bill.id) }}" style="font-weight:600;color:var(--blue);">{{ bill.bill_number }}</a></td>
                    <td>{{ bill.bill_date.strftime('%b %d, %Y') }}</td>
                    <td>{{ bill.vendor_name }}</td>
                    <td {% if bill.due_date and bill.due_date < today and bill.status in ['posted', 'partially_paid'] %}style="color:var(--red);font-weight:600;"{% endif %}>
                        {{ bill.due_date.strftime('%b %d, %Y') if bill.due_date else '—' }}
                    </td>
                    <td style="text-align:right;font-family:var(--mono);">₱{{ '{:,.2f}'.format(bill.subtotal) }}</td>
                    <td style="text-align:right;font-family:var(--mono);">₱{{ '{:,.2f}'.format(bill.vat_amount) }}</td>
                    <td style="text-align:right;font-family:var(--mono);{% if bill.withholding_tax_amount > 0 %}color:var(--red);{% endif %}">
                        {% if bill.withholding_tax_amount > 0 %}-₱{{ '{:,.2f}'.format(bill.withholding_tax_amount) }}{% else %}—{% endif %}
                    </td>
                    <td style="text-align:right;font-family:var(--mono);font-weight:600;">₱{{ '{:,.2f}'.format(bill.total_amount) }}</td>
                    <td style="text-align:right;font-family:var(--mono);font-weight:600;">
                        {% if bill.status in ['paid', 'voided', 'cancelled'] %}—{% else %}₱{{ '{:,.2f}'.format(bill.balance) }}{% endif %}
                    </td>
                    <td><span class="badge badge-{{ badge_map.get(bill.status, 'draft') }}">{{ bill.status|replace('_', ' ')|title }}</span></td>
                    <td>
                        <a href="{{ url_for('purchase_bills.view', id=bill.id) }}" class="btn-action">👁️</a>
                        {% if bill.status == 'draft' %}<a href="{{ url_for('purchase_bills.edit', id=bill.id) }}" class="btn-action">✏️</a>{% endif %}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% else %}
        {% set filters_active = q or status_filter != 'all' or vendor_filter != 'all' or date_from or date_to %}
        <div class="empty-state">
            {% if filters_active %}
            <p>No bills match your filters.</p>
            <a href="{{ url_for('purchase_bills.list_bills') }}" class="btn btn-secondary">Clear Filters</a>
            {% else %}
            <p>No purchase bills found.</p>
            <a href="{{ url_for('purchase_bills.create') }}" class="btn btn-primary">Create First Bill</a>
            {% endif %}
        </div>
        {% endif %}
    </div>

    {% if pagination and pagination.pages > 1 %}
    <div class="card-footer" style="display:flex;justify-content:space-between;align-items:center;padding:16px">
        <div>
            Showing {{ ((pagination.page - 1) * pagination.per_page) + 1 }} to
            {{ [pagination.page * pagination.per_page, pagination.total]|min }} of
            {{ pagination.total }} bills
        </div>
        <div style="display:flex;gap:8px">
            {% if pagination.has_prev %}
            <a href="{{ url_for('purchase_bills.list_bills', page=pagination.prev_num, status=status_filter, vendor=vendor_filter, q=q, date_from=date_from, date_to=date_to) }}"
               class="btn btn-secondary btn-sm">← Previous</a>
            {% endif %}
            {% if pagination.has_next %}
            <a href="{{ url_for('purchase_bills.list_bills', page=pagination.next_num, status=status_filter, vendor=vendor_filter, q=q, date_from=date_from, date_to=date_to) }}"
               class="btn btn-secondary btn-sm">Next →</a>
            {% endif %}
        </div>
    </div>
    {% endif %}
</div>

<style>
.pb-summary-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-bottom: 16px;
}
.pb-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    padding: 14px 16px;
}
.pb-card-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-2);
}
.pb-card-value {
    font-size: 20px;
    font-weight: 700;
    font-family: var(--mono);
    margin: 4px 0 2px;
}
.pb-card-detail { font-size: 12px; color: var(--text-3); }
.pb-filter-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
    margin-bottom: 16px;
}
.pb-filter-search { flex: 1; min-width: 180px; }
.pb-selected-count { font-size: 13px; color: var(--text-2); }
.btn-action {
    padding: 4px 8px;
    border-radius: 4px;
    background: var(--bg);
    border: 1px solid var(--border);
    cursor: pointer;
    font-size: 14px;
}
.btn-action:hover { background: var(--border); }
@media (max-width: 1024px) { .pb-summary-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 640px)  { .pb-summary-grid { grid-template-columns: 1fr; } }
</style>

<script>
(function () {
    const checkAll = document.getElementById('pb-check-all');
    const rowChecks = document.querySelectorAll('.pb-row-check');
    const counter = document.getElementById('pb-selected-count');
    const exportLinks = document.querySelectorAll('.pb-export-link');

    function updateSelection() {
        const selected = Array.from(rowChecks).filter(cb => cb.checked).map(cb => cb.value);
        counter.textContent = selected.length ? selected.length + ' selected' : '';
        exportLinks.forEach(link => {
            const url = new URL(link.href, window.location.origin);
            if (selected.length) {
                url.searchParams.set('ids', selected.join(','));
            } else {
                url.searchParams.delete('ids');
            }
            link.href = url.pathname + '?' + url.searchParams.toString();
        });
    }

    if (checkAll) {
        checkAll.addEventListener('change', function () {
            rowChecks.forEach(cb => { cb.checked = checkAll.checked; });
            updateSelection();
        });
    }
    rowChecks.forEach(cb => cb.addEventListener('change', updateSelection));
})();
</script>
{% endblock %}
```

Note: the old local `.badge*` CSS is gone — badges now come from the global classes in `style.css`. All colors are design tokens.

- [ ] **Step 2: Run the full integration test file**

Run: `python -m pytest tests/integration/test_purchase_bill_views.py -v`
Expected: All 14 tests pass.

- [ ] **Step 3: Commit**

```bash
git add app/purchase_bills/templates/purchase_bills/list.html
git commit -m "feat: purchase bills list redesign - summary cards, filter bar, selection, balance column"
```

---

### Task 7: Full regression run

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest`
Expected: All tests pass except the known pre-existing failure `test_user_is_active_default` (unrelated to this work). The new files add 5 unit + 14 integration tests.

- [ ] **Step 2: If anything else fails, fix before declaring done**

A failure in vendor or WHT tests most likely means the `views.py` import cleanup (Task 3) or query helper (Task 5) broke something — re-read the diff of `app/purchase_bills/views.py`.

- [ ] **Step 3: Commit any fixes**

```bash
git add -A
git commit -m "fix: regression fixes for purchase bills list redesign"
```
(Skip if nothing changed.)
