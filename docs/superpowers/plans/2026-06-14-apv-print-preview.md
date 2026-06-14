# APV Print Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a print-ready APV page, a Print button on the detail page, and an app setting controlling whether drafts or only posted vouchers can be printed.

**Architecture:** Three independent tasks: (1) add `apv_print_access` to company settings, (2) add the `/purchase-bills/<id>/print` route and standalone template, (3) add the Print button to the detail page using the new setting. No model changes. No migrations.

**Tech Stack:** Flask, Jinja2, openpyxl (unused here), SQLAlchemy, AppSettings key-value store, `@media print` CSS

**Spec:** `docs/superpowers/specs/2026-06-14-apv-print-preview-design.md`

---

### Task 1: Add `apv_print_access` app setting

**Files:**
- Modify: `app/company_settings/forms.py`
- Modify: `app/company_settings/views.py`
- Modify: `app/company_settings/templates/company_settings/form.html`

**Context:**
- `SETTINGS_KEYS` in `views.py` is the authoritative list of keys the form saves. Adding a key there is all that's needed on the backend — `AppSettings.set_setting` is called in a loop over that list.
- The form template uses `render_field(form.<field>)` inside card sections. Add a new "Documents" card after the "Accounting" section (line ~173) and before the `<div class="form-actions">` block.
- Default value when unset: `'posted_only'` — always use `AppSettings.get_setting('apv_print_access', 'posted_only')`.

- [ ] **Step 1: Add the SelectField to the form**

In `app/company_settings/forms.py`, add after the existing imports:

```python
APV_PRINT_ACCESS_CHOICES = [
    ('posted_only', 'Posted only'),
    ('draft_and_posted', 'Draft and posted'),
]
```

And add this field to `CompanySettingsForm` at the end of the class, after `officer_secretary`:

```python
    # Documents
    apv_print_access = SelectField(
        'APV Print Access', choices=APV_PRINT_ACCESS_CHOICES
    )
```

- [ ] **Step 2: Add key to SETTINGS_KEYS**

In `app/company_settings/views.py`, find `SETTINGS_KEYS = [` (line ~39). Add `'apv_print_access'` at the end of the list:

```python
SETTINGS_KEYS = [
    'company_name',
    'trade_name',
    'company_tin',
    'tin_branch_code',
    'rdo_code',
    'vat_registration_type',
    'company_address',
    'postal_code',
    'phone',
    'email',
    'fiscal_year_start',
    'officer_president',
    'officer_treasurer',
    'officer_secretary',
    'apv_print_access',
]
```

- [ ] **Step 3: Add the Documents section to the settings template**

In `app/company_settings/templates/company_settings/form.html`, find the closing `</div>` of the Accounting card (around line 173), just before `<div class="form-actions">`. Insert after the Accounting card:

```html
    <h3 class="settings-section-label settings-section-label--spaced">Documents</h3>
    <div class="card settings-card">
        <div class="card-body">
            <div class="settings-grid-2">
                {{ render_field(form.apv_print_access) }}
            </div>
        </div>
    </div>
```

- [ ] **Step 4: Verify manually**

Start the dev server (`python flask_app.py`). Log in as admin, go to Company Settings. Confirm:
- "Documents" section appears with "APV Print Access" dropdown
- Saving "Draft and posted" persists (reload page, value is still "Draft and posted")
- Saving "Posted only" persists

- [ ] **Step 5: Commit**

```
git add app/company_settings/forms.py app/company_settings/views.py app/company_settings/templates/company_settings/form.html
git commit -m "feat: add apv_print_access app setting under Documents"
```

---

### Task 2: Print preview route and template

**Files:**
- Modify: `app/purchase_bills/views.py` — add `print_bill` route after the `view` route (line ~630)
- Create: `app/purchase_bills/templates/purchase_bills/print.html`

**Context:**
- `_get_bill_or_404(id)` at line 255 in `views.py` handles both 404-if-missing and branch scope check (aborts 404 if `bill.branch_id != session['selected_branch_id']`). Use it.
- `AppSettings.get_setting` is already imported indirectly via `app.settings` — import it in the route.
- Journal entry lines are on `bill.journal_entry.lines.all()`. Sort them: non-Input-VAT debits first (by account code), Input VAT debits last among debits (by account code), then credits (by account code). Identify Input VAT accounts via `{c.input_vat_account_id for c in VATCategory.query.all() if c.input_vat_account_id}`. `VATCategory` is already imported in `views.py`.
- `ph_now()` is already imported in `views.py`.
- Company details come from `AppSettings.get_setting(key, '')`.
- The template must be standalone (no `{% extends "base.html" %}`).

