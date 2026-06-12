# Purchase Bill Form Refactor & Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract inline CSS and pure-JS utilities from `form.html` into reusable static files, add responsive breakpoints, and gate the Save Draft button on minimum required data.

**Architecture:** Three new static files (`transactions.css`, `purchase_bills_form.css`, `transaction-utils.js`) replace the 215-line `<style>` block and five utility functions in `form.html`. `validateForm()` is wired into `calculateTotals()` and the vendor invoice number input to disable the submit button until all required fields are present. A Playwright smoke test guards against regressions from future shared-file changes.

**Tech Stack:** Flask/Jinja2, Choices.js v10, pytest-playwright, pytest (smoke marker already in pytest.ini)

---

## Files

| Action | Path |
|---|---|
| Create | `app/static/transaction-utils.js` |
| Create | `app/static/transactions.css` |
| Create | `app/static/purchase_bills_form.css` |
| Modify | `app/purchase_bills/templates/purchase_bills/form.html` |
| Create | `tests/smoke/__init__.py` |
| Create | `tests/smoke/conftest.py` |
| Create | `tests/smoke/test_purchase_bill_form.py` |
| Modify | `requirements.txt` |

---

## Task 1: Create `transaction-utils.js`

Pure utility functions extracted from `form.html`. No DOM access, no global state, safe to share across all transaction forms.

**Files:**
- Create: `app/static/transaction-utils.js`

- [ ] **Step 1: Create the file**

```js
// transaction-utils.js
// Shared pure utilities for all transaction forms.
// NOTE: amtBlur expects updateLineItem(id, field, value) to be defined by the host form.

function fmt(n) {
    return n.toLocaleString('en-PH', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtNum(n) {
    return n > 0
        ? n.toLocaleString('en-PH', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
        : '—';
}

function amtFmt(n) {
    return (n || 0).toLocaleString('en-PH', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function amtFocus(el) {
    const n = parseFloat(el.value.replace(/,/g, '')) || 0;
    el.value = n.toFixed(2);
    el.select();
}

function amtBlur(el, id) {
    const n = parseFloat(el.value.replace(/,/g, '')) || 0;
    el.value = amtFmt(n);
    updateLineItem(id, 'amount', n);
}

function escHtml(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
```

- [ ] **Step 2: Commit**

```bash
git add app/static/transaction-utils.js
git commit -m "feat: add transaction-utils.js with shared pure utility functions"
```

---

## Task 2: Create `transactions.css`

Shared styles reusable across all transaction forms, plus all responsive breakpoints.

**Files:**
- Create: `app/static/transactions.css`

- [ ] **Step 1: Create the file**

