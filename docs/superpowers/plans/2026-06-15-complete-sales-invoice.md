# Complete Sales Invoice — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close all remaining gaps in the Sales Invoice module: fix the "-0.00" WHT display bug in SI and APV forms, add a batch print-list route for SI, and activate the dormant Customer List page (template already exists, view redirects to under-development, template has two attribute-name bugs).

**Architecture:** Four independent fixes, each self-contained. BUG-02 (empty VAT/WHT dropdowns) was a seed-data issue resolved by the DB reset on 2026-06-15 — the JS code was always correct; no code change required, but a regression test is added. All other changes are template or view-level; no model or migration changes.

**Tech Stack:** Flask + SQLAlchemy + Jinja2 + Choices.js; pytest for integration tests; `ph_now()` for PH timestamps.

**Branch:** `feature/sales-voucher`

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `app/sales_invoices/templates/sales_invoices/form.html` | Modify | Fix "-0.00" WHT initial value + 3 JS sites |
| `app/purchase_bills/templates/purchase_bills/form.html` | Modify | Same fix — identical pattern in APV |
| `app/sales_invoices/views.py` | Modify | Add `print_list()` route before `export_excel` |
| `app/sales_invoices/templates/sales_invoices/list_print.html` | Create | Batch print template (A4 landscape) |
| `app/sales_invoices/templates/sales_invoices/list.html` | Modify | Add Print button before Export Excel |
| `app/customers/views.py` | Modify | Implement `list_customers()` (remove under_development redirect) |
| `app/customers/templates/customers/list.html` | Modify | Fix `customer.default_vat` → `customer.default_vat_category`; fix `customer.default_wt` → `customer.default_wt_code`; replace `data-confirm` delete with custom modal |
| `tests/integration/test_sales_invoices.py` | Modify/Create | Add print-list test + BUG-02 regression test |
| `tests/integration/test_customers.py` | Modify/Create | Add customer list test |

---

## Task 1: Fix BUG-05 — "-0.00" WHT display in SI form

**Root cause:** Three JS sites concatenate `'-' + fmt(autoWt)` unconditionally, producing `-0.00` when WHT is zero. The initial HTML value is also hardcoded as `-0.00`.

**Files:**
- Modify: `app/sales_invoices/templates/sales_invoices/form.html`

- [ ] **Step 1.1 — Fix initial HTML value**

In `form.html`, find (line ~152):
```html
<span id="wtDisplay" class="bsr-amt bsr-amt--red">-0.00</span>
```
Change to:
```html
<span id="wtDisplay" class="bsr-amt bsr-amt--red">0.00</span>
```

- [ ] **Step 1.2 — Fix `calculateTotals()` WHT display update**

Find (line ~538):
```javascript
if (!wtOverrideActive)  document.getElementById('wtDisplay').textContent  = '-' + fmt(autoWt);
```
Change to:
```javascript
if (!wtOverrideActive)  document.getElementById('wtDisplay').textContent  = autoWt > 0 ? '-' + fmt(autoWt) : '0.00';
```

- [ ] **Step 1.3 — Fix `onWtOverrideInput()` display update**

Find (line ~709):
```javascript
    document.getElementById('wtDisplay').textContent  = '-' + fmt(v);
```
Change to:
```javascript
    document.getElementById('wtDisplay').textContent  = v > 0 ? '-' + fmt(v) : '0.00';
```

- [ ] **Step 1.4 — Fix `revertWtOverride()` display update**

Find (line ~719):
```javascript
    document.getElementById('wtDisplay').textContent       = '-' + fmt(autoWt);
```
Change to:
```javascript
    document.getElementById('wtDisplay').textContent       = autoWt > 0 ? '-' + fmt(autoWt) : '0.00';
```

- [ ] **Step 1.5 — Apply the same four fixes to APV form**

In `app/purchase_bills/templates/purchase_bills/form.html`:

a) Find initial HTML value (line ~152):
```html
<span id="wtDisplay" class="bsr-amt bsr-amt--red">-0.00</span>
```
Change to:
```html
<span id="wtDisplay" class="bsr-amt bsr-amt--red">0.00</span>
```

b) Find in `calculateTotals()` (line ~559):
```javascript
        document.getElementById('wtDisplay').textContent = '-' + fmt(autoWt);
```
Change to:
```javascript
        document.getElementById('wtDisplay').textContent = autoWt > 0 ? '-' + fmt(autoWt) : '0.00';
```

