# Purchase Bill Detail Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign `detail.html` so it mirrors the edit form — same fields, same two-column layout, Vendor Invoice amber banner always visible, Journal Entry section added.

**Architecture:** Two changes: (1) add `_build_je_preview(bill)` helper to `views.py` and pass `je_entries` to the template; (2) rewrite `detail.html` to render the new layout. No model changes. No new CSS file — all inline styles consistent with current template.

**Tech Stack:** Flask, Jinja2, SQLAlchemy, SQLite. No JS needed — server-rendered only.

---

## Files

| File | Change |
|---|---|
| `app/purchase_bills/views.py` | Add `_build_je_preview(bill)` helper; update `view()` to pass `je_entries` |
| `app/purchase_bills/templates/purchase_bills/detail.html` | Full rewrite of card-body; modals and badge style block unchanged |
| `tests/integration/test_purchase_bill_detail.py` | New test file |

---

## Task 1: Write failing integration tests

**Files:**
- Create: `tests/integration/test_purchase_bill_detail.py`

- [ ] **Step 1: Create the test file**

```python
"""Integration tests for the redesigned purchase bill detail page."""
import pytest
from decimal import Decimal
from app.accounts.models import Account
from app.vendors.models import Vendor
from app.purchase_bills.models import PurchaseBill, PurchaseBillItem
from app.utils import ph_now


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def get_or_create_account(db_session, code, name, acct_type, normal_balance):
    a = Account.query.filter_by(code=code).first()
    if not a:
        a = Account(code=code, name=name, account_type=acct_type,
                    normal_balance=normal_balance, is_active=True)
        db_session.add(a)
        db_session.commit()
    return a


def make_vendor(db_session, code='DV001'):
    v = Vendor(code=code, name='Detail Test Vendor',
               check_payee_name='Detail Test Vendor',
               is_active=True, payment_terms='Net 30')
    db_session.add(v)
    db_session.commit()
    return v


def make_bill_with_line(db_session, vendor, branch, expense_account,
                         vendor_invoice_number=''):
    today = ph_now().date()
    bill = PurchaseBill(
        bill_number='DET-001',
        vendor_id=vendor.id,
        vendor_name=vendor.name,
        vendor_tin='123-456-789',
        vendor_address='Test Address, Manila',
        branch_id=branch.id,
        bill_date=today,
        due_date=today,
        payment_terms='Net 30',
        vendor_invoice_number=vendor_invoice_number,
        status='draft',
        subtotal=Decimal('11200.00'),
        vat_amount=Decimal('1200.00'),
        total_before_wt=Decimal('11200.00'),
        withholding_tax_rate=Decimal('0.00'),
        withholding_tax_amount=Decimal('0.00'),
        total_amount=Decimal('11200.00'),
        amount_paid=Decimal('0.00'),
        balance=Decimal('11200.00'),
    )
    db_session.add(bill)
    db_session.flush()
    item = PurchaseBillItem(
        bill_id=bill.id,
        line_number=1,
        description='Test Service',
        amount=Decimal('11200.00'),
        vat_category='VATABLE',
        vat_rate=Decimal('12.00'),
        line_total=Decimal('11200.00'),
        vat_amount=Decimal('1200.00'),
        account_id=expense_account.id,
    )
    db_session.add(item)
    db_session.commit()
    return bill


def setup_gl_accounts(db_session):
    expense = get_or_create_account(db_session, '60001', 'Test Expense',
                                    'Expense', 'Debit')
    get_or_create_account(db_session, '20101', 'Accounts Payable - Trade',
                          'Liability', 'Credit')
    get_or_create_account(db_session, '10501', 'Input VAT - Current',
                          'Asset', 'Debit')
    get_or_create_account(db_session, '20301', 'WHT Payable - Expanded',
                          'Liability', 'Credit')
    return expense


class TestDetailPageLayout:

    def test_page_loads_and_shows_voucher_date_label(
            self, client, db_session, admin_user, main_branch):
        expense = setup_gl_accounts(db_session)
        vendor = make_vendor(db_session)
        bill = make_bill_with_line(db_session, vendor, main_branch, expense)
        login(client)
        resp = client.get(f'/purchase-bills/{bill.id}')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert 'Voucher Date' in html
        assert 'Bill Date' not in html

    def test_vendor_invoice_banner_blank(
            self, client, db_session, admin_user, main_branch):
        expense = setup_gl_accounts(db_session)
        vendor = make_vendor(db_session)
        bill = make_bill_with_line(db_session, vendor, main_branch, expense,
                                    vendor_invoice_number='')
        login(client)
        resp = client.get(f'/purchase-bills/{bill.id}')
        html = resp.data.decode('utf-8')
        assert 'Vendor Invoice' in html
        assert '— not provided —' in html

    def test_vendor_invoice_banner_shows_number(
            self, client, db_session, admin_user, main_branch):
        expense = setup_gl_accounts(db_session)
        vendor = make_vendor(db_session)
        bill = make_bill_with_line(db_session, vendor, main_branch, expense,
                                    vendor_invoice_number='INV-2026-001')
        login(client)
        resp = client.get(f'/purchase-bills/{bill.id}')
        html = resp.data.decode('utf-8')
        assert 'INV-2026-001' in html
        assert '— not provided —' not in html

    def test_journal_entry_section_present(
            self, client, db_session, admin_user, main_branch):
        expense = setup_gl_accounts(db_session)
        vendor = make_vendor(db_session)
        bill = make_bill_with_line(db_session, vendor, main_branch, expense)
        login(client)
        resp = client.get(f'/purchase-bills/{bill.id}')
        html = resp.data.decode('utf-8')
        assert 'Journal Entry' in html

    def test_bill_summary_label_present(
            self, client, db_session, admin_user, main_branch):
        expense = setup_gl_accounts(db_session)
        vendor = make_vendor(db_session)
        bill = make_bill_with_line(db_session, vendor, main_branch, expense)
        login(client)
        resp = client.get(f'/purchase-bills/{bill.id}')
        html = resp.data.decode('utf-8')
        assert 'Bill Summary' in html

    def test_line_items_account_title_column_and_no_wht_amt(
            self, client, db_session, admin_user, main_branch):
        expense = setup_gl_accounts(db_session)
        vendor = make_vendor(db_session)
        bill = make_bill_with_line(db_session, vendor, main_branch, expense)
        login(client)
        resp = client.get(f'/purchase-bills/{bill.id}')
        html = resp.data.decode('utf-8')
        assert 'Account Title' in html
        assert 'WHT Amt' not in html
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
pytest tests/integration/test_purchase_bill_detail.py -v
```