```css
/* transactions.css — shared styles for all transaction forms (purchase bills, sales invoices, receipts) */

/* ── Header layout grid ────────────────────────────────────────────────────── */
.form-main-grid {
    display: grid;
    grid-template-columns: 1fr 2fr;
    gap: 16px;
    align-items: stretch;
    margin-bottom: 24px;
}
.right-col { display: flex; flex-direction: column; gap: 12px; }
.left-col-fields { display: flex; flex-direction: column; gap: 10px; }
.left-col-fields .form-group { display: flex; align-items: center; gap: 8px; margin-bottom: 0; }
.left-col-fields .form-group .form-label {
    white-space: nowrap; margin-bottom: 0; min-width: 150px;
    font-size: 11px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.04em; color: var(--text-2);
}
.left-col-fields .form-group .form-control { flex: 1; }
.notes-col { display: flex; flex-direction: column; flex: 1; }
.notes-col .form-label {
    font-size: 11px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.04em; color: var(--text-2); margin-bottom: 6px;
}
.notes-col .form-control { flex: 1; min-height: 60px; }

/* ── Generic form row helpers ─────────────────────────────────────────────── */
.form-row-5 { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-bottom: 12px; }
.form-row-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 12px; }
.form-row-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 12px; }
.form-row-2 { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 12px; }

/* ── Line item action button ─────────────────────────────────────────────── */
.btn-action { padding: 4px 8px; border-radius: 4px; background: var(--bg); border: 1px solid var(--border); cursor: pointer; font-size: 14px; }
.btn-action:hover { background: var(--border); }

/* ── Summary panel (.bsr rows) ───────────────────────────────────────────── */
.bsr { display: grid; grid-template-columns: 1fr 130px; align-items: center; margin-bottom: 10px; gap: 8px; }
.bsr--sep { margin-top: 4px; padding-top: 10px; border-top: 1px solid var(--border); }
.bsr--total { margin-top: 4px; padding-top: 12px; border-top: 2px solid var(--border); margin-bottom: 0; }
.bsr-label { color: var(--text-2); font-size: 13px; }
.bsr-label--total { font-size: 15px; font-weight: 700; color: var(--text-1); }
.bsr-hint { font-size: 11px; color: var(--text-2); margin-left: 4px; }
.bsr-amt { font-family: var(--mono); font-weight: 600; font-size: 13px; text-align: right; display: block; }
.bsr-amt--red { color: var(--red); }
.bsr-amt--total { font-size: 18px; font-weight: 700; color: var(--blue); }
.bsr-amt-wrap { display: flex; align-items: center; justify-content: flex-end; gap: 4px; }

/* ── Choices.js compact overrides ────────────────────────────────────────── */
.choices { margin-bottom: 0; }
.choices__inner {
    min-height: 0 !important; height: 28px;
    padding: 3px 6px !important;
    font-size: 13px !important;
    border: 1px solid transparent !important;
    border-radius: 2px !important;
    background: transparent !important;
    box-shadow: none !important;
    display: flex; align-items: center;
}
.choices:hover .choices__inner { border-color: var(--border) !important; background: var(--card) !important; }
.choices.is-focused .choices__inner,
.choices.is-open .choices__inner {
    border-color: var(--blue) !important;
    background: var(--card) !important;
    border-radius: 3px !important;
}
.choices__input {
    font-size: 13px !important; font-family: inherit !important;
    background: transparent !important; margin-bottom: 0 !important;
}
.choices[data-type*=select-one] .choices__inner { padding-right: 6px !important; }
.choices[data-type*=select-one]::after { display: none !important; }
.choices__list--dropdown {
    font-size: 13px;
    border: 1px solid var(--border) !important;
    border-radius: 6px !important;
    box-shadow: 0 4px 16px rgba(0,0,0,.1) !important;
    margin-top: 2px; z-index: 999;
    min-width: 260px;
}
.choices__list--dropdown .choices__item { padding: 6px 10px; white-space: nowrap; }
.choices__list--dropdown .choices__item--selectable.is-highlighted {
    background: #eff6ff !important; color: var(--blue) !important;
}
.choices__list--single { padding: 0; overflow: hidden; }
.choices__list--single .choices__item {
    font-size: 13px; line-height: 1.3;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}

/* ── Responsive — tablet ─────────────────────────────────────────────────── */
@media (max-width: 1023px) {
    .form-main-grid {
        grid-template-columns: 1fr;
        gap: 12px;
    }
    /* Vendor card (right-col) stacks above header fields (left-col-fields) */
    .left-col-fields { order: 2; }
    .right-col       { order: 1; }

    /* JE preview + Bill Summary stack vertically */
    #jePreviewSection,
    #jePreviewSection + div {
        width: 100%;
    }
}

/* ── Responsive — mobile ─────────────────────────────────────────────────── */
@media (max-width: 639px) {
    .form-main-grid { gap: 10px; }

    /* Label above input instead of side-by-side */
    .left-col-fields .form-group {
        flex-direction: column;
        align-items: flex-start;
    }
    .left-col-fields .form-group .form-label {
        min-width: unset;
        margin-bottom: 2px;
    }
    .left-col-fields .form-group .form-control {
        width: 100%;
    }

    /* Line items table: horizontal scroll */
    #lineItemsSection > div {
        overflow-x: auto;
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add app/static/transactions.css
git commit -m "feat: add transactions.css with shared styles and responsive breakpoints"
```

---

## Task 3: Create `purchase_bills_form.css`

Bill-specific styles. Also adds three missing CSS states that are referenced in JS/HTML but were never defined: `.header-fields--active`, `.vendor-step-card--done`, `.line-items-locked--hidden`.

**Files:**
- Create: `app/static/purchase_bills_form.css`

- [ ] **Step 1: Create the file**

