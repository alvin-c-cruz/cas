# Cash Receipt Voucher (CRV) Module — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `app/cash_receipts/` (Cash Receipt Voucher) as the AR-side mirror of the working `app/cash_disbursements/` (CDV) module — record customer collections, apply them against open sales invoices, post a balanced journal entry, activate the Cash Receipts Journal, and retire the legacy `receipts` blueprint.

**Architecture:** CRV mirrors CDV file-for-file with a deterministic rename map (vendor→customer, AP→AR, expense→revenue, debit↔credit on the JE). The accounting is inverted: a posted CRV is **Cr AR / Cr Revenue / Cr Output VAT / Dr Creditable-WHT-Receivable / Dr Cash**, and on post it reduces `SalesInvoice.balance`. Most code is a copy-and-rename of CDV; this plan gives the full rename map plus verbatim code for the genuinely-inverted accounting functions and the new models.

**Tech Stack:** Flask, SQLAlchemy, Alembic (Flask-Migrate), Jinja2, pytest, openpyxl. Reference module: `app/cash_disbursements/` (~1050-line `views.py`, `models.py`, `forms.py`, `templates/`, and `tests/{unit,integration}/test_cdv_*.py`).

## Global Constraints

- **Numbering:** `CR-YYYY-MM-NNNN`, sequenced per (prefix, year, month) — mirror `generate_cdv_number()` (`CD-YYYY-MM-NNNN`).
- **GL accounts:** AR-Trade `10201`, Creditable WHT Receivable `10212`, Output VAT via `VATCategory.output_vat_account`, cash/bank from `crv.cash_account_id`, revenue from each revenue line's `account_id`.
- **JE:** `entry_type='receipt'`; must balance or posting raises `ValueError` (surfaced verbatim).
- **Totals:** `total_amount = total_ar_applied + total_revenue − total_wt`.
- **Status lifecycle:** `draft → posted` (post applies collections); **void = draft-only** (deletes draft JE); **cancel = posted-only** (reverses collections + reversal JE). This matches CDV exactly — do NOT merge void/cancel.
- **Validation:** each AR line `0 < amount_applied ≤ invoice.balance`; domain `ValueError`s surface verbatim, only broad `except Exception` is genericized (genericize-flash-keep-ValueError rule).
- **Audit:** every create/post/void/cancel calls `log_audit`/`log_create` with the CRV reference.
- **Buttons:** in-form submit = **Save**/**Update**; list launch = **+ Enter CRV** / "Enter Cash Receipt"; per Enter-vs-Create rule.
- **Branch scoping + period guard:** mirror CDV (`require_branch_selection`, `validate_transaction_date_with_flash`).
- **Model approval:** the three new tables in Task 1 were approved in the spec; no further model is introduced.

### Deterministic rename map (CDV → CRV)

Apply to every copied file. These are exact token substitutions:

| CDV token | CRV token |
|---|---|
| `cash_disbursements` | `cash_receipts` |
| `CashDisbursementVoucher` | `CashReceiptVoucher` |
| `cash_disbursement_vouchers` | `cash_receipt_vouchers` |
| `cdv` (var) / `CDV` (label) | `crv` / `CRV` |
| `cdv_number` / `cdv_date` | `crv_number` / `crv_date` |
| `cash_disbursements_bp` | `cash_receipts_bp` |
| `/cash-disbursements` (routes) | `/cash-receipts` |
| `vendor` / `vendor_id` / `vendor_name` / `vendor_tin` | `customer` / `customer_id` / `customer_name` / `customer_tin` |
| `Vendor` (model) | `Customer` |
| `CDVApLine` / `ap_lines` / `cdv_ap_lines` | `CRVArLine` / `ar_lines` / `crv_ar_lines` |
| `CDVExpenseLine` / `expense_lines` / `cdv_expense_lines` | `CRVRevenueLine` / `revenue_lines` / `crv_revenue_lines` |
| `AccountsPayable` / `accounts_payable` (rel) | `SalesInvoice` / `sales_invoice` (rel) |
| `ap_id` / `ap_number` | `invoice_id` / `invoice_number` |
| `total_expense` | `total_revenue` |
| `open_bills` / `open-bills` | `open_invoices` / `open-invoices` |
| `generate_cdv_number` | `generate_crv_number` |
| `'disbursement'` (entry_type) | `'receipt'` |
| `'CD-'` prefix | `'CR-'` prefix |
| `cd_journal` / `cd_journal_data` / `build_columnar_cd` | `cr_journal` / `cr_journal_data` / `build_columnar_cr` |
| `module='cash_disbursement'` (audit) | `module='cash_receipt'` |

**Accounting inversions (NOT mechanical — use the verbatim code in Tasks 1-3):** debit↔credit swap on the JE; AP account `20101`→AR `10201`; WHT-Payable `20301`→Creditable-WHT-Receivable `10212`; input-VAT buckets→output-VAT buckets; `SalesInvoice` uses `invoice_date`/`due_date`/`invoice_number` (not `ap_date`/`ap_number`).

---

## File Map

| File | Action | Task |
|---|---|---|
| `app/cash_receipts/__init__.py` | Create (empty pkg) | 1 |
| `app/cash_receipts/models.py` | Create (3 models) | 1 |
| `migrations/versions/<rev>_add_cash_receipt_tables.py` | Create (autogen) | 1 |
| `tests/unit/test_crv_models.py` | Create | 1 |
| `app/cash_receipts/views.py` (JE + AR-apply core) | Create (part 1) | 2 |
| `tests/integration/test_crv_posting.py` | Create | 2 |
| `app/cash_receipts/views.py` (routes) + `forms.py` | Create (part 2) | 3 |
| `app/cash_receipts/templates/cash_receipts/*.html` | Create | 3 |
| `tests/integration/test_crv_views.py` | Create | 3 |
| `app/journals/cr_journal_data.py` + `app/journals/views.py` (cr routes) | Create/Modify | 4 |
| `app/journals/templates/journals/cr_journal*.html` | Create | 4 |
| `tests/integration/test_cr_journal.py` | Create | 4 |
| `app/__init__.py`, `app/users/module_access.py`, `app/templates/base.html`, `app/receipts/` (delete) | Modify/Delete | 5 |
| `tests/integration/test_crv_wireup.py` | Create | 5 |

---

## Task 1: Models + migration + model unit tests

**Files:**
- Create: `app/cash_receipts/__init__.py` (empty), `app/cash_receipts/models.py`, `tests/unit/test_crv_models.py`
- Create (autogen): migration under `migrations/versions/`

**Interfaces produced:** `CashReceiptVoucher` (with `.calculate_totals()`, `.ar_lines`, `.revenue_lines`), `CRVArLine`, `CRVRevenueLine` (with `.calculate_amounts()`).

- [ ] **Step 1.1: Create `app/cash_receipts/__init__.py`** (empty file).

- [ ] **Step 1.2: Create `app/cash_receipts/models.py`** with the full content below. It is `app/cash_disbursements/models.py` with the rename map applied and `total_expense`→`total_revenue`, AP line→AR line (`invoice_id`/`invoice_number`/`sales_invoice`). Copy verbatim:

```python
from app import db
from app.utils import ph_now
from decimal import Decimal


class CashReceiptVoucher(db.Model):
    __tablename__ = 'cash_receipt_vouchers'

    id = db.Column(db.Integer, primary_key=True)

    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    branch = db.relationship('Branch', foreign_keys=[branch_id])

    crv_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    crv_date = db.Column(db.Date, nullable=False, index=True)

    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)
    customer = db.relationship('Customer', backref='cash_receipts')
    customer_name = db.Column(db.String(200), nullable=False)
    customer_tin = db.Column(db.String(20))

    payment_method = db.Column(db.String(20), nullable=False, default='cash')
    check_number = db.Column(db.String(50))
    check_date = db.Column(db.Date)
    check_bank = db.Column(db.String(100))

    cash_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=False)
    cash_account = db.relationship('Account', foreign_keys=[cash_account_id])

    notes = db.Column(db.Text, nullable=False, default='')

    total_ar_applied = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_revenue = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_vat = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_wt = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_amount = db.Column(db.Numeric(15, 2), default=0, nullable=False)

    vat_override = db.Column(db.Boolean, default=False, nullable=False)
    wt_override = db.Column(db.Boolean, default=False, nullable=False)

    status = db.Column(db.String(20), default='draft', nullable=False, index=True)

    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'), nullable=True)
    journal_entry = db.relationship('JournalEntry', foreign_keys=[journal_entry_id])

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[created_by_id], backref='created_crvs')
    posted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    posted_by = db.relationship('User', foreign_keys=[posted_by_id], backref='posted_crvs')
    voided_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    voided_by = db.relationship('User', foreign_keys=[voided_by_id], backref='voided_crvs')

    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)
    posted_at = db.Column(db.DateTime)
    voided_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)

    void_reason = db.Column(db.String(255))
    cancel_reason = db.Column(db.String(500))

    ar_lines = db.relationship('CRVArLine', backref='crv', lazy='select',
                               cascade='all, delete-orphan',
                               order_by='CRVArLine.line_number')
    revenue_lines = db.relationship('CRVRevenueLine', backref='crv', lazy='select',
                                    cascade='all, delete-orphan',
                                    order_by='CRVRevenueLine.line_number')

    def __repr__(self):
        return f'<CashReceiptVoucher {self.crv_number}>'

    def calculate_totals(self):
        self.total_ar_applied = sum(
            (Decimal(str(l.amount_applied)) for l in self.ar_lines),
            Decimal('0.00')
        )
        auto_revenue = Decimal('0.00')
        auto_vat = Decimal('0.00')
        auto_wt = Decimal('0.00')
        for line in self.revenue_lines:
            auto_revenue += Decimal(str(line.line_total))
            auto_vat += Decimal(str(line.vat_amount))
            auto_wt += Decimal(str(line.wt_amount or 0))
        self.total_revenue = auto_revenue
        if not self.vat_override:
            self.total_vat = auto_vat
        if not self.wt_override:
            self.total_wt = auto_wt
        self.total_amount = self.total_ar_applied + self.total_revenue - self.total_wt

    def to_dict(self):
        return {
            'id': self.id,
            'crv_number': self.crv_number,
            'crv_date': self.crv_date.isoformat() if self.crv_date else None,
            'customer_id': self.customer_id,
            'customer_name': self.customer_name,
            'payment_method': self.payment_method,
            'total_ar_applied': float(self.total_ar_applied),
            'total_revenue': float(self.total_revenue),
            'total_vat': float(self.total_vat),
            'total_wt': float(self.total_wt),
            'total_amount': float(self.total_amount),
            'status': self.status,
        }


class CRVArLine(db.Model):
    __tablename__ = 'crv_ar_lines'

    id = db.Column(db.Integer, primary_key=True)
    crv_id = db.Column(db.Integer, db.ForeignKey('cash_receipt_vouchers.id'),
                       nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey('sales_invoices.id'), nullable=False)
    sales_invoice = db.relationship('SalesInvoice', foreign_keys=[invoice_id])
    invoice_number = db.Column(db.String(50), nullable=False)
    original_balance = db.Column(db.Numeric(15, 2), nullable=False)
    amount_applied = db.Column(db.Numeric(15, 2), nullable=False)

    def __repr__(self):
        return f'<CRVArLine crv={self.crv_id} inv={self.invoice_number}>'

    def to_dict(self):
        return {
            'id': self.id,
            'invoice_id': self.invoice_id,
            'invoice_number': self.invoice_number,
            'original_balance': float(self.original_balance),
            'amount_applied': float(self.amount_applied),
        }


class CRVRevenueLine(db.Model):
    __tablename__ = 'crv_revenue_lines'

    id = db.Column(db.Integer, primary_key=True)
    crv_id = db.Column(db.Integer, db.ForeignKey('cash_receipt_vouchers.id'),
                       nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(500), nullable=False)
    amount = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    vat_category = db.Column(db.String(100))
    vat_rate = db.Column(db.Numeric(5, 2), default=0, nullable=False)
    line_total = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    vat_amount = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'))
    account = db.relationship('Account')
    wt_id = db.Column(db.Integer, db.ForeignKey('withholding_tax.id'), nullable=True)
    withholding_tax = db.relationship('WithholdingTax', foreign_keys=[wt_id])
    wt_rate = db.Column(db.Numeric(5, 2), nullable=True)
    wt_amount = db.Column(db.Numeric(15, 2), default=Decimal('0.00'),
                          server_default='0.00', nullable=False)

    def __repr__(self):
        return f'<CRVRevenueLine crv={self.crv_id} line={self.line_number}>'

    def calculate_amounts(self):
        vat_rate = Decimal(str(self.vat_rate)) if self.vat_rate else Decimal('0')
        if vat_rate > 0:
            net_base = Decimal(str(self.amount)) / (1 + vat_rate / Decimal('100'))
        else:
            net_base = Decimal(str(self.amount))
        self.line_total = Decimal(str(self.amount))
        self.vat_amount = (Decimal(str(self.amount)) - net_base).quantize(
            Decimal('0.01'), rounding='ROUND_HALF_UP')
        wt_rate = Decimal(str(self.wt_rate)) if self.wt_rate else Decimal('0')
        self.wt_amount = (net_base * wt_rate / Decimal('100')).quantize(
            Decimal('0.01'), rounding='ROUND_HALF_UP')

    def to_dict(self):
        return {
            'id': self.id,
            'line_number': self.line_number,
            'description': self.description,
            'amount': float(self.amount),
            'vat_category': self.vat_category,
            'vat_rate': float(self.vat_rate),
            'line_total': float(self.line_total),
            'vat_amount': float(self.vat_amount),
            'account_id': self.account_id,
            'wt_id': self.wt_id,
            'wt_code': self.withholding_tax.code if self.withholding_tax else None,
            'wt_rate': float(self.wt_rate) if self.wt_rate is not None else None,
            'wt_amount': float(self.wt_amount),
        }
```

- [ ] **Step 1.3: Register models for migration autodetect in `app/__init__.py`.** Find the CDV model import (line 182: `from app.cash_disbursements.models import CashDisbursementVoucher, CDVApLine, CDVExpenseLine`) and add immediately after it:

```python
    from app.cash_receipts.models import CashReceiptVoucher, CRVArLine, CRVRevenueLine
```

(Blueprint registration and legacy-receipts removal happen in Task 5 — keep this step to the model import only so the migration can autogenerate now.)

- [ ] **Step 1.4: Generate the migration.**

```
flask db migrate -m "add cash receipt voucher tables"
```

Open the generated file under `migrations/versions/`. Confirm `upgrade()` creates `cash_receipt_vouchers`, `crv_ar_lines`, `crv_revenue_lines` (and only those — no unrelated drops). If autogen added spurious drops from model drift, delete those lines. Then:

```
flask db upgrade
```

Expected: "Running upgrade … add cash receipt voucher tables".

- [ ] **Step 1.5: Write `tests/unit/test_crv_models.py`.** Model `tests/unit/test_cdv_models.py` (read it first), renamed. Cover: `CRVRevenueLine.calculate_amounts()` extracts 12% VAT from an inclusive amount and computes WHT on the net base; `CashReceiptVoucher.calculate_totals()` sums `total_ar_applied`, `total_revenue`, `total_vat`, `total_wt` and computes `total_amount = ar_applied + revenue − wt`; `vat_override`/`wt_override` suppress auto recompute. Use the `db_session` fixture. Example core test:

```python
import pytest
from decimal import Decimal
from app.cash_receipts.models import CashReceiptVoucher, CRVArLine, CRVRevenueLine

pytestmark = [pytest.mark.unit]


def test_revenue_line_extracts_vat_and_wt():
    line = CRVRevenueLine(line_number=1, description='x',
                          amount=Decimal('1120.00'), vat_rate=Decimal('12.00'),
                          wt_rate=Decimal('2.00'))
    line.calculate_amounts()
    assert line.line_total == Decimal('1120.00')
    assert line.vat_amount == Decimal('120.00')      # 1120 - 1000
    assert line.wt_amount == Decimal('20.00')        # 2% of 1000 net

def test_totals_ar_plus_revenue_minus_wt(db_session):
    crv = CashReceiptVoucher(crv_number='CR-2026-06-0001', crv_date=None,
                             branch_id=1, customer_id=1, customer_name='C',
                             cash_account_id=1)
    crv.ar_lines.append(CRVArLine(line_number=1, invoice_id=1,
                                  invoice_number='SI-2026-0001',
                                  original_balance=Decimal('500'),
                                  amount_applied=Decimal('500.00')))
    rl = CRVRevenueLine(line_number=1, description='svc',
                        amount=Decimal('1120.00'), vat_rate=Decimal('12.00'),
                        wt_rate=Decimal('2.00'))
    rl.calculate_amounts()
    crv.revenue_lines.append(rl)
    crv.calculate_totals()
    assert crv.total_ar_applied == Decimal('500.00')
    assert crv.total_revenue == Decimal('1120.00')
    assert crv.total_vat == Decimal('120.00')
    assert crv.total_wt == Decimal('20.00')
    assert crv.total_amount == Decimal('1600.00')    # 500 + 1120 - 20
```

- [ ] **Step 1.6: Run tests + commit.**

```
pytest tests/unit/test_crv_models.py -v
git add app/cash_receipts/__init__.py app/cash_receipts/models.py app/__init__.py migrations/versions/ tests/unit/test_crv_models.py
git commit -m "feat(crv): cash receipt voucher models + migration"
```

---

## Task 2: JE posting + VAT buckets + reversal core

> **After Task 1.**

**Files:**
- Create: `app/cash_receipts/views.py` (helpers only this task — the JE/accounting core)
- Create: `tests/integration/test_crv_posting.py`

**Interfaces produced:** `_post_crv_je(crv, user_id) -> JournalEntry`, `_output_vat_buckets(crv)`, `_create_crv_reversal_je(crv, reversal_date, user_id)`, `_get_gl_accounts()`, `generate_crv_number()`, `_build_crv_je_preview(crv)`.

- [ ] **Step 2.1: Start `app/cash_receipts/views.py`** with the imports + blueprint + decorators + `generate_crv_number()` + `_get_gl_accounts()`. Copy the top of `app/cash_disbursements/views.py` (lines 1-122) applying the rename map, with these specific changes:
  - Replace the AP import `from app.accounts_payable.models import AccountsPayable` with `from app.sales_invoices.models import SalesInvoice`.
  - Keep `from app.customers.models import Customer` (replace the vendor imports; drop `populate_vat_category_choices`/`generate_next_vendor_code` vendor helpers — collections don't quick-add customers in this scope).
  - `_get_gl_accounts()` returns AR + Creditable-WHT-Receivable:

```python
def _get_gl_accounts():
    """Return AR-Trade (10201) and Creditable WHT Receivable (10212) accounts."""
    return {
        'ar': Account.query.filter_by(code='10201').first(),
        'wt': Account.query.filter_by(code='10212').first(),
    }
```

  - `generate_crv_number()` mirrors `generate_cdv_number()` but with prefix `CR-{year}-{month:02d}-` and queries `CashReceiptVoucher.crv_number`.

- [ ] **Step 2.2: Add `_output_vat_buckets(crv)`** — copy `_cdv_input_vat_buckets` (CDV views.py:214-247) renamed, but read `output_vat_account` instead of `input_vat_account` and iterate `crv.revenue_lines`:

```python
def _output_vat_buckets(crv):
    """Group output VAT by VATCategory.output_vat_account. Raises if a VAT-bearing
    revenue line's category has no output account."""
    if Decimal(str(crv.total_vat)) <= 0:
        return []
    categories = {c.code: c for c in VATCategory.query.all()}
    buckets = {}
    for line in crv.revenue_lines:
        vat_amt = Decimal(str(line.vat_amount or 0))
        if vat_amt <= 0:
            continue
        cat = categories.get(line.vat_category)
        acct = cat.output_vat_account if cat else None
        if acct is None:
            label = cat.code if cat else (line.vat_category or 'unknown')
            raise ValueError(
                f"VAT category '{label}' has no Output Tax account configured. "
                "Set it in VAT Categories before posting.")
        if acct.id not in buckets:
            buckets[acct.id] = [acct, Decimal('0.00')]
        buckets[acct.id][1] += vat_amt
    ordered = [(b[0], b[1]) for b in sorted(buckets.values(), key=lambda b: b[0].code)]
    return [(acct, amt) for acct, amt in ordered if amt != Decimal('0.00')]
```

- [ ] **Step 2.2b: Add `_post_crv_je(crv, user_id)`** — the inverted JE. Use this verbatim (it is `_post_cdv_je` with debit↔credit swapped, AR/Output-VAT/WHT-Receivable accounts, and the residual absorbed into the first revenue line's CREDIT):

```python
def _post_crv_je(crv, user_id):
    """Create the receipt JE: Cr AR + Cr Revenue + Cr Output VAT; Dr WHT Recv + Dr Cash."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine

    accts = _get_gl_accounts()
    ar_account = accts['ar']
    if not ar_account:
        raise ValueError("Accounts Receivable - Trade (10201) not found in COA.")
    cash_account = crv.cash_account
    if not cash_account:
        raise ValueError("Cash/Bank account not set on the receipt.")

    wt_account = None
    if crv.total_wt and Decimal(str(crv.total_wt)) > 0:
        wt_account = accts['wt']
        if not wt_account:
            raise ValueError("Creditable Withholding Tax (10212) not found in COA.")

    je_status = 'posted' if crv.status == 'posted' else 'draft'
    je = JournalEntry(
        entry_number=generate_entry_number(crv.branch_id),
        entry_date=crv.crv_date,
        description=f'CR {crv.crv_number} — {crv.customer_name}',
        reference=crv.crv_number,
        entry_type='receipt',
        branch_id=crv.branch_id,
        created_by_id=user_id,
        status=je_status,
        posted_by_id=user_id if je_status == 'posted' else None,
        posted_at=ph_now() if je_status == 'posted' else None,
        is_balanced=False,
        total_debit=Decimal('0.00'),
        total_credit=Decimal('0.00'),
    )
    db.session.add(je)
    db.session.flush()

    line_num = 1
    first_revenue_line = None
    all_lines = []

    # Credit: AR per applied invoice
    for ar_line in crv.ar_lines:
        jl = JournalEntryLine(
            entry_id=je.id, line_number=line_num, account_id=ar_account.id,
            description=f'AR Collection: {ar_line.invoice_number}',
            debit_amount=Decimal('0.00'),
            credit_amount=Decimal(str(ar_line.amount_applied)))
        db.session.add(jl); all_lines.append(jl); line_num += 1

    # Credit: revenue (net base) per direct revenue line
    for rl in crv.revenue_lines:
        if not rl.account_id:
            continue
        net_base = Decimal(str(rl.line_total)) - Decimal(str(rl.vat_amount))
        jl = JournalEntryLine(
            entry_id=je.id, line_number=line_num, account_id=rl.account_id,
            description=rl.description or '',
            debit_amount=Decimal('0.00'), credit_amount=net_base)
        db.session.add(jl); all_lines.append(jl)
        if first_revenue_line is None:
            first_revenue_line = jl
        line_num += 1

    # Credit: output VAT buckets
    for vat_acct, vat_amt in _output_vat_buckets(crv):
        if vat_amt <= 0:
            continue
        jl = JournalEntryLine(
            entry_id=je.id, line_number=line_num, account_id=vat_acct.id,
            description=f'Output VAT: {crv.crv_number}',
            debit_amount=Decimal('0.00'), credit_amount=vat_amt)
        db.session.add(jl); all_lines.append(jl); line_num += 1

    # Debit: Creditable WHT Receivable
    if wt_account and Decimal(str(crv.total_wt)) > 0:
        jl = JournalEntryLine(
            entry_id=je.id, line_number=line_num, account_id=wt_account.id,
            description=f'Creditable WHT: {crv.crv_number}',
            debit_amount=Decimal(str(crv.total_wt)), credit_amount=Decimal('0.00'))
        db.session.add(jl); all_lines.append(jl); line_num += 1

    # Debit: Cash/Bank
    cash_line = JournalEntryLine(
        entry_id=je.id, line_number=line_num, account_id=cash_account.id,
        description=f'CR {crv.crv_number} — {crv.customer_name}',
        debit_amount=Decimal(str(crv.total_amount)), credit_amount=Decimal('0.00'))
    db.session.add(cash_line); all_lines.append(cash_line)

    sum_debits = sum((l.debit_amount for l in all_lines), Decimal('0.00'))
    sum_credits = sum((l.credit_amount for l in all_lines), Decimal('0.00'))
    residual = sum_debits - sum_credits
    if residual != Decimal('0.00') and first_revenue_line is not None:
        first_revenue_line.credit_amount += residual

    db.session.flush()
    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(
            f"CRV JE is not balanced (debit={je.total_debit}, credit={je.total_credit}). "
            "Ensure every revenue line has a revenue account assigned.")
    return je
```

- [ ] **Step 2.3: Add `_create_crv_reversal_je(crv, reversal_date, user_id)` and `_build_crv_je_preview(crv)`** — copy `_create_cdv_reversal_je` (CDV:373-414) and `_build_cdv_je_preview` (CDV:448-486) with the rename map. The reversal helper is account-agnostic (it swaps the stored JE's debits/credits) so only renames apply. For `_build_crv_je_preview`, mirror the inverted structure of `_post_crv_je` (Cr AR / Cr Revenue / Cr Output VAT / Dr WHT Recv / Dr Cash) — model it on `_build_invoice_je` in `app/sales_invoices/views.py:241-302` (already AR-side) rather than the AP-side CDV preview.

- [ ] **Step 2.4: Write `tests/integration/test_crv_posting.py`.** Use `db_with_data`/`db_session` fixtures; seed an AR account (10201), a revenue account, a cash account, and a VAT category with an output account (create inline if the fixture lacks them, mirroring `tests/integration/test_ar_aging_views.py` helpers). Cover: posting a CRV with one AR line of 500 → JE has Cr AR 500 + Dr Cash 500, balanced; a direct revenue line (1120 incl 12% VAT) → Cr Revenue 1000 + Cr Output VAT 120 + Dr Cash 1120; a mixed CRV balances; an unbalanced/misconfigured (revenue line with no output VAT account) raises `ValueError`. Assert `je.is_balanced` and `je.total_debit == je.total_credit`.

- [ ] **Step 2.5: Run + commit.**

```
pytest tests/integration/test_crv_posting.py -v
git add app/cash_receipts/views.py tests/integration/test_crv_posting.py
git commit -m "feat(crv): journal-entry posting (Cr AR / Cr Revenue / Dr Cash) + reversal"
```

---

## Task 3: AR application, open-invoices, forms, routes, templates

> **After Task 2.**

**Files:**
- Modify: `app/cash_receipts/views.py` (append routes + AR application + line parsing + form context)
- Create: `app/cash_receipts/forms.py`
- Create: `app/cash_receipts/templates/cash_receipts/{list,form,detail,print}.html`
- Create: `tests/integration/test_crv_views.py`

**Interfaces consumed:** everything from Task 2. **Produces:** routes `cash_receipts.{list_crvs,create,edit,view,post,void,cancel,print_crv,open_invoices,export_excel,export_csv}`.

- [ ] **Step 3.1: Add `_apply_ar_collections(crv)` and `_reverse_ar_collections(crv)`** — verbatim (mirror of `_apply_ap_payments`/`_reverse_ap_payments` on `SalesInvoice`):

```python
def _apply_ar_collections(crv):
    """Increase invoice amount_paid and reduce balance on CRV post."""
    for ar_line in crv.ar_lines:
        inv = ar_line.sales_invoice
        inv.amount_paid = Decimal(str(inv.amount_paid)) + Decimal(str(ar_line.amount_applied))
        inv.balance = Decimal(str(inv.total_amount)) - inv.amount_paid
        if inv.balance <= 0:
            inv.status = 'paid'
        elif inv.amount_paid > 0:
            inv.status = 'partially_paid'


def _reverse_ar_collections(crv):
    """Reverse invoice amounts on CRV cancel. Raises ValueError on inconsistency."""
    for ar_line in crv.ar_lines:
        inv = ar_line.sales_invoice
        new_paid = Decimal(str(inv.amount_paid)) - Decimal(str(ar_line.amount_applied))
        if new_paid < 0:
            raise ValueError(
                f'Cannot cancel: reversing collection on {ar_line.invoice_number} '
                f'would result in negative amount_paid.')
        inv.amount_paid = new_paid
        inv.balance = Decimal(str(inv.total_amount)) - new_paid
        inv.status = 'posted' if inv.amount_paid <= 0 else 'partially_paid'
```

- [ ] **Step 3.2: Add `open_invoices()` route** — verbatim (mirror of `open_bills`, querying `SalesInvoice`):

```python
@cash_receipts_bp.route('/cash-receipts/open-invoices')
@login_required
@staff_or_above_required
def open_invoices():
    """JSON list of open sales invoices for a customer in the current branch."""
    customer_id = request.args.get('customer_id', type=int)
    if not customer_id:
        return jsonify([])
    branch_id = session.get('selected_branch_id')
    invs = SalesInvoice.query.filter(
        SalesInvoice.branch_id == branch_id,
        SalesInvoice.customer_id == customer_id,
        SalesInvoice.status.in_(['posted', 'partially_paid']),
        SalesInvoice.balance > 0,
    ).order_by(SalesInvoice.invoice_date).all()
    return jsonify([{
        'id': i.id,
        'invoice_number': i.invoice_number,
        'invoice_date': i.invoice_date.isoformat(),
        'due_date': i.due_date.isoformat() if i.due_date else None,
        'balance': float(i.balance),
    } for i in invs])
```

- [ ] **Step 3.3: Create `app/cash_receipts/forms.py`** by copying `app/cash_disbursements/forms.py` with the rename map (vendor→customer choices). Read the CDV form first; keep field names parallel.

- [ ] **Step 3.4: Append the remaining routes to `views.py`** — copy from CDV views.py the functions `_parse_line_items` (rename: AR lines validate `0 < amount_applied <= invoice.balance` against `SalesInvoice`; revenue lines parse like expense lines), `_form_context`, `list_crvs` (124-189), `create` (601-689), `edit` (690-792), `view` (793-803), `post` (834-866), `void` (868-907), `cancel` (909-951), `print_crv` (953-967), `_crv_export_data` + `export_excel`/`export_csv` (968-1054). Apply the rename map. **Key behavioral specifics to preserve (do not deviate):**
  - `create()` builds the CRV as `draft`, parses lines, calls `crv.calculate_totals()`, then `_post_crv_je(crv, user.id)` (draft JE), links `journal_entry_id`, commits, `log_create`.
  - `post()` (accountant/admin): draft→posted, promote the JE to posted, then `_apply_ar_collections(crv)`, commit, `log_audit(module='cash_receipt', action='post', ...)`.
  - `void()` (staff+): **draft only**; delete the draft JE; status→voided; require ≥10-char reason; `log_audit action='void'`.
  - `cancel()` (accountant/admin): **posted only**; `_reverse_ar_collections(crv)` then `_create_crv_reversal_je(...)`; status→cancelled; require ≥10-char reason + valid `reversal_date`; surface `ValueError` verbatim; `log_audit action='cancel'`.
  - AR-line validation rejects `amount_applied > invoice.balance` with a domain `ValueError`/flash that names the invoice and its open balance.

- [ ] **Step 3.5: Create the four templates** under `app/cash_receipts/templates/cash_receipts/` by copying the CDV templates (`app/cash_disbursements/templates/cash_disbursements/{list,form,detail,print}.html`) with the rename map. Specifics: the AR-line picker calls `/cash-receipts/open-invoices?customer_id=` and shows `invoice_number / invoice_date / balance`; route the customer + line VT/WT selects through `initSearchSelect` (search-select pattern); submit button reads **Save**/**Update**; list launch button reads **+ Enter CRV**. Use design tokens only (no hardcoded styling).