Expected: all 6 tests fail — `Voucher Date` not in HTML, `Vendor Invoice` not in HTML, `Journal Entry` not in HTML, etc. (old template lacks all of these).

---

## Task 2: Add `_build_je_preview` helper and update view

**Files:**
- Modify: `app/purchase_bills/views.py` (after `_get_gl_accounts`, before `_get_all_accounts_for_select`)

- [ ] **Step 1: Add `_build_je_preview` after `_get_gl_accounts` (line 36)**

Insert the following function between `_get_gl_accounts` (ends at line 36) and `_get_all_accounts_for_select` (starts at line 39):

```python
def _build_je_preview(bill):
    """Return list of {code, name, debit, credit} dicts for the JE section.

    For posted bills reads from the stored JournalEntry. For drafts,
    computes the same entries the post route would create.
    """
    if bill.journal_entry:
        return [
            {
                'code': line.account.code if line.account else '—',
                'name': line.account.name if line.account else '—',
                'debit': line.debit_amount,
                'credit': line.credit_amount,
            }
            for line in sorted(bill.journal_entry.lines.all(),
                               key=lambda l: l.line_number)
        ]

    accts = _get_gl_accounts()
    entries = []

    for item in bill.line_items:
        if not item.account_id:
            continue
        net_base = Decimal(str(item.line_total)) - Decimal(str(item.vat_amount))
        entries.append({
            'code': item.account.code if item.account else '—',
            'name': item.account.name if item.account else '—',
            'debit': net_base,
            'credit': Decimal('0.00'),
        })

    vat_amount = Decimal(str(bill.vat_amount))
    if vat_amount > 0 and accts['input_vat']:
        entries.append({
            'code': accts['input_vat'].code,
            'name': accts['input_vat'].name,
            'debit': vat_amount,
            'credit': Decimal('0.00'),
        })

    wt_amount = Decimal(str(bill.withholding_tax_amount))
    if wt_amount > 0 and accts['wt']:
        entries.append({
            'code': accts['wt'].code,
            'name': accts['wt'].name,
            'debit': Decimal('0.00'),
            'credit': wt_amount,
        })

    if accts['ap']:
        entries.append({
            'code': accts['ap'].code,
            'name': accts['ap'].name,
            'debit': Decimal('0.00'),
            'credit': Decimal(str(bill.total_amount)),
        })

    return entries
```

