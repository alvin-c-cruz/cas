# Vendor Module Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix vendor module bugs (confirm() delete, payment terms mismatch, readonly code field) and add a tabbed vendor detail page with AP aging, WHT YTD, and paginated bill history.

**Architecture:** Server-rendered Flask views, Approach A — tab switching via `?tab=` query param (full page reload), aging/WHT helpers in a new `app/vendors/utils.py`, detail page at `GET /vendors/<id>`. All existing routes unchanged except list (vendor name becomes a link).

**Tech Stack:** Flask, SQLAlchemy, SQLite (batch migrations), Jinja2, WTForms, pytest, Flask-Migrate/Alembic.

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `app/vendors/forms.py` | Modify | Fix payment terms choices |
| `app/vendors/utils.py` | **Create** | `compute_ap_aging`, `compute_wht_ytd` helpers |
| `app/vendors/views.py` | Modify | Add `detail()` route |
| `app/vendors/templates/vendors/list.html` | Modify | Delete modal, vendor name links |
| `app/vendors/templates/vendors/form.html` | Modify | Locked code field visual |
| `app/vendors/templates/vendors/detail.html` | **Create** | Tabbed detail page |
| `migrations/versions/XXXX_fix_payment_terms.py` | **Create** | Data migration COD→Cash on Delivery |
| `tests/unit/test_vendor_model.py` | **Create** | Unit tests for aging/WHT helpers |
| `tests/integration/test_vendor_views.py` | **Create** | Integration tests for all routes |

---

## Context for Every Task

**App factory pattern:** `app/__init__.py::create_app()` registers all blueprints. The vendors blueprint is `vendors_bp` in `app/vendors/views.py`, registered as `vendors`.

**PurchaseBill key fields:** `vendor_id` (FK), `branch_id` (FK), `bill_number`, `bill_date` (Date), `due_date` (Date), `status` (string: `draft|posted|partially_paid|paid|cancelled|voided`), `subtotal`, `vat_amount`, `withholding_tax_amount`, `total_before_wt`, `total_amount` (= net after WHT). No `net_payable` field — use `total_amount`.

**Time:** Always use `ph_now()` from `app.utils`, never `datetime.now()`.

**Audit trail:** Every create/update/delete calls `log_create`/`log_update`/`log_delete` from `app.audit.utils`.

**Test fixtures available** (from `tests/conftest.py`): `db_session`, `client`, `admin_user`, `accountant_user`, `staff_user`, `viewer_user`, `main_branch`, `cash_account`, `expense_account`. `db_session` creates/drops all tables per test. `client` is an unauthenticated test client. Use `client.post('/login', data={...})` to log in.

**Login in tests:**
```python
def login(client, username='admin', password='ac1123581321'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)
```

---

## Task 1: Fix Payment Terms (Forms + Data Migration)

**Files:**
- Modify: `app/vendors/forms.py`
- Create: `migrations/versions/XXXX_fix_payment_terms.py`

- [ ] **Step 1: Update form choices**

In `app/vendors/forms.py`, find the `payment_terms` field and change the two affected tuples:

```python
# Before (around line 43-50):
payment_terms = SelectField('Payment Terms', choices=[
    ('Net 15', 'Net 15'),
    ('Net 30', 'Net 30'),
    ('Net 45', 'Net 45'),
    ('Net 60', 'Net 60'),
    ('COD', 'Cash on Delivery'),
    ('Advance', 'Advance Payment')
], validators=[DataRequired()])

# After:
payment_terms = SelectField('Payment Terms', choices=[
    ('Net 15', 'Net 15'),
    ('Net 30', 'Net 30'),
    ('Net 45', 'Net 45'),
    ('Net 60', 'Net 60'),
    ('Cash on Delivery', 'Cash on Delivery'),
    ('Advance Payment', 'Advance Payment')
], validators=[DataRequired()])
```

- [ ] **Step 2: Create blank migration**

```powershell
flask db revision -m "fix payment terms data"
```

Expected: creates `migrations/versions/XXXX_fix_payment_terms_data.py`

- [ ] **Step 3: Edit the migration to add data updates**

Open the newly created migration file. Replace the empty `upgrade()` and `downgrade()` bodies:

```python
def upgrade():
    op.execute("UPDATE vendor SET payment_terms = 'Cash on Delivery' WHERE payment_terms = 'COD'")
    op.execute("UPDATE vendor SET payment_terms = 'Advance Payment' WHERE payment_terms = 'Advance'")


def downgrade():
    op.execute("UPDATE vendor SET payment_terms = 'COD' WHERE payment_terms = 'Cash on Delivery'")
    op.execute("UPDATE vendor SET payment_terms = 'Advance' WHERE payment_terms = 'Advance Payment'")
```

- [ ] **Step 4: Run the migration**

```powershell
flask db upgrade
```

Expected: `Running upgrade ... -> XXXX`

- [ ] **Step 5: Verify in shell**

```powershell
flask shell
```

```python
from app.vendors.models import Vendor
Vendor.query.all()  # confirm no vendor has payment_terms='COD' or 'Advance'
exit()
```

- [ ] **Step 6: Commit**

```powershell
git add app/vendors/forms.py migrations/versions/
git commit -m "fix: normalize payment terms stored values (COD→Cash on Delivery, Advance→Advance Payment)"
```

---

## Task 2: Unit Tests — compute_ap_aging and compute_wht_ytd (Write Failing Tests)

**Files:**
- Create: `tests/unit/test_vendor_model.py`

These are DB-touching unit tests — they use `db_session` and `main_branch` from conftest.

- [ ] **Step 1: Create the test file**

Create `tests/unit/test_vendor_model.py`:

```python
"""Unit tests for vendor AP aging and WHT YTD helpers."""
import pytest
from datetime import date, timedelta
from decimal import Decimal

from app.vendors.models import Vendor
from app.purchase_bills.models import PurchaseBill, PurchaseBillItem
from app.utils import ph_now


def make_vendor(db_session, code='TV001', name='Test Vendor'):
    v = Vendor(code=code, name=name, check_payee_name=name, is_active=True)
    db_session.add(v)
    db_session.flush()
    return v


def make_bill(db_session, vendor, branch, bill_number, due_date, status='posted',
              total_amount=Decimal('1000.00')):
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
        payment_terms='Net 30',
    )
    db_session.add(b)
    db_session.flush()
    return b


@pytest.mark.usefixtures('app')
class TestApAging:
    def test_aging_buckets(self, db_session, main_branch):
        from app.vendors.utils import compute_ap_aging
        vendor = make_vendor(db_session)
        today = ph_now().date()

        make_bill(db_session, vendor, main_branch, 'B001',
                  due_date=today + timedelta(days=5),
                  total_amount=Decimal('100.00'))   # current
        make_bill(db_session, vendor, main_branch, 'B002',
                  due_date=today - timedelta(days=15),
                  total_amount=Decimal('200.00'))   # 1-30
        make_bill(db_session, vendor, main_branch, 'B003',
                  due_date=today - timedelta(days=45),
                  total_amount=Decimal('300.00'))   # 31-60
        make_bill(db_session, vendor, main_branch, 'B004',
                  due_date=today - timedelta(days=75),
                  total_amount=Decimal('400.00'))   # 61-90
        make_bill(db_session, vendor, main_branch, 'B005',
                  due_date=today - timedelta(days=100),
                  total_amount=Decimal('500.00'))   # 90+
        db_session.commit()

        aging = compute_ap_aging(vendor.id)
        assert aging['current'] == Decimal('100.00')
        assert aging['1_30'] == Decimal('200.00')
        assert aging['31_60'] == Decimal('300.00')
        assert aging['61_90'] == Decimal('400.00')
        assert aging['90_plus'] == Decimal('500.00')
        assert aging['total'] == Decimal('1500.00')

    def test_aging_excludes_draft_and_voided(self, db_session, main_branch):
        from app.vendors.utils import compute_ap_aging
        vendor = make_vendor(db_session, code='TV002')
        today = ph_now().date()

        make_bill(db_session, vendor, main_branch, 'B006',
                  due_date=today - timedelta(days=10), status='draft',
                  total_amount=Decimal('999.00'))
        make_bill(db_session, vendor, main_branch, 'B007',
                  due_date=today - timedelta(days=10), status='voided',
                  total_amount=Decimal('999.00'))
        db_session.commit()

        aging = compute_ap_aging(vendor.id)
        assert aging['total'] == Decimal('0.00')

    def test_aging_bill_with_no_due_date_skipped(self, db_session, main_branch):
        from app.vendors.utils import compute_ap_aging
        # due_date is required by model (nullable=False), so we just verify
        # that bills with due_date=None are safely skipped (defensive coding)
        vendor = make_vendor(db_session, code='TV003')
        # No bills — should return all zeros
        db_session.commit()
        aging = compute_ap_aging(vendor.id)
        assert aging['total'] == Decimal('0.00')


@pytest.mark.usefixtures('app')
class TestWhtYtd:
    def test_wht_ytd_current_year_only(self, db_session, main_branch):
        from app.vendors.utils import compute_wht_ytd
        from app.withholding_tax.models import WithholdingTax

        vendor = make_vendor(db_session, code='TV004')
        wt = WithholdingTax.query.filter_by(code='WC010').first()
        assert wt is not None, "Seed WHT WC010 not found — run flask seed-db first"

        today = ph_now().date()
        prior_year_date = date(today.year - 1, 6, 1)

        # Current year bill with WHT
        bill_current = make_bill(db_session, vendor, main_branch, 'B010',
                                 due_date=today, status='posted',
                                 total_amount=Decimal('1000.00'))
        item_current = PurchaseBillItem(
            bill_id=bill_current.id,
            description='Service', quantity=1, unit_cost=Decimal('1000.00'),
            vat_rate=Decimal('0.00'), vat_amount=Decimal('0.00'),
            line_total=Decimal('1000.00'),
            wt_id=wt.id, wt_rate=wt.rate,
            wt_amount=Decimal('100.00'),
        )
        db_session.add(item_current)

        # Prior year bill — must be excluded
        bill_prior = PurchaseBill(
            bill_number='B011', vendor_id=vendor.id, vendor_name=vendor.name,
            vendor_tin='', vendor_address='', branch_id=main_branch.id,
            bill_date=prior_year_date, due_date=prior_year_date,
            status='posted', subtotal=Decimal('500.00'),
            vat_amount=Decimal('0.00'), total_before_wt=Decimal('500.00'),
            withholding_tax_rate=Decimal('0.00'), withholding_tax_amount=Decimal('50.00'),
            total_amount=Decimal('450.00'), payment_terms='Net 30',
        )
        db_session.add(bill_prior)
        db_session.flush()
        item_prior = PurchaseBillItem(
            bill_id=bill_prior.id,
            description='Old Service', quantity=1, unit_cost=Decimal('500.00'),
            vat_rate=Decimal('0.00'), vat_amount=Decimal('0.00'),
            line_total=Decimal('500.00'),
            wt_id=wt.id, wt_rate=wt.rate,
            wt_amount=Decimal('50.00'),
        )
        db_session.add(item_prior)
        db_session.commit()

        result = compute_wht_ytd(vendor.id)
        assert len(result) == 1
        assert result[0]['code'] == 'WC010'
        assert result[0]['total'] == Decimal('100.00')

    def test_wht_ytd_groups_by_code(self, db_session, main_branch):
        from app.vendors.utils import compute_wht_ytd
        from app.withholding_tax.models import WithholdingTax

        vendor = make_vendor(db_session, code='TV005')
        wt010 = WithholdingTax.query.filter_by(code='WC010').first()
        wt060 = WithholdingTax.query.filter_by(code='WC060').first()
        assert wt010 and wt060

        today = ph_now().date()
        bill = make_bill(db_session, vendor, main_branch, 'B020',
                         due_date=today, status='posted',
                         total_amount=Decimal('2000.00'))
        db_session.add(PurchaseBillItem(
            bill_id=bill.id, description='Prof Fees', quantity=1,
            unit_cost=Decimal('1000.00'), vat_rate=Decimal('0.00'),
            vat_amount=Decimal('0.00'), line_total=Decimal('1000.00'),
            wt_id=wt010.id, wt_rate=wt010.rate, wt_amount=Decimal('100.00'),
        ))
        db_session.add(PurchaseBillItem(
            bill_id=bill.id, description='Contractor', quantity=1,
            unit_cost=Decimal('1000.00'), vat_rate=Decimal('0.00'),
            vat_amount=Decimal('0.00'), line_total=Decimal('1000.00'),
            wt_id=wt060.id, wt_rate=wt060.rate, wt_amount=Decimal('20.00'),
        ))
        db_session.commit()

        result = compute_wht_ytd(vendor.id)
        codes = {r['code']: r['total'] for r in result}
        assert codes['WC010'] == Decimal('100.00')
        assert codes['WC060'] == Decimal('20.00')
```

