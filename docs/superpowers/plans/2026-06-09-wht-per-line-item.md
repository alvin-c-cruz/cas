# WHT Per Line Item — Purchase Bills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move withholding tax from bill-level to per-line-item on Purchase Bills, driven by the selected vendor's configured WHT codes.

**Architecture:** Three-layer change — model (new FK + snapshot fields on `PurchaseBillItem`, `calculate_totals()` sums from lines), form/JS (vendor-change AJAX fetches WHT codes, per-line select, serialises `wt_id`/`wt_rate`), BIR report (groups by `(vendor_id, wt_id)` instead of `vendor_id`). The DB column `withholding_tax_rate` on `PurchaseBill` is retained at `0.00` (non-destructive); `withholding_tax_amount` is now derived from line sums.

**Tech Stack:** Flask 3, SQLAlchemy 2, Flask-Migrate/Alembic, SQLite (batch mode for schema changes), Jinja2, vanilla JS (fetch API).

---

## File Map

| File | Change |
|---|---|
| `app/purchase_bills/models.py` | Add `wt_id`, `wt_rate`, `wt_amount` to `PurchaseBillItem`; update `calculate_amounts()`, `to_dict()`; update `PurchaseBill.calculate_totals()` and `to_dict()` |
| `app/purchase_bills/forms.py` | Remove `withholding_tax_rate` field |
| `app/purchase_bills/views.py` | Import `WithholdingTax`; update `create` + `edit` to resolve wt per line; set `withholding_tax_rate=Decimal('0.00')` |
| `app/purchase_bills/templates/purchase_bills/form.html` | Add WHT column; vendor-change AJAX; rewrite JS |
| `app/purchase_bills/templates/purchase_bills/detail.html` | Add WHT column to line items; remove `(rate%)` from totals header |
| `app/vendors/views.py` | Add `GET /vendors/<id>/defaults` JSON endpoint |
| `app/reports/bir.py` | Import `selectinload`; eager-load `line_items`; group by `(vendor_id, wt_id)` |
| `migrations/versions/<hash>_add_wht_to_purchase_bill_items.py` | Three nullable columns on `purchase_bill_items` |
| `tests/unit/test_wht_per_line_item.py` | New test file |

---

## Task 1: Update `PurchaseBillItem` model

**Files:**
- Modify: `app/purchase_bills/models.py`
- Test: `tests/unit/test_wht_per_line_item.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_wht_per_line_item.py`:

```python
"""Unit tests for WHT per line item on PurchaseBillItem."""
import pytest
from decimal import Decimal
from app.purchase_bills.models import PurchaseBillItem


class TestPurchaseBillItemWht:
    def _make_item(self, **kwargs):
        defaults = dict(
            line_number=1,
            description='Office supplies',
            quantity=Decimal('2.0000'),
            unit_cost=Decimal('500.00'),
            vat_rate=Decimal('12.00'),
            wt_id=None,
            wt_rate=None,
        )
        defaults.update(kwargs)
        return PurchaseBillItem(**defaults)

    def test_wt_amount_zero_when_no_wht(self):
        item = self._make_item()
        item.calculate_amounts()
        assert item.wt_amount == Decimal('0.00')

    def test_wt_amount_computed_from_line_total(self):
        # line_total = 2 * 500 = 1000; wt = 1000 * 10 / 100 = 100
        item = self._make_item(wt_rate=Decimal('10.00'))
        item.calculate_amounts()
        assert item.line_total == Decimal('1000.00')
        assert item.wt_amount == Decimal('100.00')

    def test_calculate_amounts_still_sets_line_total_and_vat(self):
        item = self._make_item(wt_rate=Decimal('2.00'))
        item.calculate_amounts()
        assert item.line_total == Decimal('1000.00')
        assert item.vat_amount == Decimal('120.00')  # 1000 * 12%

    def test_to_dict_includes_wt_fields(self):
        item = self._make_item(wt_id=3, wt_rate=Decimal('10.00'))
        item.calculate_amounts()
        d = item.to_dict()
        assert d['wt_id'] == 3
        assert d['wt_rate'] == 10.0
        assert d['wt_amount'] == 100.0

    def test_to_dict_wt_none_when_no_wht(self):
        item = self._make_item()
        item.calculate_amounts()
        d = item.to_dict()
        assert d['wt_id'] is None
        assert d['wt_rate'] is None
        assert d['wt_amount'] == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
pytest tests/unit/test_wht_per_line_item.py -v
```

Expected: FAIL — `PurchaseBillItem` has no attribute `wt_id`, `wt_rate`, or `wt_amount`.

- [ ] **Step 3: Add fields to `PurchaseBillItem`**

In `app/purchase_bills/models.py`, after line `account = db.relationship('Account')` (around line 186), add:

```python
    # Withholding tax (per line, vendor-driven)
    wt_id = db.Column(db.Integer, db.ForeignKey('withholding_tax.id'), nullable=True)
    withholding_tax = db.relationship('WithholdingTax', foreign_keys=[wt_id])
    wt_rate = db.Column(db.Numeric(5, 2), nullable=True)   # snapshot at bill creation time
    wt_amount = db.Column(db.Numeric(15, 2), default=Decimal('0.00'), nullable=False)
```

