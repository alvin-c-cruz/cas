# "+ Add Vendor" Inline Modal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users create a vendor from a CSRF-protected modal opened via an "➕ Add Vendor…" option inside the vendor search-select on Accounts Payable and Cash Disbursement forms, without losing the in-progress transaction.

**Architecture:** Extend the existing `/vendors/create` view to answer AJAX requests with JSON (HTML path unchanged). Extract the vendor form fields into a shared Jinja partial reused by the full vendor page and a new modal partial. Two small static JS modules — one initializes the VAT search-select via the project-standard Choices.js (replacing the page's homegrown widget), the other wires the sentinel option, modal open/submit, and Choices injection of the new vendor. The AP and CD `form.html` templates include the modal and call the shared init.

**Tech Stack:** Flask, Flask-WTF, SQLAlchemy, Jinja2, Choices.js (bundled at `app/static/choices.min.js`), pytest.

**Design spec:** `docs/superpowers/specs/2026-06-16-add-vendor-inline-modal-design.md`

> **Note on a deliberate refactor:** The full vendor page (`vendors/form.html`) currently uses a ~130-line homegrown VAT search-select widget. To keep the field markup DRY between the full page and the modal, this plan replaces that widget with the project's standard Choices.js (per the `search-select-pattern` convention) and moves form styling into a scoped external stylesheet. Task 3 includes a regression test proving the full vendor create page still works.

---

## File Structure

**Create:**
- `app/static/vendor-form.css` — form layout/checkbox styles, scoped under `.vendor-form-scope`, shared by full page + modal.
- `app/vendors/templates/vendors/_form_fields.html` — the vendor field rows (no `<form>`, no action buttons). VAT field is a plain `<select>` enhanced by Choices.js.
- `app/static/vendor-form-widgets.js` — `initVendorVatSelect(root)`: idempotently turns the VAT `<select>` inside `root` into a Choices.js search-select.
- `app/vendors/templates/vendors/_quick_add_modal.html` — hidden overlay + `<form>` wrapping the partial + Cancel/Create buttons.
- `app/static/vendor-quick-add.js` — `initVendorQuickAdd(opts)`: sentinel option, modal open/close, AJAX submit, error render, Choices injection.
- `tests/integration/test_vendor_quick_add.py` — endpoint + regression tests.

**Modify:**
- `app/vendors/views.py` — `create()` becomes JSON-aware.
- `app/vendors/templates/vendors/form.html` — include partial, load Choices + new CSS/JS, drop homegrown widget JS/CSS.
- `app/accounts_payable/templates/accounts_payable/form.html` — include modal, load JS, add sentinel guard.
- `app/cash_disbursements/templates/cash_disbursements/form.html` — include modal, load JS, add sentinel guard.

---

## Task 1: JSON-aware vendor create endpoint

**Files:**
- Modify: `app/vendors/views.py:134-201` (the `create()` view)
- Test: `tests/integration/test_vendor_quick_add.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_vendor_quick_add.py`:

```python
"""Integration tests for the inline '+ Add Vendor' quick-add flow."""
import pytest
from decimal import Decimal

from app.vendors.models import Vendor
from app.vat_categories.models import VATCategory
from app.audit.models import AuditLog

pytestmark = [pytest.mark.vendors, pytest.mark.integration]

AJAX = {'X-Requested-With': 'XMLHttpRequest'}


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def make_vat_category(db_session, code='V12DG', name='Input Tax Domestic Goods', rate='12.00'):
    cat = VATCategory.query.filter_by(code=code).first()
    if not cat:
        cat = VATCategory(code=code, name=name, rate=Decimal(rate), is_active=True)
        db_session.add(cat)
        db_session.commit()
    return cat


class TestVendorQuickAddEndpoint:
    def test_ajax_create_returns_json_and_audits(self, client, db_session, admin_user, main_branch):
        login(client)
        make_vat_category(db_session)
        resp = client.post('/vendors/create', data={
            'code': 'QA001',
            'name': 'Quick Add Vendor',
            'check_payee_name': 'Quick Add Vendor',
            'payment_terms': 'Net 30',
            'default_vat_category': 'V12DG',
            'is_active': '1',
        }, headers=AJAX)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['ok'] is True
        vendor = Vendor.query.filter_by(code='QA001').first()
        assert vendor is not None
        assert body['vendor']['id'] == vendor.id
        assert body['vendor']['label'] == f'{vendor.code} - {vendor.name}'
        audit = AuditLog.query.filter_by(module='vendor', action='create',
                                         record_id=vendor.id).first()
        assert audit is not None

    def test_ajax_validation_error_returns_422(self, client, db_session, admin_user, main_branch):
        login(client)
        make_vat_category(db_session)
        resp = client.post('/vendors/create', data={
            'code': '',  # required -> validation error
            'name': '',
            'default_vat_category': 'V12DG',
            'is_active': '1',
        }, headers=AJAX)
        assert resp.status_code == 422
        body = resp.get_json()
        assert body['ok'] is False
        assert 'code' in body['errors']
        assert Vendor.query.filter_by(name='').first() is None

    def test_ajax_duplicate_code_returns_422(self, client, db_session, admin_user, main_branch):
        login(client)
        make_vat_category(db_session)
        existing = Vendor(code='DUP001', name='Existing', is_active=True, payment_terms='Net 30')
        db_session.add(existing)
        db_session.commit()
        resp = client.post('/vendors/create', data={
            'code': 'DUP001',
            'name': 'Another',
            'check_payee_name': 'Another',
            'payment_terms': 'Net 30',
            'default_vat_category': 'V12DG',
            'is_active': '1',
        }, headers=AJAX)
        assert resp.status_code == 422
        body = resp.get_json()
        assert body['ok'] is False
        assert 'code' in body['errors']

    def test_html_path_still_redirects(self, client, db_session, admin_user, main_branch):
        """Regression: non-AJAX create keeps redirecting to the vendor list."""
        login(client)
        make_vat_category(db_session)
        resp = client.post('/vendors/create', data={
            'code': 'HTML01',
            'name': 'Html Path Vendor',
            'check_payee_name': 'Html Path Vendor',
            'payment_terms': 'Net 30',
            'default_vat_category': 'V12DG',
            'is_active': '1',
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert '/vendors' in resp.headers['Location']

    def test_ajax_create_denied_for_viewer(self, client, db_session, viewer_user, main_branch):
        login(client, username='viewer', password='viewer123')
        make_vat_category(db_session)
        resp = client.post('/vendors/create', data={
            'code': 'VWX001', 'name': 'Nope', 'payment_terms': 'Net 30',
            'default_vat_category': 'V12DG', 'is_active': '1',
        }, headers=AJAX, follow_redirects=False)
        assert resp.status_code == 302  # bounced by staff_or_above_required
        assert Vendor.query.filter_by(code='VWX001').first() is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/integration/test_vendor_quick_add.py -v`
Expected: FAIL — AJAX requests currently fall through to `render_template`, so `resp.get_json()` returns `None` / status is 200 HTML, not 422 JSON.

- [ ] **Step 3: Add a JSON-negotiation helper and branch the view**

In `app/vendors/views.py`, add a module-level helper just after the imports block (after line 17, below `vendors_bp = Blueprint(...)`):

```python
def _wants_json():
    """True when the request is an AJAX/JSON call (modal quick-add)."""
    return (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.accept_mimetypes.best == 'application/json'
    )
```

`jsonify` and `request` are already imported at the top of the file.

- [ ] **Step 4: Return JSON on the duplicate-code branch**

In `create()`, replace the duplicate-code block (currently lines 144-147):

```python
        existing = Vendor.query.filter_by(code=form.code.data).first()
        if existing:
            flash(f'Vendor code "{form.code.data}" already exists.', 'error')
            return render_template('vendors/form.html', form=form, vendor=None)
```

with:

```python
        existing = Vendor.query.filter_by(code=form.code.data).first()
        if existing:
            if _wants_json():
                return jsonify(ok=False, errors={'code': f'Vendor code "{form.code.data}" already exists.'}), 422
            flash(f'Vendor code "{form.code.data}" already exists.', 'error')
            return render_template('vendors/form.html', form=form, vendor=None)
```

- [ ] **Step 5: Return JSON on the success branch**

In `create()`, immediately after the `flash(f'Vendor "{vendor.name}" created successfully!', 'success')` line (currently line 182) and before `return redirect(...)`, change the success return so it reads:

```python
            flash(f'Vendor "{vendor.name}" created successfully!', 'success')
            if _wants_json():
                return jsonify(ok=True, vendor={
                    'id': vendor.id,
                    'label': f'{vendor.code} - {vendor.name}',
                })
            return redirect(url_for('vendors.list_vendors'))
```

- [ ] **Step 6: Return JSON when WTForms validation fails**

`form.validate_on_submit()` is `False` on a POST with invalid fields, so the view currently falls through to the GET-defaults block and re-renders. Add an explicit AJAX branch. Immediately *after* the entire `if form.validate_on_submit():` block ends (i.e. just before the `# Set defaults for new vendor` comment, currently line 192), insert:

```python
    if request.method == 'POST' and _wants_json():
        return jsonify(ok=False, errors={f: errs[0] for f, errs in form.errors.items()}), 422
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `pytest tests/integration/test_vendor_quick_add.py -v`
Expected: PASS (all 5 tests).

- [ ] **Step 8: Commit**

```bash
git add app/vendors/views.py tests/integration/test_vendor_quick_add.py
git commit -m "feat(vendors): JSON-aware create endpoint for quick-add modal"
```

---

## Task 2: Shared scoped form stylesheet

**Files:**
- Create: `app/static/vendor-form.css`

This extracts the reusable form-layout/checkbox CSS from `vendors/form.html`'s inline `<style>` (lines 181-462), scoped under `.vendor-form-scope` so it does not collide with AP/CD page styles. Button, `.vendor-form-container`, and homegrown `.search-select-*` styles are intentionally omitted (buttons live outside the partial; the search-select is replaced by Choices.js).

- [ ] **Step 1: Create the stylesheet**

Create `app/static/vendor-form.css`:

```css
/* Shared vendor form-field styling. Scoped under .vendor-form-scope so it
   is safe to load on the AP / CD transaction pages (modal) without leaking. */
.vendor-form-scope { display: flex; flex-direction: column; gap: 12px; }

.vendor-form-scope .form-row-3col {
    display: grid;
    grid-template-columns: 150px 1fr 1fr;
    gap: 12px;
}
.vendor-form-scope .form-row-2col {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
}
.vendor-form-scope .form-group { margin-bottom: 0; }
.vendor-form-scope .form-group label {
    display: block;
    font-size: 16px;
    font-weight: 500;
    color: var(--text-1);
    margin-bottom: 3px;
}
.vendor-form-scope .section-label {
    display: block;
    font-size: 16px;
    font-weight: 600;
    color: var(--text-1);
    margin-bottom: 9px;
}
.vendor-form-scope .form-control-sm {
    width: 100%;
    padding: 6px 9px;
    font-size: 16px;
    line-height: 1.4;
    border: 1px solid var(--border);
    border-radius: 5px;
    transition: border-color 0.15s ease-in-out;
}
.vendor-form-scope .form-control-sm:focus {
    outline: none;
    border-color: var(--primary);
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}
.vendor-form-scope textarea.form-control-sm { resize: vertical; min-height: 60px; }

.vendor-form-scope .wt-checkbox-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    padding: 15px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
}
.vendor-form-scope .wt-checkbox-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 6px;
    background: var(--card);
    border-radius: 5px;
}
.vendor-form-scope .wt-checkbox-item .form-checkbox {
    width: 24px; height: 24px; margin: 0; cursor: pointer; flex-shrink: 0;
}
.vendor-form-scope .wt-checkbox-item label {
    flex: 1; font-size: 16px; color: var(--text-1); cursor: pointer; margin: 0;
    display: flex; flex-direction: column; gap: 3px; line-height: 1.3;
}
.vendor-form-scope .wt-checkbox-item label > span:first-child {
    display: flex; align-items: center; gap: 6px;
}
.vendor-form-scope .wt-badge {
    display: inline-block; padding: 3px 9px;
    background: var(--primary); color: #fff;
    font-size: 13px; font-weight: 600; border-radius: 3px; line-height: 1.2;
}
.vendor-form-scope .wt-description {
    font-size: 13px; color: var(--text-2); font-weight: 400; line-height: 1.2;
}
.vendor-form-scope .error-message { color: var(--alert-error-text); font-size: 15px; margin-top: 3px; }
.vendor-form-scope .field-locked {
    background: var(--surface) !important; cursor: not-allowed !important;
    color: var(--text-2); pointer-events: none;
}