c) Find in `onWtOverrideInput()` (line ~657):
```javascript
    document.getElementById('wtDisplay').textContent = '-' + fmt(v);
```
Change to:
```javascript
    document.getElementById('wtDisplay').textContent = v > 0 ? '-' + fmt(v) : '0.00';
```

d) Find in `revertWtOverride()` (line ~667):
```javascript
    document.getElementById('wtDisplay').textContent = '-' + fmt(autoWt);
```
Change to:
```javascript
    document.getElementById('wtDisplay').textContent = autoWt > 0 ? '-' + fmt(autoWt) : '0.00';
```

- [ ] **Step 1.6 — Commit**

```
git add app/sales_invoices/templates/sales_invoices/form.html
git add app/purchase_bills/templates/purchase_bills/form.html
git commit -m "fix: show 0.00 instead of -0.00 when WHT is zero in SI and APV forms (BUG-05)"
```

---

## Task 2: Add SI Print List

**Files:**
- Modify: `app/sales_invoices/views.py`
- Create: `app/sales_invoices/templates/sales_invoices/list_print.html`
- Modify: `app/sales_invoices/templates/sales_invoices/list.html`
- Test: `tests/integration/test_sales_invoices.py`

- [ ] **Step 2.1 — Write the failing test**

In `tests/integration/test_sales_invoices.py`, add:

```python
def test_print_list_get_empty(client, db_session, accountant_user):
    """Print list renders 200 with no invoices."""
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = accountant_user.branches[0].id
    client.post('/login', data={'username': accountant_user.username,
                                'password': 'password'}, follow_redirects=True)
    response = client.get('/sales-invoices/print')
    assert response.status_code == 200
    assert b'SALES INVOICES' in response.data
```

- [ ] **Step 2.2 — Run test to confirm it fails**

```
pytest tests/integration/test_sales_invoices.py::test_print_list_get_empty -v
```

Expected: FAIL — `404` because route does not exist yet.

- [ ] **Step 2.3 — Add `print_list()` route to `views.py`**

In `app/sales_invoices/views.py`, add the route immediately before the `export_excel` route (search for `@sales_invoices_bp.route('/sales-invoices/export/excel')`):

```python
@sales_invoices_bp.route('/sales-invoices/print')
@login_required
def print_list():
    from app.settings import AppSettings
    invoices = (_filtered_invoices_query(include_ids=True)
                .order_by(SalesInvoice.invoice_date.desc()).all())
    company_name = AppSettings.get_setting('company_name') or ''
    return render_template(
        'sales_invoices/list_print.html',
        invoices=invoices,
        company_name=company_name,
        today=ph_now().date(),
        printed_at=ph_now(),
        status_filter=request.args.get('status', 'all'),
        date_from=request.args.get('date_from', ''),
        date_to=request.args.get('date_to', ''),
    )
```

- [ ] **Step 2.4 — Create `list_print.html`**

Create `app/sales_invoices/templates/sales_invoices/list_print.html`:

```html
{% extends "base.html" %}
{% block title %}Sales Invoices — Print Preview{% endblock %}
{% block page_title %}Sales Invoices — Print Preview{% endblock %}

{% block extra_css %}
<style>
  .si-print-actions { display: flex; gap: 8px; justify-content: flex-end; }

  .si-header { text-align: center; border-bottom: 2px solid #111; padding-bottom: 10px; margin-bottom: 14px; }
  .si-header .company-name { font-size: 16px; font-weight: 700; letter-spacing: .5px; }
  .si-header .doc-title    { font-size: 14px; font-weight: 700; letter-spacing: 1px; margin-top: 6px; }
  .si-header .period-label { font-size: 11px; color: #555; margin-top: 3px; }

  .si-scroll { overflow-x: auto; }
  .si-table { width: 100%; border-collapse: collapse; font-size: 10px; }
  .si-table th, .si-table td { border: 1px solid #aaa; padding: 3px 6px; white-space: nowrap; }
  .si-table th { background: #222; color: #fff; font-weight: 700; text-align: left; }
  .si-table td.num { text-align: right; font-family: monospace; }
  .si-table th.num { text-align: right; }
  .si-total td { border-top: 2px solid #111; font-weight: 700; background: #f0f0f0; }
  .audit-footer { margin-top: 8px; font-size: 9px; color: #888; text-align: right;
                  border-top: 1px solid #ddd; padding-top: 4px; }

  @media print {
    nav.sidebar, header.topbar, .si-print-actions, .card-header { display: none !important; }
    .main { margin-left: 0 !important; padding: 0 !important; }
    .content-wrapper, .card { box-shadow: none !important; border: none !important; }
    .si-scroll { overflow: visible !important; }
    @page { size: A4 landscape; margin: 10mm; }
    .si-table { font-size: 8px; }
    .si-table thead { display: table-header-group; }
    .si-table tbody tr { break-inside: avoid; page-break-inside: avoid; }
    .si-header { page-break-after: avoid; }
  }
</style>
{% endblock %}

{% block content %}
<div class="card">
  <div class="card-header">
    <div class="si-print-actions">
      <button onclick="window.print()" class="btn btn-secondary btn-sm">Print</button>
      <a href="{{ url_for('sales_invoices.list_invoices', status=status_filter, date_from=date_from, date_to=date_to) }}" class="btn btn-secondary btn-sm">Back</a>
    </div>
  </div>
  <div class="card-body">

    <div class="si-header">
      {% if company_name %}<div class="company-name">{{ company_name | upper }}</div>{% endif %}
      <div class="doc-title">SALES INVOICES</div>
      {% set parts = [] %}
      {% if status_filter and status_filter != 'all' %}{% set _ = parts.append(status_filter | replace('_', ' ') | title) %}{% endif %}
      {% if date_from %}{% set _ = parts.append('From ' + date_from) %}{% endif %}
      {% if date_to %}{% set _ = parts.append('To ' + date_to) %}{% endif %}
      <div class="period-label">{{ parts | join(' · ') if parts else 'All Records' }}</div>
    </div>

    {% if invoices %}
    {% set total_subtotal = namespace(v=0) %}
    {% set total_vat = namespace(v=0) %}
    {% set total_wht = namespace(v=0) %}
    {% set total_net = namespace(v=0) %}
    <div class="si-scroll">
    <table class="si-table">
      <thead>
        <tr>
          <th>Date</th>
          <th>SI #</th>
          <th>Customer</th>
          <th>Due Date</th>
          <th class="num">Subtotal</th>
          <th class="num">VAT</th>
          <th class="num">WHT</th>
          <th class="num">Net Receivable</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {% for inv in invoices %}
        {% set total_subtotal.v = total_subtotal.v + inv.subtotal %}
        {% set total_vat.v = total_vat.v + inv.vat_amount %}
        {% set total_wht.v = total_wht.v + inv.withholding_tax_amount %}
        {% set total_net.v = total_net.v + inv.total_amount %}
        <tr {% if inv.status == 'voided' %}style="text-decoration:line-through;background:#ffebee;"{% elif inv.status == 'draft' %}style="background:#fffde7;"{% endif %}>
          <td>{{ inv.invoice_date.strftime('%d-%b-%Y') }}</td>
          <td>{{ inv.invoice_number }}</td>
          <td>{{ inv.customer_name }}</td>
          <td {% if inv.due_date and inv.due_date < today and inv.status in ['posted', 'partially_paid'] %}style="color:#b91c1c;font-weight:700;"{% endif %}>
            {{ inv.due_date.strftime('%d-%b-%Y') if inv.due_date else '—' }}
          </td>
          <td class="num">{{ '{:,.2f}'.format(inv.subtotal) }}</td>
          <td class="num">{{ '{:,.2f}'.format(inv.vat_amount) }}</td>
          <td class="num">{% if inv.withholding_tax_amount > 0 %}({{ '{:,.2f}'.format(inv.withholding_tax_amount) }}){% else %}—{% endif %}</td>
          <td class="num">{{ '{:,.2f}'.format(inv.total_amount) }}</td>
          <td>{{ inv.status | replace('_', ' ') | title }}</td>
        </tr>
        {% endfor %}
        <tr class="si-total">
          <td colspan="4">TOTAL ({{ invoices | length }} record{{ 's' if invoices | length != 1 else '' }})</td>
          <td class="num">{{ '{:,.2f}'.format(total_subtotal.v) }}</td>
          <td class="num">{{ '{:,.2f}'.format(total_vat.v) }}</td>
          <td class="num">{% if total_wht.v > 0 %}({{ '{:,.2f}'.format(total_wht.v) }}){% else %}—{% endif %}</td>
          <td class="num">{{ '{:,.2f}'.format(total_net.v) }}</td>
          <td></td>
        </tr>
      </tbody>
    </table>
    </div>
    {% else %}
    <p style="margin-top:16px; color:#555;">No Sales Invoices match the selected filters.</p>
    {% endif %}

    <div class="audit-footer">
      Printed: {{ printed_at.strftime('%d %b %Y %I:%M %p') }}
    </div>

  </div>
</div>
{% endblock %}
```

