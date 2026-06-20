# Inline "Add Customer" Quick-Add Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the customer picker on the Sales Invoice and Cash Receipt forms an inline "Add Customer" quick-add modal that creates a customer via AJAX and auto-selects it, mirroring the existing vendor quick-add on the AP/CD forms.

**Architecture:** Faithful mirror of the vendor quick-add. The same `customers.create` view serves both HTML and JSON (detected via `_wants_json()`). A new modal partial + `customer-quick-add.js` (`initCustomerQuickAdd`) reuse the shared `initSearchSelect` so the picker matches the vendor field. The SI and CRV views build a `customer_quick_add_form` for the modal; both forms include the modal + scripts and route their customer `<select>` through `initCustomerQuickAdd`.

**Tech Stack:** Flask, WTForms, SQLAlchemy, Choices.js (bundled), Playwright (e2e), pytest.

## Global Constraints

- **No JS popups** — the modal is HTML with `{{ csrf_token() }}` (never `confirm/alert/prompt`).
- **Design tokens only** — modal reuses existing `customer-form.css` / `style.css` tokens; no hardcoded hex.
- **Master-data button verb** — the modal submit button reads **"Create Customer"** (not "Save").
- **Audit in CRUD tests** — any create test asserts an `AuditLog` row (module='customer', action='create').
- **TDD** — failing test first, watched fail, minimal code, watched pass, commit.
- **Cache-busters** — every new `app/static/*` `<script>`/`<link>` carries `?v=1`; bump on later edits.
- **PowerShell commits** — NEVER put ASCII double-quotes in a here-string commit body (paraphrase).
- **PH time** — unchanged; the create view already uses `ph_now` defaults.
- **No model changes** — this feature touches no `models.py`.

## File Structure

- `app/customers/views.py` — MODIFY: add `_wants_json()`, `staff_or_above_required`, `build_customer_quick_add_form()`; JSON branches + decorator swap on `create()`.
- `app/customers/templates/customers/_quick_add_modal.html` — CREATE: the modal partial.
- `app/static/customer-quick-add.js` — CREATE: `initCustomerQuickAdd({selectEl})`.
- `app/sales_invoices/views.py` — MODIFY: pass `customer_quick_add_form` to the 6 form renders.
- `app/sales_invoices/templates/sales_invoices/form.html` — MODIFY: assets + modal include + picker wiring + guard.
- `app/cash_receipts/views.py` — MODIFY: add `customer_quick_add_form` to `_form_context()`.
- `app/cash_receipts/templates/cash_receipts/form.html` — MODIFY: assets + modal include + picker wiring + `onCustomerChange` guard.
- `tests/integration/test_customers.py` — MODIFY: JSON-branch + staff-access tests.
- `tests/e2e/test_si_smoke.py` — MODIFY: SI quick-add e2e.
- `tests/e2e/test_crv_smoke.py` — CREATE: CRV quick-add e2e.

**Note (verified):** no existing test asserts staff is *blocked* from `customers.create`, so the staff+ loosening breaks nothing.

---

### Task 1: Backend — `customers.create` JSON branch, staff+ gate, quick-add form helper

**Files:**
- Modify: `app/customers/views.py`
- Test: `tests/integration/test_customers.py`

**Interfaces:**
- Produces: `build_customer_quick_add_form()` → a populated `CustomerForm` (choices set, `code` pre-generated, `is_active='1'`, `payment_terms='Net 30'`). Consumed by Tasks 2 & 3.
- Produces: `customers.create` returns `jsonify(ok=True, customer={'id': int, 'label': '<code> - <name>'})` (200) on AJAX success; `jsonify(ok=False, errors={field: msg}), 422` on duplicate/invalid.

- [ ] **Step 1: Write the failing tests**

Add to `tests/integration/test_customers.py`:

```python
def test_create_json_returns_customer_on_success(
        client, db_session, accountant_user, main_branch):
    """AJAX POST to customers.create returns ok=True + the new customer's id/label."""
    import json
    from app.customers.models import Customer
    from app.audit.models import AuditLog
    _login_accountant(client, accountant_user, main_branch)

    resp = client.post('/customers/create',
                       data={'code': 'C001', 'name': 'Quick Corp',
                             'payment_terms': 'Net 30', 'is_active': '1',
                             'default_vat_category': '', 'default_wt_code': ''},
                       headers={'X-Requested-With': 'XMLHttpRequest'})

    assert resp.status_code == 200
    body = json.loads(resp.data)
    assert body['ok'] is True
    cust = Customer.query.filter_by(code='C001').first()
    assert cust is not None
    assert body['customer']['id'] == cust.id
    assert body['customer']['label'] == 'C001 - Quick Corp'
    assert AuditLog.query.filter_by(module='customer', action='create',
                                    record_id=cust.id).count() == 1


def test_create_json_duplicate_code_returns_422(
        client, db_session, accountant_user, main_branch):
    """A duplicate code on the JSON path returns 422 with a code error (no HTML)."""
    import json
    from app.customers.models import Customer
    db_session.add(Customer(code='C001', name='Existing', payment_terms='Net 30',
                            is_active=True))
    db_session.commit()
    _login_accountant(client, accountant_user, main_branch)

    resp = client.post('/customers/create',
                       data={'code': 'C001', 'name': 'Dupe', 'payment_terms': 'Net 30',
                             'is_active': '1', 'default_vat_category': '',
                             'default_wt_code': ''},
                       headers={'X-Requested-With': 'XMLHttpRequest'})

    assert resp.status_code == 422
    body = json.loads(resp.data)
    assert body['ok'] is False
    assert 'code' in body['errors']


def test_create_json_invalid_returns_422(
        client, db_session, accountant_user, main_branch):
    """Missing required name on the JSON path returns 422 with a field error."""
    import json
    _login_accountant(client, accountant_user, main_branch)

    resp = client.post('/customers/create',
                       data={'code': 'C001', 'name': '', 'payment_terms': 'Net 30',
                             'is_active': '1', 'default_vat_category': '',
                             'default_wt_code': ''},
                       headers={'X-Requested-With': 'XMLHttpRequest'})

    assert resp.status_code == 422
    body = json.loads(resp.data)
    assert body['ok'] is False
    assert 'name' in body['errors']


def test_staff_can_create_customer(client, db_session, staff_user, main_branch):
    """Access change: staff (not just accountant/admin) may create a customer."""
    from app.customers.models import Customer
    staff_user.set_branches([main_branch])
    db_session.commit()
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/login', data={'username': 'staff', 'password': 'staff123'},
                follow_redirects=True)

    resp = client.post('/customers/create',
                       data={'code': 'C001', 'name': 'Staff Made Corp',
                             'payment_terms': 'Net 30', 'is_active': '1',
                             'default_vat_category': '', 'default_wt_code': ''},
                       follow_redirects=True)

    assert resp.status_code == 200
    assert Customer.query.filter_by(code='C001').first() is not None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/integration/test_customers.py -k "json or staff_can_create" -p no:cacheprovider -q`
Expected: the 3 JSON tests FAIL (HTML/redirect returned, not JSON; `json.loads` or status assert fails); `test_staff_can_create_customer` FAILS (staff redirected by the accountant/admin gate → customer not created).

- [ ] **Step 3: Add the helpers + JSON branch + decorator swap**

In `app/customers/views.py`, add `jsonify` to the flask import:

```python
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
```

Add after `accountant_or_admin_required` (keep `accountant_or_admin_required` for edit/delete):

```python
def staff_or_above_required(f):
    """Staff, accountant, and admin allowed (matches vendors; used by quick-add create)."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if current_user.role not in ['staff', 'accountant', 'admin']:
            flash('You do not have permission to perform this action.', 'error')
            return redirect(url_for('dashboard.home'))
        return f(*args, **kwargs)
    return decorated_function


def _wants_json():
    """True when the request is an AJAX/JSON call (modal quick-add)."""
    return (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.accept_mimetypes.best == 'application/json'
    )


def build_customer_quick_add_form():
    """A populated CustomerForm for the inline Add-Customer modal."""
    form = CustomerForm()
    populate_dropdown_choices(form)
    form.code.data = generate_next_customer_code()
    form.is_active.data = '1'
    form.payment_terms.data = 'Net 30'
    return form
```

