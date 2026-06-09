# Vendor Module Overhaul Design

**Date:** 2026-06-09
**Scope:** `app/vendors/` — list, create, edit, delete, new detail page
**Approach:** Cleanup existing CRUD bugs + add vendor detail page with AP aging and bill history

---

## Problem

The vendors module has several bugs and gaps:

1. `list.html` used non-existent fields `vendor.default_vat` and `vendor.default_wt` — both now fixed.
2. Delete button uses `confirm()` — violates no-JS-popups rule.
3. No vendor detail/view page — staff and viewer roles have no read-only view; all users must enter edit mode to see vendor data.
4. Payment terms mismatch — form stores `'COD'` / `'Advance'` but displays `'Cash on Delivery'` / `'Advance Payment'`; the list shows the raw stored value.
5. Readonly code field on edit has no visual indicator — looks editable but isn't.
6. No test coverage for the vendor module.

---

## Out of Scope

- Vendor import (CSV/Excel)
- Vendor portal / external access
- WHT on sales invoices or receipts
- Vendor credit notes

---

## Routing

| Route | Method | Change |
|---|---|---|
| `GET /vendors` | GET | Existing — vendor name/code become links to detail; delete uses custom modal |
| `GET /vendors/<id>` | GET | **New** — vendor detail page |
| `GET /vendors/create` | GET, POST | Existing — no change |
| `GET/POST /vendors/<id>/edit` | GET, POST | Existing — readonly code visual fix; payment terms fix |
| `POST /vendors/<id>/delete` | POST | Existing — no change (modal submits here) |
| `GET /vendors/<id>/defaults` | GET | Existing AJAX endpoint — no change |

---

## Bug Fixes

### 1. Delete modal (no-JS-popups rule)

Remove `onsubmit="return confirm(...)"` from `list.html`. Replace with a custom HTML modal per vendor row following the standard delete-modal pattern from `PROJECT_FOUNDATIONS.md §3`:

```html
<!-- Trigger button -->
<button type="button" class="btn-action btn-action-delete"
        onclick="document.getElementById('delete-modal-{{ vendor.id }}').style.display='flex'">
    Delete
</button>

<!-- Modal -->
<div id="delete-modal-{{ vendor.id }}" class="modal-overlay" style="display:none;">
    <div class="modal-box">
        <p>Delete vendor <strong>{{ vendor.name }}</strong>? This cannot be undone.</p>
        <form method="POST" action="{{ url_for('vendors.delete', id=vendor.id) }}">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <div class="modal-actions">
                <button type="submit" class="btn btn-danger btn-sm">Delete</button>
                <button type="button" class="btn btn-secondary btn-sm"
                        onclick="document.getElementById('delete-modal-{{ vendor.id }}').style.display='none'">
                    Cancel
                </button>
            </div>
        </form>
    </div>
</div>
```

### 2. Payment terms consistency

**`forms.py`** — change the two affected choices:
```python
# Before
('COD', 'Cash on Delivery'),
('Advance', 'Advance Payment'),
# After
('Cash on Delivery', 'Cash on Delivery'),
('Advance Payment', 'Advance Payment'),
```

**Migration** — update existing rows:
```sql
UPDATE vendor SET payment_terms = 'Cash on Delivery' WHERE payment_terms = 'COD';
UPDATE vendor SET payment_terms = 'Advance Payment' WHERE payment_terms = 'Advance';
```

### 3. Readonly code field visual indicator

In `form.html`, on edit mode, apply a locked style to the code field:
```html
{{ form.code(
    class="form-control form-control-sm" + (" field-locked" if vendor else ""),
    readonly=(not vendor) is False,
    ...
) }}
```
Add CSS:
```css
.field-locked {
    background: #f3f4f6;
    cursor: not-allowed;
    color: #6b7280;
}
```
Also append `" (locked)"` to the field label when in edit mode.

---

## New: Vendor Detail Page

### Route

```python
@vendors_bp.route('/vendors/<int:id>')
@login_required
def detail(id):
    vendor = Vendor.query.get_or_404(id)
    # AP aging
    aging = compute_ap_aging(vendor.id)
    # WHT YTD
    wht_ytd = compute_wht_ytd(vendor.id)
    return render_template('vendors/detail.html',
                           vendor=vendor,
                           aging=aging,
                           wht_ytd=wht_ytd)
```

The same view function handles both tabs. The active tab is determined from the `tab` query param (default: `overview`). Filters and pagination are also query params, so the full URL preserves state on reload:

```
GET /vendors/<id>?tab=bills&page=1&date_from=2026-01-01&date_to=2026-06-30&status=posted
```

When `tab=overview`, the view computes aging and WHT YTD but skips the bills query. When `tab=bills`, the view runs the bills pagination query but skips aging/WHT YTD — so each tab only pays for what it needs.

### AP Aging Calculation

Computed from `PurchaseBill` records for this vendor where `status IN ('posted')` and `withholding_tax_amount` or `net_payable` is still outstanding (i.e., no Receipt linked, or partially paid). For simplicity in this iteration: **outstanding = posted bills where no receipt has been recorded against them**. (Full partial-payment tracking is a future feature.)

Aging buckets based on `due_date` relative to today (Philippine time via `ph_now()`):