- [ ] **Step 2.5 — Add Print button to `list.html`**

In `app/sales_invoices/templates/sales_invoices/list.html`, find (line ~121):
```html
        <div class="card-header-actions" style="display:flex; gap:8px; align-items:center;">
            <span id="si-selected-count" class="si-selected-count"></span>
            <a href="{{ url_for('sales_invoices.export_excel', ...
```

Add the Print button before the Export Excel link:
```html
        <div class="card-header-actions" style="display:flex; gap:8px; align-items:center;">
            <span id="si-selected-count" class="si-selected-count"></span>
            <a href="{{ url_for('sales_invoices.print_list', status=status_filter, customer=customer_filter, q=q, date_from=date_from, date_to=date_to) }}"
               class="btn btn-secondary btn-sm">Print</a>
            <a href="{{ url_for('sales_invoices.export_excel', ...
```

- [ ] **Step 2.6 — Run the test to confirm it passes**

```
pytest tests/integration/test_sales_invoices.py::test_print_list_get_empty -v
```

Expected: PASS — 200 with `SALES INVOICES` in body.

- [ ] **Step 2.7 — Commit**

```
git add app/sales_invoices/views.py
git add app/sales_invoices/templates/sales_invoices/list_print.html
git add app/sales_invoices/templates/sales_invoices/list.html
git add tests/integration/test_sales_invoices.py
git commit -m "feat: add Print list to Sales Invoices (route + template + button)"
```

---

## Task 3: Implement Customer List (vendor-maintenance pattern)

**Context:** The `list_customers()` view redirects to under-development. The existing template is a poor draft with two attribute bugs and a `data-confirm` delete. Per instruction, rewrite the template wholesale to match the vendor maintenance structure exactly: linked code/name, BIR-incomplete warning, proper delete modal using `btn-danger`, and vendor CSS. Adaptations for customers: no detail page → link to edit page; WT is a single `default_wt_code` string field (not a relationship).

**Files:**
- Modify: `app/customers/views.py`
- Modify: `app/customers/templates/customers/list.html` (full rewrite)
- Test: `tests/integration/test_customers.py`

- [ ] **Step 3.1 — Write the failing tests**

Create/modify `tests/integration/test_customers.py`:

```python
def test_customer_list_renders_empty(client, db_session, accountant_user):
    """Customer list returns 200 with empty state on a fresh DB."""
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = accountant_user.branches[0].id
    client.post('/login', data={'username': accountant_user.username,
                                'password': 'password'}, follow_redirects=True)
    response = client.get('/customers')
    assert response.status_code == 200
    assert b'Customer Maintenance' in response.data
    assert b'No customers found' in response.data


def test_customer_list_shows_customer(client, db_session, accountant_user):
    """Customer list shows code, name, and BIR-incomplete badge when TIN is missing."""
    from app.customers.models import Customer
    cust = Customer(code='C001', name='Test Corp', payment_terms='Net 30',
                    is_active=True)  # no TIN — should show BIR warning
    db_session.add(cust)
    db_session.commit()

    with client.session_transaction() as sess:
        sess['selected_branch_id'] = accountant_user.branches[0].id
    client.post('/login', data={'username': accountant_user.username,
                                'password': 'password'}, follow_redirects=True)
    response = client.get('/customers')
    assert response.status_code == 200
    assert b'Test Corp' in response.data
    assert b'C001' in response.data
    assert b'BIR incomplete' in response.data


def test_customer_list_delete_modal_present(client, db_session, accountant_user):
    """Delete modal is in the HTML — no data-confirm attribute anywhere."""
    from app.customers.models import Customer
    cust = Customer(code='C001', name='Test Corp', payment_terms='Net 30', is_active=True)
    db_session.add(cust)
    db_session.commit()

    with client.session_transaction() as sess:
        sess['selected_branch_id'] = accountant_user.branches[0].id
    client.post('/login', data={'username': accountant_user.username,
                                'password': 'password'}, follow_redirects=True)
    response = client.get('/customers')
    assert b'delete-modal-' in response.data
    assert b'data-confirm' not in response.data  # no JS confirm()
```