```css
/* purchase_bills_form.css — styles specific to the purchase bill create/edit form */

/* ── Vendor step card ────────────────────────────────────────────────────── */
.vendor-step-card {
    border: 2px solid var(--amber, #f59e0b);
    background: #fffbeb;
    border-radius: 8px;
    padding: 20px 24px;
    margin-bottom: 24px;
    transition: border-color 0.2s ease, background 0.2s ease;
}
.vendor-step-card--done {
    border-color: var(--green, #22c55e);
    background: var(--card);
}
.right-col .vendor-step-card { margin-bottom: 0; }
.vendor-step-label {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #92400e;
    margin-bottom: 10px;
    transition: color 0.2s ease;
}
.vendor-step-card--done .vendor-step-label { color: var(--text-2); }
.vendor-badges { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; min-height: 0; }
.vendor-badge {
    background: #dcfce7;
    color: #166534;
    border: 1px solid #86efac;
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 600;
}

/* ── Header field dimming ─────────────────────────────────────────────────── */
.header-fields {
    opacity: 0.65;
    pointer-events: none;
    transition: opacity 0.2s ease;
}
.header-fields--active {
    opacity: 1;
    pointer-events: auto;
}

/* ── Line items locked placeholder ───────────────────────────────────────── */
.line-items-locked {
    border: 2px dashed var(--amber, #f59e0b);
    background: #fffbeb;
    border-radius: 8px;
    padding: 40px 24px;
    text-align: center;
    margin-top: 24px;
}
.line-items-locked--hidden { display: none; }

/* ── Totals override buttons ─────────────────────────────────────────────── */
.totals-pencil {
    background: none; border: none; cursor: pointer;
    font-size: 12px; opacity: 0.35; padding: 0; transition: opacity 0.15s;
}
.totals-pencil:hover { opacity: 0.9; }
.totals-pencil:focus-visible { opacity: 0.9; outline: 2px solid var(--blue); outline-offset: 2px; }
.totals-revert {
    background: var(--bg); border: 1px solid var(--border); border-radius: 3px;
    cursor: pointer; font-size: 11px; padding: 1px 5px; color: var(--text-2);
}
.totals-revert:hover { background: var(--border); }

/* ── VAT/WT override input ───────────────────────────────────────────────── */
.bsr-input {
    width: 110px; text-align: right; font-family: var(--mono);
    font-size: 13px; border: 1px solid var(--blue); border-radius: 4px; padding: 3px 7px;
}

/* ── Bill Summary panel ──────────────────────────────────────────────────── */
.bill-summary-panel {
    background: var(--bg);
    padding: 20px;
    border-radius: 6px;
    min-width: 320px;
}

/* ── Line items table ────────────────────────────────────────────────────── */
#lineItemsTable { border-collapse: collapse; }
#lineItemsTable thead th {
    font-size: 11px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.04em; padding: 5px 6px;
    color: var(--text-2); background: var(--bg);
}
#lineItemsTable tbody tr { border-bottom: 1px solid var(--border); }
#lineItemsTable tbody td { padding: 2px 3px; vertical-align: middle; }
#lineItemsTable tbody td .form-control {
    padding: 3px 6px; height: 28px; font-size: 13px;
    border-color: transparent; background: transparent; border-radius: 2px;
}
#lineItemsTable tbody td .form-control:hover {
    border-color: var(--border); background: var(--card);
}
#lineItemsTable tbody td .form-control:focus {
    border-color: var(--blue); background: var(--card); border-radius: 3px;
}

/* ── Save Draft hint ─────────────────────────────────────────────────────── */
#saveHint {
    font-size: 12px;
    color: var(--red, #ef4444);
    margin: 6px 0 0;
    min-height: 18px;
}
```

- [ ] **Step 2: Commit**

```bash
git add app/static/purchase_bills_form.css
git commit -m "feat: add purchase_bills_form.css with bill-specific styles and missing CSS states"
```

---

## Task 4: Update `form.html`

Wire in the three new static files, remove the `<style>` block, remove now-duplicated utility functions from the inline script, add `page-purchase-bill` class, add `id="submitBtn"` + `disabled` + `<p id="saveHint">` to the form actions.

**Files:**
- Modify: `app/purchase_bills/templates/purchase_bills/form.html`

