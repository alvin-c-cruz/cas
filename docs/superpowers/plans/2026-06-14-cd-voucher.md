# Cash Disbursement Voucher (CDV) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the CDV module — a Cash Disbursement Voucher that records cash payments to vendors, pays off open APV bills, records direct expense payments, and auto-creates a balanced `disbursement` journal entry.

**Architecture:** Mirrors APV (Purchase Bills) — blueprint at `app/cash_disbursements/`, three models (`CashDisbursementVoucher` header + `CDVApLine` AP application rows + `CDVExpenseLine` identical to `PurchaseBillItem`), JE created on save and promoted on post, APV bill balances updated on post and reversed on cancel.

**Tech Stack:** Flask + SQLAlchemy + SQLite, Flask-WTF, Choices.js (bundled), openpyxl, Flask-Migrate

---

## File Map

**Create:**
- `app/cash_disbursements/__init__.py` — empty package marker
- `app/cash_disbursements/models.py` — `CashDisbursementVoucher`, `CDVApLine`, `CDVExpenseLine`
- `app/cash_disbursements/forms.py` — `CashDisbursementForm`
- `app/cash_disbursements/views.py` — all routes + JE helpers
- `app/cash_disbursements/utils.py` — `compute_cdv_summary`
- `app/cash_disbursements/templates/cash_disbursements/list.html`
- `app/cash_disbursements/templates/cash_disbursements/form.html`
- `app/cash_disbursements/templates/cash_disbursements/detail.html`
- `app/cash_disbursements/templates/cash_disbursements/print.html`
- `tests/unit/test_cdv_models.py`
- `tests/integration/test_cdv_views.py`

**Modify:**
- `app/__init__.py` — import models + register blueprint
- `app/templates/base.html` — update Cash Disbursements nav link

---

## Task 1: Data Models

**Files:**
- Create: `app/cash_disbursements/__init__.py`
- Create: `app/cash_disbursements/models.py`

- [ ] **Step 1: Create the package and models file**

Create `app/cash_disbursements/__init__.py` (empty).

Create `app/cash_disbursements/models.py`:

```python
from app import db
from app.utils import ph_now
from decimal import Decimal


class CashDisbursementVoucher(db.Model):
    __tablename__ = 'cash_disbursement_vouchers'

    id = db.Column(db.Integer, primary_key=True)

    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    branch = db.relationship('Branch', foreign_keys=[branch_id])

    cdv_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    cdv_date = db.Column(db.Date, nullable=False, index=True)

    vendor_id = db.Column(db.Integer, db.ForeignKey('vendors.id'), nullable=False, index=True)
    vendor = db.relationship('Vendor', backref='cash_disbursements')
    vendor_name = db.Column(db.String(200), nullable=False)
    vendor_tin = db.Column(db.String(20))

    payment_method = db.Column(db.String(20), nullable=False, default='cash')
    check_number = db.Column(db.String(50))
    check_date = db.Column(db.Date)
    check_bank = db.Column(db.String(100))

    cash_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=False)
    cash_account = db.relationship('Account', foreign_keys=[cash_account_id])

    notes = db.Column(db.Text, nullable=False, default='')

    total_ap_applied = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_expense = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_vat = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_wt = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_amount = db.Column(db.Numeric(15, 2), default=0, nullable=False)

    vat_override = db.Column(db.Boolean, default=False, nullable=False)
    wt_override = db.Column(db.Boolean, default=False, nullable=False)

    status = db.Column(db.String(20), default='draft', nullable=False, index=True)

    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'), nullable=True)
    journal_entry = db.relationship('JournalEntry', foreign_keys=[journal_entry_id])

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[created_by_id], backref='created_cdvs')
    posted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    posted_by = db.relationship('User', foreign_keys=[posted_by_id], backref='posted_cdvs')
    voided_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    voided_by = db.relationship('User', foreign_keys=[voided_by_id], backref='voided_cdvs')

    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)
    posted_at = db.Column(db.DateTime)
    voided_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)

    void_reason = db.Column(db.String(255))
    cancel_reason = db.Column(db.String(500))

    ap_lines = db.relationship('CDVApLine', backref='cdv', lazy='select',
                               cascade='all, delete-orphan',
                               order_by='CDVApLine.line_number')
    expense_lines = db.relationship('CDVExpenseLine', backref='cdv', lazy='select',
                                    cascade='all, delete-orphan',
                                    order_by='CDVExpenseLine.line_number')

    def __repr__(self):
        return f'<CashDisbursementVoucher {self.cdv_number}>'

    def calculate_totals(self):
        self.total_ap_applied = sum(
            (Decimal(str(l.amount_applied)) for l in self.ap_lines),
            Decimal('0.00')
        )
        auto_expense = Decimal('0.00')
        auto_vat = Decimal('0.00')
        auto_wt = Decimal('0.00')
        for line in self.expense_lines:
            auto_expense += Decimal(str(line.line_total))
            auto_vat += Decimal(str(line.vat_amount))
            auto_wt += Decimal(str(line.wt_amount or 0))
        self.total_expense = auto_expense
        if not self.vat_override:
            self.total_vat = auto_vat
        if not self.wt_override:
            self.total_wt = auto_wt
        self.total_amount = self.total_ap_applied + self.total_expense - self.total_wt

    def to_dict(self):
        return {
            'id': self.id,
            'cdv_number': self.cdv_number,
            'cdv_date': self.cdv_date.isoformat() if self.cdv_date else None,
            'vendor_id': self.vendor_id,
            'vendor_name': self.vendor_name,
            'payment_method': self.payment_method,
            'total_ap_applied': float(self.total_ap_applied),
            'total_expense': float(self.total_expense),
            'total_vat': float(self.total_vat),
            'total_wt': float(self.total_wt),
            'total_amount': float(self.total_amount),
            'status': self.status,
        }


class CDVApLine(db.Model):
    __tablename__ = 'cdv_ap_lines'

    id = db.Column(db.Integer, primary_key=True)
    cdv_id = db.Column(db.Integer, db.ForeignKey('cash_disbursement_vouchers.id'),
                       nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
    bill_id = db.Column(db.Integer, db.ForeignKey('purchase_bills.id'), nullable=False)
    bill = db.relationship('PurchaseBill', foreign_keys=[bill_id])
    bill_number = db.Column(db.String(50), nullable=False)
    original_balance = db.Column(db.Numeric(15, 2), nullable=False)
    amount_applied = db.Column(db.Numeric(15, 2), nullable=False)

    def __repr__(self):
        return f'<CDVApLine cdv={self.cdv_id} bill={self.bill_number}>'

    def to_dict(self):
        return {
            'id': self.id,
            'bill_id': self.bill_id,
            'bill_number': self.bill_number,
            'original_balance': float(self.original_balance),
            'amount_applied': float(self.amount_applied),
        }


class CDVExpenseLine(db.Model):
    __tablename__ = 'cdv_expense_lines'

    id = db.Column(db.Integer, primary_key=True)
    cdv_id = db.Column(db.Integer, db.ForeignKey('cash_disbursement_vouchers.id'),
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
        return f'<CDVExpenseLine cdv={self.cdv_id} line={self.line_number}>'

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
            'wt_rate': float(self.wt_rate) if self.wt_rate is not None else None,
            'wt_amount': float(self.wt_amount),
        }
```