- [ ] **Step 4: Update `calculate_amounts()`**

Replace the existing `calculate_amounts` method body (lines 191–194):

```python
    def calculate_amounts(self):
        """Calculate line totals, VAT amount, and WHT amount."""
        self.line_total = Decimal(str(self.quantity)) * Decimal(str(self.unit_cost))
        self.vat_amount = self.line_total * Decimal(str(self.vat_rate)) / Decimal('100')
        wt_rate = self.wt_rate if self.wt_rate is not None else Decimal('0.00')
        self.wt_amount = self.line_total * Decimal(str(wt_rate)) / Decimal('100')
```

- [ ] **Step 5: Update `PurchaseBillItem.to_dict()`**

Replace the existing `to_dict` return dict to include wht fields:

```python
    def to_dict(self):
        """Convert line item to dictionary."""
        return {
            'id': self.id,
            'line_number': self.line_number,
            'description': self.description,
            'quantity': float(self.quantity),
            'unit_cost': float(self.unit_cost),
            'vat_category': self.vat_category,
            'vat_rate': float(self.vat_rate),
            'line_total': float(self.line_total),
            'vat_amount': float(self.vat_amount),
            'account_id': self.account_id,
            'wt_id': self.wt_id,
            'wt_rate': float(self.wt_rate) if self.wt_rate is not None else None,
            'wt_amount': float(self.wt_amount),
        }
```

- [ ] **Step 6: Update `PurchaseBill.calculate_totals()`**

Replace line 118 in `PurchaseBill.calculate_totals()`:

```python
        # Old: self.withholding_tax_amount = self.subtotal * Decimal(str(self.withholding_tax_rate)) / Decimal('100')
        # New: sum WHT from all line items
        self.withholding_tax_amount = sum(
            (item.wt_amount or Decimal('0.00')) for item in self.line_items
        )
```

- [ ] **Step 7: Update `PurchaseBill.to_dict()`**

Remove the `'withholding_tax_rate'` key from the return dict (line 140). The dict should no longer include it.

- [ ] **Step 8: Run tests to verify they pass**

```powershell
pytest tests/unit/test_wht_per_line_item.py -v
```

Expected: all 5 PASS.

- [ ] **Step 9: Commit**

```powershell
git add app/purchase_bills/models.py tests/unit/test_wht_per_line_item.py
git commit -m "feat: add wt_id/wt_rate/wt_amount to PurchaseBillItem; sum from lines in calculate_totals"
```

---

## Task 2: Database migration

**Files:**
- Create: `migrations/versions/<hash>_add_wht_to_purchase_bill_items.py` (auto-generated)

- [ ] **Step 1: Generate migration**

```powershell
flask db migrate -m "add wht fields to purchase bill items"
```

- [ ] **Step 2: Open the generated migration and verify / patch it**

Find the new file in `migrations/versions/`. Open it. The `upgrade()` function must use **batch mode** (required for SQLite FK changes) and **name the FK constraint explicitly** (SQLite batch alter raises `ValueError: Constraint must have a name` otherwise). Replace the auto-generated `upgrade()` and `downgrade()` with:

```python
def upgrade():
    with op.batch_alter_table('purchase_bill_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('wt_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('wt_rate', sa.Numeric(precision=5, scale=2), nullable=True))
        batch_op.add_column(sa.Column('wt_amount', sa.Numeric(precision=15, scale=2),
                                      server_default='0.00', nullable=False))
        batch_op.create_foreign_key(
            'fk_purchase_bill_items_wt_id',
            'withholding_tax', ['wt_id'], ['id']
        )


def downgrade():
    with op.batch_alter_table('purchase_bill_items', schema=None) as batch_op:
        batch_op.drop_constraint('fk_purchase_bill_items_wt_id', type_='foreignkey')
        batch_op.drop_column('wt_amount')
        batch_op.drop_column('wt_rate')
        batch_op.drop_column('wt_id')
```

Check the imports at the top of the migration file — `sa` and `op` must be imported. They will be there by default; do not remove them.

- [ ] **Step 3: Run migration**

```powershell
flask db upgrade
```

Expected: `Running upgrade <prev> -> <new>, add wht fields to purchase bill items` with no errors.

- [ ] **Step 4: Commit**

```powershell
git add migrations/
git commit -m "migration: add wt_id, wt_rate, wt_amount to purchase_bill_items"
```

---

## Task 3: Remove `withholding_tax_rate` from form

**Files:**
- Modify: `app/purchase_bills/forms.py`

- [ ] **Step 1: Remove the field**

In `app/purchase_bills/forms.py`, delete the entire `withholding_tax_rate` field block (lines 48–51):

```python
    withholding_tax_rate = DecimalField('Withholding Tax Rate (%)', validators=[
        Optional(),
        NumberRange(min=0, max=100, message='Withholding tax rate must be between 0 and 100.')
    ], places=2, default=0.00)
```

Also remove unused imports if they become unused: `DecimalField` and `NumberRange` are only used by this field — remove them from the import line too.

Updated imports line:

```python
from wtforms import StringField, DateField, TextAreaField, SelectField
from wtforms.validators import DataRequired, Length, Optional
```

- [ ] **Step 2: Verify the form still imports cleanly**

```powershell
python -c "from app.purchase_bills.forms import PurchaseBillForm; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```powershell
git add app/purchase_bills/forms.py
git commit -m "feat: remove withholding_tax_rate from PurchaseBillForm (now per line)"
```

---

## Task 4: Add `GET /vendors/<id>/defaults` API endpoint

**Files:**
- Modify: `app/vendors/views.py`

- [ ] **Step 1: Add `jsonify` to the Flask import**

In `app/vendors/views.py` line 1, update the flask import:

```python
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
```

- [ ] **Step 2: Add the endpoint**

Append the following route at the end of `app/vendors/views.py` (before the last newline):

```python
@vendors_bp.route('/vendors/<int:id>/defaults')
@login_required
def vendor_defaults(id):
    """Return vendor's WHT codes and default VAT category for AJAX."""
    vendor = Vendor.query.get_or_404(id)
    return jsonify({
        'withholding_taxes': [
            {
                'id': wt.id,
                'code': wt.code,
                'name': wt.name,
                'rate': float(wt.rate),
            }
            for wt in vendor.withholding_taxes
            if wt.is_active
        ],
        'default_vat_category': vendor.default_vat_category,
    })
```

- [ ] **Step 3: Verify the route is accessible (run dev server and curl)**

```powershell
# Start server in background first, then:
python -c "
from flask_app import app
with app.test_client() as c:
    from flask_login import login_user
    from app.users.models import User
    with app.app_context():
        admin = User.query.filter_by(username='admin').first()
        print('Vendor defaults route registered:', any('/vendors/' in str(r) and 'defaults' in str(r) for r in app.url_map.iter_rules()))
"
```

Expected output includes `True`.

- [ ] **Step 4: Commit**

```powershell
git add app/vendors/views.py
git commit -m "feat: add GET /vendors/<id>/defaults API endpoint"
```

---

## Task 5: Update `create` and `edit` views to handle per-line WHT

**Files:**
- Modify: `app/purchase_bills/views.py`

- [ ] **Step 1: Add `WithholdingTax` import**

In `app/purchase_bills/views.py`, update the imports section. After the line:

```python
from app.accounts.models import Account
```

Add:

```python
from app.withholding_tax.models import WithholdingTax
```

- [ ] **Step 2: Update the `create` view — fix bill instantiation**

In the `create` view (around line 270), replace:

```python
                withholding_tax_rate=form.withholding_tax_rate.data or Decimal('0.00'),
```

With:

```python
                withholding_tax_rate=Decimal('0.00'),
```

- [ ] **Step 3: Update the `create` view — add WHT resolution per line item**

In the `create` view, inside the `for idx, item_data in enumerate(line_items, start=1):` loop, add WHT resolution after the VAT resolution block:

Replace the entire loop body (from `vat_rate = Decimal('0.00')` through `line_item.calculate_amounts()`):

```python
                for idx, item_data in enumerate(line_items, start=1):
                    vat_rate = Decimal('0.00')
                    vat_category = item_data.get('vat_category')
                    if vat_category:
                        vat_cat = VATCategory.query.filter_by(code=vat_category, is_active=True).first()
                        if vat_cat:
                            vat_rate = Decimal(str(vat_cat.rate))

                    wt_id = int(item_data['wt_id']) if item_data.get('wt_id') else None
                    wt_rate = None
                    if wt_id:
                        wt_obj = WithholdingTax.query.get(wt_id)
                        if wt_obj:
                            wt_rate = wt_obj.rate

                    line_item = PurchaseBillItem(
                        line_number=idx,
                        description=item_data.get('description', ''),
                        quantity=Decimal(str(item_data.get('quantity', 1))),
                        unit_cost=Decimal(str(item_data.get('unit_cost', 0))),
                        vat_category=vat_category,
                        vat_rate=vat_rate,
                        account_id=int(item_data.get('account_id')) if item_data.get('account_id') else None,
                        wt_id=wt_id,
                        wt_rate=wt_rate,
                    )
                    line_item.calculate_amounts()
                    bill.line_items.append(line_item)
```

- [ ] **Step 4: Update the `edit` view — fix bill attribute assignment**

In the `edit` view (around line 389), replace:

```python
            bill.withholding_tax_rate = form.withholding_tax_rate.data or Decimal('0.00')
```

With:

```python
            bill.withholding_tax_rate = Decimal('0.00')