- [ ] **Step 3.6: Write `tests/integration/test_crv_views.py`.** Model `tests/integration/test_cdv_views.py`. Cover: create draft (GET form 200; POST creates draft + draft JE); post applies collection → invoice `balance` reduced and status flips to `partially_paid`/`paid`; full application → `paid`; over-application (`amount_applied > balance`) rejected with the invoice named; void (draft) deletes JE; cancel (posted) reverses collection (invoice balance restored) + creates reversal JE; `open_invoices` returns only open invoices for the customer/branch; branch scoping (other branch → 404); role gating (viewer blocked); **audit row asserted after create/post/void/cancel**.

- [ ] **Step 3.7: Run + commit.**

```
pytest tests/integration/test_crv_views.py -v
git add app/cash_receipts/ tests/integration/test_crv_views.py
git commit -m "feat(crv): AR application, open-invoices, forms, routes, templates"
```

---

## Task 4: Cash Receipts Journal (/journals/cr)

> **After Task 3** (needs posted CRVs/receipt JEs to report).

**Files:**
- Create: `app/journals/cr_journal_data.py`
- Modify: `app/journals/views.py` (activate `cr_journal`, add `cr_journal_export`, `_cr_journal_context`)
- Create: `app/journals/templates/journals/cr_journal.html` (+ `cr_journal_print.html` if CD has one)
- Create: `tests/integration/test_cr_journal.py`

