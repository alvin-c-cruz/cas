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

---

## Task 5: List Template

**Files:**
- Create: `app/cash_disbursements/templates/cash_disbursements/list.html`

- [ ] **Step 1: Create the list template**

Create `app/cash_disbursements/templates/cash_disbursements/list.html`:

```html
{% extends "base.html" %}
{% block title %}Cash Disbursements{% endblock %}
{% block page_title %}Cash Disbursements{% endblock %}
{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', filename='choices.min.css') }}">
<style>
.cdv-summary-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
    margin-bottom: 16px;
}
.cdv-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    padding: 14px 16px;
}
.cdv-card-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-2);
}
.cdv-card-value {
    font-size: 20px;
    font-weight: 700;
    font-family: var(--mono);
    margin: 4px 0 2px;
}
.cdv-card-detail { font-size: 12px; color: var(--text-3); }
.cdv-filter-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: flex-end;
    margin-bottom: 16px;
}
.cdv-filter-bar .form-control { width: auto; }
.cdv-filter-bar select.form-control { width: 160px; }
.cdv-filter-bar input[type="date"].form-control { width: 150px; }
.cdv-filter-search { flex: 1 1 200px; min-width: 180px; }
.cdv-date-group { display: flex; flex-direction: column; gap: 2px; }
.cdv-date-group__label {
    font-size: 10px; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.05em; color: #64748b; padding-left: 2px;
}
.btn-action {
    padding: 4px 8px; border-radius: 4px;
    background: var(--bg); border: 1px solid var(--border);
    cursor: pointer; font-size: 14px;
}
.btn-action:hover { background: var(--border); }
.choices__list--dropdown { min-width: 220px; }
.choices__list--dropdown .choices__list { max-height: 200px; overflow-y: auto; }
.cdv-filter-bar .choices { width: 160px; margin-bottom: 0; }
.cdv-filter-bar .choices__inner {
    padding: 10px 36px 10px 14px; font-size: 14px;
    border: 1px solid #cbd5e1; border-radius: 6px;
    background: white; min-height: unset;
    font-family: 'Inter', sans-serif; box-sizing: border-box; transition: all 0.2s;
}
.cdv-filter-bar .choices.is-focused .choices__inner,
.cdv-filter-bar .choices.is-open .choices__inner {
    border-color: #3b82f6; box-shadow: 0 0 0 3px rgba(59,130,246,0.1); outline: none;
}
.cdv-filter-bar .choices__list--single { padding: 0; }
.cdv-filter-bar .choices__list--single .choices__item { font-size: 14px; font-family: 'Inter', sans-serif; }
.cdv-filter-bar .choices[data-type*='select-one']::after { border-color: #64748b transparent transparent; right: 14px; }
.cdv-filter-bar .choices[data-type*='select-one'].is-open::after { border-color: transparent transparent #64748b; }
@media (max-width: 1024px) { .cdv-summary-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 640px)  { .cdv-summary-grid { grid-template-columns: 1fr; } }
</style>
{% endblock %}
{% block content %}

<div class="cdv-summary-grid">
    <div class="cdv-card">
        <div class="cdv-card-label">Disbursed This Month</div>
        <div class="cdv-card-value">₱{{ '{:,.2f}'.format(summary.disbursed_this_month) }}</div>
        <div class="cdv-card-detail">posted CDVs</div>
    </div>
    <div class="cdv-card">
        <div class="cdv-card-label">Drafts</div>
        <div class="cdv-card-value">{{ summary.draft_count }}</div>
        <div class="cdv-card-detail">to finish</div>
    </div>
    <div class="cdv-card">
        <div class="cdv-card-label" style="color:var(--red);">Cancelled</div>
        <div class="cdv-card-value" style="color:var(--red);">{{ summary.cancelled_count }}</div>
        <div class="cdv-card-detail">this branch</div>
    </div>
</div>

<form method="GET" action="{{ url_for('cash_disbursements.list_cdvs') }}" class="cdv-filter-bar">
    <input type="text" name="q" value="{{ q }}" placeholder="Search CD # or vendor"
           class="form-control form-control-sm cdv-filter-search">
    <select name="status" class="form-control form-control-sm">
        <option value="all" {% if status_filter == 'all' %}selected{% endif %}>All Statuses</option>
        <option value="draft" {% if status_filter == 'draft' %}selected{% endif %}>Draft</option>
        <option value="posted" {% if status_filter == 'posted' %}selected{% endif %}>Posted</option>
        <option value="voided" {% if status_filter == 'voided' %}selected{% endif %}>Voided</option>
        <option value="cancelled" {% if status_filter == 'cancelled' %}selected{% endif %}>Cancelled</option>
    </select>
    <select name="vendor" id="vendor-filter" class="form-control form-control-sm">
        <option value="all">All Vendors</option>
        {% for v in vendors %}
        <option value="{{ v.id }}" {% if vendor_filter == v.id|string %}selected{% endif %}>{{ v.name }}</option>
        {% endfor %}
    </select>
    <select name="payment_method" class="form-control form-control-sm">
        <option value="all" {% if pm_filter == 'all' %}selected{% endif %}>All Methods</option>
        <option value="cash" {% if pm_filter == 'cash' %}selected{% endif %}>Cash</option>
        <option value="check" {% if pm_filter == 'check' %}selected{% endif %}>Check</option>
        <option value="bank_transfer" {% if pm_filter == 'bank_transfer' %}selected{% endif %}>Bank Transfer</option>
        <option value="online" {% if pm_filter == 'online' %}selected{% endif %}>Online</option>
    </select>
    <label class="cdv-date-group">
        <span class="cdv-date-group__label">From</span>
        <input type="date" name="date_from" value="{{ date_from }}" class="form-control form-control-sm">
    </label>
    <label class="cdv-date-group">
        <span class="cdv-date-group__label">To</span>
        <input type="date" name="date_to" value="{{ date_to }}" class="form-control form-control-sm">
    </label>
    <button type="submit" class="btn btn-primary btn-sm">Filter</button>
    <a href="{{ url_for('cash_disbursements.list_cdvs') }}" class="btn btn-secondary btn-sm">Clear</a>
</form>

<div class="card">
    <div class="card-header">
        <div class="card-header-actions" style="display:flex; gap:8px; align-items:center;">
            <a href="{{ url_for('cash_disbursements.export_excel', status=status_filter, vendor=vendor_filter, q=q, date_from=date_from, date_to=date_to) }}"
               class="btn btn-secondary">📊 Export Excel</a>
            <a href="{{ url_for('cash_disbursements.export_csv_route', status=status_filter, vendor=vendor_filter, q=q, date_from=date_from, date_to=date_to) }}"
               class="btn btn-secondary">📄 Export CSV</a>
            {% if current_user.role in ['staff', 'accountant', 'admin'] %}
            <a href="{{ url_for('cash_disbursements.create') }}" class="btn btn-primary">➕ Enter CDV</a>
            {% endif %}
        </div>
    </div>
    <div class="card-body">
        {% if cdvs %}
        {% set badge_map = {'draft':'draft','posted':'posted','voided':'void','cancelled':'cancelled'} %}
        <div class="table-wrap">
        <table class="table">
            <thead>
                <tr>
                    <th>CD #</th><th>Date</th><th>Vendor</th><th>Method</th>
                    <th style="text-align:right;">AP Applied</th>
                    <th style="text-align:right;">Expenses</th>
                    <th style="text-align:right;">WT</th>
                    <th style="text-align:right;">Net Cash Out</th>
                    <th>Status</th><th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {% for cdv in cdvs %}
                <tr>
                    <td><a href="{{ url_for('cash_disbursements.view', id=cdv.id) }}"
                           style="font-weight:600;color:var(--blue);">{{ cdv.cdv_number }}</a></td>
                    <td>{{ cdv.cdv_date.strftime('%b %d, %Y') }}</td>
                    <td>{{ cdv.vendor_name }}</td>
                    <td>{{ cdv.payment_method|replace('_',' ')|title }}</td>
                    <td style="text-align:right;font-family:var(--mono);">
                        {% if cdv.total_ap_applied > 0 %}₱{{ '{:,.2f}'.format(cdv.total_ap_applied) }}{% else %}—{% endif %}
                    </td>
                    <td style="text-align:right;font-family:var(--mono);">
                        {% if cdv.total_expense > 0 %}₱{{ '{:,.2f}'.format(cdv.total_expense) }}{% else %}—{% endif %}
                    </td>
                    <td style="text-align:right;font-family:var(--mono);{% if cdv.total_wt > 0 %}color:var(--red);{% endif %}">
                        {% if cdv.total_wt > 0 %}-₱{{ '{:,.2f}'.format(cdv.total_wt) }}{% else %}—{% endif %}
                    </td>
                    <td style="text-align:right;font-family:var(--mono);font-weight:600;">₱{{ '{:,.2f}'.format(cdv.total_amount) }}</td>
                    <td><span class="badge badge-{{ badge_map.get(cdv.status, 'draft') }}">{{ cdv.status|title }}</span></td>
                    <td>
                        <a href="{{ url_for('cash_disbursements.view', id=cdv.id) }}" class="btn-action">👁️</a>
                        {% if cdv.status == 'draft' %}
                        <a href="{{ url_for('cash_disbursements.edit', id=cdv.id) }}" class="btn-action">✏️</a>
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        </div>
        {% else %}
        {% set filters_active = q or status_filter != 'all' or vendor_filter != 'all' or date_from or date_to %}
        <div class="empty-state">
            {% if filters_active %}
            <p>No CDVs match your filters.</p>
            <a href="{{ url_for('cash_disbursements.list_cdvs') }}" class="btn btn-secondary">Clear Filters</a>
            {% else %}
            <p>No Cash Disbursement Vouchers found.</p>
            {% if current_user.role in ['staff', 'accountant', 'admin'] %}
            <a href="{{ url_for('cash_disbursements.create') }}" class="btn btn-primary">Enter First CDV</a>
            {% endif %}
            {% endif %}
        </div>
        {% endif %}
    </div>

    {% if pagination and pagination.pages > 1 %}
    <div class="card-footer" style="display:flex;justify-content:space-between;align-items:center;padding:16px">
        <div>
            Showing {{ ((pagination.page - 1) * pagination.per_page) + 1 }} to
            {{ [pagination.page * pagination.per_page, pagination.total]|min }} of
            {{ pagination.total }} CDVs
        </div>
        <div style="display:flex;gap:8px">
            {% if pagination.has_prev %}
            <a href="{{ url_for('cash_disbursements.list_cdvs', page=pagination.prev_num, status=status_filter, vendor=vendor_filter, q=q, date_from=date_from, date_to=date_to) }}"
               class="btn btn-secondary btn-sm">← Previous</a>
            {% endif %}
            {% if pagination.has_next %}
            <a href="{{ url_for('cash_disbursements.list_cdvs', page=pagination.next_num, status=status_filter, vendor=vendor_filter, q=q, date_from=date_from, date_to=date_to) }}"
               class="btn btn-secondary btn-sm">Next →</a>
            {% endif %}
        </div>
    </div>
    {% endif %}
</div>

<script src="{{ url_for('static', filename='choices.min.js') }}"></script>
<script>
(function () {
    const vendorSel = document.getElementById('vendor-filter');
    if (vendorSel) {
        new Choices(vendorSel, { searchEnabled: true, itemSelectText: '', shouldSort: false, allowHTML: false });
    }
})();
</script>
{% endblock %}
```