@media (max-width: 768px) {
    .vendor-form-scope .form-row-3col,
    .vendor-form-scope .form-row-2col { grid-template-columns: 1fr; }
    .vendor-form-scope .wt-checkbox-grid { grid-template-columns: 1fr; }
}
```

- [ ] **Step 2: Commit**

```bash
git add app/static/vendor-form.css
git commit -m "feat(vendors): add scoped shared vendor-form stylesheet"
```

---

## Task 3: Extract field partial + Choices.js VAT widget; refactor full vendor page

**Files:**
- Create: `app/vendors/templates/vendors/_form_fields.html`
- Create: `app/static/vendor-form-widgets.js`
- Modify: `app/vendors/templates/vendors/form.html`
- Test: `tests/integration/test_vendor_quick_add.py` (add a render regression test)

- [ ] **Step 1: Write the failing regression test**

Append to `tests/integration/test_vendor_quick_add.py`:

```python
class TestFullVendorPageRegression:
    def test_full_create_page_renders_with_choices_vat(self, client, db_session,
                                                        admin_user, main_branch):
        login(client)
        make_vat_category(db_session)
        resp = client.get('/vendors/create')
        assert resp.status_code == 200
        # Field partial is in use
        assert b'vendor-form-scope' in resp.data
        # VAT is now a Choices.js select, not the homegrown widget
        assert b'vat-search-input' not in resp.data
        assert b'choices.min.js' in resp.data
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/integration/test_vendor_quick_add.py::TestFullVendorPageRegression -v`
Expected: FAIL — page still contains `vat-search-input` and lacks `vendor-form-scope`.

- [ ] **Step 3: Create the field partial**

Create `app/vendors/templates/vendors/_form_fields.html` (the field rows only — no `<form>`, no submit buttons; consumer supplies those):

```jinja
{# Vendor form fields. Wrap the include in:
   <div class="vendor-form-scope"> ... </div>
   Requires `form` and (optionally) `withholding_taxes`, `vendor`, `selected_wt_ids`. #}

<div class="form-row-3col">
    <div class="form-group">
        <label for="{{ form.code.id }}">{{ form.code.label.text }}</label>
        {{ form.code(
            class="form-control form-control-sm" + (" field-locked" if vendor else ""),
            autocomplete="new-password",
            readonly=(vendor is not none),
            **{'data-lpignore': 'true'}
        ) }}
        {% if form.code.errors %}<div class="error-message">{{ form.code.errors[0] }}</div>{% endif %}
    </div>
    <div class="form-group">
        <label for="{{ form.name.id }}">{{ form.name.label.text }}</label>
        {{ form.name(class="form-control form-control-sm", autocomplete="new-password", **{'data-lpignore': 'true', 'data-form-type': 'other'}) }}
        {% if form.name.errors %}<div class="error-message">{{ form.name.errors[0] }}</div>{% endif %}
    </div>
    <div class="form-group">
        <label for="{{ form.check_payee_name.id }}">{{ form.check_payee_name.label.text }}</label>
        {{ form.check_payee_name(class="form-control form-control-sm", autocomplete="new-password", **{'data-lpignore': 'true'}) }}
        {% if form.check_payee_name.errors %}<div class="error-message">{{ form.check_payee_name.errors[0] }}</div>{% endif %}
    </div>
</div>

<div class="form-row-2col">
    <div class="form-group">
        <label for="{{ form.contact_person.id }}">{{ form.contact_person.label.text }}</label>
        {{ form.contact_person(class="form-control form-control-sm", autocomplete="new-password", **{'data-lpignore': 'true'}) }}
        {% if form.contact_person.errors %}<div class="error-message">{{ form.contact_person.errors[0] }}</div>{% endif %}
    </div>
    <div class="form-group">
        <label for="{{ form.phone.id }}">{{ form.phone.label.text }}</label>
        {{ form.phone(class="form-control form-control-sm", autocomplete="new-password", **{'data-lpignore': 'true'}) }}
        {% if form.phone.errors %}<div class="error-message">{{ form.phone.errors[0] }}</div>{% endif %}
    </div>
</div>

<div class="form-row-2col">
    <div class="form-group">
        <label for="{{ form.email.id }}">{{ form.email.label.text }}</label>
        {{ form.email(class="form-control form-control-sm", type="email", autocomplete="off", **{'data-lpignore': 'true'}) }}
        {% if form.email.errors %}<div class="error-message">{{ form.email.errors[0] }}</div>{% endif %}
    </div>
    <div class="form-group">
        <label for="{{ form.tin.id }}">{{ form.tin.label.text }}</label>
        {{ form.tin(class="form-control form-control-sm", autocomplete="new-password", **{'data-lpignore': 'true'}) }}
        {% if form.tin.errors %}<div class="error-message">{{ form.tin.errors[0] }}</div>{% endif %}
    </div>
</div>

<div class="form-row-2col">
    <div class="form-group">
        <label for="{{ form.address.id }}">{{ form.address.label.text }}</label>
        {{ form.address(class="form-control form-control-sm", rows="2", autocomplete="new-password", **{'data-lpignore': 'true'}) }}
        {% if form.address.errors %}<div class="error-message">{{ form.address.errors[0] }}</div>{% endif %}
    </div>
    <div class="form-group">
        <label for="{{ form.postal_code.id }}">{{ form.postal_code.label.text }}</label>
        {{ form.postal_code(class="form-control form-control-sm", autocomplete="new-password", **{'data-lpignore': 'true'}) }}
        {% if form.postal_code.errors %}<div class="error-message">{{ form.postal_code.errors[0] }}</div>{% endif %}
    </div>
</div>

<div class="form-row-3col">
    <div class="form-group">
        <label for="{{ form.payment_terms.id }}">{{ form.payment_terms.label.text }}</label>
        {{ form.payment_terms(class="form-control form-control-sm vendor-payment-terms", autocomplete="new-password", **{'data-lpignore': 'true'}) }}
        {% if form.payment_terms.errors %}<div class="error-message">{{ form.payment_terms.errors[0] }}</div>{% endif %}
    </div>
    <div class="form-group">
        <label for="{{ form.default_vat_category.id }}">{{ form.default_vat_category.label.text }}</label>
        {{ form.default_vat_category(class="form-control form-control-sm vendor-vat-select", **{'data-lpignore': 'true'}) }}
        {% if form.default_vat_category.errors %}<div class="error-message">{{ form.default_vat_category.errors[0] }}</div>{% endif %}
    </div>
    <div class="form-group">
        <label for="{{ form.is_active.id }}">{{ form.is_active.label.text }}</label>
        {{ form.is_active(class="form-control form-control-sm", autocomplete="new-password", **{'data-lpignore': 'true'}) }}
        {% if form.is_active.errors %}<div class="error-message">{{ form.is_active.errors[0] }}</div>{% endif %}
    </div>
</div>

<div class="form-group">
    <label class="section-label">Default Withholding Tax</label>
    <div class="wt-checkbox-grid">
        {% if withholding_taxes %}
            {% for wt in withholding_taxes %}
            <div class="wt-checkbox-item">
                <input type="checkbox" class="form-checkbox" id="wt_{{ wt.id }}"
                       name="withholding_tax_ids" value="{{ wt.id }}"
                       {% if vendor and selected_wt_ids and wt.id in selected_wt_ids %}checked{% endif %}>
                <label for="wt_{{ wt.id }}">
                    <span>{{ wt.code }} <span class="wt-badge">{{ wt.rate }}%</span></span>
                    <span class="wt-description">{{ wt.name }}</span>
                </label>
            </div>
            {% endfor %}
        {% else %}
            <div class="wt-checkbox-item">
                <span style="color: var(--text-2); font-style: italic;">No withholding taxes configured. Please set up withholding taxes in the maintenance module.</span>
            </div>
        {% endif %}
    </div>
</div>
```

- [ ] **Step 4: Create the VAT-widget JS**

Create `app/static/vendor-form-widgets.js`:

```javascript
/* Turns the vendor "Default VAT Category" <select> inside `root` into a
   Choices.js search-select. Idempotent: safe to call again on the same root
   (e.g. each time the quick-add modal opens). Requires Choices to be loaded. */
function initVendorVatSelect(root) {
    if (!root || typeof Choices === 'undefined') return null;
    const sel = root.querySelector('select.vendor-vat-select');
    if (!sel || sel.dataset.choicesReady === '1') return null;
    sel.dataset.choicesReady = '1';
    return new Choices(sel, {
        searchEnabled: true,
        itemSelectText: '',
        shouldSort: false,
        searchResultLimit: 50,
        allowHTML: false,
    });
}
```

- [ ] **Step 5: Refactor `vendors/form.html` to use the partial + Choices**

Replace the entire body of `app/vendors/templates/vendors/form.html`. The new file: includes the partial inside a `.vendor-form-scope` wrapper, keeps the page-specific `<form>`/buttons/anti-autofill inputs and the unsaved-changes tracking, loads `choices.min.css`/`choices.min.js` + `vendor-form.css` + `vendor-form-widgets.js`, and initializes the VAT select. Write the file as:

```jinja
{% extends "base.html" %}

{% block title %}{{ 'Edit Vendor' if vendor else 'Create Vendor' }}{% endblock %}
{% block page_title %}{{ 'Edit Vendor' if vendor else 'Create Vendor' }}{% endblock %}

{% block content %}
<link rel="stylesheet" href="{{ url_for('static', filename='choices.min.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='vendor-form.css') }}">

<div class="vendor-form-container">
    <form method="POST" novalidate autocomplete="off" data-track-changes="{{ 'true' if vendor else 'false' }}">
        {{ form.hidden_tag() }}

        <!-- Hidden dummy fields to prevent browser autocomplete -->
        <input type="text" name="prevent_autofill" style="position:absolute;top:-9999px;left:-9999px;" autocomplete="off" tabindex="-1" aria-hidden="true">
        <input type="password" name="prevent_password" style="position:absolute;top:-9999px;left:-9999px;" autocomplete="off" tabindex="-1" aria-hidden="true">

        <div class="vendor-form-scope">
            {% include "vendors/_form_fields.html" %}
        </div>

        <div class="form-actions">
            <button type="submit" class="btn btn-primary btn-sm">
                {{ 'Update Vendor' if vendor else 'Create Vendor' }}
            </button>
            <a href="{{ url_for('vendors.list_vendors') }}" class="btn btn-secondary btn-sm">Cancel</a>
        </div>
    </form>
</div>

<style>
/* Page-only chrome (container + buttons). Field styling lives in vendor-form.css. */
.vendor-form-container {
    max-width: 100%;
    padding: 18px;
    background: var(--card);
    border-radius: 6px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}
.form-actions {
    display: flex; gap: 12px; justify-content: flex-start;
    margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border);
}
.btn-sm { padding: 6px 18px; font-size: 16px; line-height: 1.4; border-radius: 5px; font-weight: 500; }
</style>