- [ ] **Step 4.1: Create `app/journals/cr_journal_data.py`** by copying `app/journals/cd_journal_data.py` with the rename map. The columnar grouping keys on the receipt JE's accounts: AR (`10201`) as the control column, output-VAT account ids, and revenue accounts as the spread columns (mirror how CD groups AP/input-VAT/expense). `build_columnar_cr(posted_entries, draft_entries, ar_account_id, wt_account_id, output_vat_account_ids, ...)` and `build_cr_journal_xlsx(...)`.

- [ ] **Step 4.2: Activate the routes in `app/journals/views.py`.** Replace the stub `cr_journal` (currently `return redirect(url_for('dashboard.under_development', feature='Cash Receipts Journal'))`) with a real handler mirroring `cd_journal` (lines 369+): build `_cr_journal_context(branch_id)` (mirror `_cd_journal_context`, filtering JEs with `entry_type='receipt'`), render `journals/cr_journal.html`. Add `cr_journal_export` mirroring `cd_journal_export`. Add the `from app.journals.cr_journal_data import build_columnar_cr, build_cr_journal_xlsx` import at top.

- [ ] **Step 4.3: Create templates** `journals/cr_journal.html` (+ print) by copying the CD journal templates with the rename map.

- [ ] **Step 4.4: Write `tests/integration/test_cr_journal.py`.** Post a CRV (reuse a helper from Task 3 tests), then GET `/journals/cr` → 200 and the receipt appears in the columnar grid; GET `/journals/cr/export` → xlsx (PK magic bytes). Branch scoping + role gating.