- [ ] **Step 1: Add the route to views.py**

In `app/purchase_bills/views.py`, after the `view` route (after line 630), insert:

```python
@purchase_bills_bp.route('/purchase-bills/<int:id>/print')
@login_required
def print_bill(id):
    """Standalone print preview for an APV."""
    from app.settings import AppSettings
    bill = _get_bill_or_404(id)

    # Sort JE lines: non-VAT debits → VAT debits → credits, each by account code
    je_lines = []
    if bill.journal_entry:
        vat_account_ids = {
            c.input_vat_account_id
            for c in VATCategory.query.all()
            if c.input_vat_account_id
        }
        lines = bill.journal_entry.lines.all()
        debit_non_vat = sorted(
            [l for l in lines if (l.debit_amount or 0) > 0 and l.account_id not in vat_account_ids],
            key=lambda l: l.account.code
        )
        debit_vat = sorted(
            [l for l in lines if (l.debit_amount or 0) > 0 and l.account_id in vat_account_ids],
            key=lambda l: l.account.code
        )
        credits = sorted(
            [l for l in lines if (l.credit_amount or 0) > 0],
            key=lambda l: l.account.code
        )
        je_lines = debit_non_vat + debit_vat + credits

    company = {
        'name': AppSettings.get_setting('company_name', ''),
        'address': AppSettings.get_setting('company_address', ''),
        'tin': AppSettings.get_setting('company_tin', ''),
    }

    return render_template(
        'purchase_bills/print.html',
        bill=bill,
        je_lines=je_lines,
        company=company,
        printed_at=ph_now(),
    )
```

- [ ] **Step 2: Create the print template**

