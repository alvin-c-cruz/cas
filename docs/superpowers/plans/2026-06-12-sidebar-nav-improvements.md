# Sidebar Navigation Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three navigation problems: User Management shown to wrong role, unimplemented feature links broken, and Receipts & Payments split into two separate sidebar links.

**Architecture:** All changes are template-only except Task 1 (new view + template for the Under Development page). The dashboard blueprint gains one new route. `base.html` gets three targeted patches: role gate fix, two new receipt links, and dead-link rewires.

**Tech Stack:** Flask + Jinja2, pytest, existing `dashboard_bp` blueprint, existing `receipts_bp` blueprint.

**Spec:** `docs/superpowers/specs/2026-06-12-sidebar-nav-improvements-design.md`

**Conventions (from CLAUDE.md):** No JS popups; design tokens only; `pytest -q --no-cov` for quick runs; audit log assertions in every CRUD test (N/A here — no writes). Repo root: `C:\envs\cas`.

---

### Task 1: Under Development page — route + template

**Files:**
- Modify: `app/dashboard/views.py`
- Create: `app/dashboard/templates/dashboard/under_development.html`
- Test: `tests/integration/test_under_development.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_under_development.py`:

```python
"""Under Development page renders for authenticated users (sidebar nav)."""


def login(client, username='admin', password='ac1123581321'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


class TestUnderDevelopmentPage:
    def test_redirects_unauthenticated_to_login(self, client, db_session, admin_user):
        resp = client.get('/under-development', follow_redirects=False)
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']

    def test_renders_for_authenticated_user(self, client, db_session, admin_user):
        login(client)
        resp = client.get('/under-development')
        assert resp.status_code == 200
        assert b'Under Development' in resp.data

    def test_feature_name_shown_when_provided(self, client, db_session, admin_user):
        login(client)
        resp = client.get('/under-development?feature=Cash+Flow')
        assert resp.status_code == 200
        assert b'Cash Flow' in resp.data

    def test_generic_message_when_no_feature(self, client, db_session, admin_user):
        login(client)
        resp = client.get('/under-development')
        assert resp.status_code == 200
        assert b'This feature' in resp.data
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
python -m pytest tests/integration/test_under_development.py -q --no-cov
```
Expected: FAIL — `404` (route doesn't exist yet).

- [ ] **Step 3: Add route to `app/dashboard/views.py`**

Read the file first. Add after the existing `get_action_items` function (before any `if __name__` block or end of file):

```python
@dashboard_bp.route('/under-development')
@login_required
def under_development():
    feature = request.args.get('feature', '')
    return render_template('dashboard/under_development.html', feature=feature)
```

Ensure `request` is already imported at the top of the file (it uses `request.args`). Check the existing imports — if `request` is missing, add it to the `from flask import ...` line.

- [ ] **Step 4: Create the template**

Create `app/dashboard/templates/dashboard/under_development.html`:

```html
{% extends "base.html" %}

{% block title %}Under Development - CAS{% endblock %}

{% block content %}
<div class="page-container">
    <div class="page-header">
        <h1 class="page-title">🚧 Under Development</h1>
    </div>

    <div class="card" style="max-width: 520px; margin: 3rem auto; text-align: center; padding: 2.5rem;">
        <div style="font-size: 3rem; margin-bottom: 1rem;">🚧</div>
        <h2 style="margin-bottom: 0.75rem;">Coming Soon</h2>
        <p style="color: var(--text-muted); margin-bottom: 2rem;">
            {% if feature %}
                <strong>{{ feature }}</strong> is not yet available.
            {% else %}
                This feature is not yet available.
            {% endif %}
            Check back in a future update.
        </p>
        <button class="btn btn-secondary" onclick="history.back()">← Go Back</button>
    </div>
</div>
{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

```powershell
python -m pytest tests/integration/test_under_development.py -q --no-cov
```
Expected: 4 passed.

- [ ] **Step 6: Commit**

```powershell
git add app/dashboard/views.py app/dashboard/templates/dashboard/under_development.html tests/integration/test_under_development.py
git commit -m "feat: Under Development page for unimplemented nav links"
```

---

### Task 2: Sidebar role fix — User Management + Admin section visibility

**Files:**
- Modify: `app/templates/base.html`
- Test: `tests/integration/test_sidebar_roles.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_sidebar_roles.py`:

```python
"""Sidebar shows correct links per role."""


def login(client, username, password):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


class TestSidebarRoles:
    def test_admin_sees_user_management(self, client, db_session, admin_user):
        login(client, 'admin', 'ac1123581321')
        resp = client.get('/dashboard')
        assert b'User Management' in resp.data

    def test_accountant_does_not_see_user_management(self, client, db_session,
                                                      admin_user, accountant_user):
        login(client, 'accountant', 'accountant123')
        resp = client.get('/dashboard')
        assert b'User Management' not in resp.data

    def test_accountant_sees_audit_log(self, client, db_session,
                                       admin_user, accountant_user):
        login(client, 'accountant', 'accountant123')
        resp = client.get('/dashboard')
        assert b'Audit Log' in resp.data

    def test_staff_does_not_see_admin_section(self, client, db_session,
                                              admin_user, staff_user):
        login(client, 'staff', 'staff123')
        resp = client.get('/dashboard')
        assert b'User Management' not in resp.data
        assert b'Audit Log' not in resp.data

    def test_viewer_does_not_see_admin_section(self, client, db_session,
                                               admin_user, viewer_user):
        login(client, 'viewer', 'viewer123')
        resp = client.get('/dashboard')
        assert b'User Management' not in resp.data
        assert b'Audit Log' not in resp.data
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
python -m pytest tests/integration/test_sidebar_roles.py -q --no-cov
```
Expected: `test_accountant_does_not_see_user_management` FAIL (accountant currently sees it).

- [ ] **Step 3: Apply two fixes in `app/templates/base.html`**

Read the file. Make these two targeted edits:

**Fix A — User Management gate** (around line 1205):

Find:
```jinja2
{% if current_user.is_authenticated and current_user.role in ['admin', 'accountant'] %}
                    <a href="{{ url_for('users.list_users') }}"
```

Change `role in ['admin', 'accountant']` to `role == 'admin'`.

**Fix B — Wrap Admin section** (around line 1188):

Find the comment and opening tag:
```html
            <!-- Admin Section -->
            <div class="nav-section">
```

Replace with:
```html
            <!-- Admin Section -->
            {% if current_user.is_authenticated and current_user.role in ['admin', 'accountant'] %}
            <div class="nav-section">
```

Then find the closing `</div>` that ends the Admin section (it comes after the Audit Log link block, around line 1225) and add the `{% endif %}` immediately after it:
```html
            </div>
            {% endif %}
```

- [ ] **Step 4: Run tests to verify they pass**

```powershell
python -m pytest tests/integration/test_sidebar_roles.py -q --no-cov
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```powershell
git add app/templates/base.html tests/integration/test_sidebar_roles.py
git commit -m "fix: User Management admin-only; hide Admin section from staff/viewer"
```

---

### Task 3: Wire dead links to Under Development page + fix General Ledger

**Files:**
- Modify: `app/templates/base.html`
- Test: extend `tests/integration/test_under_development.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_under_development.py`:

```python
class TestDeadLinksWired:
    def test_general_ledger_link_not_customers(self, client, db_session, admin_user):
        login(client)
        resp = client.get('/dashboard')
        assert b'customers/customers' not in resp.data or \
               b'General Ledger' not in resp.data  # link must not go to /customers/customers

    def test_cash_flow_not_hash(self, client, db_session, admin_user):
        login(client)
        resp = client.get('/dashboard')
        # href="#" should not appear next to Cash Flow
        html = resp.data.decode()
        cash_flow_idx = html.find('Cash Flow')
        snippet = html[max(0, cash_flow_idx - 100):cash_flow_idx]
        assert 'href="#"' not in snippet
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
python -m pytest tests/integration/test_under_development.py::TestDeadLinksWired -q --no-cov
```
Expected: FAIL (links still point to `#` / `customers/customers`).

- [ ] **Step 3: Update the three dead links in `app/templates/base.html`**

Read the file. Make three replacements in the Ledger and Financial Reports sections:

**General Ledger** (Ledger section, link currently using `url_for('customers.list_customers')` with text "General Ledger"):

```jinja2
<a href="{{ url_for('dashboard.under_development', feature='General Ledger') }}" class="nav-item {% if request.endpoint == 'dashboard.under_development' and request.args.get('feature') == 'General Ledger' %}active{% endif %}">
    <span class="nav-icon">📖</span>
    <span class="nav-text">General Ledger</span>
</a>
```

**Cash Flow** (Financial Reports section, currently `href="#"`):

```jinja2
<a href="{{ url_for('dashboard.under_development', feature='Cash Flow') }}" class="nav-item {% if request.endpoint == 'dashboard.under_development' and request.args.get('feature') == 'Cash Flow' %}active{% endif %}">
    <span class="nav-icon">💸</span>
    <span class="nav-text">Cash Flow</span>
</a>
```

**Annual ITR** (BIR Reports section, currently `href="#"`):

```jinja2
<a href="{{ url_for('dashboard.under_development', feature='Annual ITR') }}" class="nav-item {% if request.endpoint == 'dashboard.under_development' and request.args.get('feature') == 'Annual ITR' %}active{% endif %}">
    <span class="nav-icon">📄</span>
    <span class="nav-text">Annual ITR</span>
</a>
```

- [ ] **Step 4: Run tests**

```powershell
python -m pytest tests/integration/test_under_development.py -q --no-cov
```
Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add app/templates/base.html tests/integration/test_under_development.py
git commit -m "fix: dead nav links (General Ledger, Cash Flow, Annual ITR) point to Under Development page"
```

---

### Task 4: Split Receipts & Payments + wire + New dropdown

**Files:**
- Modify: `app/templates/base.html`
- Test: `tests/integration/test_sidebar_roles.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_sidebar_roles.py`:

```python
class TestReceiptLinks:
    def test_collections_link_present(self, client, db_session, admin_user):
        login(client, 'admin', 'ac1123581321')
        resp = client.get('/dashboard')
        assert b'Collections' in resp.data

    def test_payments_link_present(self, client, db_session, admin_user):
        login(client, 'admin', 'ac1123581321')
        resp = client.get('/dashboard')
        assert b'Payments' in resp.data

    def test_receipts_and_payments_single_link_gone(self, client, db_session, admin_user):
        login(client, 'admin', 'ac1123581321')
        resp = client.get('/dashboard')
        assert b'Receipts &amp; Payments' not in resp.data
        assert b'Receipts & Payments' not in resp.data
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
python -m pytest tests/integration/test_sidebar_roles.py::TestReceiptLinks -q --no-cov
```
Expected: FAIL (single "Receipts & Payments" link exists, no "Collections" / "Payments").

- [ ] **Step 3: Replace Receipts & Payments link in `app/templates/base.html`**

Read the file. Find the single Receipts & Payments nav item (in the Transactions section) and replace it with two links:

```jinja2
<a href="{{ url_for('receipts.list_receipts') }}?type=collection" class="nav-item {% if request.endpoint and request.endpoint.startswith('receipts.') and request.args.get('type') == 'collection' %}active{% endif %}">
    <span class="nav-icon">💰</span>
    <span class="nav-text">Collections</span>
</a>
<a href="{{ url_for('receipts.list_receipts') }}?type=payment" class="nav-item {% if request.endpoint and request.endpoint.startswith('receipts.') and request.args.get('type') == 'payment' %}active{% endif %}">
    <span class="nav-icon">💸</span>
    <span class="nav-text">Payments</span>
</a>
```

- [ ] **Step 4: Wire the + New dropdown**

Find the `+ New` dropdown block (around line 1294). Replace the two placeholder `#` entries for New Collection and New Payment:

```jinja2
<a href="{{ url_for('receipts.create') }}?type=collection" class="topbar-new-item">
    💰 New Collection
</a>
<a href="{{ url_for('receipts.create') }}?type=payment" class="topbar-new-item">
    💸 New Payment
</a>
```

Note: the receipts create route function is named `create` (not `create_receipt`) — confirmed from `app/receipts/views.py` line 108. It reads `request.args.get('type', 'collection')` on GET to pre-select the transaction type.

- [ ] **Step 5: Run all tests**

```powershell
python -m pytest tests/integration/test_sidebar_roles.py tests/integration/test_under_development.py -q --no-cov
```
Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add app/templates/base.html tests/integration/test_sidebar_roles.py
git commit -m "feat: split Collections/Payments sidebar links; wire + New dropdown"
```