- [ ] **Step 4.5: Run + commit.**

```
pytest tests/integration/test_cr_journal.py -v
git add app/journals/cr_journal_data.py app/journals/views.py app/journals/templates/journals/ tests/integration/test_cr_journal.py
git commit -m "feat(crv): activate Cash Receipts Journal (/journals/cr) + export"
```

---

## Task 5: Wire-up + retire legacy receipts + nav/permission repoint

> **After Tasks 3-4.**

**Files:**
- Modify: `app/__init__.py` (register CRV blueprint; remove legacy receipts model+blueprint)
- Modify: `app/users/module_access.py` (repoint `collections`)
- Modify: `app/templates/base.html` (Cash Receipts sidebar link)
- Delete: `app/receipts/` package
- Create: `tests/integration/test_crv_wireup.py`

- [ ] **Step 5.1: Register the CRV blueprint in `app/__init__.py`.** Near the CDV blueprint import (line 208) and registration (line 229), add:

```python
    from app.cash_receipts.views import cash_receipts_bp
```
```python
    app.register_blueprint(cash_receipts_bp)
```

- [ ] **Step 5.2: Remove the legacy receipts registration.** Delete line 183 (`from app.receipts.models import Receipt`), line 201 (`from app.receipts.views import receipts_bp`), and line 222 (`app.register_blueprint(receipts_bp)`). (The CRV model import was already added in Task 1.3.)

