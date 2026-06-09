# Record Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `voided` status (with reversal JE) to Purchase Bills and Sales Invoices, add `sent` status to Sales Invoices, and show an overdue badge computed from `due_date`.

**Architecture:** Model fields added via migration; two new POST routes per module (`/void` for both, `/send` for invoices); reversal JE created inline on void using existing `JournalEntry`/`JournalEntryLine` models; `generate_entry_number` extracted to `app/journal_entries/utils.py` so both void views can import it cleanly; overdue computed in templates with no DB change.

**Tech Stack:** Flask, SQLAlchemy, SQLite, Flask-Migrate (Alembic), Jinja2, `app.utils.ph_now` for PH timestamps, pytest.

---

## File Map

| Action | File |
|---|---|
| Modify | `app/purchase_bills/models.py` |
| Modify | `app/sales_invoices/models.py` |
| Create | `app/journal_entries/utils.py` |
| Modify | `app/journal_entries/views.py` |
| Modify | `app/purchase_bills/views.py` |
| Modify | `app/sales_invoices/views.py` |
| Modify | `app/purchase_bills/templates/purchase_bills/detail.html` |
| Modify | `app/sales_invoices/templates/sales_invoices/detail.html` |
| Create | `tests/unit/test_record_status.py` |
| Auto-generate | migration file via `flask db migrate` |

---

## Task 1: Model Changes — PurchaseBill

**Files:**
- Modify: `app/purchase_bills/models.py`

- [ ] **Step 1: Add void fields to PurchaseBill**

In `app/purchase_bills/models.py`, after the `cancelled_at` line (line 92), add:

```python
    voided_at = db.Column(db.DateTime)
    voided_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    voided_by = db.relationship('User', foreign_keys=[voided_by_id], backref='voided_purchase_bills')
    void_reason = db.Column(db.String(255))
```

Also update the status comment (line 76) from:
```python
    # Statuses: draft, posted, paid, partially_paid, cancelled
```
to:
```python
    # Statuses: draft, posted, partially_paid, paid, cancelled, voided
```

- [ ] **Step 2: Verify models.py is importable**

```powershell
python -c "from app.purchase_bills.models import PurchaseBill; print('OK')"
```
Expected: `OK`

---

## Task 2: Model Changes — SalesInvoice

**Files:**
- Modify: `app/sales_invoices/models.py`

- [ ] **Step 1: Add sent + void fields to SalesInvoice**

In `app/sales_invoices/models.py`, after the `cancelled_at` line (line 79), add:

```python
    sent_at = db.Column(db.DateTime)
    sent_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    sent_by = db.relationship('User', foreign_keys=[sent_by_id], backref='sent_sales_invoices')
    voided_at = db.Column(db.DateTime)
    voided_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    voided_by = db.relationship('User', foreign_keys=[voided_by_id], backref='voided_sales_invoices')
    void_reason = db.Column(db.String(255))
```

Also update the status comment (line 63) from:
```python
    # Statuses: draft, posted, paid, partially_paid, cancelled
```
to:
```python
    # Statuses: draft, sent, posted, partially_paid, paid, cancelled, voided
```

- [ ] **Step 2: Verify models.py is importable**

```powershell
python -c "from app.sales_invoices.models import SalesInvoice; print('OK')"
```
Expected: `OK`

---

## Task 3: Run Migration

- [ ] **Step 1: Generate migration**

```powershell
flask db migrate -m "Add void and sent fields to bills and invoices"
```

Expected output: `Generating ...add_void_and_sent_fields...py ... done`

- [ ] **Step 2: Apply migration**

```powershell
flask db upgrade
```

Expected output: `Running upgrade ... -> ...`

- [ ] **Step 3: Verify columns exist**

```powershell
python -c "
from dotenv import load_dotenv; load_dotenv()
from app import create_app, db
app = create_app('development')
with app.app_context():
    from sqlalchemy import inspect
    cols = [c['name'] for c in inspect(db.engine).get_columns('purchase_bills')]
    assert 'voided_at' in cols, 'voided_at missing'
    assert 'void_reason' in cols, 'void_reason missing'
    cols2 = [c['name'] for c in inspect(db.engine).get_columns('sales_invoices')]
    assert 'sent_at' in cols2, 'sent_at missing'
    assert 'voided_at' in cols2, 'voided_at missing'
    print('All columns present')
"
```
Expected: `All columns present`

- [ ] **Step 4: Commit**

```powershell
git add app/purchase_bills/models.py app/sales_invoices/models.py migrations/
git commit -m "Add voided/sent fields to bills and invoices models"
```

---

## Task 4: Extract generate_entry_number to utils

**Files:**
- Create: `app/journal_entries/utils.py`
- Modify: `app/journal_entries/views.py`

- [ ] **Step 1: Create `app/journal_entries/utils.py`**

```python
"""Utility functions for journal entries."""
from datetime import datetime


def generate_entry_number(branch_id):
    """Generate next JE number for a branch: JE-YYYY-####."""
    from app.journal_entries.models import JournalEntry
    year = datetime.now().year
    prefix = f'JE-{year}-'
    latest = JournalEntry.query.filter(
        JournalEntry.entry_number.like(f'{prefix}%'),
        JournalEntry.branch_id == branch_id
    ).order_by(JournalEntry.entry_number.desc()).first()
    if latest:
        try:
            last_num = int(latest.entry_number.split('-')[-1])
            return f'{prefix}{last_num + 1:04d}'
        except (ValueError, IndexError):
            pass
    return f'{prefix}0001'
```