<script src="{{ url_for('static', filename='choices.min.js') }}"></script>
<script src="{{ url_for('static', filename='vendor-form-widgets.js') }}"></script>
<script>
document.addEventListener('DOMContentLoaded', function () {
    initVendorVatSelect(document);

    // Unsaved-change tracking for the dynamic WHT checkboxes (edit mode).
    const trackedForm = document.querySelector('form[data-track-changes="true"]');
    if (trackedForm) {
        trackedForm.querySelectorAll('input[name="withholding_tax_ids"]').forEach(cb => {
            cb.addEventListener('change', () => trackedForm.dispatchEvent(new Event('change', { bubbles: true })));
        });
    }
});
</script>
{% endblock %}
```

- [ ] **Step 6: Run the regression test + full vendor suite**

Run: `pytest tests/integration/test_vendor_quick_add.py tests/integration/test_vendor_views.py -v`
Expected: PASS — full page renders with `vendor-form-scope`, no `vat-search-input`, and existing vendor CRUD/audit tests still pass.

- [ ] **Step 7: Commit**

```bash
git add app/vendors/templates/vendors/_form_fields.html app/static/vendor-form-widgets.js app/vendors/templates/vendors/form.html tests/integration/test_vendor_quick_add.py
git commit -m "refactor(vendors): extract field partial, switch VAT picker to Choices.js"
```

---

## Task 4: Quick-add modal partial

**Files:**
- Create: `app/vendors/templates/vendors/_quick_add_modal.html`

This is included once on each transaction page. It needs `form` (a `VendorForm`) and `withholding_taxes` in context — Task 6 and Task 7 add those to the AP/CD view renders.

- [ ] **Step 1: Create the modal partial**

Create `app/vendors/templates/vendors/_quick_add_modal.html`:

```jinja
{# Inline "Add Vendor" modal. Requires `vendor_quick_add_form` and
   `vendor_quick_add_whts` in the template context. Styling: design tokens only. #}
<div id="vendorQuickAddOverlay"
     style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.5);
            z-index:1200; align-items:flex-start; justify-content:center; overflow:auto; padding:32px 16px;">
  <div style="background:var(--card); border-radius:8px; padding:24px; max-width:880px; width:100%;
              box-shadow:0 10px 30px rgba(0,0,0,0.25);">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
      <h3 style="margin:0; font-size:18px;">Add Vendor</h3>
      <button type="button" id="vendorQuickAddClose"
              style="background:none; border:none; font-size:22px; cursor:pointer; color:var(--text-1);"
              aria-label="Close">&times;</button>
    </div>

    <div id="vendorQuickAddError" class="form-error" style="display:none; margin-bottom:12px;"></div>

    <form id="vendorQuickAddForm" method="POST" action="{{ url_for('vendors.create') }}" novalidate>
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <div class="vendor-form-scope">
        {% with form = vendor_quick_add_form, withholding_taxes = vendor_quick_add_whts, vendor = None %}
          {% include "vendors/_form_fields.html" %}
        {% endwith %}
      </div>
      <div style="display:flex; gap:12px; justify-content:flex-end; margin-top:20px;">
        <button type="button" id="vendorQuickAddCancel" class="btn btn-secondary">Cancel</button>
        <button type="submit" id="vendorQuickAddSubmit" class="btn btn-primary">Create Vendor</button>
      </div>
    </form>
  </div>