- [ ] **Step 5.3: Repoint `collections` in `app/users/module_access.py`.** Change the `collections` registry entry's `endpoints` from `('receipts.',)` to:

```python
     'endpoints': ('cash_receipts.', 'journals.cr_journal')},
```

- [ ] **Step 5.4: Update the sidebar in `app/templates/base.html`.** Find the "Cash Receipts" nav link (currently pointing at the `receipts` blueprint) and repoint it to `url_for('cash_receipts.list_crvs')`, keeping the `{% if can_access_module(current_user, 'collections') %}` gate and mirroring the active-state match used for the Cash Disbursements link (`request.endpoint.startswith('cash_receipts.')`). Grep `base.html` for `receipts.` and update every occurrence; if the inline `<style>` block is not involved, leave styles alone (base.html inline-style hazard).

- [ ] **Step 5.5: Delete the legacy package.** `git rm -r app/receipts/`. Then grep the repo for any remaining `from app.receipts` / `receipts_bp` / `url_for('receipts.` references and fix/remove them (e.g. templates, tests). The legacy `receipts` DB table is left intact (no migration drop).

- [ ] **Step 5.6: Write `tests/integration/test_crv_wireup.py`.** Cover: `/cash-receipts` reachable (200 for admin with branch); the old `/receipts` endpoint no longer registered (`url_for('receipts.list_receipts')` raises / route 404); a staff user WITHOUT `collections` is redirected (302) from `/cash-receipts`, WITH it reaches 200 (mirror `test_module_access.py` style); sidebar shows the Cash Receipts link pointing at `/cash-receipts` for a permitted user.