- [ ] **Step 3.2 — Run tests to confirm they fail**

```
pytest tests/integration/test_customers.py -v
```

Expected: all three FAIL — redirects to `/under-development`.

- [ ] **Step 3.3 — Wire up `list_customers()` in `views.py`**

In `app/customers/views.py`, replace:
```python
@customers_bp.route('/customers')
@login_required
def list_customers():
    return redirect(url_for('dashboard.under_development', feature='Customers'))
```
With:
```python
@customers_bp.route('/customers')
@login_required
def list_customers():
    customers = Customer.query.order_by(Customer.code).all()
    return render_template('customers/list.html', customers=customers)
```

- [ ] **Step 3.4 — Rewrite `customers/list.html` to match vendor maintenance**

Replace the entire contents of `app/customers/templates/customers/list.html` with:

```html
{% extends "base.html" %}

{% block title %}Customer Maintenance{% endblock %}
{% block page_title %}Customer Maintenance{% endblock %}

{% block content %}

<div class="content-header">
    <div class="search-box">
        <input type="text" id="searchInput" placeholder="Search by name, code, or TIN..." class="search-input">
    </div>
    <div class="page-actions" style="display: flex; gap: 8px;">
        <a href="{{ url_for('customers.export_excel') }}" class="btn btn-secondary">
            📊 Export Excel
        </a>
        <a href="{{ url_for('customers.export_csv_route') }}" class="btn btn-secondary">
            📄 Export CSV
        </a>
        {% if current_user.role in ['accountant', 'admin'] %}
        <a href="{{ url_for('customers.create') }}" class="btn btn-primary">
            + Create Customer
        </a>
        {% endif %}
    </div>
</div>

<div class="card">
    <div class="card-body">
        <table class="data-table" id="customersTable">
            <thead>
                <tr>
                    <th>CODE</th>
                    <th>NAME</th>
                    <th>CONTACT PERSON</th>
                    <th>PHONE</th>
                    <th>TIN</th>
                    <th>TERMS</th>
                    <th>DEFAULT VAT</th>
                    <th>DEFAULT WT</th>
                    <th>STATUS</th>
                    <th>ACTIONS</th>
                </tr>
            </thead>
            <tbody>
                {% for customer in customers %}
                <tr>
                    <td><a href="{{ url_for('customers.edit', id=customer.id) }}" class="customer-link"><strong>{{ customer.code }}</strong></a></td>
                    <td>
                        <a href="{{ url_for('customers.edit', id=customer.id) }}" class="customer-link">{{ customer.name }}</a>
                        {% set bir_missing = [] %}
                        {% if not customer.tin %}{% set bir_missing = bir_missing + ['TIN'] %}{% endif %}
                        {% if not customer.address %}{% set bir_missing = bir_missing + ['Address'] %}{% endif %}
                        {% if not customer.postal_code %}{% set bir_missing = bir_missing + ['Postal Code'] %}{% endif %}
                        {% if bir_missing %}
                        <br><span class="badge-bir-warn" title="BIR info missing: {{ bir_missing | join(', ') }}">⚠ BIR incomplete</span>
                        {% endif %}
                    </td>
                    <td>{{ customer.contact_person or '—' }}</td>
                    <td>{{ customer.phone or '—' }}</td>
                    <td>{{ customer.tin or '—' }}</td>
                    <td>{{ customer.payment_terms }}</td>
                    <td>
                        {% if customer.default_vat_category %}
                        <span class="badge badge-vat">{{ customer.default_vat_category }}</span>
                        {% else %}
                        —
                        {% endif %}
                    </td>
                    <td>
                        {% if customer.default_wt_code %}
                        <span class="badge badge-wt">{{ customer.default_wt_code }}</span>
                        {% else %}
                        —
                        {% endif %}
                    </td>
                    <td>
                        {% if customer.is_active %}
                            <span class="badge badge-success">Active</span>
                        {% else %}
                            <span class="badge badge-inactive">Inactive</span>
                        {% endif %}
                    </td>
                    <td>
                        {% if current_user.role in ['accountant', 'admin'] %}
                        <div class="action-buttons">
                            <a href="{{ url_for('customers.edit', id=customer.id) }}" class="btn-action btn-action-edit" title="Edit">Edit</a>
                            <button type="button" class="btn-action btn-action-delete"
                                    onclick="document.getElementById('delete-modal-{{ customer.id }}').style.display='flex'">
                                Delete
                            </button>
                        </div>
                        <!-- Delete confirmation modal -->
                        <div id="delete-modal-{{ customer.id }}"
                             style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:1000; align-items:center; justify-content:center;">
                            <div style="background:var(--card); border-radius:8px; padding:32px; max-width:440px; width:90%; box-shadow:0 8px 24px rgba(0,0,0,0.2);">
                                <h3 style="margin:0 0 12px 0;">Delete Customer</h3>
                                <p style="color:var(--text-2); margin-bottom:24px;">
                                    Delete <strong>{{ customer.code }} — {{ customer.name }}</strong>? This cannot be undone.
                                </p>
                                <div style="display:flex; gap:12px; justify-content:flex-end;">
                                    <button type="button" class="btn btn-secondary btn-sm"
                                            onclick="document.getElementById('delete-modal-{{ customer.id }}').style.display='none'">
                                        Cancel
                                    </button>
                                    <form method="POST" action="{{ url_for('customers.delete', id=customer.id) }}" style="display:inline;">
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
                </tr>
                {% endfor %}
            </tbody>
        </table>

        {% if not customers %}
        <div class="empty-state">
            <p>No customers found.</p>
            {% if current_user.role in ['accountant', 'admin'] %}
            <p><a href="{{ url_for('customers.create') }}" class="btn btn-primary">Add your first customer</a></p>
            {% endif %}
        </div>
        {% endif %}
    </div>
</div>

<style>
.content-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
    gap: 20px;
}

.search-box {
    flex: 1;
    max-width: 400px;
}

.search-input {
    width: 100%;
    padding: 10px 15px;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    font-size: 14px;
    font-family: inherit;
}

.search-input:focus {
    outline: none;
    border-color: #3b82f6;
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

.badge-vat {
    background: #dcfce7;
    color: #166534;
    border: 1px solid #bbf7d0;
    padding: 4px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
    display: inline-block;
}

.badge-wt {
    background: #dbeafe;
    color: #1e40af;
    border: 1px solid #bfdbfe;
    padding: 4px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
    display: inline-block;
}

.badge-success {
    background: #dcfce7;
    color: #166534;
    border: 1px solid #bbf7d0;
}

.badge-inactive {
    background: #f3f4f6;
    color: #6b7280;
    border: 1px solid #e5e7eb;
}

.badge {
    padding: 4px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
    display: inline-block;
}

.btn-danger {
    background: var(--red);
    color: white;
    border: none;
    padding: 6px 18px;
    font-size: 14px;
    border-radius: 5px;
    font-weight: 500;
    cursor: pointer;
}
.btn-danger:hover {
    background: #dc2626;
}
.btn.btn-secondary.btn-sm {
    background: #6b7280;
    color: white;
    border: none;
    padding: 6px 18px;
    font-size: 14px;
    border-radius: 5px;
    font-weight: 500;
    cursor: pointer;
}
.btn.btn-secondary.btn-sm:hover {
    background: #4b5563;
}

.customer-link {
    color: inherit;
    text-decoration: none;
}
.customer-link:hover {
    color: var(--blue);
    text-decoration: underline;
}

.badge-bir-warn {
    background: #fef3c7;
    color: #92400e;
    border: 1px solid #fde68a;
    padding: 2px 7px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 600;
    display: inline-block;
    cursor: default;
    letter-spacing: 0.01em;
}
</style>

<script>
document.getElementById('searchInput')?.addEventListener('input', function(e) {
    const searchTerm = e.target.value.toLowerCase();
    const table = document.getElementById('customersTable');
    const rows = table.querySelectorAll('tbody tr');
    rows.forEach(row => {
        row.style.display = row.textContent.toLowerCase().includes(searchTerm) ? '' : 'none';
    });
});
</script>
{% endblock %}
```