- [ ] **Step 2: Run tests — expect FAIL (utils.py doesn't exist yet)**

```powershell
pytest tests/unit/test_vendor_model.py -v
```

Expected: `ImportError: cannot import name 'compute_ap_aging' from 'app.vendors.utils'`

---

## Task 3: Implement app/vendors/utils.py

**Files:**
- Create: `app/vendors/utils.py`

- [ ] **Step 1: Create utils.py**

Create `app/vendors/utils.py`:

```python
from decimal import Decimal
from app.utils import ph_now


def compute_ap_aging(vendor_id):
    """Return AP aging buckets for a vendor (posted bills only, no receipts check)."""
    from app.purchase_bills.models import PurchaseBill
    today = ph_now().date()
    bills = PurchaseBill.query.filter_by(vendor_id=vendor_id, status='posted').all()
    buckets = {
        'current': Decimal('0.00'),
        '1_30': Decimal('0.00'),
        '31_60': Decimal('0.00'),
        '61_90': Decimal('0.00'),
        '90_plus': Decimal('0.00'),
    }
    for bill in bills:
        if bill.due_date is None:
            continue
        days_overdue = (today - bill.due_date).days
        amount = bill.total_amount or Decimal('0.00')
        if days_overdue <= 0:
            buckets['current'] += amount
        elif days_overdue <= 30:
            buckets['1_30'] += amount
        elif days_overdue <= 60:
            buckets['31_60'] += amount
        elif days_overdue <= 90:
            buckets['61_90'] += amount
        else:
            buckets['90_plus'] += amount
    buckets['total'] = sum(buckets.values(), Decimal('0.00'))
    return buckets


def compute_wht_ytd(vendor_id):
    """Return list of {code, name, total} dicts for WHT withheld this calendar year."""
    from app import db
    from app.purchase_bills.models import PurchaseBill, PurchaseBillItem
    from app.withholding_tax.models import WithholdingTax
    from sqlalchemy import extract
    year = ph_now().year
    rows = (
        db.session.query(
            PurchaseBillItem.wt_id,
            db.func.sum(PurchaseBillItem.wt_amount).label('total')
        )
        .join(PurchaseBill, PurchaseBillItem.bill_id == PurchaseBill.id)
        .filter(
            PurchaseBill.vendor_id == vendor_id,
            PurchaseBill.status == 'posted',
            extract('year', PurchaseBill.bill_date) == year,
            PurchaseBillItem.wt_id.isnot(None),
        )
        .group_by(PurchaseBillItem.wt_id)
        .all()
    )
    result = []
    for row in rows:
        wt = WithholdingTax.query.get(row.wt_id)
        if wt:
            result.append({'code': wt.code, 'name': wt.name, 'total': row.total or Decimal('0.00')})
    return result
```

- [ ] **Step 2: Run tests — expect PASS**

```powershell
pytest tests/unit/test_vendor_model.py -v
```

Expected: `5 passed`

- [ ] **Step 3: Commit**

```powershell
git add app/vendors/utils.py tests/unit/test_vendor_model.py
git commit -m "feat: add vendor AP aging and WHT YTD helpers with unit tests"
```

---

## Task 4: Fix Delete Modal in list.html

**Files:**
- Modify: `app/vendors/templates/vendors/list.html`

The existing delete button at lines 83-85 uses `confirm()` — this violates the project's no-JS-popups rule. Replace with a custom HTML modal per row.

- [ ] **Step 1: Replace delete button and add modal**

In `list.html`, find and replace the entire `<td>` actions cell for each vendor row. Replace the current content:

```html
<td>
    {% if current_user.role in ['accountant', 'admin'] %}
    <div class="action-buttons">
        <a href="{{ url_for('vendors.edit', id=vendor.id) }}" class="btn-action btn-action-edit" title="Edit">
            Edit
        </a>
        <form method="POST" action="{{ url_for('vendors.delete', id=vendor.id) }}" style="display: inline;" onsubmit="return confirm('Are you sure you want to delete vendor {{ vendor.name }}?');">
            <button type="submit" class="btn-action btn-action-delete" title="Delete">Delete</button>
        </form>
    </div>
    {% else %}
    —
    {% endif %}
</td>
```

With:

```html
<td>
    {% if current_user.role in ['accountant', 'admin'] %}
    <div class="action-buttons">
        <a href="{{ url_for('vendors.edit', id=vendor.id) }}" class="btn-action btn-action-edit" title="Edit">Edit</a>
        <button type="button" class="btn-action btn-action-delete"
                onclick="document.getElementById('delete-modal-{{ vendor.id }}').style.display='flex'">
            Delete
        </button>
    </div>
    <!-- Delete confirmation modal -->
    <div id="delete-modal-{{ vendor.id }}"
         style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:1000; align-items:center; justify-content:center;">
        <div style="background:var(--card); border-radius:8px; padding:32px; max-width:440px; width:90%; box-shadow:0 8px 24px rgba(0,0,0,0.2);">
            <h3 style="margin:0 0 12px 0;">Delete Vendor</h3>
            <p style="color:var(--text-2); margin-bottom:24px;">
                Delete <strong>{{ vendor.code }} — {{ vendor.name }}</strong>? This cannot be undone.
            </p>
            <div style="display:flex; gap:12px; justify-content:flex-end;">
                <button type="button" class="btn btn-secondary btn-sm"
                        onclick="document.getElementById('delete-modal-{{ vendor.id }}').style.display='none'">
                    Cancel
                </button>
                <form method="POST" action="{{ url_for('vendors.delete', id=vendor.id) }}" style="display:inline;">
                    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                    <button type="submit" class="btn btn-danger btn-sm">Delete</button>
                </form>
            </div>
        </div>
    </div>
    {% else %}
    —
    {% endif %}
</td>
```

- [ ] **Step 2: Add btn-danger CSS** (if not already in the stylesheet)

At the end of the `<style>` block in `list.html`, add:

```css
.btn-danger {
    background: #ef4444;
    color: white;
    border: none;
    padding: 6px 18px;
    font-size: 16px;
    border-radius: 5px;
    font-weight: 500;
    cursor: pointer;
}
.btn-danger:hover {
    background: #dc2626;
}
```

- [ ] **Step 3: Verify in browser**

Navigate to `http://localhost:5000/vendors`. Click Delete on a vendor. Confirm the modal appears (not a browser popup). Click Cancel — modal closes. Click Delete — vendor is deleted.

- [ ] **Step 4: Commit**

```powershell
git add app/vendors/templates/vendors/list.html
git commit -m "fix: replace confirm() delete with custom HTML modal in vendor list"
```

---

## Task 5: Fix Readonly Code Field Visual Indicator

**Files:**
- Modify: `app/vendors/templates/vendors/form.html`

- [ ] **Step 1: Update the code field label and input**

Find the code field section in `form.html` (around lines 21-27):

```html
<div class="form-group">
    <label for="{{ form.code.id }}">{{ form.code.label.text }}</label>
    {{ form.code(class="form-control form-control-sm", autocomplete="new-password", readonly=(not vendor), **{'data-lpignore': 'true'}) }}
    {% if form.code.errors %}
        <div class="error-message">{{ form.code.errors[0] }}</div>
    {% endif %}
</div>
```

Replace with:

```html
<div class="form-group">
    <label for="{{ form.code.id }}">
        {{ form.code.label.text }}
        {% if vendor %}<span class="field-locked-label">(locked)</span>{% endif %}
    </label>
    {{ form.code(
        class="form-control form-control-sm" + (" field-locked" if vendor else ""),
        autocomplete="new-password",
        readonly=(vendor is not none),
        **{'data-lpignore': 'true'}
    ) }}
    {% if form.code.errors %}
        <div class="error-message">{{ form.code.errors[0] }}</div>
    {% endif %}
</div>
```

- [ ] **Step 2: Add CSS to the form's `<style>` block**

At the end of the `<style>` block in `form.html`, add:

```css
.field-locked {
    background: #f3f4f6;
    cursor: not-allowed;
    color: #6b7280;
}
.field-locked-label {
    font-size: 12px;
    font-weight: 400;
    color: #9ca3af;
    margin-left: 4px;
}
```

- [ ] **Step 3: Verify in browser**

Navigate to `http://localhost:5000/vendors/1/edit`. Confirm that Vendor Code field has a gray background and shows "(locked)" next to the label.

Navigate to `http://localhost:5000/vendors/create`. Confirm that Vendor Code field on create looks normal (white background, no locked label).

- [ ] **Step 4: Commit**

```powershell
git add app/vendors/templates/vendors/form.html
git commit -m "fix: add visual indicator for readonly vendor code field on edit"
```

---

## Task 6: Update list.html — Vendor Name Links to Detail Page

**Files:**
- Modify: `app/vendors/templates/vendors/list.html`

- [ ] **Step 1: Wrap vendor code and name in detail links**

Find the two cells in the `{% for vendor in vendors %}` loop:

```html
<td><strong>{{ vendor.code }}</strong></td>
<td>{{ vendor.name }}</td>
```

Replace with:

```html
<td><a href="{{ url_for('vendors.detail', id=vendor.id) }}" class="vendor-link"><strong>{{ vendor.code }}</strong></a></td>
<td><a href="{{ url_for('vendors.detail', id=vendor.id) }}" class="vendor-link">{{ vendor.name }}</a></td>
```

- [ ] **Step 2: Add link CSS to the `<style>` block**

```css
.vendor-link {
    color: inherit;
    text-decoration: none;
}
.vendor-link:hover {
    color: #3b82f6;
    text-decoration: underline;
}
```

- [ ] **Step 3: Commit**

```powershell
git add app/vendors/templates/vendors/list.html
git commit -m "feat: vendor code and name in list link to detail page"
```

---

## Task 7: Integration Tests — Vendor Views (Write Failing Tests First)

**Files:**
- Create: `tests/integration/test_vendor_views.py`

- [ ] **Step 1: Create the test file**

Create `tests/integration/test_vendor_views.py`:

```python
"""Integration tests for vendor views — CRUD, detail page, role checks."""
import pytest
from datetime import date, timedelta
from decimal import Decimal

from app.vendors.models import Vendor
from app.purchase_bills.models import PurchaseBill
from app.audit.models import AuditLog
from app.utils import ph_now


def login(client, username='admin', password='ac1123581321'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def make_vendor(db_session, code='IV001', name='Integration Vendor'):
    v = Vendor(code=code, name=name, check_payee_name=name, is_active=True,
               payment_terms='Net 30')
    db_session.add(v)
    db_session.commit()
    return v


def make_bill(db_session, vendor, branch, bill_number='PB-IT-001',
              status='posted', days_overdue=0):
    today = ph_now().date()
    due = today - timedelta(days=days_overdue)
    b = PurchaseBill(
        bill_number=bill_number, vendor_id=vendor.id,
        vendor_name=vendor.name, vendor_tin='', vendor_address='',
        branch_id=branch.id, bill_date=today, due_date=due,
        status=status, subtotal=Decimal('1000.00'),
        vat_amount=Decimal('0.00'), total_before_wt=Decimal('1000.00'),
        withholding_tax_rate=Decimal('0.00'), withholding_tax_amount=Decimal('0.00'),
        total_amount=Decimal('1000.00'), payment_terms='Net 30',
    )
    db_session.add(b)
    db_session.commit()
    return b


class TestVendorList:
    def test_list_renders(self, client, db_session, admin_user, main_branch):
        login(client)
        vendor = make_vendor(db_session)
        resp = client.get('/vendors')
        assert resp.status_code == 200
        assert b'Integration Vendor' in resp.data

    def test_list_vendor_name_is_link_to_detail(self, client, db_session, admin_user, main_branch):
        login(client)
        vendor = make_vendor(db_session, code='IV002', name='Link Test Vendor')
        resp = client.get('/vendors')
        assert resp.status_code == 200
        assert f'/vendors/{vendor.id}'.encode() in resp.data

    def test_list_shows_vat_and_wt_badges(self, client, db_session, admin_user, main_branch):
        from app.withholding_tax.models import WithholdingTax
        login(client)
        v = Vendor(code='IV003', name='Badge Vendor', check_payee_name='Badge Vendor',
                   is_active=True, payment_terms='Net 30',
                   default_vat_category='Vatable (12%)')
        wt = WithholdingTax.query.filter_by(code='WC010').first()
        if wt:
            v.withholding_taxes.append(wt)
        db_session.add(v)
        db_session.commit()
        resp = client.get('/vendors')
        assert b'Vatable (12%)' in resp.data
        if wt:
            assert b'WC010' in resp.data


class TestVendorDetail:
    def test_detail_overview_loads(self, client, db_session, admin_user, main_branch):
        login(client)
        vendor = make_vendor(db_session, code='DV001', name='Detail Test Vendor')
        resp = client.get(f'/vendors/{vendor.id}')
        assert resp.status_code == 200
        assert b'Detail Test Vendor' in resp.data
        assert b'AP Aging' in resp.data
        assert b'WHT Withheld' in resp.data

    def test_detail_shows_aging(self, client, db_session, admin_user, main_branch):
        login(client)
        vendor = make_vendor(db_session, code='DV002', name='Aging Vendor')
        make_bill(db_session, vendor, main_branch, 'PB-AG-001',
                  status='posted', days_overdue=45)
        resp = client.get(f'/vendors/{vendor.id}')
        assert resp.status_code == 200
        assert b'1,000.00' in resp.data

    def test_detail_bills_tab_renders(self, client, db_session, admin_user, main_branch):
        login(client)
        vendor = make_vendor(db_session, code='DV003', name='Bills Tab Vendor')
        make_bill(db_session, vendor, main_branch, 'PB-BT-001')
        resp = client.get(f'/vendors/{vendor.id}?tab=bills')
        assert resp.status_code == 200
        assert b'PB-BT-001' in resp.data

    def test_detail_bills_date_filter(self, client, db_session, admin_user, main_branch):
        login(client)
        vendor = make_vendor(db_session, code='DV004', name='Date Filter Vendor')
        today = ph_now().date()
        # Bill from today
        b1 = make_bill(db_session, vendor, main_branch, 'PB-DF-001')
        b1.bill_date = today
        # Bill from last year
        b2 = make_bill(db_session, vendor, main_branch, 'PB-DF-002')
        b2.bill_date = date(today.year - 1, 1, 1)
        db_session.commit()

        from_date = today.isoformat()
        resp = client.get(f'/vendors/{vendor.id}?tab=bills&date_from={from_date}')
        assert resp.status_code == 200
        assert b'PB-DF-001' in resp.data
        assert b'PB-DF-002' not in resp.data

    def test_detail_bills_status_filter(self, client, db_session, admin_user, main_branch):
        login(client)
        vendor = make_vendor(db_session, code='DV005', name='Status Filter Vendor')
        make_bill(db_session, vendor, main_branch, 'PB-SF-001', status='posted')
        make_bill(db_session, vendor, main_branch, 'PB-SF-002', status='draft')
        resp = client.get(f'/vendors/{vendor.id}?tab=bills&status=draft')
        assert resp.status_code == 200
        assert b'PB-SF-002' in resp.data
        assert b'PB-SF-001' not in resp.data

    def test_staff_can_view_detail(self, client, db_session, staff_user, main_branch):
        login(client, username='staff', password='ac1123581321')
        vendor = make_vendor(db_session, code='DV006', name='Staff View Vendor')
        resp = client.get(f'/vendors/{vendor.id}')
        assert resp.status_code == 200
        assert b'Staff View Vendor' in resp.data


class TestVendorCrud:
    def test_create_vendor_and_audit(self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.post('/vendors/create', data={
            'code': 'NEW001',
            'name': 'New Test Vendor',
            'check_payee_name': 'New Test Vendor',
            'payment_terms': 'Net 30',
            'is_active': '1',
        }, follow_redirects=True)
        assert resp.status_code == 200
        vendor = Vendor.query.filter_by(code='NEW001').first()
        assert vendor is not None
        audit = AuditLog.query.filter_by(module='vendor', action='create',
                                         record_id=vendor.id).first()
        assert audit is not None
        assert audit.performed_by == 'admin'

    def test_edit_vendor_and_audit(self, client, db_session, admin_user, main_branch):
        login(client)
        vendor = make_vendor(db_session, code='ED001', name='Edit Me')
        resp = client.post(f'/vendors/{vendor.id}/edit', data={
            'code': 'ED001',
            'name': 'Edited Name',
            'check_payee_name': 'Edited Name',
            'payment_terms': 'Net 15',
            'is_active': '1',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db_session.refresh(vendor)
        assert vendor.name == 'Edited Name'
        audit = AuditLog.query.filter_by(module='vendor', action='update',
                                         record_id=vendor.id).first()
        assert audit is not None

    def test_delete_vendor_and_audit(self, client, db_session, admin_user, main_branch):
        login(client)
        vendor = make_vendor(db_session, code='DEL001', name='Delete Me')
        vid = vendor.id
        resp = client.post(f'/vendors/{vid}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert Vendor.query.get(vid) is None
        audit = AuditLog.query.filter_by(module='vendor', action='delete',
                                         record_id=vid).first()
        assert audit is not None

    def test_staff_cannot_edit(self, client, db_session, staff_user, main_branch):
        login(client, username='staff', password='ac1123581321')
        vendor = make_vendor(db_session, code='STF001', name='Staff Test')
        resp = client.post(f'/vendors/{vendor.id}/edit', data={
            'code': 'STF001', 'name': 'Changed', 'check_payee_name': 'Changed',
            'payment_terms': 'Net 30', 'is_active': '1',
        }, follow_redirects=True)
        # Staff gets redirected away (403 or redirect to dashboard)
        db_session.refresh(vendor)
        assert vendor.name == 'Staff Test'  # unchanged

    def test_staff_cannot_delete(self, client, db_session, staff_user, main_branch):
        login(client, username='staff', password='ac1123581321')
        vendor = make_vendor(db_session, code='STF002', name='Staff Delete Test')
        vid = vendor.id
        client.post(f'/vendors/{vid}/delete', follow_redirects=True)
        assert Vendor.query.get(vid) is not None  # not deleted
```

- [ ] **Step 2: Run tests — expect FAIL (detail route doesn't exist)**

```powershell
pytest tests/integration/test_vendor_views.py -v
```

Expected: Several tests fail because `GET /vendors/<id>` returns 404 (detail route not yet added) and some pass (list, CRUD).

---

## Task 8: Add detail() Route to views.py

**Files:**
- Modify: `app/vendors/views.py`

- [ ] **Step 1: Add import for PurchaseBill at top of views.py**

Find the imports section at the top of `app/vendors/views.py` and add:

```python
from app.purchase_bills.models import PurchaseBill
```

- [ ] **Step 2: Add the detail() view function**

Add the following function **before** the `create` route (or after `list_vendors`, either is fine — just before the `create` function):

```python
@vendors_bp.route('/vendors/<int:id>')
@login_required
def detail(id):
    """Vendor detail page — tabbed: overview (aging + WHT YTD) and bills history."""
    vendor = Vendor.query.get_or_404(id)
    tab = request.args.get('tab', 'overview')

    total_bills = PurchaseBill.query.filter_by(vendor_id=id).count()

    if tab == 'bills':
        page = request.args.get('page', 1, type=int)
        date_from_str = request.args.get('date_from', '')
        date_to_str = request.args.get('date_to', '')
        status_filter = request.args.get('status', 'all')

        query = PurchaseBill.query.filter_by(vendor_id=id)
        if date_from_str:
            from datetime import date as date_type
            try:
                query = query.filter(PurchaseBill.bill_date >= date_type.fromisoformat(date_from_str))
            except ValueError:
                pass
        if date_to_str:
            from datetime import date as date_type
            try:
                query = query.filter(PurchaseBill.bill_date <= date_type.fromisoformat(date_to_str))
            except ValueError:
                pass
        if status_filter and status_filter != 'all':
            query = query.filter(PurchaseBill.status == status_filter)

        pagination = query.order_by(PurchaseBill.bill_date.desc()).paginate(
            page=page, per_page=20, error_out=False
        )
        return render_template(
            'vendors/detail.html',
            vendor=vendor,
            tab='bills',
            total_bills=total_bills,
            pagination=pagination,
            date_from=date_from_str,
            date_to=date_to_str,
            status_filter=status_filter,
        )
    else:
        from app.vendors.utils import compute_ap_aging, compute_wht_ytd
        aging = compute_ap_aging(vendor.id)
        wht_ytd = compute_wht_ytd(vendor.id)
        return render_template(
            'vendors/detail.html',
            vendor=vendor,
            tab='overview',
            total_bills=total_bills,
            aging=aging,
            wht_ytd=wht_ytd,
        )
```

- [ ] **Step 2: Verify the route is registered by checking the URL map**

```powershell
flask shell
```

```python
from flask import current_app
print([str(r) for r in current_app.url_map.iter_rules() if 'vendor' in str(r)])
exit()
```

Expected: `/vendors/<id>` appears in the list alongside `/vendors/<id>/edit`.

- [ ] **Step 3: Commit**

```powershell
git add app/vendors/views.py
git commit -m "feat: add vendor detail route with AP aging and bills history tabs"
```

---

## Task 9: Create templates/vendors/detail.html

**Files:**
- Create: `app/vendors/templates/vendors/detail.html`

- [ ] **Step 1: Create the template**

Create `app/vendors/templates/vendors/detail.html`:

```html
{% extends "base.html" %}

{% block title %}{{ vendor.name }} — Vendor{% endblock %}
{% block page_title %}{{ vendor.name }}{% endblock %}

{% block content %}
{% from "macros.html" import render_flash_messages %}
{{ render_flash_messages() }}

<!-- Header row: code/status + Edit button -->
<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
    <div style="display:flex; align-items:center; gap:12px;">
        <span style="color:var(--text-2); font-size:14px; font-weight:500;">{{ vendor.code }}</span>
        <span class="badge {% if vendor.is_active %}badge-success{% else %}badge-inactive{% endif %}">
            {{ 'Active' if vendor.is_active else 'Inactive' }}
        </span>
    </div>
    {% if current_user.role in ['accountant', 'admin'] %}
    <a href="{{ url_for('vendors.edit', id=vendor.id) }}" class="btn btn-primary btn-sm">Edit Vendor</a>
    {% endif %}
</div>

<!-- Tab bar -->
<div class="vendor-tab-bar">
    <a href="{{ url_for('vendors.detail', id=vendor.id, tab='overview') }}"
       class="vendor-tab {% if tab == 'overview' %}active{% endif %}">Overview</a>
    <a href="{{ url_for('vendors.detail', id=vendor.id, tab='bills') }}"
       class="vendor-tab {% if tab == 'bills' %}active{% endif %}">Bills ({{ total_bills }})</a>
</div>

{% if tab == 'overview' %}
<!-- ── OVERVIEW TAB ── -->
<div class="vendor-overview-grid">

    <!-- Left: Vendor Info -->
    <div class="card">
        <div class="card-body">
            <h4 style="margin:0 0 16px 0; font-size:15px; font-weight:600;">Vendor Information</h4>
            <table class="vendor-info-table">
                <tr><td>Code</td><td><strong>{{ vendor.code }}</strong></td></tr>
                <tr><td>Name</td><td>{{ vendor.name }}</td></tr>
                <tr><td>Check Payee</td><td>{{ vendor.check_payee_name or '—' }}</td></tr>
                <tr><td>TIN</td><td>{{ vendor.tin or '—' }}</td></tr>
                <tr><td>Contact</td><td>{{ vendor.contact_person or '—' }}</td></tr>
                <tr><td>Phone</td><td>{{ vendor.phone or '—' }}</td></tr>
                <tr><td>Email</td><td>{{ vendor.email or '—' }}</td></tr>
                <tr><td>Address</td><td>{{ vendor.address or '—' }}</td></tr>
                <tr><td>Postal Code</td><td>{{ vendor.postal_code or '—' }}</td></tr>
                <tr><td>Payment Terms</td><td>{{ vendor.payment_terms }}</td></tr>
                <tr>
                    <td>Default VAT</td>
                    <td>
                        {% if vendor.default_vat_category %}
                        <span class="badge badge-vat">{{ vendor.default_vat_category }}</span>
                        {% else %}—{% endif %}
                    </td>
                </tr>
                <tr>
                    <td>Default WHT</td>
                    <td>
                        {% for wt in vendor.withholding_taxes %}
                        <span class="badge badge-wt">{{ wt.code }}</span>
                        {% else %}—{% endfor %}
                    </td>
                </tr>
            </table>
        </div>
    </div>

    <!-- Right column -->
    <div style="display:flex; flex-direction:column; gap:20px;">

        <!-- AP Aging -->
        <div class="card">
            <div class="card-body">
                <h4 style="margin:0 0 16px 0; font-size:15px; font-weight:600;">AP Aging (Posted Bills)</h4>
                <table class="vendor-info-table">
                    <tr><td>Current (not yet due)</td><td class="amount-cell">₱{{ '{:,.2f}'.format(aging['current']) }}</td></tr>
                    <tr><td>1–30 days overdue</td><td class="amount-cell">₱{{ '{:,.2f}'.format(aging['1_30']) }}</td></tr>
                    <tr><td>31–60 days overdue</td><td class="amount-cell">₱{{ '{:,.2f}'.format(aging['31_60']) }}</td></tr>
                    <tr><td>61–90 days overdue</td><td class="amount-cell">₱{{ '{:,.2f}'.format(aging['61_90']) }}</td></tr>
                    <tr><td>90+ days overdue</td><td class="amount-cell" style="color:#ef4444;">₱{{ '{:,.2f}'.format(aging['90_plus']) }}</td></tr>
                    <tr class="aging-total-row">
                        <td><strong>Total Outstanding</strong></td>
                        <td class="amount-cell"><strong>₱{{ '{:,.2f}'.format(aging['total']) }}</strong></td>
                    </tr>
                </table>
            </div>
        </div>

        <!-- WHT YTD -->
        <div class="card">
            <div class="card-body">
                <h4 style="margin:0 0 16px 0; font-size:15px; font-weight:600;">WHT Withheld YTD</h4>
                {% if wht_ytd %}
                <table class="vendor-info-table">
                    {% for row in wht_ytd %}
                    <tr>
                        <td>{{ row.code }} — {{ row.name }}</td>
                        <td class="amount-cell">₱{{ '{:,.2f}'.format(row.total) }}</td>
                    </tr>
                    {% endfor %}
                </table>
                {% else %}
                <p style="color:var(--text-2); font-style:italic; margin:0;">No WHT recorded this calendar year.</p>
                {% endif %}
            </div>
        </div>
    </div>
</div>

{% else %}
<!-- ── BILLS TAB ── -->
<div style="margin-top:16px;">

    <!-- Filter bar -->
    <form method="GET" action="{{ url_for('vendors.detail', id=vendor.id) }}"
          style="display:flex; gap:12px; align-items:flex-end; margin-bottom:16px; flex-wrap:wrap;">
        <input type="hidden" name="tab" value="bills">
        <div>
            <label style="font-size:13px; font-weight:500; display:block; margin-bottom:4px;">Date From</label>
            <input type="date" name="date_from" value="{{ date_from }}"
                   class="form-control form-control-sm" style="width:160px;">
        </div>
        <div>
            <label style="font-size:13px; font-weight:500; display:block; margin-bottom:4px;">Date To</label>
            <input type="date" name="date_to" value="{{ date_to }}"
                   class="form-control form-control-sm" style="width:160px;">
        </div>
        <div>
            <label style="font-size:13px; font-weight:500; display:block; margin-bottom:4px;">Status</label>
            <select name="status" class="form-control form-control-sm" style="width:150px;">
                <option value="all" {% if status_filter == 'all' %}selected{% endif %}>All Statuses</option>
                <option value="draft" {% if status_filter == 'draft' %}selected{% endif %}>Draft</option>
                <option value="posted" {% if status_filter == 'posted' %}selected{% endif %}>Posted</option>
                <option value="partially_paid" {% if status_filter == 'partially_paid' %}selected{% endif %}>Partially Paid</option>
                <option value="paid" {% if status_filter == 'paid' %}selected{% endif %}>Paid</option>
                <option value="voided" {% if status_filter == 'voided' %}selected{% endif %}>Voided</option>
                <option value="cancelled" {% if status_filter == 'cancelled' %}selected{% endif %}>Cancelled</option>
            </select>
        </div>
        <button type="submit" class="btn btn-primary btn-sm" style="align-self:flex-end;">Filter</button>
        <a href="{{ url_for('vendors.detail', id=vendor.id, tab='bills') }}"
           class="btn btn-secondary btn-sm" style="align-self:flex-end;">Clear</a>
    </form>

    <!-- Bills table -->
    <div class="card">
        <div class="card-body" style="padding:0;">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>BILL #</th>
                        <th>BILL DATE</th>
                        <th>DUE DATE</th>
                        <th style="text-align:right;">SUBTOTAL</th>
                        <th style="text-align:right;">INPUT VAT</th>
                        <th style="text-align:right;">WHT</th>
                        <th style="text-align:right;">NET AMOUNT</th>
                        <th>STATUS</th>
                    </tr>
                </thead>
                <tbody>
                    {% for bill in pagination.items %}
                    <tr>
                        <td>
                            <a href="{{ url_for('purchase_bills.detail', id=bill.id) }}"
                               style="color:#3b82f6; text-decoration:none;">
                                {{ bill.bill_number }}
                            </a>
                        </td>
                        <td>{{ bill.bill_date.strftime('%b %d, %Y') }}</td>
                        <td>{{ bill.due_date.strftime('%b %d, %Y') }}</td>
                        <td style="text-align:right;">₱{{ '{:,.2f}'.format(bill.subtotal) }}</td>
                        <td style="text-align:right;">₱{{ '{:,.2f}'.format(bill.vat_amount) }}</td>
                        <td style="text-align:right; color:#ef4444;">
                            {% if bill.withholding_tax_amount > 0 %}
                            -₱{{ '{:,.2f}'.format(bill.withholding_tax_amount) }}
                            {% else %}—{% endif %}
                        </td>
                        <td style="text-align:right; font-weight:600;">₱{{ '{:,.2f}'.format(bill.total_amount) }}</td>
                        <td>
                            <span class="badge status-{{ bill.status }}">{{ bill.status | replace('_', ' ') | title }}</span>
                        </td>
                    </tr>
                    {% else %}
                    <tr>
                        <td colspan="8" style="text-align:center; color:var(--text-2); padding:32px; font-style:italic;">
                            No bills found.
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    <!-- Pagination -->
    {% if pagination.pages > 1 %}
    <div style="display:flex; justify-content:center; align-items:center; gap:12px; margin-top:16px;">
        {% if pagination.has_prev %}
        <a href="{{ url_for('vendors.detail', id=vendor.id, tab='bills', page=pagination.prev_num,
                            date_from=date_from, date_to=date_to, status=status_filter) }}"
           class="btn btn-secondary btn-sm">← Previous</a>
        {% endif %}
        <span style="font-size:14px; color:var(--text-2);">
            Page {{ pagination.page }} of {{ pagination.pages }}
            ({{ pagination.total }} bills)
        </span>
        {% if pagination.has_next %}
        <a href="{{ url_for('vendors.detail', id=vendor.id, tab='bills', page=pagination.next_num,
                            date_from=date_from, date_to=date_to, status=status_filter) }}"
           class="btn btn-primary btn-sm">Next →</a>
        {% endif %}
    </div>
    {% endif %}
</div>
{% endif %}

<style>
.vendor-tab-bar {
    display: flex;
    gap: 0;
    border-bottom: 2px solid var(--border);
    margin-bottom: 20px;
}
.vendor-tab {
    padding: 10px 20px;
    font-size: 14px;
    font-weight: 500;
    color: var(--text-2);
    text-decoration: none;
    border-bottom: 2px solid transparent;
    margin-bottom: -2px;
    transition: color 0.15s, border-color 0.15s;
}
.vendor-tab:hover {
    color: var(--text);
}
.vendor-tab.active {
    color: #3b82f6;
    border-bottom-color: #3b82f6;
    font-weight: 600;
}
.vendor-overview-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
}
.vendor-info-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
}
.vendor-info-table td {
    padding: 6px 8px;
    vertical-align: top;
}
.vendor-info-table td:first-child {
    color: var(--text-2);
    width: 40%;
    white-space: nowrap;
}
.vendor-info-table tr + tr td {
    border-top: 1px solid var(--border);
}
.amount-cell {
    text-align: right;
    font-variant-numeric: tabular-nums;
}
.aging-total-row td {
    border-top: 2px solid var(--border) !important;
    padding-top: 10px !important;
}
.status-draft { background:#f3f4f6; color:#6b7280; border:1px solid #e5e7eb; }
.status-posted { background:#dbeafe; color:#1e40af; border:1px solid #bfdbfe; }
.status-partially_paid { background:#fef3c7; color:#92400e; border:1px solid #fde68a; }
.status-paid { background:#dcfce7; color:#166534; border:1px solid #bbf7d0; }
.status-voided { background:#fee2e2; color:#991b1b; border:1px solid #fecaca; }
.status-cancelled { background:#f3f4f6; color:#6b7280; border:1px solid #e5e7eb; }
.badge {
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
    display: inline-block;
}
.badge-vat { background:#dcfce7; color:#166534; border:1px solid #bbf7d0; }
.badge-wt  { background:#dbeafe; color:#1e40af; border:1px solid #bfdbfe; }
.badge-success  { background:#dcfce7; color:#166534; border:1px solid #bbf7d0; }
.badge-inactive { background:#f3f4f6; color:#6b7280; border:1px solid #e5e7eb; }
.btn-sm {
    padding: 6px 16px;
    font-size: 14px;
    border-radius: 5px;
    font-weight: 500;
    cursor: pointer;
    border: none;
    text-decoration: none;
    display: inline-block;
    line-height: 1.4;
}
.btn-primary { background:#3b82f6; color:white; }
.btn-primary:hover { background:#2563eb; }
.btn-secondary { background:#6b7280; color:white; }
.btn-secondary:hover { background:#4b5563; }
@media (max-width: 768px) {
    .vendor-overview-grid { grid-template-columns: 1fr; }
}
</style>
{% endblock %}
```

- [ ] **Step 2: Run integration tests — expect PASS**

```powershell
pytest tests/integration/test_vendor_views.py -v
```

Expected: All tests pass. If `purchase_bills.detail` endpoint name is wrong, check `app/purchase_bills/views.py` for the correct endpoint name and update `url_for(...)` in the template.

- [ ] **Step 3: Run the full test suite**

```powershell
pytest -v
```

Expected: All existing tests still pass plus new tests.

- [ ] **Step 4: Smoke test in browser**

1. Navigate to `http://localhost:5000/vendors` — confirm vendor code and name are clickable links, delete shows a modal (no browser popup)
2. Click a vendor name — confirm detail page loads at `/vendors/1` with Overview tab active
3. Confirm vendor info, AP aging table, WHT YTD section are all visible
4. Click "Bills" tab — confirm bills table loads with filter bar
5. Apply a date filter — confirm it narrows results
6. Navigate to `/vendors/1/edit` — confirm Vendor Code field shows gray background and "(locked)" label

- [ ] **Step 5: Commit**

```powershell
git add app/vendors/templates/vendors/detail.html tests/integration/test_vendor_views.py
git commit -m "feat: vendor detail page with AP aging, WHT YTD, and paginated bill history"
```

---

## Self-Review

**Spec coverage check:**
- ✅ Delete modal (no-JS-popups) — Task 4
- ✅ Payment terms fix — Task 1
- ✅ Readonly code visual — Task 5
- ✅ Vendor detail page — Tasks 7–9
- ✅ Overview tab: vendor info + AP aging + WHT YTD — Task 9
- ✅ Bills tab: paginated, date range filter, status filter — Tasks 8–9
- ✅ List: vendor name links to detail — Task 6
- ✅ Unit tests for aging/WHT — Tasks 2–3
- ✅ Integration tests for all routes + role checks — Tasks 7–9

**Type consistency:** `compute_ap_aging` returns a dict with keys `current`, `1_30`, `31_60`, `61_90`, `90_plus`, `total` — used identically in utils.py (Task 3) and detail.html (Task 9). `compute_wht_ytd` returns `list[dict]` with keys `code`, `name`, `total` — consistent across utils.py and template.

**No placeholders found.**