- [ ] **Step 5.7: Full regression + commit.**

```
pytest tests/unit/test_crv_models.py tests/integration/test_crv_posting.py tests/integration/test_crv_views.py tests/integration/test_cr_journal.py tests/integration/test_crv_wireup.py tests/integration/test_module_access.py -v
pytest -m "unit or integration" --tb=short -q 2>&1 | tail -20
git add -A
git commit -m "feat(crv): wire up cash_receipts blueprint, retire legacy receipts, repoint nav/permissions"
```

Expected: all CRV suites pass; no NEW failures vs the known baseline (`project-preexisting-test-failures`).

---

## Self-Review Checklist

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| `CashReceiptVoucher`/`CRVArLine`/`CRVRevenueLine` tables + migration | 1 |
| `calculate_totals` (ar+revenue−wt) / `calculate_amounts` VAT extraction | 1 |
| JE: Cr AR / Cr Revenue / Cr Output VAT / Dr WHT Recv / Dr Cash, balanced-or-raise | 2 |
| Output-VAT buckets via `VATCategory.output_vat_account` | 2 |
| Reversal JE helper | 2 |
| `_apply_ar_collections` reduces `SalesInvoice.balance` + status flip | 3 |
| `_reverse_ar_collections` on cancel | 3 |
| Over-application rejected (`amount_applied ≤ balance`) | 3 |
| `open_invoices` JSON endpoint | 3 |
| list/create/edit/view/post/void/cancel/print/export routes | 3 |
| Forms + templates (Save/Update + Enter CRV + design tokens + search-select) | 3 |
| Void=draft-only, Cancel=posted-only | 3 |
| `CR-YYYY-MM-NNNN` numbering | 2 |
| Audit on every write | 1,3 |
| Cash Receipts Journal `/journals/cr` + export | 4 |
| Register CRV blueprint; retire legacy `receipts` | 5 |
| Repoint `collections` registry + sidebar | 5 |
| Staff `collections` gating now applies | 5 |
| Period guard on post | 3 |
| Domain ValueError verbatim, broad Exception genericized | 2,3 |

**Placeholder scan:** No TBD/TODO. Mechanical copies are specified by exact source file + rename map (deterministic), with verbatim code for all non-mechanical (inverted-accounting, AR-application, model) functions.

**Type consistency:** `crv.ar_lines[*].amount_applied`/`invoice_id`/`sales_invoice`; `crv.revenue_lines[*].calculate_amounts()`; `_post_crv_je → JournalEntry`; `_apply_ar_collections(crv)`; `open_invoices` returns `{id, invoice_number, invoice_date, due_date, balance}`. All consistent across tasks. `total_revenue` (not `total_expense`) used throughout.