- [ ] **Step 1: Add CSS links at the top of the template (after `choices.min.css` link)**

Find:
```html
<link rel="stylesheet" href="{{ url_for('static', filename='choices.min.css') }}">
```

Replace with:
```html
<link rel="stylesheet" href="{{ url_for('static', filename='choices.min.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='transactions.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='purchase_bills_form.css') }}">
```

- [ ] **Step 2: Add `page-purchase-bill` class to the outer card div**

Find:
```html
<div class="card">
    <div class="card-body">
```

Replace with:
```html
<div class="card page-purchase-bill">
    <div class="card-body">
```

- [ ] **Step 3: Load `transaction-utils.js` before the inline script**

Find:
```html
<script src="{{ url_for('static', filename='choices.min.js') }}"></script>
<script>
```

Replace with:
```html
<script src="{{ url_for('static', filename='choices.min.js') }}"></script>
<script src="{{ url_for('static', filename='transaction-utils.js') }}"></script>
<script>
```

- [ ] **Step 4: Remove the five utility functions now in `transaction-utils.js`**

Delete these blocks from the inline `<script>` (they are now provided by `transaction-utils.js`):

```js
const fmt = n => n.toLocaleString('en-PH', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtNum = n => n > 0
    ? n.toLocaleString('en-PH', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : '—';
const amtFmt = n => (n || 0).toLocaleString('en-PH', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function amtFocus(el) {
    const n = parseFloat(el.value.replace(/,/g, '')) || 0;
    el.value = n.toFixed(2);
    el.select();
}

function amtBlur(el, id) {
    const n = parseFloat(el.value.replace(/,/g, '')) || 0;
    el.value = amtFmt(n);
    updateLineItem(id, 'amount', n);
}
```

```js
// ── HTML escape helper ────────────────────────────────────────────────────────

function escHtml(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
```

- [ ] **Step 5: Add `id="submitBtn"` and `disabled` to the submit button, add `<p id="saveHint">`**

Find:
```html
                <div class="form-actions" style="margin-top: 32px;">
                    <button type="submit" class="btn btn-primary">
                        {{ 'Update Draft' if bill else 'Save Draft' }}
                    </button>
                    <a href="{{ url_for('purchase_bills.list_bills') }}" class="btn btn-secondary">Back</a>
                </div>
```

Replace with:
```html
                <div class="form-actions" style="margin-top: 32px;">
                    <button type="submit" id="submitBtn" class="btn btn-primary" disabled>
                        {{ 'Update Draft' if bill else 'Save Draft' }}
                    </button>
                    <a href="{{ url_for('purchase_bills.list_bills') }}" class="btn btn-secondary">Back</a>
                </div>
                <p id="saveHint"></p>
```

- [ ] **Step 6: Remove the `<style>` block**

Delete everything from `<style>` to `</style>` (approximately lines 764–978 in the current file). The entire block between these tags is now covered by `transactions.css` and `purchase_bills_form.css`.

- [ ] **Step 7: Verify the form still renders correctly**

Run: `python flask_app.py`

Navigate to `http://localhost:5000/purchase-bills/create`. Confirm:
- Form loads with no missing styles
- Vendor step card shows amber border
- Header fields are dimmed
- Save Draft button is disabled
- Selecting a vendor un-dims the header fields and shows the line items section

- [ ] **Step 8: Commit**

```bash
git add app/purchase_bills/templates/purchase_bills/form.html
git commit -m "refactor: wire external CSS/JS in bill form, remove inline style block"
```

---

## Task 5: Write Failing Playwright Smoke Tests

Set up Playwright, write the tests. They will fail until Task 6 implements `validateForm()`.

**Files:**
- Modify: `requirements.txt`
- Create: `tests/smoke/__init__.py`
- Create: `tests/smoke/conftest.py`
- Create: `tests/smoke/test_purchase_bill_form.py`

- [ ] **Step 1: Add `pytest-playwright` to `requirements.txt`**

Add after the `faker` line:
```
playwright==1.44.0
pytest-playwright==0.5.0
```

- [ ] **Step 2: Install and download browsers**

```bash
pip install playwright==1.44.0 pytest-playwright==0.5.0
playwright install chromium
```