</div>
```

- [ ] **Step 2: Commit**

```bash
git add app/vendors/templates/vendors/_quick_add_modal.html
git commit -m "feat(vendors): add inline quick-add modal partial"
```

---

## Task 5: Quick-add JS module

**Files:**
- Create: `app/static/vendor-quick-add.js`

- [ ] **Step 1: Create the JS module**

Create `app/static/vendor-quick-add.js`:

```javascript
/* Inline "+ Add Vendor" wiring. Call initVendorQuickAdd once per page.
   opts = { choices, selectEl }  where `choices` is the page's Choices instance
   for the vendor select and `selectEl` is that <select> element.
   Requires Choices to be loaded and #vendorQuickAddOverlay to be present. */
const VENDOR_ADD_SENTINEL = '__add_vendor__';

function initVendorQuickAdd(opts) {
    const { choices, selectEl } = opts;
    const overlay = document.getElementById('vendorQuickAddOverlay');
    if (!choices || !selectEl || !overlay) return;

    const form = document.getElementById('vendorQuickAddForm');
    const errorBox = document.getElementById('vendorQuickAddError');
    const submitBtn = document.getElementById('vendorQuickAddSubmit');

    // Pin the sentinel choice to the top of the dropdown.
    choices.setChoices(
        [{ value: VENDOR_ADD_SENTINEL, label: '➕ Add Vendor…' }],
        'value', 'label', false
    );

    // Remember the last real selection so opening/cancelling the modal restores it.
    let lastValue = selectEl.value && selectEl.value !== VENDOR_ADD_SENTINEL ? selectEl.value : '';

    function openModal() {
        errorBox.style.display = 'none';
        errorBox.textContent = '';
        overlay.style.display = 'flex';
        // Init the modal's VAT search-select (idempotent).
        if (typeof initVendorVatSelect === 'function') initVendorVatSelect(overlay);
    }

    function closeModal() {
        overlay.style.display = 'none';
    }

    selectEl.addEventListener('change', function () {
        if (selectEl.value === VENDOR_ADD_SENTINEL) {
            // Restore the previous real selection, then open the modal.
            choices.setChoiceByValue(lastValue || '');
            openModal();
        } else {
            lastValue = selectEl.value;
        }
    });

    document.getElementById('vendorQuickAddClose').addEventListener('click', closeModal);
    document.getElementById('vendorQuickAddCancel').addEventListener('click', closeModal);
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
                    // Add the new vendor and select it; this fires `change`, which
                    // runs the page's own vendor handler (defaults / open bills).
                    choices.setChoices(
                        [{ value: String(body.vendor.id), label: body.vendor.label }],
                        'value', 'label', false
                    );
                    lastValue = String(body.vendor.id);
                    choices.setChoiceByValue(String(body.vendor.id));
                    closeModal();
                    form.reset();
                } else {
                    const errs = body.errors || {};
                    const first = Object.values(errs)[0] || 'Could not create vendor. Please check the fields.';
                    errorBox.textContent = first;
                    errorBox.style.display = '';
                }
            })
            .catch(() => {
                errorBox.textContent = 'Network error — vendor was not created.';
                errorBox.style.display = '';
            })
            .finally(() => { submitBtn.disabled = false; });
    });
}
```

- [ ] **Step 2: Commit**

```bash
git add app/static/vendor-quick-add.js
git commit -m "feat(vendors): add quick-add modal JS wiring"
```

---

## Task 6: Wire Accounts Payable form

**Files:**
- Modify: `app/accounts_payable/views.py` (both `create()` ~line 445 and `edit()` ~line 625 renders)
- Modify: `app/accounts_payable/templates/accounts_payable/form.html`

- [ ] **Step 1: Pass a VendorForm + WHT list into the AP template**

In `app/accounts_payable/views.py`, add this import near the top (with the other `app.*` imports):

```python
from app.vendors.forms import VendorForm
from app.vendors.views import populate_vat_category_choices, generate_next_vendor_code
from app.withholding_tax.models import WithholdingTax
```

Then build the quick-add context once and pass it to **both** `render_template('accounts_payable/form.html', ...)` calls (in `create()` and `edit()`). Just before each `return render_template('accounts_payable/form.html', ...)`, add:

```python
        quick_add_form = VendorForm()
        populate_vat_category_choices(quick_add_form)
        quick_add_form.code.data = generate_next_vendor_code()
        quick_add_form.is_active.data = '1'
        quick_add_form.payment_terms.data = 'Net 30'
        quick_add_whts = WithholdingTax.query.filter_by(is_active=True).order_by(WithholdingTax.code).all()