Create `app/purchase_bills/templates/purchase_bills/print.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>APV {{ bill.bill_number }}</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: Arial, sans-serif; font-size: 11px; color: #111; background: #fff; }

  .screen-only { }
  @media print {
    .screen-only { display: none !important; }
    @page { size: A4 portrait; margin: 15mm; }
  }

  /* Screen wrapper to simulate A4 */
  .page-wrap { max-width: 740px; margin: 0 auto; padding: 24px; }

  /* Header */
  .apv-header { text-align: center; border-bottom: 2px solid #111; padding-bottom: 10px; margin-bottom: 12px; }
  .apv-header .company-name { font-size: 16px; font-weight: 700; letter-spacing: .5px; }
  .apv-header .company-sub { font-size: 10px; color: #444; margin-top: 2px; }
  .apv-header .doc-title { font-size: 14px; font-weight: 700; letter-spacing: 2px; margin-top: 8px; }

  /* Info row */
  .info-row { display: flex; gap: 16px; margin-bottom: 10px; }
  .info-row table { border-collapse: collapse; flex: 1; font-size: 10px; }
  .info-row td { border: 1px solid #aaa; padding: 3px 7px; }
  .info-row td.label { background: #f0f0f0; font-weight: 600; width: 42%; }
  .vendor-header { background: #222; color: #fff; font-weight: 700; }

  /* Particulars */
  .particulars { width: 100%; border-collapse: collapse; font-size: 10px; margin-bottom: 10px; }
  .particulars th { background: #222; color: #fff; padding: 4px 7px; text-align: left; border: 1px solid #555; }
  .particulars td { border: 1px solid #aaa; padding: 3px 7px; }
  .particulars td.amount { text-align: right; font-family: monospace; }

  /* JE + Summary row */
  .je-summary-row { display: flex; gap: 12px; margin-bottom: 10px; }
  .je-block { flex: 1; }
  .summary-block { flex: 0 0 210px; }
  .section-label { font-weight: 700; font-size: 10px; border: 1px solid #aaa; border-bottom: none; padding: 3px 7px; background: #f0f0f0; }
  .je-table { width: 100%; border-collapse: collapse; font-size: 10px; }
  .je-table th { background: #ddd; border: 1px solid #aaa; padding: 3px 7px; text-align: left; }
  .je-table th.num { text-align: right; }
  .je-table td { border: 1px solid #aaa; padding: 3px 7px; }
  .je-table td.num { text-align: right; font-family: monospace; }
  .je-table tr.totals { font-weight: 700; background: #f0f0f0; }
  .summary-inner { border: 1px solid #aaa; padding: 10px 12px; font-size: 10px; }
  .summary-row { display: flex; justify-content: space-between; margin-bottom: 7px; }
  .summary-row .slabel { color: #555; }
  .summary-row .sval { font-family: monospace; font-weight: 600; }
  .summary-row .sval.red { color: #c00; }
  .summary-divider { height: 1px; background: #ccc; margin: 6px 0; }
  .summary-divider-double { height: 2px; background: #888; margin: 8px 0; }
  .summary-net { display: flex; justify-content: space-between; }
  .summary-net .netlabel { font-weight: 700; font-size: 11px; }
  .summary-net .netval { font-family: monospace; font-weight: 700; font-size: 13px; color: #1565c0; }

  /* Notes */
  .notes-box { border: 1px solid #aaa; padding: 5px 8px; margin-bottom: 10px; background: #fffde7; font-size: 10px; }
  .notes-box .notes-label { font-weight: 700; font-size: 9px; color: #555; text-transform: uppercase; margin-right: 8px; }

  /* Signatures */
  .sig-row { display: flex; margin-top: 8px; }
  .sig-box { flex: 1; border: 1px solid #aaa; border-right: none; padding: 5px 7px; min-height: 56px; }
  .sig-box:last-child { border-right: 1px solid #aaa; }
  .sig-box .sig-title { font-size: 9px; font-weight: 700; color: #555; margin-bottom: 24px; }
  .sig-box .sig-line { border-top: 1px solid #666; padding-top: 2px; font-size: 9px; color: #555; }

  /* Footer */
  .audit-footer { margin-top: 6px; font-size: 9px; color: #888; text-align: center; border-top: 1px solid #ddd; padding-top: 4px; }

  /* Print button */
  .print-bar { margin-bottom: 20px; display: flex; gap: 8px; }
  .btn-print { padding: 8px 20px; background: #1565c0; color: #fff; border: none; border-radius: 4px; font-size: 13px; cursor: pointer; }
  .btn-close { padding: 8px 20px; background: #666; color: #fff; border: none; border-radius: 4px; font-size: 13px; cursor: pointer; text-decoration: none; }
</style>
</head>
<body>
<div class="page-wrap">

  <!-- Screen-only controls -->
  <div class="print-bar screen-only">
    <button class="btn-print" onclick="window.print()">Print</button>
    <a class="btn-close" href="{{ url_for('purchase_bills.view', id=bill.id) }}">Close</a>
  </div>

  <!-- Company header -->
  <div class="apv-header">
    <div class="company-name">{{ company.name | upper }}</div>
    <div class="company-sub">
      {{ company.address }}{% if company.address and company.tin %} &nbsp;·&nbsp; {% endif %}{% if company.tin %}TIN: {{ company.tin }}{% endif %}
    </div>
    <div class="doc-title">ACCOUNTS PAYABLE VOUCHER</div>
  </div>

  <!-- Info row -->
  <div class="info-row">
    <table>
      <tr><td class="label">APV No.</td><td><strong>{{ bill.bill_number }}</strong></td></tr>
      <tr><td class="label">Date</td><td>{{ bill.bill_date.strftime('%d %B %Y') }}</td></tr>
      <tr><td class="label">Due Date</td><td>{{ bill.due_date.strftime('%d %B %Y') if bill.due_date else '—' }}</td></tr>
      <tr><td class="label">Terms</td><td>{{ bill.payment_terms or '—' }}</td></tr>
    </table>
    <table>
      <tr><td colspan="2" class="label vendor-header">VENDOR</td></tr>
      <tr><td colspan="2"><strong>{{ bill.vendor_name }}</strong></td></tr>
      <tr><td class="label">TIN</td><td>{{ bill.vendor_tin or '—' }}</td></tr>
      <tr><td class="label">Invoice No.</td><td>{{ bill.vendor_invoice_number or '—' }}</td></tr>
      <tr><td class="label">Invoice Date</td><td>{{ bill.vendor_invoice_date.strftime('%d %B %Y') if bill.vendor_invoice_date else '—' }}</td></tr>
    </table>
  </div>

  <!-- Particulars -->
  <table class="particulars">
    <thead>
      <tr>
        <th style="width:4%">#</th>
        <th>Description / Particulars</th>
        <th style="width:18%;text-align:right">Amount</th>
        <th style="width:26%">Account</th>
      </tr>
    </thead>
    <tbody>
      {% for item in bill.line_items.order_by('line_number').all() %}
      <tr>
        <td>{{ item.line_number }}</td>
        <td>{{ item.description }}</td>
        <td class="amount">{{ '{:,.2f}'.format(item.amount) }}</td>
        <td>{{ item.account.name if item.account else '—' }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>

  <!-- Journal Entry + Summary -->
  <div class="je-summary-row">
    <!-- Journal Entry -->
    <div class="je-block">
      <div class="section-label">JOURNAL ENTRY</div>
      <table class="je-table">
        <thead>
          <tr>
            <th style="width:14%">Code</th>
            <th>Account Title</th>
            <th class="num" style="width:22%">Debit</th>
            <th class="num" style="width:22%">Credit</th>
          </tr>
        </thead>
        <tbody>
          {% set total_debit = namespace(v=0) %}
          {% set total_credit = namespace(v=0) %}
          {% for line in je_lines %}
          {% set dr = line.debit_amount or 0 %}
          {% set cr = line.credit_amount or 0 %}
          {% set total_debit.v = total_debit.v + dr %}
          {% set total_credit.v = total_credit.v + cr %}
          <tr>
            <td>{{ line.account.code }}</td>
            <td>{{ line.account.name }}</td>
            <td class="num">{% if dr %}{{ '{:,.2f}'.format(dr) }}{% endif %}</td>
            <td class="num">{% if cr %}{{ '{:,.2f}'.format(cr) }}{% endif %}</td>
          </tr>
          {% endfor %}
        </tbody>
        <tfoot>
          <tr class="totals">
            <td colspan="2">TOTAL</td>
            <td class="num">{{ '{:,.2f}'.format(total_debit.v) }}</td>
            <td class="num">{{ '{:,.2f}'.format(total_credit.v) }}</td>
          </tr>
        </tfoot>
      </table>
    </div>

    <!-- Summary -->
    <div class="summary-block">
      <div class="section-label">SUMMARY</div>
      <div class="summary-inner">
        <div class="summary-row">
          <span class="slabel">Gross Amount:</span>
          <span class="sval">&#8369;{{ '{:,.2f}'.format(bill.subtotal) }}</span>
        </div>
        <div class="summary-row">
          <span class="slabel">Less: Input VAT:</span>
          <span class="sval">&#8369;{{ '{:,.2f}'.format(bill.vat_amount) }}</span>
        </div>
        <div class="summary-divider"></div>
        <div class="summary-row">
          <span class="slabel">Net of VAT:</span>
          <span class="sval">&#8369;{{ '{:,.2f}'.format(bill.subtotal - bill.vat_amount) }}</span>
        </div>
        <div class="summary-row">
          <span class="slabel">Add: Input VAT:</span>
          <span class="sval">&#8369;{{ '{:,.2f}'.format(bill.vat_amount) }}</span>
        </div>
        <div class="summary-row">
          <span class="slabel">Less: Withholding Tax:</span>
          <span class="sval red">-&#8369;{{ '{:,.2f}'.format(bill.withholding_tax_amount) }}</span>
        </div>
        <div class="summary-divider-double"></div>
        <div class="summary-net">
          <span class="netlabel">Net Amount Payable:</span>
          <span class="netval">&#8369;{{ '{:,.2f}'.format(bill.total_amount) }}</span>
        </div>
      </div>
    </div>
  </div>

  <!-- Notes -->
  {% if bill.notes %}
  <div class="notes-box">
    <span class="notes-label">Notes:</span>{{ bill.notes }}
  </div>
  {% endif %}

  <!-- Signatures -->
  <div class="sig-row">
    <div class="sig-box">
      <div class="sig-title">PREPARED BY</div>
      <div class="sig-line">Name &amp; Date</div>
    </div>
    <div class="sig-box">
      <div class="sig-title">REVIEWED BY</div>
      <div class="sig-line">Name &amp; Date</div>
    </div>
    <div class="sig-box">
      <div class="sig-title">APPROVED BY</div>
      <div class="sig-line">Name &amp; Date</div>
    </div>
  </div>

  <!-- Audit footer (posted bills only) -->
  {% if bill.status != 'draft' and bill.posted_by %}
  <div class="audit-footer">
    Posted by: {{ bill.posted_by.username }} &nbsp;·&nbsp; {{ bill.posted_at.strftime('%d %b %Y') if bill.posted_at else '' }}
    &nbsp;|&nbsp; Printed: {{ printed_at.strftime('%d %b %Y %I:%M %p') }}
  </div>
  {% endif %}

</div>
</body>
</html>
```