- [ ] **Step 2: Update the `view()` function (line 456–459)**

Replace:
```python
@purchase_bills_bp.route('/purchase-bills/<int:id>')
@login_required
def view(id):
    """View purchase bill details."""
    bill = _get_bill_or_404(id)
    return render_template('purchase_bills/detail.html', bill=bill)
```

With:
```python
@purchase_bills_bp.route('/purchase-bills/<int:id>')
@login_required
def view(id):
    """View purchase bill details."""
    bill = _get_bill_or_404(id)
    je_entries = _build_je_preview(bill)
    return render_template('purchase_bills/detail.html', bill=bill,
                           je_entries=je_entries)
```

---

## Task 3: Rewrite `detail.html`

**Files:**
- Modify: `app/purchase_bills/templates/purchase_bills/detail.html`

Replace only the `<div class="card-body">` block (lines 101–251). Everything before (modals) and after (closing `</div>` and `<style>` block) stays unchanged.

- [ ] **Step 1: Replace the card-body block**

The new `card-body` content (replace lines 101–252 with this):

```html
    <div class="card-body">

        <!-- ── Two-column header ──────────────────────────────────────────── -->
        <div style="display:grid; grid-template-columns:1fr 1.5fr; gap:24px; margin-bottom:32px;">

            <!-- LEFT: header fields + vendor invoice banner -->
            <div style="display:flex; flex-direction:column; gap:10px;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span style="color:var(--text-2); font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.04em;">AP Number</span>
                    <span style="font-weight:600; font-family:var(--mono);">{{ bill.bill_number }}</span>
                </div>
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span style="color:var(--text-2); font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.04em;">Voucher Date</span>
                    <span>{{ bill.bill_date.strftime('%b %d, %Y') }}</span>
                </div>
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span style="color:var(--text-2); font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.04em;">Due Date</span>
                    <span>{{ bill.due_date.strftime('%b %d, %Y') }}</span>
                </div>
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span style="color:var(--text-2); font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.04em;">Payment Terms</span>
                    <span>{{ bill.payment_terms }}</span>
                </div>
                {% if bill.reference %}
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span style="color:var(--text-2); font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.04em;">Reference/PO</span>
                    <span>{{ bill.reference }}</span>
                </div>
                {% endif %}

                <!-- Vendor Invoice banner — always shown -->
                <div style="background:#fef9c3; border:1px solid #fde047; border-radius:8px; padding:14px 16px; margin-top:6px;">
                    <div style="font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:0.06em; color:#92400e; margin-bottom:8px;">Vendor Invoice</div>
                    <div style="display:flex; justify-content:space-between; align-items:baseline; gap:8px;">
                        <div>
                            <div style="font-size:10px; color:#a16207; margin-bottom:2px;">Invoice #</div>
                            <div style="font-weight:700; font-size:16px; color:#78350f; font-family:var(--mono);">{{ bill.vendor_invoice_number if bill.vendor_invoice_number else '— not provided —' }}</div>
                        </div>
                        <div style="text-align:right;">
                            <div style="font-size:10px; color:#a16207; margin-bottom:2px;">Invoice Date</div>
                            <div style="font-weight:600; color:#92400e;">{{ bill.vendor_invoice_date.strftime('%b %d, %Y') if bill.vendor_invoice_date else '—' }}</div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- RIGHT: vendor card + notes -->
            <div style="display:flex; flex-direction:column; gap:16px;">
                <div style="border:2px solid var(--green, #22c55e); background:#f0fdf4; border-radius:8px; padding:16px 20px;">
                    <div style="font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:0.05em; color:#15803d; margin-bottom:8px;">Vendor</div>
                    <div style="font-weight:700; font-size:15px; margin-bottom:4px;">{{ bill.vendor_name }}</div>
                    {% if bill.vendor_tin %}
                    <div style="color:var(--text-2); font-size:12px; margin-bottom:2px;">TIN: {{ bill.vendor_tin }}</div>
                    {% endif %}
                    {% if bill.vendor_address %}
                    <div style="color:var(--text-2); font-size:12px;">{{ bill.vendor_address }}</div>
                    {% endif %}
                </div>
                {% if bill.notes %}
                <div style="background:var(--bg); border-radius:6px; padding:14px 16px;">
                    <div style="font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.04em; color:var(--text-2); margin-bottom:8px;">Notes</div>
                    <p style="margin:0; color:var(--text-2); white-space:pre-wrap; font-size:13px;">{{ bill.notes }}</p>
                </div>
                {% endif %}
            </div>
        </div>

        <!-- ── Line Items ──────────────────────────────────────────────────── -->
        <table class="table" style="margin-bottom:24px;">
            <thead>
                <tr>
                    <th>#</th>
                    <th>Description</th>
                    <th style="text-align:right;">Amount (VAT-incl.)</th>
                    <th>VAT</th>
                    <th>WHT</th>
                    <th>Account Title</th>
                </tr>
            </thead>
            <tbody>
                {% for item in bill.line_items %}
                <tr>
                    <td>{{ item.line_number }}</td>
                    <td>{{ item.description or '—' }}</td>
                    <td style="text-align:right; font-family:var(--mono); font-weight:600;">₱{{ '{:,.2f}'.format(item.line_total) }}</td>
                    <td>{{ item.vat_category or 'N/A' }} ({{ '{:.2f}'.format(item.vat_rate) }}%)</td>
                    <td style="font-size:12px;">
                        {% if item.withholding_tax %}{{ item.withholding_tax.code }} ({{ '{:.2f}'.format(item.wt_rate) }}%){% else %}—{% endif %}
                    </td>
                    <td style="font-size:12px; color:var(--text-2);">{{ item.account.code ~ ' : ' ~ item.account.name if item.account else '—' }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>

        <!-- ── Journal Entry + Bill Summary ───────────────────────────────── -->
        <div style="display:grid; grid-template-columns:1fr 340px; gap:24px;">

            <!-- Journal Entry -->
            <div>
                <h3 style="font-size:14px; font-weight:600; color:var(--text-2); margin-bottom:12px;">Journal Entry</h3>
                <table class="table">
                    <thead>
                        <tr>
                            <th>Code</th>
                            <th>Account Title</th>
                            <th style="text-align:right;">Debit</th>
                            <th style="text-align:right;">Credit</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% set ns = namespace(total_debit=0, total_credit=0) %}
                        {% for entry in je_entries %}
                        {% set ns.total_debit = ns.total_debit + entry.debit %}
                        {% set ns.total_credit = ns.total_credit + entry.credit %}
                        <tr>
                            <td style="color:var(--text-2); font-size:12px;">{{ entry.code }}</td>
                            <td style="{{ 'padding-left:24px;' if entry.credit > 0 else '' }}">{{ entry.name }}</td>
                            <td style="text-align:right; font-family:var(--mono);">
                                {% if entry.debit > 0 %}{{ '{:,.2f}'.format(entry.debit) }}{% else %}—{% endif %}
                            </td>
                            <td style="text-align:right; font-family:var(--mono);">
                                {% if entry.credit > 0 %}{{ '{:,.2f}'.format(entry.credit) }}{% else %}—{% endif %}
                            </td>
                        </tr>
                        {% endfor %}
                        <tr style="font-weight:700; border-top:2px solid var(--border);">
                            <td colspan="2">Total</td>
                            <td style="text-align:right; font-family:var(--mono);">{{ '{:,.2f}'.format(ns.total_debit) }}</td>
                            <td style="text-align:right; font-family:var(--mono);">{{ '{:,.2f}'.format(ns.total_credit) }}</td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <!-- Bill Summary -->
            <div style="background:var(--bg); padding:20px; border-radius:6px;">
                <h3 style="font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.04em; color:var(--text-2); margin:0 0 14px;">Bill Summary</h3>
                <div style="display:flex; justify-content:space-between; margin-bottom:10px;">
                    <span style="color:var(--text-2);">Gross Amount:</span>
                    <span style="font-family:var(--mono); font-weight:600;">₱{{ '{:,.2f}'.format(bill.subtotal) }}</span>
                </div>
                <div style="display:flex; justify-content:space-between; margin-bottom:10px;">
                    <span style="color:var(--text-2);">
                        Less: Input VAT:
                        {% if bill.vat_override %}<span style="font-size:10px; font-weight:700; color:var(--amber); margin-left:4px; border:1px solid currentColor; border-radius:3px; padding:1px 4px;">MANUAL</span>{% endif %}
                    </span>
                    <span style="font-family:var(--mono); font-weight:600;">₱{{ '{:,.2f}'.format(bill.vat_amount) }}</span>
                </div>
                <div style="height:1px; background:var(--border); margin:8px 0;"></div>
                <div style="display:flex; justify-content:space-between; margin-bottom:10px;">
                    <span style="color:var(--text-2);">Net of VAT:</span>
                    <span style="font-family:var(--mono); font-weight:600;">₱{{ '{:,.2f}'.format(bill.subtotal - bill.vat_amount) }}</span>
                </div>
                <div style="display:flex; justify-content:space-between; margin-bottom:10px;">
                    <span style="color:var(--text-2);">Add: Input VAT:</span>
                    <span style="font-family:var(--mono); font-weight:600;">₱{{ '{:,.2f}'.format(bill.vat_amount) }}</span>
                </div>
                <div style="display:flex; justify-content:space-between; margin-bottom:10px;">
                    <span style="color:var(--text-2);">
                        Less: Withholding Tax:
                        {% if bill.wt_override %}<span style="font-size:10px; font-weight:700; color:var(--amber); margin-left:4px; border:1px solid currentColor; border-radius:3px; padding:1px 4px;">MANUAL</span>{% endif %}
                    </span>
                    <span style="font-family:var(--mono); font-weight:600; color:var(--red);">-₱{{ '{:,.2f}'.format(bill.withholding_tax_amount) }}</span>
                </div>
                <div style="height:2px; background:var(--border); margin:10px 0;"></div>
                <div style="display:flex; justify-content:space-between;">
                    <span style="font-size:16px; font-weight:700;">Net Amount Payable:</span>
                    <span style="font-family:var(--mono); font-size:18px; font-weight:700; color:var(--blue);">₱{{ '{:,.2f}'.format(bill.total_amount) }}</span>
                </div>
                {% if bill.amount_paid and bill.amount_paid > 0 %}
                <div style="display:flex; justify-content:space-between; margin-top:10px;">
                    <span style="color:var(--text-2);">Amount Paid:</span>
                    <span style="font-family:var(--mono);">₱{{ '{:,.2f}'.format(bill.amount_paid) }}</span>
                </div>
                <div style="display:flex; justify-content:space-between; padding-top:8px; border-top:1px solid var(--border);">
                    <span style="font-weight:600;">Balance:</span>
                    <span style="font-family:var(--mono); font-weight:600; color:{{ 'var(--red)' if bill.balance > 0 else 'var(--green)' }};">₱{{ '{:,.2f}'.format(bill.balance) }}</span>
                </div>
                {% endif %}
            </div>
        </div>

        <!-- ── Audit Trail ─────────────────────────────────────────────────── -->
        <div style="margin-top:24px; padding-top:24px; border-top:1px solid var(--border); font-size:12px; color:var(--text-3);">
            Created by {{ bill.created_by.username if bill.created_by else '—' }} on {{ bill.created_at.strftime('%b %d, %Y %H:%M') if bill.created_at else '—' }}
            {% if bill.posted_by %}
             &mdash; Posted by {{ bill.posted_by.username }} on {{ bill.posted_at.strftime('%b %d, %Y %H:%M') if bill.posted_at else '—' }}
            {% endif %}
            {% if bill.voided_by %}
             &mdash; Voided by {{ bill.voided_by.username }} on {{ bill.voided_at.strftime('%b %d, %Y %H:%M') if bill.voided_at else '—' }} &mdash; <em>{{ bill.void_reason }}</em>
            {% endif %}
            {% if bill.cancel_reason %}
             &mdash; Cancelled on {{ bill.cancelled_at.strftime('%b %d, %Y %H:%M') if bill.cancelled_at else '—' }} &mdash; <em>{{ bill.cancel_reason }}</em>
            {% endif %}
        </div>

    </div>
```

- [ ] **Step 2: Run the new tests**

```powershell
pytest tests/integration/test_purchase_bill_detail.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 3: Run the full test suite**

```powershell
pytest -m "not slow" -q
```

Expected: no regressions. Previously passing tests remain green.

- [ ] **Step 4: Commit**

```powershell
git add app/purchase_bills/views.py `
        app/purchase_bills/templates/purchase_bills/detail.html `
        tests/integration/test_purchase_bill_detail.py
git commit -m "feat: redesign purchase bill detail page to mirror edit form layout"
```