- [ ] **Step 2: Register models in `app/__init__.py`**

In `app/__init__.py`, after line `from app.purchase_bills.models import ...`, add:

```python
from app.cash_disbursements.models import CashDisbursementVoucher, CDVApLine, CDVExpenseLine
```

- [ ] **Step 3: Generate and run migration**

```powershell
flask db migrate -m "add cash_disbursement_vouchers, cdv_ap_lines, cdv_expense_lines tables"
flask db upgrade
```

Expected: migration runs cleanly, three new tables created.

- [ ] **Step 4: Verify tables exist**

```powershell
python -c "from app import create_app, db; app = create_app('development'); ctx = app.app_context(); ctx.push(); print([t for t in db.engine.dialect.get_table_names(db.engine.connect()) if 'cdv' in t or 'cash_disb' in t])"
```

Expected: `['cash_disbursement_vouchers', 'cdv_ap_lines', 'cdv_expense_lines']`

- [ ] **Step 5: Commit**

```powershell
git add app/cash_disbursements/__init__.py app/cash_disbursements/models.py app/__init__.py migrations/
git commit -m "feat: add CDV, CDVApLine, CDVExpenseLine models and migration"
```

---

## Task 2: Unit Tests for Models

**Files:**
- Create: `tests/unit/test_cdv_models.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_cdv_models.py`:

```python
"""Unit tests for CDVExpenseLine and CashDisbursementVoucher model methods."""
import pytest
from decimal import Decimal
from app.cash_disbursements.models import (
    CashDisbursementVoucher, CDVApLine, CDVExpenseLine
)

pytestmark = [pytest.mark.unit]


@pytest.mark.usefixtures("app")
class TestCDVExpenseLineCalculateAmounts:

    def _make_line(self, amount, vat_rate=Decimal('0'), wt_rate=None):
        line = CDVExpenseLine()
        line.amount = Decimal(str(amount))
        line.vat_rate = vat_rate
        line.wt_rate = Decimal(str(wt_rate)) if wt_rate is not None else None
        line.calculate_amounts()
        return line

    def test_zero_vat_line_total_equals_amount(self):
        line = self._make_line('1000.00', vat_rate=Decimal('0'))
        assert line.line_total == Decimal('1000.00')
        assert line.vat_amount == Decimal('0.00')

    def test_twelve_percent_vat_extracted(self):
        # 11200 VAT-inclusive at 12%: net = 10000, vat = 1200
        line = self._make_line('11200.00', vat_rate=Decimal('12'))
        assert line.line_total == Decimal('11200.00')
        assert line.vat_amount == Decimal('1200.00')

    def test_line_total_always_equals_amount(self):
        line = self._make_line('5000.00', vat_rate=Decimal('12'))
        assert line.line_total == line.amount

    def test_wht_computed_on_net_base(self):
        # net_base = 10000, wt at 2% = 200
        line = self._make_line('11200.00', vat_rate=Decimal('12'), wt_rate='2')
        assert line.wt_amount == Decimal('200.00')

    def test_wht_zero_when_no_rate(self):
        line = self._make_line('5000.00', vat_rate=Decimal('0'), wt_rate=None)
        assert line.wt_amount == Decimal('0.00')

    def test_zero_vat_no_wht(self):
        line = self._make_line('3000.00')
        assert line.vat_amount == Decimal('0.00')
        assert line.wt_amount == Decimal('0.00')
        assert line.line_total == Decimal('3000.00')


@pytest.mark.usefixtures("app")
class TestCDVCalculateTotals:

    def _make_expense_line(self, amount, vat_rate=Decimal('0'), wt_rate=None):
        line = CDVExpenseLine()
        line.amount = Decimal(str(amount))
        line.vat_rate = Decimal(str(vat_rate))
        line.wt_rate = Decimal(str(wt_rate)) if wt_rate is not None else None
        line.calculate_amounts()
        return line

    def _make_ap_line(self, amount_applied):
        line = CDVApLine()
        line.amount_applied = Decimal(str(amount_applied))
        return line

    def _make_cdv(self, ap_lines=None, expense_lines=None):
        cdv = CashDisbursementVoucher()
        cdv.vat_override = False
        cdv.wt_override = False
        cdv.ap_lines = ap_lines or []
        cdv.expense_lines = expense_lines or []
        return cdv

    def test_ap_only_cdv(self):
        cdv = self._make_cdv(ap_lines=[self._make_ap_line('5000.00')])
        cdv.calculate_totals()
        assert cdv.total_ap_applied == Decimal('5000.00')
        assert cdv.total_expense == Decimal('0.00')
        assert cdv.total_wt == Decimal('0.00')
        assert cdv.total_amount == Decimal('5000.00')

    def test_expense_only_cdv(self):
        line = self._make_expense_line('11200.00', vat_rate=Decimal('12'), wt_rate='2')
        cdv = self._make_cdv(expense_lines=[line])
        cdv.calculate_totals()
        assert cdv.total_expense == Decimal('11200.00')
        assert cdv.total_vat == Decimal('1200.00')
        assert cdv.total_wt == Decimal('200.00')
        # total_amount = 0 + 11200 - 200 = 11000
        assert cdv.total_amount == Decimal('11000.00')

    def test_mixed_cdv(self):
        ap = self._make_ap_line('3000.00')
        exp = self._make_expense_line('5600.00', vat_rate=Decimal('12'), wt_rate='2')
        cdv = self._make_cdv(ap_lines=[ap], expense_lines=[exp])
        cdv.calculate_totals()
        # total_ap_applied = 3000
        # total_expense = 5600, total_vat = 600, wt = 100
        # total_amount = 3000 + 5600 - 100 = 8500
        assert cdv.total_ap_applied == Decimal('3000.00')
        assert cdv.total_expense == Decimal('5600.00')
        assert cdv.total_wt == Decimal('100.00')
        assert cdv.total_amount == Decimal('8500.00')

    def test_multiple_ap_lines_summed(self):
        cdv = self._make_cdv(ap_lines=[
            self._make_ap_line('1000.00'),
            self._make_ap_line('2000.00'),
        ])
        cdv.calculate_totals()
        assert cdv.total_ap_applied == Decimal('3000.00')
        assert cdv.total_amount == Decimal('3000.00')

    def test_wt_override_not_recalculated(self):
        line = self._make_expense_line('11200.00', vat_rate=Decimal('12'), wt_rate='2')
        cdv = self._make_cdv(expense_lines=[line])
        cdv.wt_override = True
        cdv.total_wt = Decimal('500.00')  # manual override
        cdv.calculate_totals()
        assert cdv.total_wt == Decimal('500.00')  # unchanged
```

- [ ] **Step 2: Run tests — expect PASS (models already exist from Task 1)**

```powershell
pytest tests/unit/test_cdv_models.py -v
```

Expected: all 11 tests PASS.

- [ ] **Step 3: Commit**

```powershell
git add tests/unit/test_cdv_models.py
git commit -m "test: unit tests for CDVExpenseLine.calculate_amounts and CashDisbursementVoucher.calculate_totals"
```