- [ ] **Step 3: Verify manually**

Navigate to `http://127.0.0.1:5000/purchase-bills/30/print` (or any existing bill ID). Confirm:
- Page loads without sidebar or navbar
- Company name, APV number, vendor, line items, JE, summary, signature boxes all render
- "Print" button triggers browser print dialog
- "Close" link returns to the detail page

- [ ] **Step 4: Commit**

```
git add app/purchase_bills/views.py app/purchase_bills/templates/purchase_bills/print.html
git commit -m "feat: APV print preview route and standalone template"
```

---

### Task 3: Print button on APV detail page

**Files:**
- Modify: `app/purchase_bills/views.py` — pass `apv_print_access` to the `view` route's template context
- Modify: `app/purchase_bills/templates/purchase_bills/detail.html` — add Print button with visibility logic

**Context:**
- The `view` route is at line 623 of `views.py`. It currently renders `detail.html` with `bill` and `je_entries`.
- Button visibility: if `apv_print_access == 'posted_only'`, show only when `bill.status in ('posted', 'partially_paid', 'paid')`. If `draft_and_posted`, show when `bill.status not in ('voided', 'cancelled')`.
- The action bar in `detail.html` contains the existing Edit, Post, Cancel, Void buttons. Find it by searching for `url_for('purchase_bills.edit'` in that template.