- [ ] **Step 3.5 — Run tests to confirm they pass**

```
pytest tests/integration/test_customers.py -v
```

Expected: all three PASS.

- [ ] **Step 3.6 — Commit**

```
git add app/customers/views.py
git add app/customers/templates/customers/list.html
git add tests/integration/test_customers.py
git commit -m "feat: implement customer list matching vendor maintenance structure"
```

---

## Task 4: BUG-02 Regression Test

**Context:** BUG-02 (VAT/WHT dropdowns showing only "No VAT"/"None" in dynamic SI rows) was a seed-data issue — the old `seed_minimal` seeded 4 generic VAT categories (VATABLE/etc.) instead of the 7 BIR-specific codes. The code in `addLineItem()` correctly uses `vatCategories.map(...)`. After the DB reset on 2026-06-15 with the updated seed, the bug is resolved. This task adds a server-side regression test ensuring the form context is always populated.

**Files:**
- Test: `tests/integration/test_sales_invoices.py`

- [ ] **Step 4.1 — Add regression test**

In `tests/integration/test_sales_invoices.py`, add:

```python
def test_si_create_form_vat_context(client, db_session, accountant_user):
    """SI create form must pass 7 VAT categories and 3 WHT codes to JS globals.

    Regression for BUG-02: empty dropdowns in dynamic line item rows caused by
    missing seed data. Verify server always sends non-empty arrays.
    """
    from app.vat_categories.models import VATCategory
    from app.withholding_tax.models import WithholdingTax

    # Seed minimal VAT + WHT data mirroring seed_minimal()
    vat_codes = ['VEX', 'V0', 'INV', 'V12CG', 'V12DG', 'V12SV', 'V12IM']
    for code in vat_codes:
        db_session.add(VATCategory(code=code, name=code, rate=0.0,
                                   description='', is_active=True))
    for code in ['WC158', 'WC160', 'WC100']:
        db_session.add(WithholdingTax(code=code, name=code,
                                      description='', rate=1.0, is_active=True))
    db_session.commit()

    with client.session_transaction() as sess:
        sess['selected_branch_id'] = accountant_user.branches[0].id
    client.post('/login', data={'username': accountant_user.username,
                                'password': 'password'}, follow_redirects=True)

    response = client.get('/sales-invoices/create')
    assert response.status_code == 200

    # All 7 VAT codes must appear in the rendered JS globals
    for code in vat_codes:
        assert code.encode() in response.data, f"VAT code {code} missing from form context"

    # All 3 WHT codes must appear
    for code in ['WC158', 'WC160', 'WC100']:
        assert code.encode() in response.data, f"WHT code {code} missing from form context"
```

