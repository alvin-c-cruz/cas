# Bill Entry Form Layout Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `form.html` so the vendor field is a prominent "Step 1" amber card, header fields are dimmed until vendor is selected, line items are locked behind vendor selection, and edit mode loads in the completed state immediately.

**Architecture:** Pure frontend change — one template file, no backend or model changes. Two Jinja-rendered states (create vs edit) drive the initial HTML; JS handles all transitions. Existing JS functions (calculateTotals, rebuildAllWhtSelects, etc.) are kept unchanged; only the vendor-change handler and init block are replaced.

**Tech Stack:** Jinja2 template, vanilla JS, existing Flask-WTF form, existing `/vendors/{id}/defaults` JSON endpoint.

---

## Files

| File | Change |
|---|---|
| `app/purchase_bills/templates/purchase_bills/form.html` | Full rewrite |
| `tests/integration/test_purchase_bill_views.py` | Add `TestFormLayout` class |

---

### Task 1: Integration tests for initial render (create + edit mode)

These tests check server-rendered HTML only — Jinja state, not JS transitions.

**Files:**
- Modify: `tests/integration/test_purchase_bill_views.py`

- [ ] **Step 1: Add `TestFormLayout` class with create-mode test**

Open `tests/integration/test_purchase_bill_views.py`. The file already has `make_vendor()` and `make_bill()` helpers and a `login()` helper. Add this class at the end:

```python
class TestFormLayout:
    """Tests for the bill entry form initial render state."""

    def test_create_mode_initial_render(self, client, db_session, admin_user, main_branch):
        """Create mode: vendor card amber, header dimmed, line items locked, totals hidden."""
        login(client)
        resp = client.get('/purchase-bills/create')
        assert resp.status_code == 200
        html = resp.data.decode()

        # Vendor step card present in amber (not done) state
        assert 'id="vendorCard"' in html
        assert 'vendor-step-card' in html
        assert 'vendor-step-card--done' not in html

        # Header fields wrapper present but NOT active (dimmed)
        assert 'id="headerFields"' in html
        assert 'header-fields--active' not in html

        # Locked placeholder visible
        assert 'id="lineItemsLocked"' in html
        assert 'line-items-locked--hidden' not in html

        # Line items section hidden
        assert 'id="lineItemsSection"' in html
        assert 'id="lineItemsSection" style="display:none"' in html

    def test_edit_mode_initial_render(self, client, db_session, admin_user, main_branch):
        """Edit mode: vendor card green, header active, line items visible immediately."""
        vendor = make_vendor(db_session, code='EDIT-V1', name='Edit Vendor')
        bill = make_bill(db_session, vendor, main_branch, 'PB-TEST-EDIT', status='draft')
        login(client)

        resp = client.get(f'/purchase-bills/{bill.id}/edit')
        assert resp.status_code == 200
        html = resp.data.decode()

        # Vendor card in done/green state
        assert 'vendor-step-card--done' in html

        # Header fields active (not dimmed)
        assert 'header-fields--active' in html

        # Locked placeholder hidden
        assert 'line-items-locked--hidden' in html

        # Line items section visible (no display:none)
        assert 'id="lineItemsSection" style="display:none"' not in html
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest tests/integration/test_purchase_bill_views.py::TestFormLayout -v --no-cov
```