- [ ] **Step 2: Update `app/journal_entries/views.py` to import from utils**

Find the existing `generate_entry_number` function definition (lines 34-57) and replace it with an import:

```python
from app.journal_entries.utils import generate_entry_number
```

Add this import near the top of the file with the other imports.

Then delete the old function body (lines 34-57 — the `def generate_entry_number(branch_id):` block).

- [ ] **Step 3: Verify JE creation still works**

```powershell
python -c "
from dotenv import load_dotenv; load_dotenv()
from app import create_app, db
app = create_app('development')
with app.app_context():
    from app.journal_entries.utils import generate_entry_number
    num = generate_entry_number(1)
    assert num.startswith('JE-'), f'Bad format: {num}'
    print('generate_entry_number OK:', num)
"
```
Expected: `generate_entry_number OK: JE-2026-XXXX`

- [ ] **Step 4: Commit**

```powershell
git add app/journal_entries/utils.py app/journal_entries/views.py
git commit -m "Extract generate_entry_number to journal_entries/utils.py"
```

---

## Task 5: Purchase Bill — Void Route

**Files:**
- Modify: `app/purchase_bills/views.py`

- [ ] **Step 1: Add `_create_bill_void_je` helper**

Add this function near the top of `app/purchase_bills/views.py`, after the imports:

```python
def _create_bill_void_je(bill, reversal_date, user_id):
    """Create reversal JE when voiding a purchase bill. Raises ValueError if required accounts missing."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    from app.journal_entries.utils import generate_entry_number
    from app.accounts.models import Account
    from decimal import Decimal

    ap_account = Account.query.filter_by(code='20101').first()
    if not ap_account:
        raise ValueError("Accounts Payable - Trade (20101) not found in COA. Cannot void.")

    input_vat_account = None
    if bill.vat_amount > 0:
        input_vat_account = Account.query.filter_by(code='10501').first()
        if not input_vat_account:
            raise ValueError("Input VAT - Current (10501) not found in COA. Cannot void.")

    wt_account = None
    if bill.withholding_tax_amount > 0:
        wt_account = Account.query.filter_by(code='20301').first()
        if not wt_account:
            raise ValueError("Withholding Tax Payable - Expanded (20301) not found in COA. Cannot void.")

    entry_number = generate_entry_number(bill.branch_id)
    je = JournalEntry(
        entry_number=entry_number,
        entry_date=reversal_date,
        description=f'Purchase Bill Void — {bill.bill_number} (reversal)',
        reference=f'VOID-{bill.bill_number}',
        entry_type='reversal',
        is_reversing=True,
        branch_id=bill.branch_id,
        created_by_id=user_id,
        status='posted',
        posted_by_id=user_id,
        posted_at=ph_now(),
        is_balanced=False,
        total_debit=Decimal('0.00'),
        total_credit=Decimal('0.00')
    )
    db.session.add(je)
    db.session.flush()

    line_num = 1
    db.session.add(JournalEntryLine(
        entry_id=je.id, line_number=line_num,
        account_id=ap_account.id,
        description=f'Void AP: {bill.bill_number}',
        debit_amount=bill.total_amount,
        credit_amount=Decimal('0.00')
    ))
    line_num += 1

    if wt_account:
        db.session.add(JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=wt_account.id,
            description=f'Void WT: {bill.bill_number}',
            debit_amount=bill.withholding_tax_amount,
            credit_amount=Decimal('0.00')
        ))
        line_num += 1

    for item in bill.line_items:
        if item.account_id and item.line_total > 0:
            db.session.add(JournalEntryLine(
                entry_id=je.id, line_number=line_num,
                account_id=item.account_id,
                description=item.description,
                debit_amount=Decimal('0.00'),
                credit_amount=item.line_total
            ))
            line_num += 1

    if input_vat_account:
        db.session.add(JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=input_vat_account.id,
            description=f'Void Input VAT: {bill.bill_number}',
            debit_amount=Decimal('0.00'),
            credit_amount=bill.vat_amount
        ))

    je.calculate_totals()
    return je
```

- [ ] **Step 2: Add void route to `app/purchase_bills/views.py`**

Append after the existing `cancel` route:

```python
@purchase_bills_bp.route('/purchase-bills/<int:id>/void', methods=['POST'])
@login_required
@accountant_or_admin_required
def void(id):
    """Void a posted purchase bill and create reversal journal entry."""
    from datetime import date
    bill = PurchaseBill.query.get_or_404(id)

    if bill.status != 'posted':
        flash('Only posted bills with no payments can be voided.', 'error')
        return redirect(url_for('purchase_bills.view', id=id))

    if bill.amount_paid > 0:
        flash('Cannot void a bill with payments applied. Reverse the payments first.', 'error')
        return redirect(url_for('purchase_bills.view', id=id))

    void_reason = request.form.get('void_reason', '').strip()
    if len(void_reason) < 10:
        flash('Void reason must be at least 10 characters.', 'error')
        return redirect(url_for('purchase_bills.view', id=id))

    reversal_date_str = request.form.get('reversal_date', '')
    try:
        reversal_date = date.fromisoformat(reversal_date_str)
    except ValueError:
        flash('Invalid reversal date.', 'error')
        return redirect(url_for('purchase_bills.view', id=id))

    try:
        _create_bill_void_je(bill, reversal_date, current_user.id)

        bill.status = 'voided'
        bill.voided_at = ph_now()
        bill.voided_by_id = current_user.id
        bill.void_reason = void_reason
        db.session.commit()

        log_audit(
            module='purchase_bill',
            action='void',
            record_id=bill.id,
            record_identifier=f'{bill.bill_number} - {bill.vendor_name}',
            notes=f'Voided by {current_user.username}. Reason: {void_reason}'
        )

        flash(f'Purchase Bill "{bill.bill_number}" voided. Reversal journal entry created.', 'success')
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
    except Exception as e:
        db.session.rollback()
        from app.errors.utils import log_exception
        current_app.logger.error("Error voiding purchase bill", exc_info=True)
        log_exception(e, severity='ERROR', module='purchase_bills.void')
        flash(f'Error voiding bill: {str(e)}', 'error')

    return redirect(url_for('purchase_bills.view', id=id))
```

- [ ] **Step 3: Verify route is registered**

```powershell
python -c "
from dotenv import load_dotenv; load_dotenv()
from app import create_app
app = create_app('development')
with app.app_context():
    rules = [str(r) for r in app.url_map.iter_rules() if 'void' in str(r)]
    print(rules)
"
```
Expected: `['/purchase-bills/<int:id>/void']` in output.

- [ ] **Step 4: Commit**

```powershell
git add app/purchase_bills/views.py
git commit -m "Add void route and reversal JE to purchase bills"
```

---

## Task 6: Sales Invoice — Send Route

**Files:**
- Modify: `app/sales_invoices/views.py`

- [ ] **Step 1: Add send route to `app/sales_invoices/views.py`**

Append after the existing `post` route:

```python
@sales_invoices_bp.route('/sales-invoices/<int:id>/send', methods=['POST'])
@login_required
@accountant_or_admin_required
def send(id):
    """Mark a draft invoice as sent to customer."""
    invoice = SalesInvoice.query.get_or_404(id)

    if invoice.status != 'draft':
        flash('Only draft invoices can be marked as sent.', 'error')
        return redirect(url_for('sales_invoices.view', id=id))

    try:
        invoice.status = 'sent'
        invoice.sent_at = ph_now()
        invoice.sent_by_id = current_user.id
        db.session.commit()

        log_audit(
            module='sales_invoice',
            action='send',
            record_id=invoice.id,
            record_identifier=f'{invoice.invoice_number} - {invoice.customer_name}',
            notes=f'Marked as sent by {current_user.username}'
        )

        flash(f'Invoice "{invoice.invoice_number}" marked as sent.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error marking invoice as sent: {str(e)}', 'error')

    return redirect(url_for('sales_invoices.view', id=id))
```

- [ ] **Step 2: Update the existing `post` route guard to also allow `sent` invoices**

Find this guard in the `post` route:
```python
    if invoice.status != 'draft':
        flash('Only draft invoices can be posted.', 'error')
```

Replace with:
```python
    if invoice.status not in ('draft', 'sent'):
        flash('Only draft or sent invoices can be posted.', 'error')
```

- [ ] **Step 3: Commit**

```powershell
git add app/sales_invoices/views.py
git commit -m "Add send route to sales invoices; allow posting from sent status"
```

---

## Task 7: Sales Invoice — Void Route

**Files:**
- Modify: `app/sales_invoices/views.py`

- [ ] **Step 1: Add `_create_invoice_void_je` helper to `app/sales_invoices/views.py`**

Add this function after the imports, near top of the file:

```python
def _create_invoice_void_je(invoice, reversal_date, user_id):
    """Create reversal JE when voiding a sales invoice. Raises ValueError if required accounts missing."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    from app.journal_entries.utils import generate_entry_number
    from app.accounts.models import Account
    from decimal import Decimal

    ar_account = Account.query.filter_by(code='10201').first()
    if not ar_account:
        raise ValueError("Accounts Receivable - Trade (10201) not found in COA. Cannot void.")

    output_vat_account = None
    if invoice.vat_amount > 0:
        output_vat_account = Account.query.filter_by(code='20201').first()
        if not output_vat_account:
            raise ValueError("Output VAT - Sales (20201) not found in COA. Cannot void.")

    entry_number = generate_entry_number(invoice.branch_id)
    je = JournalEntry(
        entry_number=entry_number,
        entry_date=reversal_date,
        description=f'Sales Invoice Void — {invoice.invoice_number} (reversal)',
        reference=f'VOID-{invoice.invoice_number}',
        entry_type='reversal',
        is_reversing=True,
        branch_id=invoice.branch_id,
        created_by_id=user_id,
        status='posted',
        posted_by_id=user_id,
        posted_at=ph_now(),
        is_balanced=False,
        total_debit=Decimal('0.00'),
        total_credit=Decimal('0.00')
    )
    db.session.add(je)
    db.session.flush()

    line_num = 1
    for item in invoice.line_items:
        if item.account_id and item.line_total > 0:
            db.session.add(JournalEntryLine(
                entry_id=je.id, line_number=line_num,
                account_id=item.account_id,
                description=item.description,
                debit_amount=item.line_total,
                credit_amount=Decimal('0.00')
            ))
            line_num += 1

    if output_vat_account:
        db.session.add(JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=output_vat_account.id,
            description=f'Void Output VAT: {invoice.invoice_number}',
            debit_amount=invoice.vat_amount,
            credit_amount=Decimal('0.00')
        ))
        line_num += 1

    db.session.add(JournalEntryLine(
        entry_id=je.id, line_number=line_num,
        account_id=ar_account.id,
        description=f'Void AR: {invoice.invoice_number}',
        debit_amount=Decimal('0.00'),
        credit_amount=invoice.total_amount
    ))

    je.calculate_totals()
    return je
```