- [ ] **Step 2: Verify list page renders**

Start the server and navigate to `/cash-disbursements`. Expected: page renders, summary cards show zeroes, empty-state message appears.

- [ ] **Step 3: Commit**

```powershell
git add app/cash_disbursements/templates/cash_disbursements/list.html
git commit -m "feat: CDV list template"
```

---

## Task 6: Create and Edit Routes

**Files:**
- Modify: `app/cash_disbursements/views.py` — add `create`, `edit`, `_post_cdv_je`, `_cdv_input_vat_buckets`, `_apply_cdv_overrides`, `_build_cdv_je_preview` helpers

The create and edit routes mirror APV exactly. The key differences are:
1. Line items come in two hidden fields: `ap_lines` (JSON) and `expense_lines` (JSON)
2. `cash_account_id` is required (the account being credited)
3. No `due_date` field; `payment_method`/check fields instead

- [ ] **Step 1: Add helper functions to views.py**

Append to `app/cash_disbursements/views.py` after `open_bills()`:

```python
def _cdv_input_vat_buckets(cdv):
    """Group expense lines' input VAT by VATCategory.input_vat_account."""
    if Decimal(str(cdv.total_vat)) <= 0:
        return []
    categories = {c.code: c for c in VATCategory.query.all()}
    buckets = {}
    for line in cdv.expense_lines:
        vat_amt = Decimal(str(line.vat_amount or 0))
        if vat_amt <= 0:
            continue
        cat = categories.get(line.vat_category)
        acct = cat.input_vat_account if cat else None
        if acct is None:
            label = cat.code if cat else (line.vat_category or 'unknown')
            raise ValueError(
                f"VAT category '{label}' has no Input Tax account configured.")
        if acct.id not in buckets:
            buckets[acct.id] = [acct, Decimal('0.00')]
        buckets[acct.id][1] += vat_amt
    ordered = [(b[0], b[1]) for b in sorted(buckets.values(), key=lambda b: b[0].code)]
    total = sum((amt for _, amt in ordered), Decimal('0.00'))
    override_diff = Decimal(str(cdv.total_vat)) - total
    if override_diff != Decimal('0.00') and ordered:
        largest_id = max(ordered, key=lambda b: b[1])[0].id
        ordered = [
            (acct, amt + override_diff if acct.id == largest_id else amt)
            for acct, amt in ordered
        ]
    ordered = [(acct, amt) for acct, amt in ordered if amt != Decimal('0.00')]
    if any(amt < Decimal('0.00') for _, amt in ordered):
        raise ValueError('VAT override is too far below computed VAT to allocate.')
    return ordered


def _post_cdv_je(cdv, user_id):
    """Create a draft or posted disbursement JE for a CDV."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine

    _accts = _get_gl_accounts()
    ap_account = _accts['ap']
    if not ap_account:
        raise ValueError("Accounts Payable - Trade (20101) not found in COA.")

    cash_account = cdv.cash_account
    if not cash_account:
        raise ValueError("Cash/Bank account not found.")

    wt_account = None
    if cdv.total_wt and Decimal(str(cdv.total_wt)) > 0:
        wt_account = _accts['wt']
        if not wt_account:
            raise ValueError("WHT Payable - Expanded (20301) not found in COA.")

    je_status = 'posted' if cdv.status == 'posted' else 'draft'
    entry_number = generate_entry_number(cdv.branch_id)
    je = JournalEntry(
        entry_number=entry_number,
        entry_date=cdv.cdv_date,
        description=f'CD {cdv.cdv_number} — {cdv.vendor_name}',
        reference=cdv.cdv_number,
        entry_type='disbursement',
        branch_id=cdv.branch_id,
        created_by_id=user_id,
        status=je_status,
        posted_by_id=user_id if je_status == 'posted' else None,
        posted_at=ph_now() if je_status == 'posted' else None,
        is_balanced=False,
        total_debit=Decimal('0.00'),
        total_credit=Decimal('0.00')
    )
    db.session.add(je)
    db.session.flush()

    line_num = 1
    first_expense_line = None
    all_lines = []

    # Debit 1: AP lines (Dr Accounts Payable per applied bill)
    for ap_line in cdv.ap_lines:
        je_line = JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=ap_account.id,
            description=f'AP Payment: {ap_line.bill_number}',
            debit_amount=Decimal(str(ap_line.amount_applied)),
            credit_amount=Decimal('0.00')
        )
        db.session.add(je_line)
        all_lines.append(je_line)
        line_num += 1

    # Debit 2: Expense net bases
    for exp_line in cdv.expense_lines:
        if not exp_line.account_id:
            continue
        net_base = Decimal(str(exp_line.line_total)) - Decimal(str(exp_line.vat_amount))
        je_line = JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=exp_line.account_id,
            description=exp_line.description or '',
            debit_amount=net_base,
            credit_amount=Decimal('0.00')
        )
        db.session.add(je_line)
        all_lines.append(je_line)
        if first_expense_line is None:
            first_expense_line = je_line
        line_num += 1

    # Debit 3: Input VAT buckets (from expense lines)
    for vat_acct, vat_amt in _cdv_input_vat_buckets(cdv):
        if vat_amt <= 0:
            continue
        vat_line = JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=vat_acct.id,
            description=f'Input VAT: {cdv.cdv_number}',
            debit_amount=vat_amt,
            credit_amount=Decimal('0.00')
        )
        db.session.add(vat_line)
        all_lines.append(vat_line)
        line_num += 1

    # Credit 1: WHT Payable (if any)
    if wt_account and Decimal(str(cdv.total_wt)) > 0:
        wt_line = JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=wt_account.id,
            description=f'WHT Payable: {cdv.cdv_number}',
            debit_amount=Decimal('0.00'),
            credit_amount=Decimal(str(cdv.total_wt))
        )
        db.session.add(wt_line)
        all_lines.append(wt_line)
        line_num += 1

    # Credit 2: Cash/Bank account
    cash_line = JournalEntryLine(
        entry_id=je.id, line_number=line_num,
        account_id=cash_account.id,
        description=f'CD {cdv.cdv_number} — {cdv.vendor_name}',
        debit_amount=Decimal('0.00'),
        credit_amount=Decimal(str(cdv.total_amount))
    )
    db.session.add(cash_line)
    all_lines.append(cash_line)

    # Absorb rounding residual into first expense debit line
    # (AP-only CDVs have no residual — exact user inputs, no VAT extraction)
    sum_debits = sum((l.debit_amount for l in all_lines), Decimal('0.00'))
    sum_credits = sum((l.credit_amount for l in all_lines), Decimal('0.00'))
    residual = sum_credits - sum_debits
    if residual != Decimal('0.00') and first_expense_line is not None:
        first_expense_line.debit_amount += residual

    db.session.flush()
    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(
            f"CDV JE is not balanced "
            f"(debit={je.total_debit}, credit={je.total_credit}). "
            "Ensure every expense line has an account assigned."
        )
    return je


def _create_cdv_reversal_je(cdv, reversal_date, user_id):
    """Swap all debits/credits from the CDV's original JE."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine

    source_je = cdv.journal_entry
    if source_je is None:
        raise ValueError(f'CDV {cdv.cdv_number} has no journal entry to reverse.')

    entry_number = generate_entry_number(cdv.branch_id)
    je = JournalEntry(
        entry_number=entry_number,
        entry_date=reversal_date,
        description=f'CDV Cancel — {cdv.cdv_number} (reversal)',
        reference=f'CANCEL-{cdv.cdv_number}',
        entry_type='reversal',
        is_reversing=True,
        reversed_entry_id=source_je.id,
        branch_id=cdv.branch_id,
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

    for i, src in enumerate(source_je.lines.all(), start=1):
        rev = JournalEntryLine(
            entry_id=je.id, line_number=i,
            account_id=src.account_id,
            description=f'Cancel: {src.description}',
            debit_amount=src.credit_amount,
            credit_amount=src.debit_amount
        )
        db.session.add(rev)

    db.session.flush()
    je.calculate_totals()
    return je


def _apply_cdv_overrides(cdv):
    """Apply VAT/WT manual overrides from request.form to cdv."""
    import decimal as _decimal
    vat_override = request.form.get('vat_override') == '1'
    wt_override = request.form.get('wt_override') == '1'
    cdv.vat_override = vat_override
    cdv.wt_override = wt_override
    if vat_override:
        try:
            vat_val = Decimal(request.form.get('vat_override_value', '0') or '0')
            if vat_val < 0:
                raise ValueError('negative')
        except (_decimal.InvalidOperation, ValueError):
            db.session.rollback()
            flash('Invalid VAT override value.', 'danger')
            return redirect(url_for('cash_disbursements.list_cdvs'))
        cdv.total_vat = vat_val
    if wt_override:
        try:
            wt_val = Decimal(request.form.get('wt_override_value', '0') or '0')
            if wt_val < 0:
                raise ValueError('negative')
        except (_decimal.InvalidOperation, ValueError):
            db.session.rollback()
            flash('Invalid WHT override value.', 'danger')
            return redirect(url_for('cash_disbursements.list_cdvs'))
        cdv.total_wt = wt_val
    cdv.total_amount = cdv.total_ap_applied + cdv.total_expense - cdv.total_wt
    return None


def _build_cdv_je_preview(cdv):
    """Return [{code, name, debit, credit}] for the JE section on the detail page."""
    if cdv.journal_entry:
        return [
            {
                'code': line.account.code if line.account else '—',
                'name': line.account.name if line.account else '—',
                'debit': line.debit_amount,
                'credit': line.credit_amount,
            }
            for line in cdv.journal_entry.lines.all()
        ]
    # Draft preview computed on-the-fly (same as APV pattern)
    accts = _get_gl_accounts()
    entries = []
    for ap_line in cdv.ap_lines:
        if accts['ap']:
            entries.append({'code': accts['ap'].code, 'name': accts['ap'].name,
                            'debit': Decimal(str(ap_line.amount_applied)), 'credit': Decimal('0.00')})
    for exp_line in cdv.expense_lines:
        if not exp_line.account_id or not exp_line.account:
            continue
        net_base = Decimal(str(exp_line.line_total)) - Decimal(str(exp_line.vat_amount))
        entries.append({'code': exp_line.account.code, 'name': exp_line.account.name,
                        'debit': net_base, 'credit': Decimal('0.00')})
    try:
        for vat_acct, vat_amt in _cdv_input_vat_buckets(cdv):
            entries.append({'code': vat_acct.code, 'name': vat_acct.name,
                            'debit': vat_amt, 'credit': Decimal('0.00')})
    except ValueError:
        pass
    if cdv.total_wt and Decimal(str(cdv.total_wt)) > 0 and accts['wt']:
        entries.append({'code': accts['wt'].code, 'name': accts['wt'].name,
                        'debit': Decimal('0.00'), 'credit': Decimal(str(cdv.total_wt))})
    if cdv.cash_account:
        entries.append({'code': cdv.cash_account.code, 'name': cdv.cash_account.name,
                        'debit': Decimal('0.00'), 'credit': Decimal(str(cdv.total_amount))})
    return entries


def _parse_line_items(cdv):
    """Parse ap_lines and expense_lines from request.form JSON. Mutates cdv in place."""
    # AP lines
    ap_lines_data = request.form.getlist('ap_lines')
    ap_lines = json.loads(ap_lines_data[0]) if ap_lines_data and ap_lines_data[0] else []
    for idx, item in enumerate(ap_lines, start=1):
        bill = PurchaseBill.query.get(int(item['bill_id']))
        if not bill:
            continue
        ap_line = CDVApLine(
            line_number=idx,
            bill_id=bill.id,
            bill_number=bill.bill_number,
            original_balance=Decimal(str(item.get('original_balance', bill.balance))),
            amount_applied=Decimal(str(item['amount_applied'])),
        )
        cdv.ap_lines.append(ap_line)

    # Expense lines
    exp_lines_data = request.form.getlist('expense_lines')
    exp_lines = json.loads(exp_lines_data[0]) if exp_lines_data and exp_lines_data[0] else []
    for idx, item in enumerate(exp_lines, start=1):
        vat_rate = Decimal('0.00')
        vat_category = item.get('vat_category')
        if vat_category:
            vat_cat = VATCategory.query.filter_by(code=vat_category, is_active=True).first()
            if vat_cat:
                vat_rate = Decimal(str(vat_cat.rate))
        wt_id = int(item['wt_id']) if item.get('wt_id') else None
        wt_rate = None
        if wt_id:
            wt_obj = WithholdingTax.query.get(wt_id)
            if wt_obj:
                wt_rate = wt_obj.rate
        exp_line = CDVExpenseLine(
            line_number=idx,
            description=item.get('description', ''),
            amount=Decimal(str(item.get('amount', 0))),
            vat_category=vat_category,
            vat_rate=vat_rate,
            account_id=int(item['account_id']) if item.get('account_id') else None,
            wt_id=wt_id,
            wt_rate=wt_rate,
        )
        exp_line.calculate_amounts()
        cdv.expense_lines.append(exp_line)
```