Expected: Chromium browser downloaded to playwright cache.

- [ ] **Step 3: Create `tests/smoke/__init__.py`**

```python
```
(empty file)

- [ ] **Step 4: Create `tests/smoke/conftest.py`**

```python
import pytest
import threading
from app import create_app, db as _db
from app.users.models import User
from app.branches.models import Branch
from app.accounts.models import Account
from app.vendors.models import Vendor
from app.vat_categories.models import VATCategory


@pytest.fixture(scope="session")
def smoke_app():
    import os
    os.environ['SECRET_KEY'] = 'smoke-test-secret'
    app = create_app('testing')
    app.config['TESTING'] = False   # so login_required works normally
    app.config['WTF_CSRF_ENABLED'] = False
    with app.app_context():
        _db.create_all()
        _seed_smoke_data(app)
        yield app
        _db.drop_all()


def _seed_smoke_data(app):
    with app.app_context():
        branch = Branch(name='Main Branch', code='MAIN', is_active=True)
        _db.session.add(branch)
        _db.session.flush()

        user = User(username='smoke', email='smoke@test.com',
                    full_name='Smoke Tester', role='accountant', is_active=True)
        user.set_password('smoke123')
        _db.session.add(user)

        vat = VATCategory(code='VAT', name='VATable (12%)', rate=12.0, is_active=True)
        _db.session.add(vat)

        acct = Account(code='50101', name='Purchases', is_active=True)
        _db.session.add(acct)

        vendor = Vendor(
            name='Test Supplier', code='SUP001',
            default_vat_category='VAT', payment_terms='Net 30',
            is_active=True
        )
        _db.session.add(vendor)
        _db.session.commit()


@pytest.fixture(scope="session")
def live_url(smoke_app):
    """Start Flask dev server in a background thread, return its base URL."""
    import os, socket
    # pick a free port
    s = socket.socket(); s.bind(('', 0)); port = s.getsockname()[1]; s.close()
    server_thread = threading.Thread(
        target=lambda: smoke_app.run(port=port, use_reloader=False, threaded=True),
        daemon=True
    )
    server_thread.start()
    import time; time.sleep(1)   # let it start
    return f'http://localhost:{port}'


@pytest.fixture
def logged_in_page(page, live_url):
    """Return a Playwright page already logged in as the smoke accountant."""
    page.goto(f'{live_url}/login')
    page.click('#password')
    page.fill('#username', 'smoke')
    page.fill('#password', 'smoke123')
    page.click('button[type="submit"]')
    page.wait_for_url(f'{live_url}/**')
    return page, live_url
```

- [ ] **Step 5: Create `tests/smoke/test_purchase_bill_form.py`**

```python
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.smoke


def test_page_loads_with_disabled_submit(logged_in_page):
    page, base = logged_in_page
    page.goto(f'{base}/purchase-bills/create')
    expect(page.locator('#submitBtn')).to_be_disabled()
    expect(page.locator('#lineItemsSection')).to_be_hidden()


def test_submit_still_disabled_after_vendor_no_invoice(logged_in_page):
    page, base = logged_in_page
    page.goto(f'{base}/purchase-bills/create')
    page.select_option('#vendor_id', label='Test Supplier')
    page.wait_for_selector('#lineItemsSection', state='visible')
    # No vendor invoice number yet
    expect(page.locator('#submitBtn')).to_be_disabled()
    hint = page.locator('#saveHint')
    expect(hint).to_contain_text('vendor invoice number')


def test_submit_still_disabled_with_invoice_but_no_account(logged_in_page):
    page, base = logged_in_page
    page.goto(f'{base}/purchase-bills/create')
    page.select_option('#vendor_id', label='Test Supplier')
    page.wait_for_selector('#lineItemsSection', state='visible')
    page.fill('#vendor_invoice_number', 'INV-001')
    expect(page.locator('#submitBtn')).to_be_disabled()
    hint = page.locator('#saveHint')
    expect(hint).to_contain_text('account title')


def test_submit_enabled_when_all_required_fields_present(logged_in_page):
    page, base = logged_in_page
    page.goto(f'{base}/purchase-bills/create')
    page.select_option('#vendor_id', label='Test Supplier')
    page.wait_for_selector('#lineItemsSection', state='visible')

    page.fill('#vendor_invoice_number', 'INV-001')

    # Set amount on first line
    amount_input = page.locator('#lineItemsBody tr:first-child td:nth-child(2) input')
    amount_input.click()
    amount_input.fill('1000.00')
    amount_input.dispatch_event('blur')

    # Select account on first line (choose the first non-disabled option)
    acct_select = page.locator('#lineItemsBody tr:first-child .acct-select')
    acct_select.select_option(index=1)   # first real (non-placeholder) option
    # Trigger Choices.js change
    page.evaluate("document.querySelector('.acct-select').dispatchEvent(new Event('change'))")

    expect(page.locator('#submitBtn')).to_be_enabled()
```