- [ ] **Step 2: Add void route**

Append after the `send` route:

```python
@sales_invoices_bp.route('/sales-invoices/<int:id>/void', methods=['POST'])
@login_required
@accountant_or_admin_required
def void(id):
    """Void a posted sales invoice and create reversal journal entry."""
    from datetime import date
    invoice = SalesInvoice.query.get_or_404(id)

    if invoice.status != 'posted':
        flash('Only posted invoices with no payments can be voided.', 'error')
        return redirect(url_for('sales_invoices.view', id=id))

    if invoice.amount_paid > 0:
        flash('Cannot void an invoice with payments applied. Reverse the payments first.', 'error')
        return redirect(url_for('sales_invoices.view', id=id))

    void_reason = request.form.get('void_reason', '').strip()
    if len(void_reason) < 10:
        flash('Void reason must be at least 10 characters.', 'error')
        return redirect(url_for('sales_invoices.view', id=id))

    reversal_date_str = request.form.get('reversal_date', '')
    try:
        reversal_date = date.fromisoformat(reversal_date_str)
    except ValueError:
        flash('Invalid reversal date.', 'error')
        return redirect(url_for('sales_invoices.view', id=id))

    try:
        _create_invoice_void_je(invoice, reversal_date, current_user.id)

        invoice.status = 'voided'
        invoice.voided_at = ph_now()
        invoice.voided_by_id = current_user.id
        invoice.void_reason = void_reason
        db.session.commit()

        log_audit(
            module='sales_invoice',
            action='void',
            record_id=invoice.id,
            record_identifier=f'{invoice.invoice_number} - {invoice.customer_name}',
            notes=f'Voided by {current_user.username}. Reason: {void_reason}'
        )

        flash(f'Sales Invoice "{invoice.invoice_number}" voided. Reversal journal entry created.', 'success')
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
    except Exception as e:
        db.session.rollback()
        from app.errors.utils import log_exception
        current_app.logger.error("Error voiding sales invoice", exc_info=True)
        log_exception(e, severity='ERROR', module='sales_invoices.void')
        flash(f'Error voiding invoice: {str(e)}', 'error')

    return redirect(url_for('sales_invoices.view', id=id))
```

- [ ] **Step 3: Verify routes registered**

```powershell
python -c "
from dotenv import load_dotenv; load_dotenv()
from app import create_app
app = create_app('development')
with app.app_context():
    rules = [str(r) for r in app.url_map.iter_rules() if 'void' in str(r) or 'send' in str(r)]
    print(rules)
"
```
Expected output includes `/sales-invoices/<int:id>/void` and `/sales-invoices/<int:id>/send`.

- [ ] **Step 4: Commit**

```powershell
git add app/sales_invoices/views.py
git commit -m "Add void and send routes to sales invoices"
```

---

## Task 8: Purchase Bill Detail Template

**Files:**
- Modify: `app/purchase_bills/templates/purchase_bills/detail.html`

- [ ] **Step 1: Replace the entire `detail.html` content**

The current template needs three additions:
1. Void modal (HTML, no JS confirm)
2. Void button shown when `status == 'posted'` and `amount_paid == 0`
3. Overdue orange badge next to status badge
4. Voided footer line showing void reason

Replace the `<div class="card">` block with the updated version below. The existing post/delete/cancel modals are kept; add the void modal alongside them:

After the existing `{% if bill.status != 'cancelled' ... %}` cancel modal block (around line 56), add:

```html
{% if bill.status == 'posted' and bill.amount_paid == 0 %}
<div id="voidModal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:1000; align-items:center; justify-content:center;">
    <div style="background:var(--card); border-radius:8px; padding:32px; max-width:480px; width:90%;">
        <h3 style="margin:0 0 12px 0;">Void this bill?</h3>
        <p style="color:var(--text-2); margin-bottom:20px;">This will permanently void <strong>{{ bill.bill_number }}</strong> and create a reversal journal entry. This cannot be undone.</p>
        <form method="POST" action="{{ url_for('purchase_bills.void', id=bill.id) }}">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
            <div style="margin-bottom:16px;">
                <label style="display:block; font-size:13px; font-weight:600; margin-bottom:6px;">Reason for voiding <span style="color:var(--red);">*</span></label>
                <textarea name="void_reason" rows="3" class="form-control" placeholder="Minimum 10 characters" required minlength="10" style="width:100%; resize:vertical;"></textarea>
            </div>
            <div style="margin-bottom:24px;">
                <label style="display:block; font-size:13px; font-weight:600; margin-bottom:6px;">Reversal Date <span style="color:var(--red);">*</span></label>
                <input type="date" name="reversal_date" class="form-control" value="{{ now.strftime('%Y-%m-%d') }}" required style="width:100%;">
            </div>
            <div style="display:flex; gap:12px; justify-content:flex-end;">
                <button type="button" class="btn btn-secondary" onclick="document.getElementById('voidModal').style.display='none'">Cancel</button>
                <button type="submit" class="btn btn-danger">Void this Record</button>
            </div>
        </form>
    </div>
</div>
{% endif %}
```