- [ ] **Step 4.2 — Run the regression test**

```
pytest tests/integration/test_sales_invoices.py::test_si_create_form_vat_context -v
```

Expected: PASS.

- [ ] **Step 4.3 — Commit**

```
git add tests/integration/test_sales_invoices.py
git commit -m "test: add BUG-02 regression test — SI form must expose all VAT/WHT codes to JS"
```

---

## Task 5: Run Full Test Suite + Push

- [ ] **Step 5.1 — Run the full suite**

```
pytest -x -q
```

Expected: All tests pass. If any fail, fix them before continuing.

- [ ] **Step 5.2 — Push the branch**

```
git push origin feature/sales-voucher
```

---

## Self-Review

**Spec coverage check:**

| Gap | Task | Covered? |
|-----|------|---------|
| BUG-05: "-0.00" WHT in SI | Task 1 | ✓ |
| BUG-05: "-0.00" WHT in APV | Task 1, Step 1.5 | ✓ |
| SI Print List (route) | Task 2, Step 2.3 | ✓ |
| SI Print List (template) | Task 2, Step 2.4 | ✓ |
| SI Print button in list | Task 2, Step 2.5 | ✓ |
| Customer list redirects to under-development | Task 3, Step 3.3 | ✓ |
| Customer list: attribute bugs, `data-confirm`, BIR warning, linked code/name | Task 3, Step 3.4 | ✓ |
| BUG-02 regression test | Task 4 | ✓ |

**Placeholder scan:** No TBDs, no "implement later", no references to undefined functions.

**Type consistency:** `_filtered_invoices_query` already defined in `views.py` and used in `export_excel` — reusing the same call. `SalesInvoice.invoice_date`, `invoice_number`, `customer_name`, `vat_amount`, `withholding_tax_amount`, `total_amount`, `status` — all confirmed in model. `Customer.default_vat_category`, `Customer.default_wt_code` — confirmed in `app/customers/models.py`.