| Bucket | Condition |
|---|---|
| Current | `due_date >= today` |
| 1–30 days | `today - 30 <= due_date < today` |
| 31–60 days | `today - 60 <= due_date < today - 30` |
| 61–90 days | `today - 90 <= due_date < today - 60` |
| 90+ days | `due_date < today - 90` |

Helper function in `app/vendors/utils.py` (new file):

```python
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from app.utils import ph_now

def compute_ap_aging(vendor_id):
    from app.purchase_bills.models import PurchaseBill
    today = ph_now().date()
    bills = PurchaseBill.query.filter_by(
        vendor_id=vendor_id, status='posted'
    ).all()
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
        amount = bill.net_payable or Decimal('0.00')
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
```

### WHT YTD Calculation

Sum of `PurchaseBillItem.wt_amount` grouped by `wt_id` for all posted bills for this vendor in the current calendar year.

```python
def compute_wht_ytd(vendor_id):
    from app.purchase_bills.models import PurchaseBill, PurchaseBillItem
    from sqlalchemy import extract
    year = ph_now().year
    rows = (
        db.session.query(
            PurchaseBillItem.wt_id,
            PurchaseBillItem.wt_rate,
            db.func.sum(PurchaseBillItem.wt_amount).label('total')
        )
        .join(PurchaseBill)
        .filter(
            PurchaseBill.vendor_id == vendor_id,
            PurchaseBill.status == 'posted',
            extract('year', PurchaseBill.bill_date) == year,
            PurchaseBillItem.wt_id.isnot(None)
        )
        .group_by(PurchaseBillItem.wt_id, PurchaseBillItem.wt_rate)
        .all()
    )
    from app.withholding_tax.models import WithholdingTax
    result = []
    for row in rows:
        wt = WithholdingTax.query.get(row.wt_id)
        if wt:
            result.append({'code': wt.code, 'name': wt.name, 'total': row.total})
    return result
```

### Bills Tab Query

```python
from app.purchase_bills.models import PurchaseBill

query = PurchaseBill.query.filter_by(vendor_id=vendor.id)

if date_from:
    query = query.filter(PurchaseBill.bill_date >= date_from)
if date_to:
    query = query.filter(PurchaseBill.bill_date <= date_to)
if status and status != 'all':
    query = query.filter(PurchaseBill.status == status)

query = query.order_by(PurchaseBill.bill_date.desc())
pagination = query.paginate(page=page, per_page=20, error_out=False)
```

### Detail Page Template Layout

`templates/vendors/detail.html`:

```
[Vendor Name — Code]          [Edit Vendor button]

[Overview] [Bills (N)]        ← tab bar

— Overview tab —
┌─────────────────────┐  ┌──────────────────────────────┐
│  Vendor Info        │  │  AP Aging (posted bills)     │
│  Code:              │  │  Current:          ₱0.00     │
│  Name:              │  │  1–30 days:        ₱0.00     │
│  TIN:               │  │  31–60 days:       ₱0.00     │
│  Contact:           │  │  61–90 days:       ₱0.00     │
│  Phone:             │  │  90+ days:         ₱0.00     │
│  Email:             │  │  Total Outstanding:₱0.00     │
│  Address:           │  ├──────────────────────────────┤
│  Terms:             │  │  WHT Withheld YTD            │
│  Default VAT: badge │  │  WC010 Professional Fees:    │
│  Default WT: badges │  │                    ₱0.00     │
│  Status:            │  └──────────────────────────────┘
└─────────────────────┘

— Bills tab —
[Date From] [Date To] [Status ▼] [Filter] [Clear]

Bill # | Date | Due Date | Subtotal | VAT | WHT | Net Payable | Status
...20 rows...
[pagination]
```

The "Bills (N)" tab label shows the total count of bills for this vendor (all time, all statuses).

---

## List Page Changes

- `vendor.code` and `vendor.name` cells wrapped in `<a href="{{ url_for('vendors.detail', id=vendor.id) }}">` 
- Delete button replaced with modal trigger (see Bug Fix #1 above)

---

## Tests

### Unit — `tests/unit/test_vendor_model.py`

- `test_vendor_defaults` — new vendor has `is_active=True`, `payment_terms='Net 30'`
- `test_ap_aging_buckets` — bills with due dates in each bucket land correctly
- `test_ap_aging_excludes_draft_void` — draft and void bills are excluded
- `test_wht_ytd_current_year_only` — prior-year bills excluded from YTD sum
- `test_wht_ytd_groups_by_code` — multiple WHT codes produce separate rows

### Integration — `tests/integration/test_vendor_views.py`

- `test_list_renders` — list page loads, vendor name is a link
- `test_detail_overview` — detail page loads, aging table present, vendor info visible
- `test_detail_bills_tab` — bills tab renders paginated list
- `test_detail_bills_date_filter` — date range filter narrows results
- `test_detail_bills_status_filter` — status filter narrows results
- `test_create_vendor` — POST creates vendor, audit log entry exists
- `test_edit_vendor` — POST updates vendor, audit log entry exists
- `test_delete_vendor` — POST deletes vendor, audit log entry exists
- `test_staff_cannot_edit` — staff user gets redirected on edit/delete
- `test_staff_can_view_detail` — staff user can access detail page