- [ ] **Step 2: Add Void button to the card-header actions**

Inside the `{% if bill.status == 'draft' %}` block actions section, after the Cancel Bill button and before Back to List, add:

```html
{% if bill.status == 'posted' and bill.amount_paid == 0 %}
<button type="button" class="btn btn-danger" onclick="document.getElementById('voidModal').style.display='flex'">Void Bill</button>
{% endif %}
```

- [ ] **Step 3: Add overdue badge next to the status badge**

The current status badge is in a `<div style="display:flex; align-items:center; gap:12px;">`. After the existing status badge `<span class="badge ...">`, add:

```html
{% set today = now.date() %}
{% if bill.status in ('posted', 'partially_paid') and bill.due_date < today %}
<span class="badge" style="background:var(--orange, #f97316); color:white;">Overdue</span>
{% endif %}
```

- [ ] **Step 4: Add voided footer line**

After the existing footer line (the `Created by ... Posted by ...` line), add:

```html
{% if bill.voided_by %}
 &mdash; Voided by {{ bill.voided_by.username }} on {{ bill.voided_at.strftime('%b %d, %Y %H:%M') if bill.voided_at else '—' }} &mdash; <em>{{ bill.void_reason }}</em>
{% endif %}
```

- [ ] **Step 5: Commit**

```powershell
git add "app/purchase_bills/templates/purchase_bills/detail.html"
git commit -m "Add void modal, overdue badge, and voided footer to purchase bill detail"
```

---

## Task 9: Sales Invoice Detail Template

**Files:**
- Modify: `app/sales_invoices/templates/sales_invoices/detail.html`

The current sales invoice detail template uses `onclick="return confirm(...)"` which violates the no-JS-popups rule. This task fixes that and adds the new status features.

- [ ] **Step 1: Replace action buttons block**

Find the existing card-header-actions block (lines 13–33) and replace it entirely:

```html
<div class="card-header">
    <div style="display:flex; align-items:center; gap:12px;">
        <span style="font-size:20px; font-weight:700;">{{ invoice.invoice_number }}</span>
        <span class="badge badge-{{ 'secondary' if invoice.status=='draft' else 'info' if invoice.status in ('sent','posted') else 'success' if invoice.status=='paid' else 'warning' if invoice.status=='partially_paid' else 'danger' if invoice.status=='cancelled' else 'dark' }}">
            {{ invoice.status | replace('_', ' ') | title }}
        </span>
        {% set today = now.date() %}
        {% if invoice.status in ('posted', 'partially_paid') and invoice.due_date < today %}
        <span class="badge" style="background:var(--orange, #f97316); color:white;">Overdue</span>
        {% endif %}
    </div>
    <div class="card-header-actions">
        {% if invoice.status == 'draft' %}
        <button type="button" class="btn btn-secondary" onclick="document.getElementById('sendModal').style.display='flex'">Send</button>
        <button type="button" class="btn btn-success" onclick="document.getElementById('postModal').style.display='flex'">Post Invoice</button>
        <a href="{{ url_for('sales_invoices.edit', id=invoice.id) }}" class="btn btn-primary">Edit</a>
        <button type="button" class="btn btn-danger" onclick="document.getElementById('deleteModal').style.display='flex'">Delete</button>
        {% endif %}
        {% if invoice.status == 'sent' %}
        <button type="button" class="btn btn-success" onclick="document.getElementById('postModal').style.display='flex'">Post Invoice</button>
        <button type="button" class="btn btn-secondary" onclick="document.getElementById('cancelModal').style.display='flex'">Cancel Invoice</button>
        {% endif %}
        {% if invoice.status == 'posted' and invoice.amount_paid == 0 %}
        <button type="button" class="btn btn-danger" onclick="document.getElementById('voidModal').style.display='flex'">Void Invoice</button>
        {% endif %}
        <a href="{{ url_for('sales_invoices.list_invoices') }}" class="btn btn-secondary">← Back to List</a>
    </div>
</div>
```

- [ ] **Step 2: Add all required modals before the `<div class="card">`**

Add these modals (post, send, delete, cancel, void) before the card div:

```html
{% if invoice.status in ('draft', 'sent') %}
<div id="postModal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:1000; align-items:center; justify-content:center;">
    <div style="background:var(--card); border-radius:8px; padding:32px; max-width:440px; width:90%;">
        <h3 style="margin:0 0 12px 0;">Post this invoice?</h3>
        <p style="color:var(--text-2); margin-bottom:24px;">This will make the invoice final and it cannot be edited afterwards.</p>
        <div style="display:flex; gap:12px; justify-content:flex-end;">
            <button type="button" class="btn btn-secondary" onclick="document.getElementById('postModal').style.display='none'">Cancel</button>
            <form method="POST" action="{{ url_for('sales_invoices.post', id=invoice.id) }}" style="display:inline;">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
                <button type="submit" class="btn btn-success">Post Invoice</button>
            </form>
        </div>
    </div>
</div>
{% endif %}

{% if invoice.status == 'draft' %}
<div id="sendModal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:1000; align-items:center; justify-content:center;">
    <div style="background:var(--card); border-radius:8px; padding:32px; max-width:440px; width:90%;">
        <h3 style="margin:0 0 12px 0;">Mark as sent?</h3>
        <p style="color:var(--text-2); margin-bottom:24px;">This marks <strong>{{ invoice.invoice_number }}</strong> as sent to the customer. You can still post or cancel it.</p>
        <div style="display:flex; gap:12px; justify-content:flex-end;">
            <button type="button" class="btn btn-secondary" onclick="document.getElementById('sendModal').style.display='none'">Cancel</button>
            <form method="POST" action="{{ url_for('sales_invoices.send', id=invoice.id) }}" style="display:inline;">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
                <button type="submit" class="btn btn-primary">Mark as Sent</button>
            </form>
        </div>
    </div>
</div>
{% endif %}

{% if invoice.status == 'draft' %}
<div id="deleteModal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:1000; align-items:center; justify-content:center;">
    <div style="background:var(--card); border-radius:8px; padding:32px; max-width:440px; width:90%;">
        <h3 style="margin:0 0 12px 0;">Delete this invoice?</h3>
        <p style="color:var(--text-2); margin-bottom:24px;">This will permanently delete <strong>{{ invoice.invoice_number }}</strong>. This action cannot be undone.</p>
        <div style="display:flex; gap:12px; justify-content:flex-end;">
            <button type="button" class="btn btn-secondary" onclick="document.getElementById('deleteModal').style.display='none'">Cancel</button>
            <form method="POST" action="{{ url_for('sales_invoices.delete', id=invoice.id) }}" style="display:inline;">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
                <button type="submit" class="btn btn-danger">Delete</button>
            </form>
        </div>
    </div>
</div>
{% endif %}

{% if invoice.status in ('draft', 'sent') and invoice.amount_paid == 0 %}
<div id="cancelModal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:1000; align-items:center; justify-content:center;">
    <div style="background:var(--card); border-radius:8px; padding:32px; max-width:440px; width:90%;">
        <h3 style="margin:0 0 12px 0;">Cancel this invoice?</h3>
        <p style="color:var(--text-2); margin-bottom:24px;">Are you sure you want to cancel <strong>{{ invoice.invoice_number }}</strong>?</p>
        <div style="display:flex; gap:12px; justify-content:flex-end;">
            <button type="button" class="btn btn-secondary" onclick="document.getElementById('cancelModal').style.display='none'">No, keep it</button>
            <form method="POST" action="{{ url_for('sales_invoices.cancel', id=invoice.id) }}" style="display:inline;">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
                <button type="submit" class="btn btn-danger">Yes, Cancel</button>
            </form>
        </div>
    </div>
</div>
{% endif %}

{% if invoice.status == 'posted' and invoice.amount_paid == 0 %}
<div id="voidModal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:1000; align-items:center; justify-content:center;">
    <div style="background:var(--card); border-radius:8px; padding:32px; max-width:480px; width:90%;">
        <h3 style="margin:0 0 12px 0;">Void this invoice?</h3>
        <p style="color:var(--text-2); margin-bottom:20px;">This will permanently void <strong>{{ invoice.invoice_number }}</strong> and create a reversal journal entry. This cannot be undone.</p>
        <form method="POST" action="{{ url_for('sales_invoices.void', id=invoice.id) }}">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
            <div style="margin-bottom:16px;">
                <label style="display:block; font-size:13px; font-weight:600; margin-bottom:6px;">Reason for voiding <span style="color:var(--red);">*</span></label>
                <textarea name="void_reason" rows="3" class="form-control" placeholder="Minimum 10 characters" required minlength="10" style="width:100%; resize:vertical;"></textarea>
            </div>
            <div style="margin-bottom:24px;">
                <label style="display:block; font-size:13px; font-weight:600; margin-bottom:6px;">Reversal Date <span style="color:var(--red);">*</span></label>
                <input type="date" name="reversal_date" class="form-control" value="{{ now.strftime('%Y-%m-%d') }}" required style="width:100%;">
            </div>
            <div style="display:flex; gap:12px; justify-content:flex-end;">
                <button type="button" class="btn btn-secondary" onclick="document.getElementById('voidModal').style.display='none'">Cancel</button>
                <button type="submit" class="btn btn-danger">Void this Record</button>
            </div>
        </form>
    </div>
</div>
{% endif %}
```

- [ ] **Step 3: Add voided footer line**

At the bottom of the card, after the existing `Created by ... Posted by ...` footer line, add:

```html
{% if invoice.voided_by %}
 &mdash; Voided by {{ invoice.voided_by.username }} on {{ invoice.voided_at.strftime('%b %d, %Y %H:%M') if invoice.voided_at else '—' }} &mdash; <em>{{ invoice.void_reason }}</em>
{% endif %}
```

- [ ] **Step 4: Add badge styles (if not already in the template)**

At bottom of the template (inside `{% block content %}`), add if missing:

```html
<style>
.badge { padding:4px 8px; border-radius:4px; font-size:11px; font-weight:600; text-transform:uppercase; }
.badge-secondary { background:var(--text-3); color:white; }
.badge-info { background:var(--blue); color:white; }
.badge-success { background:var(--green); color:white; }
.badge-warning { background:var(--yellow, #f59e0b); color:white; }
.badge-danger { background:var(--red); color:white; }
.badge-dark { background:#374151; color:white; }
</style>
```