```

- [ ] **Step 5: Update the `edit` view — add WHT resolution per line item**

In the `edit` view, inside the `for idx, item_data in enumerate(line_items, start=1):` loop, apply the same change as Step 3 — add `wt_id`/`wt_rate` resolution and pass them to `PurchaseBillItem`:

```python
                for idx, item_data in enumerate(line_items, start=1):
                    vat_rate = Decimal('0.00')
                    vat_category = item_data.get('vat_category')
                    if vat_category:
                        vat_cat = VATCategory.query.filter_by(code=vat_category, is_active=True).first()
                        if vat_cat:
                            vat_rate = Decimal(str(vat_cat.rate))

                    wt_id = int(item_data['wt_id']) if item_data.get('wt_id') else None
                    wt_rate = None
                    if wt_id:
                        wt_obj = WithholdingTax.query.get(wt_id)
                        if wt_obj:
                            wt_rate = wt_obj.rate

                    line_item = PurchaseBillItem(
                        bill_id=bill.id,
                        line_number=idx,
                        description=item_data.get('description', ''),
                        quantity=Decimal(str(item_data.get('quantity', 1))),
                        unit_cost=Decimal(str(item_data.get('unit_cost', 0))),
                        vat_category=vat_category,
                        vat_rate=vat_rate,
                        account_id=int(item_data.get('account_id')) if item_data.get('account_id') else None,
                        wt_id=wt_id,
                        wt_rate=wt_rate,
                    )
                    line_item.calculate_amounts()
                    db.session.add(line_item)
```

- [ ] **Step 6: Run the existing test suite to confirm nothing broke**

```powershell
pytest tests/unit/test_wht_per_line_item.py tests/unit/test_record_status.py -v
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```powershell
git add app/purchase_bills/views.py
git commit -m "feat: resolve wt_id/wt_rate per line in create+edit views"
```

---

## Task 6: Update `form.html` — WHT column + vendor AJAX

**Files:**
- Modify: `app/purchase_bills/templates/purchase_bills/form.html`

This task rewrites the form template's JS section substantially. Make changes carefully in order.

- [ ] **Step 1: Remove `withholding_tax_rate` form field row from header**

In `form.html`, find the block (lines 32–35):

```html
            <div class="form-row-2">
                {{ render_field(form.withholding_tax_rate) }}
                {{ render_field(form.reference) }}
            </div>
```

Replace with (only the reference field; collapse to a single-field row):

```html
            <div class="form-row-2">
                {{ render_field(form.reference) }}
                {{ render_field(form.vendor_invoice_number) }}
            </div>
```

Also remove the now-duplicated `vendor_invoice_number` row (lines 27–30 original). The final header layout should be:

```html
            <div class="form-row-3">
                {{ render_field(form.bill_number) }}
                {{ render_field(form.bill_date) }}
                {{ render_field(form.due_date) }}
            </div>

            <div class="form-row-2">
                {{ render_field(form.vendor_id) }}
                {{ render_field(form.payment_terms) }}
            </div>

            <div class="form-row-2">
                {{ render_field(form.vendor_invoice_number) }}
                {{ render_field(form.vendor_invoice_date) }}
            </div>

            <div class="form-row-2">
                {{ render_field(form.reference) }}
                {{ render_field(form.notes) }}
            </div>
```

- [ ] **Step 2: Add WHT column to the line items table header**

Replace the existing `<thead>` block:

```html
                    <thead>
                        <tr>
                            <th style="width: 38%;">Description</th>
                            <th style="width: 10%; text-align: right;">Qty</th>
                            <th style="width: 15%; text-align: right;">Unit Cost</th>
                            <th style="width: 15%;">VAT Category</th>
                            <th style="width: 17%;">Expense Account</th>
                            <th style="width: 5%;"></th>
                        </tr>
                    </thead>
```

With:

```html
                    <thead>
                        <tr>
                            <th style="width: 30%;">Description</th>
                            <th style="width: 8%; text-align: right;">Qty</th>
                            <th style="width: 12%; text-align: right;">Unit Cost</th>
                            <th style="width: 12%;">VAT Category</th>
                            <th style="width: 18%;">WHT</th>
                            <th style="width: 15%;">Expense Account</th>
                            <th style="width: 5%;"></th>
                        </tr>
                    </thead>
```

- [ ] **Step 3: Replace the entire `<script>` block**

Replace everything from `<script>` to `</script>` (lines 97–187) with the following:

```html
<script>
const vatCategories = {{ vat_categories | tojson }};
const expenseAccounts = {{ expense_accounts | tojson }};

let currentVendorWHTs = [];
let currentVendorVatCategory = '';
let lineItems = [];
let lineCounter = 0;

function buildWhtOptions(selectedId) {
    if (currentVendorWHTs.length === 0) {
        return '<option value="">None</option>';
    }
    return '<option value="">None</option>' +
        currentVendorWHTs.map(wt =>
            `<option value="${wt.id}" data-rate="${wt.rate}" ${selectedId == wt.id ? 'selected' : ''}>${wt.code} — ${wt.name} (${wt.rate}%)</option>`
        ).join('');
}

function rebuildAllWhtSelects() {
    lineItems.forEach(item => {
        const sel = document.querySelector(`#line-${item.id} .wht-select`);
        if (!sel) return;
        const prev = item.wt_id;
        sel.innerHTML = buildWhtOptions(prev);
        const stillValid = currentVendorWHTs.some(wt => wt.id == prev);
        if (!stillValid) {
            item.wt_id = null;
            item.wt_rate = null;
            sel.value = '';
        }
    });
}