```

and add `vendor_quick_add_form=quick_add_form, vendor_quick_add_whts=quick_add_whts` to the `render_template(...)` keyword args.

> If `WithholdingTax` / helpers are already imported in this file, do not duplicate the import.

- [ ] **Step 2: Add the sentinel guard to the AP vendor change handler**

In `app/accounts_payable/templates/accounts_payable/form.html`, in the vendor change handler (line 804-807), add a guard. Change:

```javascript
document.getElementById('vendor_id').addEventListener('change', function () {
    const vendorId = this.value;
    const vendorName = this.options[this.selectedIndex].text;
    if (!vendorId || vendorId == '0') return;
```

to:

```javascript
document.getElementById('vendor_id').addEventListener('change', function () {
    const vendorId = this.value;
    const vendorName = this.options[this.selectedIndex].text;
    if (!vendorId || vendorId == '0' || vendorId === '__add_vendor__') return;
```

- [ ] **Step 3: Capture the Choices instance and init quick-add**

In `app/accounts_payable/templates/accounts_payable/form.html`, the vendor Choices block (lines 865-871) currently discards the instance. Change:

```javascript
const vendorSel = document.getElementById('vendor_id');
if (vendorSel) {
    new Choices(vendorSel, {
        searchEnabled: true, itemSelectText: '', shouldSort: false,
        searchResultLimit: 50, allowHTML: false,
    });
}
```

to:

```javascript
const vendorSel = document.getElementById('vendor_id');
if (vendorSel) {
    const vendorChoices = new Choices(vendorSel, {
        searchEnabled: true, itemSelectText: '', shouldSort: false,
        searchResultLimit: 50, allowHTML: false,
    });
    initVendorQuickAdd({ choices: vendorChoices, selectEl: vendorSel });
}
```

- [ ] **Step 4: Include the modal + load the JS**

In `app/accounts_payable/templates/accounts_payable/form.html`, add the modal include just before the final `{% endblock %}` (after the existing `</script>` at line 921). Insert:

```jinja
{% include "vendors/_quick_add_modal.html" %}
<script src="{{ url_for('static', filename='vendor-form-widgets.js') }}"></script>
<script src="{{ url_for('static', filename='vendor-quick-add.js') }}"></script>
```

Place these **after** the existing `choices.min.js` script tag (line 307) is already loaded earlier in the file, so `Choices` and the page's `vendorChoices` exist. Because `initVendorQuickAdd` is called inside the main inline `<script>` (Step 3) which runs before these two `<script>` tags, move the modal include + the two `<script>` tags to just **before** the main inline script block (before line 309 `<script>` that defines the handlers is fine only if functions are defined first). To avoid ordering bugs, instead add the two `<script src>` tags immediately after line 308 (`transaction-utils.js`) and the `{% include %}` immediately before line 307's script group. Concretely:

- Insert `{% include "vendors/_quick_add_modal.html" %}` on its own line immediately **before** line 307 (`<script src="{{ url_for('static', filename='choices.min.js') }}"></script>`).
- Insert the two new `<script src>` lines immediately **after** line 308 (`transaction-utils.js`), so load order is: choices.min.js → transaction-utils.js → vendor-form-widgets.js → vendor-quick-add.js → main inline script.

- [ ] **Step 5: Manual smoke test**

Run the dev server: `python flask_app.py`
Visit `http://127.0.0.1:5000/accounts-payable/create`, open the vendor picker, choose "➕ Add Vendor…". Confirm: modal opens, the bill area is untouched, filling the form + Create adds and selects the vendor, and the line-item section unlocks with the vendor's defaults. Cancel restores any prior selection.

- [ ] **Step 6: Commit**

```bash
git add app/accounts_payable/views.py app/accounts_payable/templates/accounts_payable/form.html
git commit -m "feat(ap): inline + Add Vendor modal on AP create/edit"
```

---

## Task 7: Wire Cash Disbursement form

**Files:**
- Modify: `app/cash_disbursements/views.py` (both `create()` ~line 544 and `edit()` ~line 626 renders)
- Modify: `app/cash_disbursements/templates/cash_disbursements/form.html`

- [ ] **Step 1: Pass a VendorForm + WHT list into the CD template**

In `app/cash_disbursements/views.py`, add (if not already present) near the top imports:

```python
from app.vendors.forms import VendorForm
from app.vendors.views import populate_vat_category_choices, generate_next_vendor_code
from app.withholding_tax.models import WithholdingTax
```

Before **both** `return render_template('cash_disbursements/form.html', ...)` calls (in `create()` and `edit()`), add:

```python
        quick_add_form = VendorForm()
        populate_vat_category_choices(quick_add_form)
        quick_add_form.code.data = generate_next_vendor_code()
        quick_add_form.is_active.data = '1'
        quick_add_form.payment_terms.data = 'Net 30'
        quick_add_whts = WithholdingTax.query.filter_by(is_active=True).order_by(WithholdingTax.code).all()
```

and add `vendor_quick_add_form=quick_add_form, vendor_quick_add_whts=quick_add_whts` to each `render_template(...)`.

- [ ] **Step 2: Add the sentinel guard to `onVendorChange`**

In `app/cash_disbursements/templates/cash_disbursements/form.html`, at the top of `onVendorChange` (line 280), add a guard. Change:

```javascript
function onVendorChange(vendorId) {
    apLines = [];
```

to:

```javascript
function onVendorChange(vendorId) {
    if (vendorId === '__add_vendor__') return;
    apLines = [];
```

- [ ] **Step 3: Init quick-add against the existing `vendorChoices`**

In `app/cash_disbursements/templates/cash_disbursements/form.html`, the vendor Choices instance is already stored as `vendorChoices` (lines 256-260). Immediately after line 260 (`vendorSel.addEventListener('change', ...)`), add:

```javascript
initVendorQuickAdd({ choices: vendorChoices, selectEl: vendorSel });
```

- [ ] **Step 4: Include the modal + load the JS**

Find where `choices.min.js` is loaded in `cash_disbursements/form.html` (search for `choices.min.js`). Immediately **before** that `<script src>` tag, add:

```jinja
{% include "vendors/_quick_add_modal.html" %}
```

Immediately **after** the `transaction-utils.js` script tag (or after `choices.min.js` if `transaction-utils.js` is absent), add:

```jinja
<script src="{{ url_for('static', filename='vendor-form-widgets.js') }}"></script>
<script src="{{ url_for('static', filename='vendor-quick-add.js') }}"></script>
```

Ensure load order is: `choices.min.js` → `vendor-form-widgets.js` → `vendor-quick-add.js` → the main inline script that calls `initVendorQuickAdd`.

- [ ] **Step 5: Manual smoke test**

Visit `http://127.0.0.1:5000/cash-disbursements/create` (confirm the exact route from the CD list page), open the vendor picker, choose "➕ Add Vendor…", create a vendor, confirm it is selected and no console errors. A brand-new vendor will show no open bills — expected.

- [ ] **Step 6: Commit**

```bash
git add app/cash_disbursements/views.py app/cash_disbursements/templates/cash_disbursements/form.html
git commit -m "feat(cd): inline + Add Vendor modal on CD create/edit"
```

---

## Task 8: Page-level integration test + final suite

**Files:**
- Test: `tests/integration/test_vendor_quick_add.py`

- [ ] **Step 1: Write the failing page-render tests**

Append to `tests/integration/test_vendor_quick_add.py`:

```python
class TestQuickAddRendersOnTransactionPages:
    def test_ap_create_includes_modal_and_assets(self, client, db_session, admin_user, main_branch):
        login(client)
        make_vat_category(db_session)
        resp = client.get('/accounts-payable/create')
        assert resp.status_code == 200
        assert b'vendorQuickAddOverlay' in resp.data
        assert b'vendor-quick-add.js' in resp.data
        assert b'Add Vendor' in resp.data

    def test_cd_create_includes_modal_and_assets(self, client, db_session, admin_user, main_branch):
        login(client)
        make_vat_category(db_session)
        resp = client.get('/cash-disbursements/create')
        assert resp.status_code == 200
        assert b'vendorQuickAddOverlay' in resp.data
        assert b'vendor-quick-add.js' in resp.data
```

> If `/cash-disbursements/create` differs, correct the URL to the real CD create route (confirmed in Task 7 Step 5).

- [ ] **Step 2: Run to verify it fails, then passes after Tasks 6-7**

Run: `pytest tests/integration/test_vendor_quick_add.py::TestQuickAddRendersOnTransactionPages -v`
Expected: PASS (Tasks 6 and 7 already wired the templates). If FAIL, the include/asset wiring from Tasks 6-7 is incomplete — fix there.

- [ ] **Step 3: Run the full affected suites**

Run: `pytest tests/integration/test_vendor_quick_add.py tests/integration/test_vendor_views.py -v -m "not slow"`
Expected: PASS. Investigate any failure before continuing.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_vendor_quick_add.py
git commit -m "test(vendors): assert quick-add modal renders on AP and CD pages"
```

---

## Self-Review Notes

- **Spec coverage:** JSON endpoint (Task 1), shared partial (Task 3), modal partial (Task 4), shared JS (Task 5), AP wiring (Task 6), CD wiring (Task 7), audit assertion (Task 1), permission check (Task 1), full-page regression (Task 3), page-render checks (Task 8). All spec sections mapped.
- **Sentinel constant** `__add_vendor__` is consistent across `vendor-quick-add.js`, AP guard (Task 6 Step 2), and CD guard (Task 7 Step 2).
- **Context var names** `vendor_quick_add_form` / `vendor_quick_add_whts` match between the modal partial (Task 4) and both view renders (Tasks 6-7).
- **Function names** `initVendorVatSelect` (Task 3) and `initVendorQuickAdd` (Task 5) are referenced consistently in Tasks 6-7.
- **No vendor cache** to clear; vendors are not in the approval workflow — confirmed in the spec, no task needed.