- [ ] **Step 6: Run the tests — confirm they fail (expected)**

```bash
pytest tests/smoke/ -v --no-cov
```

Expected output: `FAILED` on `test_submit_still_disabled_after_vendor_no_invoice` and the account/enabled tests because `validateForm()` does not exist yet. `test_page_loads_with_disabled_submit` may pass since the button already has `disabled` in the HTML from Task 4.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt tests/smoke/
git commit -m "test: add Playwright smoke tests for purchase bill form validation gating"
```

---

## Task 6: Implement `validateForm()`

Wire the validation logic that makes the smoke tests pass.

**Files:**
- Modify: `app/purchase_bills/templates/purchase_bills/form.html`

- [ ] **Step 1: Add `validateForm()` to the inline script**

Add this function after `calculateTotals()` (before the VAT override section):

```js
// ── Form validation gate ──────────────────────────────────────────────────────

function validateForm() {
    const btn = document.getElementById('submitBtn');
    const hint = document.getElementById('saveHint');

    function block(msg) { btn.disabled = true; hint.textContent = msg; }
    function allow()     { btn.disabled = false; hint.textContent = ''; }

    // Vendor Invoice #
    const inv = document.getElementById('vendor_invoice_number');
    if (!inv || !inv.value.trim()) { block('Enter the vendor invoice number.'); return; }

    // At least one line
    if (lineItems.length === 0) { block('Add at least one line item.'); return; }

    // Per-line checks
    for (let i = 0; i < lineItems.length; i++) {
        const item = lineItems[i];
        const n = i + 1;
        if (!item.account_id)              { block(`Line ${n}: select an account title.`); return; }
        if (!item.amount || item.amount <= 0) { block(`Line ${n}: enter an amount greater than zero.`); return; }
        if (lineItems.length > 1 && !(item.description || '').trim()) {
            block(`Line ${n}: enter a description.`); return;
        }
    }

    allow();
}
```

- [ ] **Step 2: Call `validateForm()` at the end of `calculateTotals()`**

Find the last line of `calculateTotals()`:
```js
    renderJEPreview(subtotal, vatUsed, wtUsed);
}
```

Replace with:
```js
    renderJEPreview(subtotal, vatUsed, wtUsed);
    validateForm();
}
```

- [ ] **Step 3: Call `validateForm()` whenever the vendor invoice number changes**

Add this event listener near the bottom of the script, just before the `{% if bill %}` init block:

```js
// ── Vendor invoice # triggers validation ─────────────────────────────────────
const _invInput = document.getElementById('vendor_invoice_number');
if (_invInput) _invInput.addEventListener('input', validateForm);
```

- [ ] **Step 4: Call `validateForm()` on initial load for edit mode**

Inside `initOverrides()`, the last line is `calculateTotals();` — which already calls `validateForm()`. No extra change needed for edit mode.

For create mode (no vendor yet), `validateForm()` is not called until the first `calculateTotals()` — which is triggered by `addFirstLineItem()` → `addLineItem()` → `calculateTotals()`. The button is already `disabled` in the HTML so it shows the correct state before vendor selection.

- [ ] **Step 5: Run the smoke tests — confirm they pass**

```bash
pytest tests/smoke/ -v --no-cov
```

Expected: all 4 tests `PASSED`.

- [ ] **Step 6: Commit**

```bash
git add app/purchase_bills/templates/purchase_bills/form.html
git commit -m "feat: add validateForm() to gate Save Draft on minimum required data"
git push
```