function rebuildAllVatSelects() {
    if (!currentVendorVatCategory) return;
    lineItems.forEach(item => {
        const sel = document.querySelector(`#line-${item.id} .vat-select`);
        if (!sel) return;
        sel.value = currentVendorVatCategory;
        item.vat_category = currentVendorVatCategory;
    });
    calculateTotals();
}

document.getElementById('vendor_id').addEventListener('change', function () {
    const vendorId = this.value;
    if (!vendorId || vendorId == '0') return;
    fetch(`/vendors/${vendorId}/defaults`)
        .then(r => r.json())
        .then(data => {
            currentVendorWHTs = data.withholding_taxes || [];
            currentVendorVatCategory = data.default_vat_category || '';
            rebuildAllWhtSelects();
            rebuildAllVatSelects();
            calculateTotals();
        });
});

function addLineItem(existingItem) {
    lineCounter++;
    const item = existingItem
        ? { ...existingItem, id: lineCounter }
        : {
            id: lineCounter, description: '', quantity: 1.0, unit_cost: 0.00,
            vat_category: currentVendorVatCategory || '', account_id: null,
            wt_id: null, wt_rate: null, wt_amount: 0,
          };

    const row = document.createElement('tr');
    row.id = `line-${lineCounter}`;
    row.innerHTML = `
        <td><input type="text" class="form-control" value="${(item.description || '').replace(/"/g, '&quot;')}" onchange="updateLineItem(${lineCounter}, 'description', this.value)"></td>
        <td><input type="number" class="form-control" value="${item.quantity}" step="0.0001" min="0.0001" style="text-align:right;" onchange="updateLineItem(${lineCounter}, 'quantity', parseFloat(this.value))"></td>
        <td><input type="number" class="form-control" value="${item.unit_cost}" step="0.01" min="0" style="text-align:right;" onchange="updateLineItem(${lineCounter}, 'unit_cost', parseFloat(this.value))"></td>
        <td>
            <select class="form-control vat-select" onchange="updateLineItem(${lineCounter}, 'vat_category', this.value)">
                <option value="">No VAT</option>
                ${vatCategories.map(v => `<option value="${v.code}" ${item.vat_category === v.code ? 'selected' : ''}>${v.code} (${v.rate}%)</option>`).join('')}
            </select>
        </td>
        <td>
            <select class="form-control wht-select" onchange="updateWht(${lineCounter}, this)">
                ${buildWhtOptions(item.wt_id)}
            </select>
        </td>
        <td>
            <select class="form-control" onchange="updateLineItem(${lineCounter}, 'account_id', parseInt(this.value) || null)">
                <option value="">Select Account</option>
                ${expenseAccounts.map(a => `<option value="${a.id}" ${item.account_id === a.id ? 'selected' : ''}>${a.code} - ${a.name}</option>`).join('')}
            </select>
        </td>
        <td><button type="button" class="btn-action" onclick="removeLineItem(${lineCounter})" title="Remove">🗑️</button></td>
    `;
    document.getElementById('lineItemsBody').appendChild(row);
    lineItems.push(item);
    calculateTotals();
}

function updateWht(id, sel) {
    const item = lineItems.find(i => i.id === id);
    if (!item) return;
    const opt = sel.options[sel.selectedIndex];
    item.wt_id = sel.value ? parseInt(sel.value) : null;
    item.wt_rate = sel.value ? parseFloat(opt.dataset.rate) : null;
    calculateTotals();
}

function updateLineItem(id, field, value) {
    const item = lineItems.find(i => i.id === id);
    if (item) { item[field] = value; calculateTotals(); }
}

function removeLineItem(id) {
    document.getElementById(`line-${id}`).remove();
    lineItems = lineItems.filter(i => i.id !== id);
    calculateTotals();
}