- [ ] **Step 1: Pass apv_print_access from the view**

In `app/purchase_bills/views.py`, update the `view` function (line 625):

```python
@purchase_bills_bp.route('/purchase-bills/<int:id>')
@login_required
def view(id):
    """View purchase bill details."""
    from app.settings import AppSettings
    bill = _get_bill_or_404(id)
    je_entries = _build_je_preview(bill)
    apv_print_access = AppSettings.get_setting('apv_print_access', 'posted_only')
    return render_template('purchase_bills/detail.html', bill=bill,
                           je_entries=je_entries,
                           apv_print_access=apv_print_access)
```

- [ ] **Step 2: Add Print button to detail template**

In `app/purchase_bills/templates/purchase_bills/detail.html`, find the action bar section containing `url_for('purchase_bills.edit'`. Add the Print button inside that block:

```html
{% if (apv_print_access == 'posted_only' and bill.status in ('posted', 'partially_paid', 'paid'))
   or (apv_print_access == 'draft_and_posted' and bill.status not in ('voided', 'cancelled')) %}
<a href="{{ url_for('purchase_bills.print_bill', id=bill.id) }}"
   target="_blank"
   class="btn btn-secondary">Print</a>
{% endif %}
```

Place this just before or after the Edit button — keep consistent with the other action buttons in that bar.

- [ ] **Step 3: Verify manually — posted_only (default)**

1. Go to Company Settings → Documents → set "APV Print Access" to "Posted only" → Save
2. Open a **draft** APV → confirm no Print button
3. Open a **posted** APV → confirm Print button appears → click it → new tab opens with print preview

- [ ] **Step 4: Verify manually — draft_and_posted**

1. Go to Company Settings → set "APV Print Access" to "Draft and posted" → Save
2. Open a **draft** APV → confirm Print button appears → click it → print preview loads
3. Open a **voided** or **cancelled** APV → confirm no Print button

- [ ] **Step 5: Commit**

```
git add app/purchase_bills/views.py app/purchase_bills/templates/purchase_bills/detail.html
git commit -m "feat: Print button on APV detail page; visibility controlled by apv_print_access setting"
```
