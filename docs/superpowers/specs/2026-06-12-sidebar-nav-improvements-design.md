# Spec: Sidebar Navigation Improvements

**Date:** 2026-06-12
**Status:** Approved

## Context

During manual accountant-role testing, three navigation problems were found:
1. User Management is incorrectly visible to accountants (admin-only function)
2. Unimplemented features (Cash Flow, Annual ITR, General Ledger) link to `#` or the wrong route — confusing for demo users
3. "Receipts & Payments" is one link but Collections and Payments are distinct workflows

---

## Part 1 — Under Development page

### Route
New view function `under_development()` added to the existing `dashboard` blueprint (`app/dashboard/views.py`).

```
GET /under-development?feature=<name>
```

No login required gate needed (redirect to login handles unauthenticated access automatically via `@login_required`).

### Template
`app/dashboard/templates/dashboard/under_development.html`

Simple centered card layout consistent with existing error/empty-state pages:
- Icon: 🚧
- Heading: "Under Development"
- Subtext: "**{feature}** is not yet available. Check back in a future update." (falls back to "This feature" when no `feature` param is given)
- Button: "← Go Back" (`history.back()` via onclick)

### Links updated to point here

| Label | Old href | New href |
|-------|----------|----------|
| General Ledger | `url_for('customers.list_customers')` | `url_for('dashboard.under_development', feature='General Ledger')` |
| Cash Flow | `#` | `url_for('dashboard.under_development', feature='Cash Flow')` |
| Annual ITR | `#` | `url_for('dashboard.under_development', feature='Annual ITR')` |

---

## Part 2 — Sidebar role fixes

### User Management gate
**File:** `app/templates/base.html`

Change the User Management link condition:
```jinja2
{# Before #}
{% if current_user.role in ['admin', 'accountant'] %}
{# After #}
{% if current_user.role == 'admin' %}
```

### Admin section visibility
Wrap the entire Admin `<div class="nav-section">` in a role check so staff and viewer do not see an empty "Admin" header:

```jinja2
{% if current_user.is_authenticated and current_user.role in ['admin', 'accountant'] %}
<div class="nav-section">
    <!-- Admin section content -->
</div>
{% endif %}
```

Accountants continue to see the Audit Log link (unchanged). They no longer see User Management.

---

## Part 3 — Receipts & Payments split

### Sidebar (Transactions section)
Replace the single "Receipts & Payments" link with two entries:

```jinja2
<a href="{{ url_for('receipts.list_receipts') }}?type=collection" class="nav-item ...">
    <span class="nav-icon">💰</span>
    <span class="nav-text">Collections</span>
</a>
<a href="{{ url_for('receipts.list_receipts') }}?type=payment" class="nav-item ...">
    <span class="nav-icon">💸</span>
    <span class="nav-text">Payments</span>
</a>
```

Active-state logic: highlight Collections when `request.endpoint == 'receipts.list_receipts'` and `request.args.get('type') == 'collection'`, similarly for Payments.

### + New dropdown
Wire the two placeholder entries:

```jinja2
<a href="{{ url_for('receipts.create_receipt') }}?transaction_type=collection" class="topbar-new-item">
    💰 New Collection
</a>
<a href="{{ url_for('receipts.create_receipt') }}?transaction_type=payment" class="topbar-new-item">
    💸 New Payment
</a>
```

The receipts module already handles both types via the `transaction_type` query param — no backend changes needed.

---

## Verification

1. Log in as **accountant** → sidebar shows no User Management; Admin section is visible with only Audit Log
2. Log in as **staff** or **viewer** → Admin section is completely hidden
3. Click General Ledger / Cash Flow / Annual ITR → land on Under Development page with correct feature name; Back button returns to previous page
4. Sidebar Transactions shows "Collections" and "Payments" as separate links; each filters the receipts list correctly
5. "+ New → New Collection" opens the collection create form; "New Payment" opens the payment create form