function calculateTotals() {
    let subtotal = 0, vatTotal = 0, wtTotal = 0;
    lineItems.forEach(item => {
        const lineTotal = (item.quantity || 0) * (item.unit_cost || 0);
        subtotal += lineTotal;
        const vat = vatCategories.find(v => v.code === item.vat_category);
        if (vat) vatTotal += lineTotal * (vat.rate / 100);
        if (item.wt_rate) wtTotal += lineTotal * (item.wt_rate / 100);
    });
    const totalBeforeWt = subtotal + vatTotal;
    const netPayable = totalBeforeWt - wtTotal;
    const fmt = n => '₱' + n.toLocaleString('en-PH', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    document.getElementById('subtotalDisplay').textContent = fmt(subtotal);
    document.getElementById('vatDisplay').textContent = fmt(vatTotal);
    document.getElementById('totalBeforeWtDisplay').textContent = fmt(totalBeforeWt);
    document.getElementById('wtDisplay').textContent = '-' + fmt(wtTotal);
    document.getElementById('totalDisplay').textContent = fmt(netPayable);
}

document.getElementById('billForm').addEventListener('submit', function () {
    document.getElementById('lineItemsData').value = JSON.stringify(lineItems.map(item => ({
        description: item.description,
        quantity: item.quantity,
        unit_cost: item.unit_cost,
        vat_category: item.vat_category,
        account_id: item.account_id,
        wt_id: item.wt_id,
        wt_rate: item.wt_rate,
    })));
});

function initItems() {
    {% if bill and line_items %}
    const existingItems = {{ line_items | tojson }};
    existingItems.forEach(item => addLineItem(item));
    {% elif not bill %}
    addLineItem();
    {% endif %}
}

{% if bill %}
const initVendorId = document.getElementById('vendor_id').value;
if (initVendorId && initVendorId !== '0') {
    fetch(`/vendors/${initVendorId}/defaults`)
        .then(r => r.json())
        .then(data => {
            currentVendorWHTs = data.withholding_taxes || [];
            currentVendorVatCategory = data.default_vat_category || '';
            initItems();
        })
        .catch(() => initItems());
} else {
    initItems();
}
{% else %}
initItems();
{% endif %}
</script>
```

- [ ] **Step 4: Verify the template renders without errors**

```powershell
# Start the dev server, navigate to http://localhost:5000/purchase-bills/create
# and confirm the page loads with the WHT column visible in the line items table.
python flask_app.py
```

- [ ] **Step 5: Commit**

```powershell
git add app/purchase_bills/templates/purchase_bills/form.html
git commit -m "feat: add WHT column to purchase bill form; vendor AJAX populates WHT selects"
```

---

## Task 7: Update `detail.html` — WHT column + fix header label

**Files:**
- Modify: `app/purchase_bills/templates/purchase_bills/detail.html`

- [ ] **Step 1: Add WHT column to the line items table header**

Find the `<thead>` in the line items table (around line 164). Replace:

```html
                <tr>
                    <th>#</th>
                    <th>Description</th>
                    <th style="text-align:right;">Qty</th>
                    <th style="text-align:right;">Unit Cost</th>
                    <th>VAT</th>
                    <th>Account</th>
                    <th style="text-align:right;">Amount</th>
                    <th style="text-align:right;">VAT Amt</th>
                </tr>
```

With:

```html
                <tr>
                    <th>#</th>
                    <th>Description</th>
                    <th style="text-align:right;">Qty</th>
                    <th style="text-align:right;">Unit Cost</th>
                    <th>VAT</th>
                    <th>WHT</th>
                    <th>Account</th>
                    <th style="text-align:right;">Amount</th>
                    <th style="text-align:right;">VAT Amt</th>
                    <th style="text-align:right;">WHT Amt</th>
                </tr>
```

- [ ] **Step 2: Add WHT cells to each line item row**

Find the line item row template (around line 178). After:

```html
                    <td>{{ item.vat_category or 'N/A' }} ({{ '{:.2f}'.format(item.vat_rate) }}%)</td>
```

Add:

```html
                    <td style="font-size:12px;">
                        {% if item.withholding_tax %}{{ item.withholding_tax.code }} ({{ '{:.2f}'.format(item.wt_rate) }}%){% else %}—{% endif %}
                    </td>
```

And after the existing last `<td>` for VAT amount, add:

```html
                    <td style="text-align:right; font-family:var(--mono); color:var(--red);">
                        {% if item.wt_amount and item.wt_amount > 0 %}-₱{{ '{:,.2f}'.format(item.wt_amount) }}{% else %}—{% endif %}
                    </td>
```

- [ ] **Step 3: Fix the totals section — remove stale `(rate%)` label**

Find line 208:

```html
                    <span style="color:var(--text-2);">Withholding Tax ({{ bill.withholding_tax_rate }}%):</span>
```

Replace with:

```html
                    <span style="color:var(--text-2);">Withholding Tax:</span>
```

- [ ] **Step 4: Verify the detail page renders**

Navigate to any existing purchase bill's detail page (e.g., `http://localhost:5000/purchase-bills/1`) and confirm:
- WHT column appears in line items table
- Existing bills show `—` for WHT (they have no `wt_id`)
- Header totals show `Withholding Tax:` without `(0.00%)`

- [ ] **Step 5: Commit**

```powershell
git add app/purchase_bills/templates/purchase_bills/detail.html
git commit -m "feat: add WHT column to bill detail; remove stale rate% label from totals header"
```

---

## Task 8: Update BIR report to split by WHT code

**Files:**
- Modify: `app/reports/bir.py`

- [ ] **Step 1: Add `selectinload` to imports**

In `app/reports/bir.py` line 12 (`from sqlalchemy import func, extract`), update:

```python
from sqlalchemy import func, extract
from sqlalchemy.orm import selectinload
```

Also add the `PurchaseBillItem` import:

```python
from app.purchase_bills.models import PurchaseBill, PurchaseBillItem
```

- [ ] **Step 2: Eager-load `line_items` in the query**

Find the query in `get_alphalist_of_payees` (around line 206):

```python
    bills = query.all()
```

Replace with:

```python
    bills = query.options(selectinload(PurchaseBill.line_items)).all()
```

- [ ] **Step 3: Rewrite the grouping loop**

Replace the entire `for bill in bills:` block (lines 211–233) with:

```python
    from collections import defaultdict

    for bill in bills:
        wt_groups = defaultdict(list)
        for item in bill.line_items:
            if item.wt_id and item.wt_amount and item.wt_amount > 0:
                wt_groups[item.wt_id].append(item)

        for wt_id, items in wt_groups.items():
            wt = items[0].withholding_tax
            row_key = (bill.vendor_id, wt_id)

            if row_key not in payee_totals:
                payee_totals[row_key] = {
                    'payee_name': bill.vendor_name,
                    'payee_tin': bill.vendor_tin or '',
                    'payee_address': bill.vendor_address or '',
                    'atc_code': wt.code if wt else '',
                    'tax_rate': float(wt.rate) if wt else 0.0,
                    'gross_income': Decimal('0.00'),
                    'tax_withheld': Decimal('0.00'),
                    'month_paid': [],
                }

            payee_totals[row_key]['gross_income'] += sum(i.line_total for i in items)
            payee_totals[row_key]['tax_withheld'] += sum(i.wt_amount for i in items)

            month = bill.bill_date.month
            if month not in payee_totals[row_key]['month_paid']:
                payee_totals[row_key]['month_paid'].append(month)
```

- [ ] **Step 4: Run the full test suite**

```powershell
pytest tests/ -v -m "not slow"
```

Expected: all PASS (no BIR-related tests exist yet, but existing tests must not regress).

- [ ] **Step 5: Commit**

```powershell
git add app/reports/bir.py
git commit -m "feat: BIR alphalist groups by (vendor_id, wt_id) for multi-rate bills"
```

---

## Task 9: Integration tests

**Files:**
- Modify: `tests/unit/test_wht_per_line_item.py`

- [ ] **Step 1: Add integration tests that use the DB**

Append to `tests/unit/test_wht_per_line_item.py`:

```python
# ── Integration tests (require DB) ──────────────────────────────────────────

@pytest.fixture
def wht_codes(db_session):
    from app.withholding_tax.models import WithholdingTax
    codes = [
        WithholdingTax(code='WC010', name='Professional Fees', rate=Decimal('10.00'), is_active=True),
        WithholdingTax(code='WC060', name='Contractors', rate=Decimal('2.00'), is_active=True),
    ]
    for c in codes:
        db_session.add(c)
    db_session.commit()
    return {c.code: c for c in codes}


@pytest.fixture
def test_vendor_with_wht(db_session, wht_codes):
    from app.vendors.models import Vendor
    vendor = Vendor(code='V099', name='WHT Vendor', is_active=True,
                    default_vat_category='VATABLE')
    vendor.withholding_taxes = list(wht_codes.values())
    db_session.add(vendor)
    db_session.commit()
    return vendor


@pytest.fixture
def gl_accounts_wht(db_session):
    from app.accounts.models import Account
    accounts = [
        Account(code='20101', name='AP - Trade', account_type='Liability', normal_balance='Credit'),
        Account(code='10501', name='Input VAT', account_type='Asset', normal_balance='Debit'),
        Account(code='20301', name='WT Payable', account_type='Liability', normal_balance='Credit'),
        Account(code='50999', name='Misc Expense', account_type='Expense', normal_balance='Debit'),
    ]
    for a in accounts:
        db_session.add(a)
    db_session.commit()
    return {a.code: a for a in accounts}


class TestPurchaseBillWhtIntegration:
    def _make_bill(self, db_session, admin_user, main_branch, test_vendor_with_wht,
                   gl_accounts_wht, wht_codes):
        from app.purchase_bills.models import PurchaseBill, PurchaseBillItem
        bill = PurchaseBill(
            bill_number='PB-WHT-0001',
            bill_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            vendor_id=test_vendor_with_wht.id,
            vendor_name='WHT Vendor',
            payment_terms='Net 30',
            withholding_tax_rate=Decimal('0.00'),
            amount_paid=Decimal('0.00'),
            balance=Decimal('0.00'),
            status='draft',
            branch_id=main_branch.id,
            created_by_id=admin_user.id,
        )
        db_session.add(bill)
        db_session.flush()

        item1 = PurchaseBillItem(
            bill_id=bill.id, line_number=1, description='Consultancy',
            quantity=Decimal('1.0000'), unit_cost=Decimal('5000.00'),
            vat_rate=Decimal('12.00'), vat_category='VATABLE',
            account_id=gl_accounts_wht['50999'].id,
            wt_id=wht_codes['WC010'].id,
            wt_rate=Decimal('10.00'),
        )
        item2 = PurchaseBillItem(
            bill_id=bill.id, line_number=2, description='Construction',
            quantity=Decimal('1.0000'), unit_cost=Decimal('10000.00'),
            vat_rate=Decimal('12.00'), vat_category='VATABLE',
            account_id=gl_accounts_wht['50999'].id,
            wt_id=wht_codes['WC060'].id,
            wt_rate=Decimal('2.00'),
        )
        item1.calculate_amounts()
        item2.calculate_amounts()
        bill.line_items.append(item1)
        bill.line_items.append(item2)
        bill.calculate_totals()
        db_session.commit()
        return bill

    def test_line_wt_amounts_computed(self, db_session, admin_user, main_branch,
                                      test_vendor_with_wht, gl_accounts_wht, wht_codes):
        bill = self._make_bill(db_session, admin_user, main_branch,
                               test_vendor_with_wht, gl_accounts_wht, wht_codes)
        items = sorted(bill.line_items, key=lambda i: i.line_number)
        # item1: 5000 * 10% = 500
        assert items[0].wt_amount == Decimal('500.00')
        # item2: 10000 * 2% = 200
        assert items[1].wt_amount == Decimal('200.00')

    def test_bill_withholding_tax_amount_sums_lines(self, db_session, admin_user, main_branch,
                                                     test_vendor_with_wht, gl_accounts_wht, wht_codes):
        bill = self._make_bill(db_session, admin_user, main_branch,
                               test_vendor_with_wht, gl_accounts_wht, wht_codes)
        # 500 + 200 = 700
        assert bill.withholding_tax_amount == Decimal('700.00')

    def test_bill_total_amount_deducts_wht_sum(self, db_session, admin_user, main_branch,
                                                test_vendor_with_wht, gl_accounts_wht, wht_codes):
        bill = self._make_bill(db_session, admin_user, main_branch,
                               test_vendor_with_wht, gl_accounts_wht, wht_codes)
        # subtotal=15000, vat=1800, total_before_wt=16800, wt=700, total=16100
        assert bill.subtotal == Decimal('15000.00')
        assert bill.vat_amount == Decimal('1800.00')
        assert bill.total_before_wt == Decimal('16800.00')
        assert bill.total_amount == Decimal('16100.00')

    def test_to_dict_includes_wt_fields(self, db_session, admin_user, main_branch,
                                         test_vendor_with_wht, gl_accounts_wht, wht_codes):
        bill = self._make_bill(db_session, admin_user, main_branch,
                               test_vendor_with_wht, gl_accounts_wht, wht_codes)
        items = sorted(bill.line_items, key=lambda i: i.line_number)
        d = items[0].to_dict()
        assert d['wt_id'] == wht_codes['WC010'].id
        assert d['wt_rate'] == 10.0
        assert d['wt_amount'] == 500.0

    def test_bill_to_dict_excludes_withholding_tax_rate(self, db_session, admin_user, main_branch,
                                                          test_vendor_with_wht, gl_accounts_wht, wht_codes):
        bill = self._make_bill(db_session, admin_user, main_branch,
                               test_vendor_with_wht, gl_accounts_wht, wht_codes)
        d = bill.to_dict()
        assert 'withholding_tax_rate' not in d

    def test_void_je_uses_summed_wt_amount(self, db_session, admin_user, main_branch,
                                            test_vendor_with_wht, gl_accounts_wht, wht_codes):
        """Void JE DR side must equal total_amount + withholding_tax_amount (summed from lines)."""
        bill = self._make_bill(db_session, admin_user, main_branch,
                               test_vendor_with_wht, gl_accounts_wht, wht_codes)
        bill.status = 'posted'
        db_session.commit()
        from app.purchase_bills.views import _create_bill_void_je
        je = _create_bill_void_je(bill, date.today(), admin_user.id)
        total_debit = sum(l.debit_amount for l in je.lines)
        total_credit = sum(l.credit_amount for l in je.lines)
        assert total_debit == total_credit  # JE must balance
        assert bill.withholding_tax_amount == Decimal('700.00')
```

Note: `admin_user` and `main_branch` fixtures come from `tests/conftest.py`.

- [ ] **Step 2: Run tests**

```powershell
pytest tests/unit/test_wht_per_line_item.py -v
```

Expected: all PASS.

- [ ] **Step 3: Run the full test suite**

```powershell
pytest tests/ -v -m "not slow"
```

Expected: all PASS.

- [ ] **Step 4: Commit**

```powershell
git add tests/unit/test_wht_per_line_item.py
git commit -m "test: add integration tests for WHT per line item"
```

---

## Self-Review

**Spec coverage check:**
- [x] `PurchaseBillItem` — `wt_id`, `wt_rate`, `wt_amount`, `withholding_tax` relationship → Task 1
- [x] `calculate_amounts()` computes `wt_amount` → Task 1
- [x] `PurchaseBill.calculate_totals()` sums from lines → Task 1
- [x] Migration — additive nullable columns → Task 2
- [x] `withholding_tax_rate` removed from form → Task 3
- [x] `GET /vendors/<id>/defaults` endpoint → Task 4
- [x] Create + edit views resolve `wt_id`/`wt_rate` per line → Task 5
- [x] `form.html` — WHT column, vendor AJAX, `calculateTotals()`, serialisation → Task 6
- [x] `detail.html` — WHT column, fix `(rate%)` label → Task 7
- [x] BIR report groups by `(vendor_id, wt_id)` → Task 8
- [x] `PurchaseBillItem.to_dict()` includes wt fields → Task 1
- [x] `PurchaseBill.to_dict()` drops `withholding_tax_rate` → Task 1
- [x] Tests → Task 9

**Placeholder scan:** none found.

**Type consistency:**
- `item.wt_id` (Integer | None) — consistent across model, views, JS payload, tests ✓
- `item.wt_rate` (Decimal | None in Python; float | null in JS) — consistent ✓
- `item.wt_amount` (Decimal, non-null, default 0.00) — consistent ✓
- `wt_groups` dict keyed by `wt_id` (int) — consistent with `items[0].withholding_tax` backref ✓