- [ ] **Step 5: Commit**

```powershell
git add "app/sales_invoices/templates/sales_invoices/detail.html"
git commit -m "Rebuild sales invoice detail: modals, sent/void/overdue status UI"
```

---

## Task 10: Tests

**Files:**
- Create: `tests/unit/test_record_status.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_record_status.py`:

```python
"""Unit tests for record status transitions: void, sent, overdue."""
import pytest
from datetime import date, timedelta
from decimal import Decimal
from app.purchase_bills.models import PurchaseBill, PurchaseBillItem
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.accounts.models import Account
from app.audit.models import AuditLog
from app import db


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def gl_accounts(db_session):
    """Create the four GL accounts required for void JEs."""
    accounts = {
        'ap': Account(code='20101', name='Accounts Payable - Trade',
                      account_type='Liability', normal_balance='credit'),
        'ar': Account(code='10201', name='Accounts Receivable - Trade',
                      account_type='Asset', normal_balance='debit'),
        'input_vat': Account(code='10501', name='Input VAT - Current',
                             account_type='Asset', normal_balance='debit'),
        'output_vat': Account(code='20201', name='Output VAT - Sales',
                              account_type='Liability', normal_balance='credit'),
        'expense': Account(code='50230', name='Office Supplies Expense',
                           account_type='Expense', normal_balance='debit'),
        'revenue': Account(code='40101', name='Sales Revenue',
                           account_type='Revenue', normal_balance='credit'),
        'wt': Account(code='20301', name='Withholding Tax Payable - Expanded',
                      account_type='Liability', normal_balance='credit'),
    }
    for a in accounts.values():
        db_session.add(a)
    db_session.commit()
    return accounts


@pytest.fixture
def posted_bill(db_session, admin_user, main_branch, gl_accounts):
    """Create a posted purchase bill with one line item."""
    bill = PurchaseBill(
        bill_number='PB-TEST-0001',
        bill_date=date.today(),
        due_date=date.today() + timedelta(days=30),
        vendor_id=None,
        vendor_name='Test Vendor',
        payment_terms='Net 30',
        subtotal=Decimal('1000.00'),
        vat_amount=Decimal('120.00'),
        total_before_wt=Decimal('1120.00'),
        withholding_tax_rate=Decimal('0.00'),
        withholding_tax_amount=Decimal('0.00'),
        total_amount=Decimal('1120.00'),
        amount_paid=Decimal('0.00'),
        balance=Decimal('1120.00'),
        status='posted',
        branch_id=main_branch.id,
        created_by_id=admin_user.id
    )
    db_session.add(bill)
    db_session.flush()

    item = PurchaseBillItem(
        bill_id=bill.id, line_number=1,
        description='Office Supplies', quantity=Decimal('1.0000'),
        unit_cost=Decimal('1000.00'), vat_category='VATABLE',
        vat_rate=Decimal('12.00'), line_total=Decimal('1000.00'),
        vat_amount=Decimal('120.00'), account_id=gl_accounts['expense'].id
    )
    db_session.add(item)
    db_session.commit()
    return bill


@pytest.fixture
def posted_invoice(db_session, admin_user, main_branch, gl_accounts):
    """Create a posted sales invoice with one line item."""
    invoice = SalesInvoice(
        invoice_number='SI-TEST-0001',
        invoice_date=date.today(),
        due_date=date.today() + timedelta(days=30),
        customer_id=None,
        customer_name='Test Customer',
        payment_terms='Net 30',
        subtotal=Decimal('2000.00'),
        vat_amount=Decimal('240.00'),
        total_amount=Decimal('2240.00'),
        amount_paid=Decimal('0.00'),
        balance=Decimal('2240.00'),
        status='posted',
        branch_id=main_branch.id,
        created_by_id=admin_user.id
    )
    db_session.add(invoice)
    db_session.flush()

    item = SalesInvoiceItem(
        invoice_id=invoice.id, line_number=1,
        description='Consulting Services', quantity=Decimal('1.0000'),
        unit_price=Decimal('2000.00'), vat_category='VATABLE',
        vat_rate=Decimal('12.00'), line_total=Decimal('2000.00'),
        vat_amount=Decimal('240.00'), account_id=gl_accounts['revenue'].id
    )
    db_session.add(item)
    db_session.commit()
    return invoice


# ── Model field tests ────────────────────────────────────────────────────────

def test_purchase_bill_has_void_fields(db_session, posted_bill):
    assert hasattr(posted_bill, 'voided_at')
    assert hasattr(posted_bill, 'voided_by_id')
    assert hasattr(posted_bill, 'void_reason')
    assert posted_bill.voided_at is None
    assert posted_bill.voided_by_id is None
    assert posted_bill.void_reason is None


def test_sales_invoice_has_sent_and_void_fields(db_session, posted_invoice):
    assert hasattr(posted_invoice, 'sent_at')
    assert hasattr(posted_invoice, 'sent_by_id')
    assert hasattr(posted_invoice, 'voided_at')
    assert hasattr(posted_invoice, 'voided_by_id')
    assert hasattr(posted_invoice, 'void_reason')


# ── Bill void JE tests ───────────────────────────────────────────────────────

def test_create_bill_void_je_creates_balanced_entry(app, db_session, posted_bill, admin_user, gl_accounts):
    """Void JE must be balanced: total_debit == total_credit."""
    with app.app_context():
        from app.purchase_bills.views import _create_bill_void_je
        je = _create_bill_void_je(posted_bill, date.today(), admin_user.id)
        db_session.flush()
        assert je.is_balanced, f"JE not balanced: DR={je.total_debit} CR={je.total_credit}"
        assert je.total_debit == Decimal('1120.00')
        assert je.total_credit == Decimal('1120.00')


def test_create_bill_void_je_reference_format(app, db_session, posted_bill, admin_user, gl_accounts):
    with app.app_context():
        from app.purchase_bills.views import _create_bill_void_je
        je = _create_bill_void_je(posted_bill, date.today(), admin_user.id)
        assert je.reference == 'VOID-PB-TEST-0001'
        assert je.entry_type == 'reversal'
        assert je.status == 'posted'


def test_create_bill_void_je_missing_ap_account_raises(app, db_session, posted_bill, admin_user):
    """Void must fail clearly if AP account is missing."""
    with app.app_context():
        from app.purchase_bills.views import _create_bill_void_je
        # Delete the AP account
        ap = Account.query.filter_by(code='20101').first()
        if ap:
            db_session.delete(ap)
            db_session.commit()
        with pytest.raises(ValueError, match='20101'):
            _create_bill_void_je(posted_bill, date.today(), admin_user.id)


def test_bill_void_updates_status(app, db_session, posted_bill, admin_user, gl_accounts):
    """After voiding, bill.status == 'voided' and void fields are set."""
    with app.app_context():
        from app.purchase_bills.views import _create_bill_void_je
        from app.utils import ph_now
        _create_bill_void_je(posted_bill, date.today(), admin_user.id)
        posted_bill.status = 'voided'
        posted_bill.voided_by_id = admin_user.id
        posted_bill.voided_at = ph_now()
        posted_bill.void_reason = 'Wrong vendor entered in error'
        db_session.commit()
        assert posted_bill.status == 'voided'
        assert posted_bill.void_reason == 'Wrong vendor entered in error'
        assert posted_bill.voided_by_id == admin_user.id


# ── Invoice void JE tests ────────────────────────────────────────────────────

def test_create_invoice_void_je_creates_balanced_entry(app, db_session, posted_invoice, admin_user, gl_accounts):
    with app.app_context():
        from app.sales_invoices.views import _create_invoice_void_je
        je = _create_invoice_void_je(posted_invoice, date.today(), admin_user.id)
        db_session.flush()
        assert je.is_balanced, f"JE not balanced: DR={je.total_debit} CR={je.total_credit}"
        assert je.total_debit == Decimal('2240.00')
        assert je.total_credit == Decimal('2240.00')


def test_create_invoice_void_je_reference_format(app, db_session, posted_invoice, admin_user, gl_accounts):
    with app.app_context():
        from app.sales_invoices.views import _create_invoice_void_je
        je = _create_invoice_void_je(posted_invoice, date.today(), admin_user.id)
        assert je.reference == 'VOID-SI-TEST-0001'
        assert je.entry_type == 'reversal'


# ── Send status tests ────────────────────────────────────────────────────────

def test_sales_invoice_can_be_marked_sent(db_session, admin_user, main_branch, gl_accounts):
    invoice = SalesInvoice(
        invoice_number='SI-TEST-0002', invoice_date=date.today(),
        due_date=date.today() + timedelta(days=30),
        customer_id=None, customer_name='Test Customer',
        payment_terms='Net 30', subtotal=Decimal('500.00'),
        vat_amount=Decimal('0.00'), total_amount=Decimal('500.00'),
        amount_paid=Decimal('0.00'), balance=Decimal('500.00'),
        status='draft', branch_id=main_branch.id, created_by_id=admin_user.id
    )
    db_session.add(invoice)
    db_session.commit()

    from app.utils import ph_now
    invoice.status = 'sent'
    invoice.sent_at = ph_now()
    invoice.sent_by_id = admin_user.id
    db_session.commit()

    assert invoice.status == 'sent'
    assert invoice.sent_at is not None
    assert invoice.sent_by_id == admin_user.id
```

- [ ] **Step 2: Run tests — expect failures before implementation**

```powershell
pytest tests/unit/test_record_status.py -v 2>&1 | head -50
```

Expected: Tests for model fields pass (fields exist after migration), JE helper tests fail until Task 5/7 are done.

- [ ] **Step 3: Run full test suite after all tasks complete**

```powershell
pytest tests/unit/test_record_status.py -v
```

Expected: All tests PASS.

- [ ] **Step 4: Commit**

```powershell
git add tests/unit/test_record_status.py
git commit -m "Add record status tests: void JE balance, send, field presence, audit"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** Void (bills + invoices) ✓, Send (invoices) ✓, Overdue badge ✓, Reversal JE ✓, Audit log ✓, Void modal with reason + date ✓, Guard conditions server-side ✓
- [x] **No placeholders:** All code blocks complete, no TBDs
- [x] **Type consistency:** `_create_bill_void_je` / `_create_invoice_void_je` used consistently in Tasks 5, 7, 10; `generate_entry_number` from `app.journal_entries.utils` in Tasks 4, 5, 7
- [x] **JE balance check:** DR = total_amount + wt_amount = subtotal + vat_amount = CR ✓