- [ ] **Step 2: Add create and edit routes to views.py**

Append to `app/cash_disbursements/views.py`:

```python
def _form_context():
    """Shared context for create/edit form rendering."""
    vendors = Vendor.query.filter_by(is_active=True).order_by(Vendor.name).all()
    all_accounts = _get_all_accounts_for_select()
    vat_categories = [v.to_dict() for v in VATCategory.query.filter_by(is_active=True).order_by(VATCategory.code).all()]
    wt_codes = [w.to_dict() for w in WithholdingTax.query.filter_by(is_active=True).order_by(WithholdingTax.code).all()]
    _accts = _get_gl_accounts()
    gl_accounts = {
        'ap': {'code': _accts['ap'].code, 'name': _accts['ap'].name} if _accts['ap'] else None,
        'wt': {'code': _accts['wt'].code, 'name': _accts['wt'].name} if _accts['wt'] else None,
    }
    return dict(vendors=vendors, all_accounts=all_accounts,
                vat_categories=vat_categories, wt_codes=wt_codes,
                gl_accounts=gl_accounts)


@cash_disbursements_bp.route('/cash-disbursements/create', methods=['GET', 'POST'])
@login_required
@staff_or_above_required
def create():
    form = CashDisbursementForm()
    vendors = Vendor.query.filter_by(is_active=True).order_by(Vendor.name).all()
    form.vendor_id.choices = [(0, '-- Select Vendor --')] + [(v.id, f'{v.code} - {v.name}') for v in vendors]
    all_accounts = _get_all_accounts_for_select()
    form.cash_account_id.choices = [(0, '-- Select Account --')] + [
        (a['id'], f"{a['code']} — {a['name']}") for a in all_accounts if not a['is_group']
    ]

    if form.validate_on_submit():
        if not validate_transaction_date_with_flash(form.cdv_date.data, 'Cash Disbursement Voucher'):
            ctx = _form_context()
            return render_template('cash_disbursements/form.html', form=form, cdv=None, **ctx)
        try:
            vendor = Vendor.query.get(form.vendor_id.data)
            if not vendor:
                flash('Selected vendor not found.', 'error')
                ctx = _form_context()
                return render_template('cash_disbursements/form.html', form=form, cdv=None, **ctx)

            cdv = CashDisbursementVoucher(
                branch_id=session.get('selected_branch_id'),
                cdv_number=form.cdv_number.data,
                cdv_date=form.cdv_date.data,
                vendor_id=vendor.id,
                vendor_name=vendor.name,
                vendor_tin=vendor.tin,
                payment_method=form.payment_method.data,
                check_number=form.check_number.data or None,
                check_date=form.check_date.data or None,
                check_bank=form.check_bank.data or None,
                cash_account_id=form.cash_account_id.data,
                notes=form.notes.data,
                status='draft',
                created_by_id=current_user.id
            )
            _parse_line_items(cdv)
            cdv.calculate_totals()
            err = _apply_cdv_overrides(cdv)
            if err:
                return err

            db.session.add(cdv)
            db.session.flush()

            je = _post_cdv_je(cdv, current_user.id)
            cdv.journal_entry_id = je.id
            db.session.commit()

            log_create(
                module='cash_disbursement',
                record_id=cdv.id,
                record_identifier=f'{cdv.cdv_number} - {cdv.vendor_name}',
                new_values=model_to_dict(cdv, ['cdv_number', 'cdv_date', 'vendor_name',
                                               'payment_method', 'total_amount', 'status'])
            )
            flash(f'CDV "{cdv.cdv_number}" entered successfully!', 'success')
            return redirect(url_for('cash_disbursements.view', id=cdv.id))

        except Exception as e:
            from app.errors.utils import log_exception
            db.session.rollback()
            current_app.logger.error('Error creating CDV', exc_info=True)
            log_exception(e, severity='ERROR', module='cash_disbursements.create')
            flash(f'Error entering CDV: {str(e)}', 'error')

    if request.method == 'GET':
        form.cdv_number.data = generate_cdv_number()
        form.cdv_date.data = ph_now().date()

    ctx = _form_context()
    return render_template('cash_disbursements/form.html', form=form, cdv=None, **ctx)


@cash_disbursements_bp.route('/cash-disbursements/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@staff_or_above_required
def edit(id):
    cdv = _get_cdv_or_404(id)
    if cdv.status != 'draft':
        flash('Only draft CDVs can be edited.', 'error')
        return redirect(url_for('cash_disbursements.view', id=id))

    form = CashDisbursementForm(obj=cdv)
    vendors = Vendor.query.filter_by(is_active=True).order_by(Vendor.name).all()
    form.vendor_id.choices = [(v.id, f'{v.code} - {v.name}') for v in vendors]
    all_accounts = _get_all_accounts_for_select()
    form.cash_account_id.choices = [
        (a['id'], f"{a['code']} — {a['name']}") for a in all_accounts if not a['is_group']
    ]

    if form.validate_on_submit():
        if not validate_transaction_date_with_flash(form.cdv_date.data, 'Cash Disbursement Voucher'):
            ctx = _form_context()
            return render_template('cash_disbursements/form.html', form=form, cdv=cdv, **ctx)
        try:
            old_values = model_to_dict(cdv, ['cdv_number', 'cdv_date', 'vendor_name',
                                             'payment_method', 'total_amount', 'status'])
            vendor = Vendor.query.get(form.vendor_id.data)
            if not vendor:
                flash('Selected vendor not found.', 'error')
                ctx = _form_context()
                return render_template('cash_disbursements/form.html', form=form, cdv=cdv, **ctx)

            cdv.cdv_number = form.cdv_number.data
            cdv.cdv_date = form.cdv_date.data
            cdv.vendor_id = vendor.id
            cdv.vendor_name = vendor.name
            cdv.vendor_tin = vendor.tin
            cdv.payment_method = form.payment_method.data
            cdv.check_number = form.check_number.data or None
            cdv.check_date = form.check_date.data or None
            cdv.check_bank = form.check_bank.data or None
            cdv.cash_account_id = form.cash_account_id.data
            cdv.notes = form.notes.data

            CDVApLine.query.filter_by(cdv_id=cdv.id).delete()
            CDVExpenseLine.query.filter_by(cdv_id=cdv.id).delete()
            _parse_line_items(cdv)
            cdv.calculate_totals()
            err = _apply_cdv_overrides(cdv)
            if err:
                return err

            # Delete old JE, create fresh one
            if cdv.journal_entry_id:
                from app.journal_entries.models import JournalEntry as _JE
                old_je_id = cdv.journal_entry_id
                cdv.journal_entry_id = None
                cdv.journal_entry = None
                db.session.flush()
                old_je = db.session.get(_JE, old_je_id)
                if old_je:
                    db.session.delete(old_je)

            db.session.flush()
            je = _post_cdv_je(cdv, current_user.id)
            cdv.journal_entry_id = je.id
            db.session.commit()

            new_values = model_to_dict(cdv, ['cdv_number', 'cdv_date', 'vendor_name',
                                             'payment_method', 'total_amount', 'status'])
            log_update(
                module='cash_disbursement',
                record_id=cdv.id,
                record_identifier=f'{cdv.cdv_number} - {cdv.vendor_name}',
                old_values=old_values,
                new_values=new_values
            )
            flash(f'CDV "{cdv.cdv_number}" updated.', 'success')
            return redirect(url_for('cash_disbursements.view', id=cdv.id))

        except Exception as e:
            from app.errors.utils import log_exception
            db.session.rollback()
            current_app.logger.error('Error updating CDV', exc_info=True)
            log_exception(e, severity='ERROR', module='cash_disbursements.edit')
            flash(f'Error saving CDV: {str(e)}', 'error')

    if request.method == 'GET':
        form.vendor_id.data = cdv.vendor_id
        form.cash_account_id.data = cdv.cash_account_id

    ctx = _form_context()
    ap_lines = [line.to_dict() for line in cdv.ap_lines]
    expense_lines = [line.to_dict() for line in cdv.expense_lines]
    return render_template('cash_disbursements/form.html', form=form, cdv=cdv,
                           ap_lines=ap_lines, expense_lines=expense_lines, **ctx)
```

- [ ] **Step 3: Commit**

```powershell
git add app/cash_disbursements/views.py
git commit -m "feat: CDV create/edit routes, JE builder, helper functions"
```