Expected: 2 FAILED (the new HTML ids don't exist yet).

---

### Task 2: Rewrite form.html — HTML structure

Write the complete new `form.html`. This makes Task 1's tests pass. JS functions are carried over unchanged; the init block and vendor handler are replaced in Task 3.

**Files:**
- Modify: `app/purchase_bills/templates/purchase_bills/form.html`

- [ ] **Step 1: Write the new template**

Replace the entire contents of `app/purchase_bills/templates/purchase_bills/form.html` with:

```html
{% extends "base.html" %}

{% block title %}{{ 'Update Bill' if bill else 'Enter Bill' }}{% endblock %}
{% block page_title %}{{ 'Update Bill' if bill else 'Enter Bill' }}{% endblock %}

{% block content %}
{% from "macros.html" import render_field, render_flash_messages %}

{{ render_flash_messages() }}

<div class="card">
    <div class="card-body">
        <form method="POST" novalidate id="billForm">
            {{ form.hidden_tag() }}

            <!-- ① Vendor Step Card -->
            <div id="vendorCard" class="vendor-step-card{% if bill %} vendor-step-card--done{% endif %}">
                <div class="vendor-step-label" id="vendorCardLabel">
                    {% if bill %}✓ {{ bill.vendor_name }}{% else %}Step 1 — Select Vendor{% endif %}
                </div>
                <div id="vendorBadges" class="vendor-badges"></div>
                <select name="vendor_id" id="vendor_id" class="form-control" required
                        {% if not bill %}autofocus{% endif %}>
                    <option value="">Search or select a vendor…</option>
                    {% for choice in form.vendor_id.choices %}
                    <option value="{{ choice[0] }}"
                        {% if bill and bill.vendor_id == choice[0] %}selected{% endif %}>
                        {{ choice[1] }}
                    </option>
                    {% endfor %}
                </select>
                {% if form.vendor_id.errors %}
                <div class="form-error">{{ form.vendor_id.errors[0] }}</div>
                {% endif %}
            </div>

            <!-- ② Header Fields (dimmed until vendor selected) -->
            <div id="headerFields" class="header-fields{% if bill %} header-fields--active{% endif %}">
                <div class="form-row-3">
                    {{ render_field(form.bill_number) }}
                    {{ render_field(form.bill_date) }}
                    {{ render_field(form.due_date) }}
                </div>
                <div class="form-row-2">
                    {{ render_field(form.payment_terms) }}
                    {{ render_field(form.vendor_invoice_number) }}
                </div>
                <div class="form-row-2">
                    {{ render_field(form.vendor_invoice_date) }}
                    {{ render_field(form.reference) }}
                </div>
                <div style="margin-bottom: 16px;">
                    {{ render_field(form.notes) }}
                </div>
            </div>

            <!-- ③ Line Items Locked Placeholder -->
            <div id="lineItemsLocked" class="line-items-locked{% if bill %} line-items-locked--hidden{% endif %}">
                <div style="font-size: 28px; margin-bottom: 10px;">🔒</div>
                <div style="font-size: 14px; font-weight: 600; color: #92400e;">
                    Select a vendor above to add line items
                </div>
                <div style="font-size: 12px; color: var(--text-2); margin-top: 6px;">
                    WHT codes and VAT defaults will load from the vendor.
                </div>
            </div>

            <!-- ④ Line Items Section (hidden on create, visible on edit) -->
            <div id="lineItemsSection"{% if not bill %} style="display:none"{% endif %}>
                <div style="margin-top: 32px; padding-top: 24px; border-top: 1px solid var(--border);">
                    <h3 style="font-size: 15px; font-weight: 600; margin-bottom: 16px;">Line Items</h3>

                    <table class="table" id="lineItemsTable">
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
                        <tbody id="lineItemsBody"></tbody>
                    </table>

                    <button type="button" class="btn btn-secondary" onclick="addLineItem()">+ Add Line Item</button>
                    <input type="hidden" name="line_items" id="lineItemsData">
                </div>

                <!-- ⑤ Totals Panel -->
                <div style="display: flex; justify-content: flex-end; margin-top: 24px;">
                    <div style="background: var(--bg); padding: 20px; border-radius: 6px; min-width: 320px;">
                        <div style="display: flex; justify-content: space-between; margin-bottom: 12px;">
                            <span style="color: var(--text-2);">Subtotal:</span>
                            <span id="subtotalDisplay" style="font-family: var(--mono); font-weight: 600;">₱0.00</span>
                        </div>
                        <div style="display: flex; justify-content: space-between; margin-bottom: 12px;">
                            <span style="color: var(--text-2);">Input VAT:</span>
                            <span id="vatDisplay" style="font-family: var(--mono); font-weight: 600;">₱0.00</span>
                        </div>
                        <div style="display: flex; justify-content: space-between; margin-bottom: 12px; padding-top: 8px; border-top: 1px solid var(--border);">
                            <span style="color: var(--text-2);">Total before WT:</span>
                            <span id="totalBeforeWtDisplay" style="font-family: var(--mono); font-weight: 600;">₱0.00</span>
                        </div>
                        <div style="display: flex; justify-content: space-between; margin-bottom: 12px;">
                            <span style="color: var(--text-2);">Withholding Tax:</span>
                            <span id="wtDisplay" style="font-family: var(--mono); font-weight: 600; color: var(--red);">-₱0.00</span>
                        </div>
                        <div style="display: flex; justify-content: space-between; padding-top: 12px; border-top: 2px solid var(--border);">
                            <span style="font-size: 16px; font-weight: 700;">Net Payable:</span>
                            <span id="totalDisplay" style="font-family: var(--mono); font-size: 18px; font-weight: 700; color: var(--blue);">₱0.00</span>
                        </div>
                    </div>
                </div>

                <div class="form-actions" style="margin-top: 32px;">
                    <button type="submit" class="btn btn-primary">
                        {{ 'Update Bill' if bill else 'Enter Bill' }}
                    </button>
                    <a href="{{ url_for('purchase_bills.list_bills') }}" class="btn btn-secondary">Cancel</a>
                </div>
            </div>

        </form>
    </div>
</div>

<script>
const vatCategories = {{ vat_categories | tojson }};
const expenseAccounts = {{ expense_accounts | tojson }};

let currentVendorWHTs = [];
let currentVendorVatCategory = '';
let lineItems = [];
let lineCounter = 0;

// ── Unchanged helper functions ────────────────────────────────────────────────

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
    const autoWht = currentVendorWHTs.length === 1 ? currentVendorWHTs[0] : null;
    lineItems.forEach(item => {
        const sel = document.querySelector(`#line-${item.id} .wht-select`);
        if (!sel) return;
        const prev = item.wt_id;
        const stillValid = prev && currentVendorWHTs.some(wt => wt.id == prev);
        if (!stillValid) {
            item.wt_id = autoWht ? autoWht.id : null;
            item.wt_rate = autoWht ? autoWht.rate : null;
        }
        sel.innerHTML = buildWhtOptions(item.wt_id);
        sel.value = item.wt_id || '';
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

function applyVendorTerms(terms) {
    const termsField = document.getElementById('payment_terms');
    if (termsField) termsField.value = terms;
    const match = terms.match(/Net (\d+)/);
    if (!match) return;
    const days = parseInt(match[1]);
    const billDateVal = document.getElementById('bill_date').value;
    if (!billDateVal) return;
    const due = new Date(billDateVal);
    if (isNaN(due.getTime())) return;
    due.setDate(due.getDate() + days);
    const dueDateField = document.getElementById('due_date');
    if (dueDateField) dueDateField.value = due.toISOString().split('T')[0];
}

function addLineItem(existingItem) {
    lineCounter++;
    const item = existingItem
        ? { ...existingItem, id: lineCounter }
        : (() => {
            const autoWht = currentVendorWHTs.length === 1 ? currentVendorWHTs[0] : null;
            return {
                id: lineCounter, description: '', quantity: 1.0, unit_cost: 0.00,
                vat_category: currentVendorVatCategory || '', account_id: null,
                wt_id: autoWht ? autoWht.id : null,
                wt_rate: autoWht ? autoWht.rate : null,
                wt_amount: 0,
            };
          })();

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

// ── Vendor card state management ──────────────────────────────────────────────

function setVendorDone(vendorName, defaults) {
    const card = document.getElementById('vendorCard');
    const label = document.getElementById('vendorCardLabel');
    const badges = document.getElementById('vendorBadges');

    card.classList.add('vendor-step-card--done');
    label.textContent = '✓ ' + vendorName;

    const badgeHtml = [];
    (defaults.withholding_taxes || []).forEach(wt => {
        badgeHtml.push(`<span class="vendor-badge">${wt.code}</span>`);
    });
    if (defaults.default_vat_category) {
        badgeHtml.push(`<span class="vendor-badge">VAT: ${defaults.default_vat_category}</span>`);
    }
    badges.innerHTML = badgeHtml.join('');

    document.getElementById('headerFields').classList.add('header-fields--active');
    document.getElementById('lineItemsLocked').classList.add('line-items-locked--hidden');
    document.getElementById('lineItemsSection').style.display = '';
}

// ── Vendor change handler ─────────────────────────────────────────────────────

document.getElementById('vendor_id').addEventListener('change', function () {
    const vendorId = this.value;
    const vendorName = this.options[this.selectedIndex].text;
    if (!vendorId || vendorId == '0') return;

    fetch(`/vendors/${vendorId}/defaults`)
        .then(r => r.json())
        .then(data => {
            currentVendorWHTs = data.withholding_taxes || [];
            currentVendorVatCategory = data.default_vat_category || '';
            applyVendorTerms(data.payment_terms || 'Net 30');

            const hadItems = lineItems.length > 0;
            setVendorDone(vendorName, data);

            if (hadItems) {
                rebuildAllWhtSelects();
                rebuildAllVatSelects();
                calculateTotals();
            } else {
                addLineItem();
            }
        });
});

// ── Init ──────────────────────────────────────────────────────────────────────

function initItems() {
    {% if bill and line_items %}
    const existingItems = {{ line_items | tojson }};
    existingItems.forEach(item => addLineItem(item));
    {% endif %}
    // Create mode: no auto-add — first row added when vendor is selected
}

{% if bill %}
const initVendorId = document.getElementById('vendor_id').value;
const initVendorSel = document.getElementById('vendor_id');
const initVendorName = initVendorSel.options[initVendorSel.selectedIndex]
    ? initVendorSel.options[initVendorSel.selectedIndex].text
    : '{{ bill.vendor_name | e }}';

if (initVendorId && initVendorId !== '0') {
    fetch(`/vendors/${initVendorId}/defaults`)
        .then(r => r.json())
        .then(data => {
            currentVendorWHTs = data.withholding_taxes || [];
            currentVendorVatCategory = data.default_vat_category || '';
            setVendorDone(initVendorName, data);
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

<style>
/* Vendor Step Card */
.vendor-step-card {
    border: 2px solid var(--amber, #f59e0b);
    background: #fffbeb;
    border-radius: 8px;
    padding: 20px 24px;
    margin-bottom: 24px;
    transition: border-color 0.2s ease, background 0.2s ease;
}
.vendor-step-card--done {
    border-color: #22c55e;
    background: #f0fdf4;
}
.vendor-step-label {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #92400e;
    margin-bottom: 10px;
    transition: color 0.2s ease;
}
.vendor-step-card--done .vendor-step-label {
    color: #166534;
}
.vendor-badges {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    margin-bottom: 8px;
    min-height: 0;
}
.vendor-badge {
    background: #dcfce7;
    color: #166534;
    border: 1px solid #86efac;
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 600;
}

/* Header fields dimming */
.header-fields {
    opacity: 0.65;
    pointer-events: none;
    transition: opacity 0.2s ease;
}
.header-fields--active {
    opacity: 1;
    pointer-events: auto;
}

/* Line items locked placeholder */
.line-items-locked {
    border: 2px dashed var(--amber, #f59e0b);
    background: #fffbeb;
    border-radius: 8px;
    padding: 40px 24px;
    text-align: center;
    margin-top: 24px;
}
.line-items-locked--hidden {
    display: none;
}

/* Existing grid helpers */
.form-row-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 16px; }
.form-row-2 { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; margin-bottom: 16px; }
.btn-action { padding: 4px 8px; border-radius: 4px; background: var(--bg); border: 1px solid var(--border); cursor: pointer; font-size: 14px; }
.btn-action:hover { background: var(--border); }
</style>
{% endblock %}
```

- [ ] **Step 2: Run Task 1 tests to verify they now pass**

```
pytest tests/integration/test_purchase_bill_views.py::TestFormLayout -v --no-cov
```

Expected: 2 PASSED.

- [ ] **Step 3: Run the full purchase bill test suite to confirm no regressions**

```
pytest tests/integration/test_purchase_bill_views.py -v --no-cov
```

Expected: all tests pass (was 29 before this change).

- [ ] **Step 4: Commit**

```
git add app/purchase_bills/templates/purchase_bills/form.html tests/integration/test_purchase_bill_views.py
git commit -m "feat: bill form — amber vendor step card, dimmed header, locked line items until vendor selected"
```

---

### Task 3: Manual browser verification

These are JS-driven states that cannot be tested with pytest.

**Files:** none — browser only.

- [ ] **Step 1: Start the dev server**

```
python flask_app.py
```

- [ ] **Step 2: Seed and log in**

If the database is empty: `flask seed-db`, then open `http://localhost:5000` and log in with `admin` / `ac1123581321`.

- [ ] **Step 3: Verify create mode initial state**

Open `http://localhost:5000/purchase-bills/create`.

Check:
- Amber-bordered card at the top with "STEP 1 — SELECT VENDOR" label ✓
- Vendor `<select>` autofocused inside the card ✓
- Header fields below are visibly dimmed (lower contrast) ✓
- Locked placeholder (🔒 icon + text) visible below header ✓
- No line items table, no totals panel, no "Enter Bill" button visible ✓

- [ ] **Step 4: Verify vendor selection unlocks the form**

Select any vendor from the dropdown.

Check:
- Vendor card border turns green, label updates to "✓ [Vendor Name]" ✓
- WHT and VAT badges appear inside the card ✓
- Header fields undim (full contrast, fully clickable) ✓
- Payment Terms field auto-fills with vendor's default ✓
- Due Date computes if terms is "Net N" ✓
- Line items locked placeholder disappears ✓
- Line items table appears with one row pre-loaded (WHT and VAT filled) ✓
- Totals panel visible (all ₱0.00) ✓
- "Enter Bill" and "Cancel" buttons visible ✓

- [ ] **Step 5: Verify vendor change after line items**

Add a second line item manually. Then change the vendor dropdown to a different vendor.

Check:
- Both line items remain (not cleared) ✓
- WHT and VAT on all rows rebuild to new vendor's defaults ✓
- Payment Terms updates ✓
- Vendor card updates to new vendor name + badges ✓

- [ ] **Step 6: Verify edit mode**

Go to any existing draft bill via the list, open its detail page, click Edit.

Check:
- Vendor card is already green on load (no amber state) ✓
- Vendor name shown with "✓" prefix ✓
- Header fields fully visible and interactive (not dimmed) ✓
- Line items table visible immediately with existing rows ✓
- Totals panel visible with correct pre-computed values ✓

- [ ] **Step 7: Enter a full bill end-to-end**

From create mode: select vendor → fill in description + unit cost → click "Enter Bill". Confirm the bill saves as a draft and redirects to the detail page.
