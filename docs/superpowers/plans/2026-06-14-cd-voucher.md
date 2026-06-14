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

---

## Task 3: Form Class

**Files:**
- Create: `app/cash_disbursements/forms.py`

- [ ] **Step 1: Create the form**

Create `app/cash_disbursements/forms.py`:

```python
from flask_wtf import FlaskForm
from wtforms import StringField, DateField, TextAreaField, SelectField
from wtforms.validators import DataRequired, Length, Optional
from datetime import date


class CashDisbursementForm(FlaskForm):

    cdv_number = StringField('CD Number', validators=[
        DataRequired(message='CDV number is required.'),
        Length(max=50, message='CDV number must be 50 characters or less.')
    ])

    cdv_date = DateField('CDV Date', validators=[
        DataRequired(message='CDV date is required.')
    ], format='%Y-%m-%d', default=date.today)

    vendor_id = SelectField('Vendor', validators=[
        DataRequired(message='Vendor is required.')
    ], coerce=int)

    payment_method = SelectField('Payment Method', choices=[
        ('cash', 'Cash'),
        ('check', 'Check'),
        ('bank_transfer', 'Bank Transfer'),
        ('online', 'Online'),
    ], default='cash')

    check_number = StringField('Check Number', validators=[
        Optional(),
        Length(max=50)
    ])

    check_date = DateField('Check Date', validators=[Optional()], format='%Y-%m-%d')

    check_bank = StringField('Bank', validators=[
        Optional(),
        Length(max=100)
    ])

    cash_account_id = SelectField('Cash / Bank Account', validators=[
        DataRequired(message='Cash or bank account is required.')
    ], coerce=int)

    notes = TextAreaField('Notes (Particulars)', validators=[
        DataRequired(message='Notes are required — this becomes the Particulars in the CD Journal.')
    ])
```

- [ ] **Step 2: Commit**

```powershell
git add app/cash_disbursements/forms.py
git commit -m "feat: add CashDisbursementForm"
```

---

## Task 4: Blueprint Scaffold + Registration + Nav

**Files:**
- Create: `app/cash_disbursements/views.py` — skeleton only (list stub, open-bills stub)
- Modify: `app/__init__.py` — register blueprint
- Modify: `app/templates/base.html` — update Cash Disbursements nav link

- [ ] **Step 1: Create views.py skeleton**

Create `app/cash_disbursements/views.py`:

```python
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, session, abort, current_app
from flask_login import login_required, current_user
from functools import wraps
from sqlalchemy.orm import selectinload
from app import db
from app.cash_disbursements.models import CashDisbursementVoucher, CDVApLine, CDVExpenseLine
from app.cash_disbursements.forms import CashDisbursementForm
from app.purchase_bills.models import PurchaseBill
from app.vendors.models import Vendor
from app.accounts.models import Account
from app.vat_categories.models import VATCategory
from app.withholding_tax.models import WithholdingTax
from app.audit.utils import log_create, log_update, log_audit, model_to_dict
from app.utils import ph_now
from app.utils.export import export_to_excel, export_to_csv
from app.settings import AppSettings
from app.periods.utils import validate_transaction_date_with_flash
from app.journal_entries.utils import generate_entry_number
from datetime import date
from decimal import Decimal
import json

cash_disbursements_bp = Blueprint('cash_disbursements', __name__,
                                   template_folder='templates')


def accountant_or_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if current_user.role not in ['accountant', 'admin']:
            flash('Only Accountants and Administrators can perform this action.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


def staff_or_above_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if current_user.role not in ['staff', 'accountant', 'admin']:
            flash('You do not have permission to perform this action.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


VALID_CDV_STATUSES = {'draft', 'posted', 'voided', 'cancelled'}


@cash_disbursements_bp.before_request
def require_branch_selection():
    if current_user.is_authenticated and not session.get('selected_branch_id'):
        flash('Please select a branch to continue.', 'warning')
        return redirect(url_for('users.select_branch'))


def generate_cdv_number():
    """Generate next CDV number: CD-YYYY-MM-NNNN, sequential per month."""
    now = ph_now()
    prefix = f'CD-{now.year}-{now.month:02d}-'
    latest = CashDisbursementVoucher.query.filter(
        CashDisbursementVoucher.cdv_number.like(f'{prefix}%')
    ).order_by(CashDisbursementVoucher.cdv_number.desc()).first()
    if latest:
        try:
            last_num = int(latest.cdv_number.split('-')[-1])
            next_num = last_num + 1
        except (ValueError, IndexError):
            next_num = 1
    else:
        next_num = 1
    return f'{prefix}{next_num:04d}'


def _get_cdv_or_404(id):
    cdv = CashDisbursementVoucher.query.get_or_404(id)
    if cdv.branch_id != session.get('selected_branch_id'):
        abort(404)
    return cdv


def _get_gl_accounts():
    return {
        'ap': Account.query.filter_by(code='20101').first(),
        'wt': Account.query.filter_by(code='20301').first(),
    }


def _get_all_accounts_for_select():
    all_accts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    parent_ids = {a.parent_id for a in all_accts if a.parent_id is not None}
    id_map = {a.id: a for a in all_accts}

    def _depth(acct):
        d, p = 0, acct.parent_id
        while p and p in id_map:
            d += 1
            p = id_map[p].parent_id
        return d

    result = []
    for a in all_accts:
        d = a.to_dict()
        d['is_group'] = a.id in parent_ids
        d['depth'] = _depth(a)
        result.append(d)
    return result


@cash_disbursements_bp.route('/cash-disbursements')
@login_required
def list_cdvs():
    from app.cash_disbursements.utils import compute_cdv_summary
    page = request.args.get('page', 1, type=int)
    per_page = 50
    branch_id = session.get('selected_branch_id')
    query = CashDisbursementVoucher.query.filter_by(branch_id=branch_id)

    status_filter = request.args.get('status', 'all')
    if status_filter in VALID_CDV_STATUSES:
        query = query.filter_by(status=status_filter)

    vendor_filter = request.args.get('vendor', 'all')
    if vendor_filter != 'all':
        try:
            query = query.filter_by(vendor_id=int(vendor_filter))
        except ValueError:
            pass

    q = request.args.get('q', '').strip()
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(
            CashDisbursementVoucher.cdv_number.ilike(like),
            CashDisbursementVoucher.vendor_name.ilike(like)
        ))

    date_from = request.args.get('date_from', '')
    if date_from:
        try:
            query = query.filter(CashDisbursementVoucher.cdv_date >= date.fromisoformat(date_from))
        except ValueError:
            pass

    date_to = request.args.get('date_to', '')
    if date_to:
        try:
            query = query.filter(CashDisbursementVoucher.cdv_date <= date.fromisoformat(date_to))
        except ValueError:
            pass

    pm_filter = request.args.get('payment_method', 'all')
    if pm_filter != 'all':
        query = query.filter_by(payment_method=pm_filter)

    query = query.order_by(CashDisbursementVoucher.cdv_date.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    summary = compute_cdv_summary(branch_id)
    vendors = Vendor.query.filter_by(is_active=True).order_by(Vendor.name).all()

    return render_template('cash_disbursements/list.html',
                           cdvs=pagination.items,
                           pagination=pagination,
                           vendors=vendors,
                           summary=summary,
                           today=ph_now().date(),
                           status_filter=status_filter,
                           vendor_filter=vendor_filter,
                           q=q,
                           date_from=date_from,
                           date_to=date_to,
                           pm_filter=pm_filter)


@cash_disbursements_bp.route('/cash-disbursements/open-bills')
@login_required
def open_bills():
    """Return JSON list of open APV bills for the given vendor in the current branch."""
    vendor_id = request.args.get('vendor_id', type=int)
    if not vendor_id:
        return jsonify([])
    branch_id = session.get('selected_branch_id')
    bills = PurchaseBill.query.filter(
        PurchaseBill.branch_id == branch_id,
        PurchaseBill.vendor_id == vendor_id,
        PurchaseBill.status.in_(['posted', 'partially_paid']),
        PurchaseBill.balance > 0
    ).order_by(PurchaseBill.bill_date).all()
    return jsonify([{
        'id': b.id,
        'bill_number': b.bill_number,
        'vendor_invoice_number': b.vendor_invoice_number or '',
        'bill_date': b.bill_date.isoformat(),
        'balance': float(b.balance),
    } for b in bills])
```