> NOTE on the redirect target: `accountant_or_admin_required` in this module redirects to
> `dashboard.home`. Use `dashboard.home` here too (NOT `dashboard.index`, which is the vendor
> module's endpoint name) — copy the exact endpoint the existing customers decorator uses.

Change the `create` decorator from `@accountant_or_admin_required` to `@staff_or_above_required`.

In `create()`, the duplicate-code branch (currently flashes + re-renders) becomes:

```python
        existing = Customer.query.filter_by(code=form.code.data).first()
        if existing:
            if _wants_json():
                return jsonify(ok=False,
                               errors={'code': f'Customer code "{form.code.data}" already exists.'}), 422
            flash(f'Customer code "{form.code.data}" already exists.', 'error')
            return render_template('customers/form.html', form=form, customer=None)
```

In the success branch, after `flash(... created successfully!)` and BEFORE the redirect:

```python
            if _wants_json():
                return jsonify(ok=True, customer={
                    'id': customer.id,
                    'label': f'{customer.code} - {customer.name}',
                })
            flash(f'Customer "{customer.name}" created successfully!', 'success')
            return redirect(url_for('customers.list_customers'))
```

After the `if form.validate_on_submit():` block (before the `if request.method == 'GET':` block), add the invalid-JSON branch:

```python
    if request.method == 'POST' and _wants_json():
        return jsonify(ok=False,
                       errors={f: errs[0] for f, errs in form.errors.items()}), 422
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/integration/test_customers.py -p no:cacheprovider -q`
Expected: PASS (all customer tests, including the 4 new ones).

- [ ] **Step 5: Commit**

```
git add app/customers/views.py tests/integration/test_customers.py
git commit (here-string body, no double-quotes):
feat(customers): JSON quick-add branch + staff-create on customers.create

Add _wants_json detection so customers.create returns ok/customer JSON (200) or
422 errors for AJAX, alongside the existing HTML flow. Loosen create to staff+
(matches vendors) and add build_customer_quick_add_form() for the inline modal.
Edit/delete keep their accountant/admin gates.
```

---

### Task 2: Sales Invoice quick-add (modal + JS + wiring + e2e)

**Files:**
- Create: `app/customers/templates/customers/_quick_add_modal.html`
- Create: `app/static/customer-quick-add.js`
- Modify: `app/sales_invoices/views.py` (6 render calls)
- Modify: `app/sales_invoices/templates/sales_invoices/form.html`
- Test: `tests/e2e/test_si_smoke.py`

**Interfaces:**
- Consumes: `build_customer_quick_add_form()` (Task 1); `initSearchSelect` (search-select.js);
  `initCustomerVatSelect` / `initCustomerWtSelect` (customer-form-widgets.js).
- Produces: global `initCustomerQuickAdd({selectEl})`; reusable modal `#customerQuickAddOverlay`
  (consumed again by Task 3).

- [ ] **Step 1: Write the failing e2e test**

Add to `tests/e2e/test_si_smoke.py`:

```python
def test_add_customer_modal_creates_and_selects(logged_in_page, e2e_server):
    """The inline Add Customer modal creates a customer, auto-selects it, and reveals
    the line items (mirrors AP's quick-add)."""
    page = logged_in_page
    page.goto(e2e_server + SI_CREATE)
    page.wait_for_selector('#customer_id', state='attached')

    # Open the picker and click the add-customer action.
    _pick_in_choices(page, CUSTOMER_SCOPE, 'Add Customer')
    overlay = page.locator('#customerQuickAddOverlay')
    overlay.wait_for(state='visible')

    new_name = 'E2E Quick Customer LLC'
    overlay.locator('input[name="name"]').fill(new_name)
    page.click('#customerQuickAddSubmit')

    # Modal closes; the new customer becomes the selected chip; section revealed.
    overlay.wait_for(state='hidden')
    page.wait_for_function(
        """(name) => {
            const chip = document.querySelector('.choices:has(#customer_id) .choices__list--single .choices__item');
            return chip && chip.textContent.includes(name);
        }""",
        arg=new_name, timeout=10000,
    )
    page.wait_for_selector('#lineItemsSection', state='visible')
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest -m e2e tests/e2e/test_si_smoke.py::test_add_customer_modal_creates_and_selects -p no:cacheprovider -q -o addopts=""`
Expected: FAIL — `_pick_in_choices` can't find an "Add Customer" item (no add-action), or `#customerQuickAddOverlay` never appears (timeout).

- [ ] **Step 3: Create the modal partial**

Create `app/customers/templates/customers/_quick_add_modal.html`:

```html
{# Inline "Add Customer" modal. Requires `customer_quick_add_form` in the template
   context. Styling: design tokens only (.customer-form-scope from customer-form.css). #}
<div id="customerQuickAddOverlay"
     style="display:none; position:fixed; inset:0; background:var(--backdrop);
            z-index:1200; align-items:flex-start; justify-content:center; overflow:auto; padding:32px 16px;">
  <div style="background:var(--card); border-radius:8px; padding:24px; max-width:880px; width:100%;
              box-shadow:var(--shadow-md);">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
      <h3 style="margin:0; font-size:18px;">Add Customer</h3>
      <button type="button" id="customerQuickAddClose"
              style="background:none; border:none; font-size:22px; cursor:pointer; color:var(--text);"
              aria-label="Close">&times;</button>
    </div>

    <div id="customerQuickAddError" class="form-error" style="display:none; margin-bottom:12px; color:var(--alert-error-text);"></div>

    <form id="customerQuickAddForm" method="POST" action="{{ url_for('customers.create') }}" novalidate>
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <div class="customer-form-scope">
        {% with form = customer_quick_add_form, customer = None %}
          {% include "customers/_form_fields.html" %}
        {% endwith %}
      </div>
      <div style="display:flex; gap:12px; justify-content:flex-end; margin-top:20px;">
        <button type="button" id="customerQuickAddCancel" class="btn btn-secondary">Cancel</button>
        <button type="submit" id="customerQuickAddSubmit" class="btn btn-primary">Create Customer</button>
      </div>
    </form>
  </div>
</div>
```

- [ ] **Step 4: Create `app/static/customer-quick-add.js`**

```javascript
/* Inline "+ Add Customer" wiring for transaction customer pickers.
   Call initCustomerQuickAdd({ selectEl }) once per page.
   Requires search-select.js (initSearchSelect) and Choices to be loaded, plus
   the #customerQuickAddOverlay modal partial to be present on the page. */

function initCustomerQuickAdd(opts) {
    const selectEl = opts && opts.selectEl;
    const overlay = document.getElementById('customerQuickAddOverlay');
    if (!selectEl || !overlay || typeof initSearchSelect !== 'function') return null;

    const form = document.getElementById('customerQuickAddForm');
    const errorBox = document.getElementById('customerQuickAddError');
    const submitBtn = document.getElementById('customerQuickAddSubmit');
    let vatChoices = null;
    let wtChoices = null;

    function openModal() {
        errorBox.style.display = 'none';
        errorBox.textContent = '';
        overlay.style.display = 'flex';
        if (!vatChoices && typeof initCustomerVatSelect === 'function') {
            vatChoices = initCustomerVatSelect(overlay);
        }
        if (!wtChoices && typeof initCustomerWtSelect === 'function') {
            wtChoices = initCustomerWtSelect(overlay);
        }
    }

    function closeModal() {
        overlay.style.display = 'none';
    }

    const choices = initSearchSelect(selectEl, {
        choicesOptions: { searchResultLimit: 50 },
        addAction: { value: '__add_customer__', label: '➕ Add Customer…', onSelect: openModal },
    });

    document.getElementById('customerQuickAddClose').addEventListener('click', closeModal);
    document.getElementById('customerQuickAddCancel').addEventListener('click', closeModal);
    overlay.addEventListener('click', function (e) {
        if (e.target === overlay) closeModal();
    });

    form.addEventListener('submit', function (e) {
        e.preventDefault();
        errorBox.style.display = 'none';
        submitBtn.disabled = true;

        fetch(form.action, {
            method: 'POST',
            body: new FormData(form),
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        })
            .then(r => r.json().then(body => ({ status: r.status, body })))
            .then(({ status, body }) => {
                if (status === 200 && body.ok) {
                    choices.setChoices(
                        [{ value: String(body.customer.id), label: body.customer.label }],
                        'value', 'label', false
                    );
                    choices.setChoiceByValue(String(body.customer.id));
                    selectEl.dispatchEvent(new Event('change', { bubbles: true }));
                    closeModal();
                    form.reset();
                    if (vatChoices) vatChoices.setChoiceByValue('');
                    if (wtChoices) wtChoices.setChoiceByValue('');
                } else {
                    const errs = body.errors || {};
                    const first = Object.values(errs)[0] || 'Could not create customer. Please check the fields.';
                    errorBox.textContent = first;
                    errorBox.style.display = '';
                }
            })
            .catch(() => {
                errorBox.textContent = 'Network error — customer was not created.';
                errorBox.style.display = '';
            })
            .finally(() => { submitBtn.disabled = false; });
    });

    return choices;
}
```

- [ ] **Step 5: Pass the quick-add form from the SI view**

In `app/sales_invoices/views.py`, add the import near the other customer imports:

```python
from app.customers.views import build_customer_quick_add_form
```

Add `customer_quick_add_form=build_customer_quick_add_form(),` as a kwarg to EACH of the 6
`render_template('sales_invoices/form.html', ...)` calls (lines ~614, 624, 689, 715, 729, 798).
Example (the create GET fall-through at ~689):

```python
    return render_template('sales_invoices/form.html', form=form, invoice=None,
                           vat_categories=_vat_categories_for_form(),
                           all_accounts=_get_all_accounts_for_select(),
                           line_items=[],
                           gl_accounts=_gl_accounts_dict(),
                           wht_codes=_wht_codes_for_form(),
                           customer_quick_add_form=build_customer_quick_add_form())
```

- [ ] **Step 6: Wire the SI form template**

In `app/sales_invoices/templates/sales_invoices/form.html`:

(a) After the existing CSS links (after `accounts_payable_form.css?v=1`, ~line 14) add:

```html
<link rel="stylesheet" href="{{ url_for('static', filename='customer-form.css') }}?v=1">
```

(b) Just before `</form>` closes is not needed; include the modal AFTER the closing `</div>` of
`.page-sales-invoice` card and BEFORE the scripts (anywhere in `{% block content %}` outside the form
is fine — match where AP includes it, before the script tags):

```html
{% include "customers/_quick_add_modal.html" %}
```

(c) In the script list (where `choices.min.js` and `transaction-utils.js` are loaded, ~line 329-330),
add BEFORE the inline `<script>` block:

```html
<script src="{{ url_for('static', filename='search-select.js') }}"></script>
<script src="{{ url_for('static', filename='customer-form-widgets.js') }}?v=1"></script>
<script src="{{ url_for('static', filename='customer-quick-add.js') }}?v=1"></script>
```

(d) Replace the customer Choices init block:

```javascript
const customerSel = document.getElementById('customer_id');
if (customerSel) {
    new Choices(customerSel, {
        searchEnabled: true,
        searchResultLimit: 100,
        allowHTML: false,
        itemSelectText: '',
        shouldSort: false,
        placeholder: true,
        placeholderValue: '-- Select Customer --',
    });
}
```

with:

```javascript
const customerSel = document.getElementById('customer_id');
if (customerSel) {
    initCustomerQuickAdd({ selectEl: customerSel });
}
```

(e) Add the `__add_customer__` guard to the customer-select handler — change:

```javascript
        if (!cid || cid === '0') return;
```

to:

```javascript
        if (!cid || cid === '0' || cid === '__add_customer__') return;
```

- [ ] **Step 7: Run the e2e + SI suites to verify green**

Run: `python -m pytest -m e2e tests/e2e/test_si_smoke.py -p no:cacheprovider -q -o addopts=""`
Expected: PASS (all 3 SI e2e tests, including the new quick-add).
Run: `python -m pytest tests/integration/test_sales_invoices.py tests/integration/test_sales_invoice_views.py -p no:cacheprovider -q`
Expected: PASS (no regression in SI server-side tests).

- [ ] **Step 8: Commit**

```
git add app/customers/templates/customers/_quick_add_modal.html app/static/customer-quick-add.js app/sales_invoices/views.py app/sales_invoices/templates/sales_invoices/form.html tests/e2e/test_si_smoke.py
git commit (no double-quotes):
feat(sales-invoices): inline Add Customer quick-add on the customer picker

New customer quick-add modal + customer-quick-add.js (initCustomerQuickAdd), routed
through the shared initSearchSelect so the picker matches the vendor field. The SI
form includes the modal + customer-form assets; the view supplies a customer quick-add
form in every render path. Covered by a Playwright e2e (open picker, Add Customer,
create, auto-select, line items revealed).
```

---

### Task 3: Cash Receipt quick-add (wiring + e2e)

**Files:**
- Modify: `app/cash_receipts/views.py` (`_form_context()`)
- Modify: `app/cash_receipts/templates/cash_receipts/form.html`
- Create: `tests/e2e/test_crv_smoke.py`

**Interfaces:**
- Consumes: `build_customer_quick_add_form()`, the `#customerQuickAddOverlay` modal + `initCustomerQuickAdd`
  (Tasks 1 & 2 — reused, no new modal/JS).

- [ ] **Step 1: Write the failing e2e test**

Create `tests/e2e/test_crv_smoke.py`:

```python
"""Playwright e2e smoke for the Cash Receipt create form customer quick-add."""
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.cash_receipts]

CRV_CREATE = '/cash-receipts/create'
CUSTOMER_SCOPE = '.choices:has(#customer_id)'


def _pick_in_choices(page, scope_selector, text):
    scope = page.locator(scope_selector)
    scope.locator('.choices__inner').click()
    scope.locator('.choices__list--dropdown .choices__item', has_text=text).first.click()


def test_add_customer_modal_creates_and_selects(logged_in_page, e2e_server):
    page = logged_in_page
    page.goto(e2e_server + CRV_CREATE)
    page.wait_for_selector('#customer_id', state='attached')

    _pick_in_choices(page, CUSTOMER_SCOPE, 'Add Customer')
    overlay = page.locator('#customerQuickAddOverlay')
    overlay.wait_for(state='visible')

    new_name = 'E2E CRV Customer LLC'
    overlay.locator('input[name="name"]').fill(new_name)
    page.click('#customerQuickAddSubmit')

    overlay.wait_for(state='hidden')
    page.wait_for_function(
        """(name) => {
            const chip = document.querySelector('.choices:has(#customer_id) .choices__list--single .choices__item');
            return chip && chip.textContent.includes(name);
        }""",
        arg=new_name, timeout=10000,
    )
```

> Confirm `cash_receipts` is a registered pytest marker (it is used by existing CRV tests). If the
> CRV create route requires a seeded cash account to render, the e2e server's `seed_minimal()` already
> seeds the COA — verify the form renders 200; if not, seed a cash account in `tests/e2e/_serve.py`.

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest -m e2e tests/e2e/test_crv_smoke.py -p no:cacheprovider -q -o addopts=""`
Expected: FAIL — no "Add Customer" item / `#customerQuickAddOverlay` absent on the CRV form.

- [ ] **Step 3: Supply the quick-add form from the CRV view**

In `app/cash_receipts/views.py`: add the import:

```python
from app.customers.views import build_customer_quick_add_form
```

Locate `def _form_context(` and add to the dict it returns:

```python
        'customer_quick_add_form': build_customer_quick_add_form(),
```

Confirm all 5 `render_template('cash_receipts/form.html', ...)` paths flow through `_form_context()`
(create GET uses `_form_context(all_accounts=...)`; edit/bounce use `**ctx` where `ctx = _form_context(...)`).
If any render path does NOT use it, pass `customer_quick_add_form=build_customer_quick_add_form()` there too.

- [ ] **Step 4: Wire the CRV form template**

In `app/cash_receipts/templates/cash_receipts/form.html`:

(a) Add the customer-form CSS link near the other stylesheet links:

```html
<link rel="stylesheet" href="{{ url_for('static', filename='customer-form.css') }}?v=1">
```

(b) Include the modal (before the script tags, outside the form):

```html
{% include "customers/_quick_add_modal.html" %}
```

(c) Add the scripts before the inline `<script>` that builds the customer Choices (near the existing
`choices.min.js` load):

```html
<script src="{{ url_for('static', filename='search-select.js') }}"></script>
<script src="{{ url_for('static', filename='customer-form-widgets.js') }}?v=1"></script>
<script src="{{ url_for('static', filename='customer-quick-add.js') }}?v=1"></script>
```

(d) Replace the plain customer Choices init:

```javascript
const customerSel = document.getElementById('customer_id');
new Choices(customerSel, {
    searchEnabled: true, itemSelectText: '', shouldSort: false, allowHTML: false,
});
customerSel.addEventListener('change', () => onCustomerChange(customerSel.value));
```

with:

```javascript
const customerSel = document.getElementById('customer_id');
initCustomerQuickAdd({ selectEl: customerSel });
customerSel.addEventListener('change', () => onCustomerChange(customerSel.value));
```

(e) Guard `onCustomerChange` against the sentinel — change:

```javascript
    if (!customerId) {
```

to:

```javascript
    if (!customerId || customerId === '__add_customer__') {
```

- [ ] **Step 5: Run the e2e + CRV suites to verify green**

Run: `python -m pytest -m e2e tests/e2e/test_crv_smoke.py tests/e2e/test_si_smoke.py -p no:cacheprovider -q -o addopts=""`
Expected: PASS (CRV + SI e2e).
Run: `python -m pytest tests/integration/test_crv_views.py tests/integration/test_crv_posting.py -p no:cacheprovider -q`
Expected: PASS (no CRV server-side regression).

- [ ] **Step 6: Commit**

```
git add app/cash_receipts/views.py app/cash_receipts/templates/cash_receipts/form.html tests/e2e/test_crv_smoke.py
git commit (no double-quotes):
feat(cash-receipts): inline Add Customer quick-add on the CRV customer picker

Reuse the customer quick-add modal + initCustomerQuickAdd on the Cash Receipt form;
_form_context supplies the quick-add form to all render paths; onCustomerChange skips
the __add_customer__ sentinel. Covered by a CRV Playwright e2e.
```

---

### Task 4: Regression-map wiring + full guard

**Files:**
- Modify: `.claude/regression-map.json`

- [ ] **Step 1: Map the CRV e2e suite**

Set `cash_receipts` (add the module entry if absent) `"e2e": "tests/e2e/test_crv_smoke.py"`. The
`sales_invoices` e2e already points to `test_si_smoke.py`. Validate JSON:

Run: `python -c "import json; json.load(open('.claude/regression-map.json'))"`
Expected: no error.

- [ ] **Step 2: Full regression gate**

Run: `python -m pytest -p no:cacheprovider -q` (default suite)
Then: `python -m pytest -m e2e -p no:cacheprovider -q -o addopts=""` (e2e suite)
Expected: both green; new e2e tests included; no regressions vs. the clean baseline.

- [ ] **Step 3: Commit**

```
git add .claude/regression-map.json
git commit (no double-quotes):
chore(guard): map cash_receipts e2e smoke for the customer quick-add
```

---

## Self-Review

**Spec coverage:**
- Backend JSON + staff gate + helper → Task 1. ✓
- Modal partial + customer-quick-add.js → Task 2. ✓
- SI wiring (views 6 paths + form assets/include/picker/guard) → Task 2. ✓
- CRV wiring (`_form_context` + form assets/include/picker/onCustomerChange guard) → Task 3. ✓
- CSS/assets per host form → Tasks 2 & 3 steps 6/4. ✓
- e2e (SI + CRV) + integration (JSON branch, staff access, audit) → Tasks 1/2/3. ✓
- Access-change ripple (no stale staff-blocked test) → verified; staff-create test added (Task 1). ✓
- Regression-map → Task 4. ✓

**Type/name consistency:** `build_customer_quick_add_form` (Task 1 → consumed Tasks 2/3);
`customer_quick_add_form` context key (Task 1 helper → modal include); JSON shape
`{ok, customer:{id,label}}` and `{ok:false, errors}` (Task 1 → consumed by customer-quick-add.js
Task 2); sentinel `__add_customer__` (Task 2 JS → guarded in SI handler Task 2 + CRV onCustomerChange
Task 3); `#customerQuickAddOverlay`/`#customerQuickAddForm`/`#customerQuickAddSubmit`/
`#customerQuickAddError`/`#customerQuickAddClose`/`#customerQuickAddCancel` IDs consistent between the
modal (Task 2) and customer-quick-add.js (Task 2). Consistent. ✓

**Placeholder scan:** no TBD/TODO; every code step shows the code. The two "confirm/verify" notes
(redirect endpoint name; CRV render-path coverage; e2e seed) are explicit verification steps with the
fallback action stated, not deferred work. ✓