- [ ] **Step 2: Register the blueprint in `app/__init__.py`**

After `from app.purchase_bills.models import ...` add the model import (already done in Task 1).

After `from app.purchase_bills.views import purchase_bills_bp`, add:
```python
from app.cash_disbursements.views import cash_disbursements_bp
```

After `app.register_blueprint(purchase_bills_bp)`, add:
```python
app.register_blueprint(cash_disbursements_bp)
```

- [ ] **Step 3: Update Cash Disbursements nav link in `app/templates/base.html`**

Replace lines 1136–1140 (the "Soon" payment link) with:

```html
<a href="{{ url_for('cash_disbursements.list_cdvs') }}" class="nav-item {% if request.endpoint and request.endpoint.startswith('cash_disbursements.') %}active{% endif %}">
    <span class="nav-icon">💸</span>
    <span class="nav-text">Cash Disbursements</span>
</a>
```

- [ ] **Step 4: Smoke test — server starts and list page loads**

```powershell
python flask_app.py
```

Navigate to `http://127.0.0.1:5000/cash-disbursements`. Expected: empty list page renders without errors (utils import will fail until Task 5 — create a stub `utils.py` first if needed).

Create stub `app/cash_disbursements/utils.py` to unblock the server:

```python
from decimal import Decimal
from app.utils import ph_now


def compute_cdv_summary(branch_id):
    from app import db
    from app.cash_disbursements.models import CashDisbursementVoucher
    today = ph_now().date()
    import calendar
    month_start = today.replace(day=1)
    month_end = today.replace(day=calendar.monthrange(today.year, today.month)[1])

    disbursed = (
        db.session.query(db.func.coalesce(db.func.sum(CashDisbursementVoucher.total_amount), 0))
        .filter(
            CashDisbursementVoucher.branch_id == branch_id,
            CashDisbursementVoucher.status == 'posted',
            CashDisbursementVoucher.cdv_date >= month_start,
            CashDisbursementVoucher.cdv_date <= month_end,
        )
        .scalar()
    )
    draft_count = (
        db.session.query(db.func.count(CashDisbursementVoucher.id))
        .filter(
            CashDisbursementVoucher.branch_id == branch_id,
            CashDisbursementVoucher.status == 'draft',
        )
        .scalar()
    )
    cancelled_count = (
        db.session.query(db.func.count(CashDisbursementVoucher.id))
        .filter(
            CashDisbursementVoucher.branch_id == branch_id,
            CashDisbursementVoucher.status == 'cancelled',
        )
        .scalar()
    )
    return {
        'disbursed_this_month': Decimal(str(disbursed)).quantize(Decimal('0.01')),
        'draft_count': draft_count,
        'cancelled_count': cancelled_count,
    }
```

- [ ] **Step 5: Commit**

```powershell
git add app/cash_disbursements/views.py app/cash_disbursements/utils.py app/__init__.py app/templates/base.html
git commit -m "feat: CDV blueprint scaffold, registration, nav link, utils stub"
```
