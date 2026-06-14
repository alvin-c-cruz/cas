# Sales Voucher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the `app/sales_invoices/` skeleton into a fully functional Sales Voucher (SV) module — the AR-side mirror of the AP Voucher.

**Architecture:** Upgrade-in-place. Patch `SalesInvoice`/`SalesInvoiceItem` models via a single Alembic migration, rewrite `views.py` and all templates to match APV patterns. VAT-inclusive line items (VAT extracted from amount). WHT on invoice booked as Creditable WHT Receivable (Dr). JE created on save (draft), promoted on post.

**Tech Stack:** Flask, SQLAlchemy, SQLite, Flask-WTF, Flask-Migrate (Alembic), Choices.js (bundled at `app/static/`), openpyxl

**Spec:** `docs/superpowers/specs/2026-06-14-sales-voucher-design.md`
**Blueprint:** `app/purchase_bills/` — read it when in doubt about patterns.

---

## File Map

**Create:**
- `app/sales_invoices/utils.py`
- `app/sales_invoices/templates/sales_invoices/list.html`
- `app/sales_invoices/templates/sales_invoices/form.html`
- `app/sales_invoices/templates/sales_invoices/detail.html`
- `app/sales_invoices/templates/sales_invoices/print.html`
- `tests/integration/test_sales_invoices.py`

**Modify:**
- `app/sales_invoices/models.py`
- `app/sales_invoices/views.py`
- `app/sales_invoices/forms.py`
- `app/vat_categories/models.py`
- `app/vat_categories/forms.py`
- `app/vat_categories/views.py`
- `app/__init__.py`

---

## Task 1: Add Creditable WHT Receivable account to COA (prerequisite)

The JE for a sales invoice debits a "Creditable Withholding Tax" asset account. The seeded COA has no such account — add it before touching any JE code.

**Files:** none (UI action)

- [ ] **Step 1: Log in as accountant, go to Chart of Accounts → Create**

  Fill in:
  - Code: `10212`
  - Name: `Creditable Withholding Tax`
  - Parent: `10210` (Other Receivables — this makes it a child leaf)
  - Normal Balance: Debit
  - Account Type: Asset

- [ ] **Step 2: If approval workflow applies, approve the request**

  Log in as a second accountant/admin and approve via Action Items.

- [ ] **Step 3: Verify the account exists**

  ```bash
  flask shell
  ```
  ```python
  from app.accounts.models import Account
  a = Account.query.filter_by(code='10212').first()
  print(a.id, a.name)   # Should print: <id> Creditable Withholding Tax
  exit()
  ```

- [ ] **Step 4: Commit note**

  No code change — document the account code `10212` in a comment when it appears in `_get_gl_accounts()` (Task 8).

---

## Task 2: VATCategory model — add `output_vat_account_id`

**Files:**
- Modify: `app/vat_categories/models.py`
- Modify: `app/vat_categories/forms.py`
- Modify: `app/vat_categories/views.py`

- [ ] **Step 1: Write the failing test**

  ```python
  # tests/unit/test_vat_category_model.py  (add to existing file or create)
  def test_vat_category_has_output_vat_account_id(db_session):
      from app.vat_categories.models import VATCategory
      cat = VATCategory(code='TEST', name='Test', rate=12.0)
      db_session.add(cat)
      db_session.commit()
      assert hasattr(cat, 'output_vat_account_id')
      assert cat.output_vat_account_id is None
      d = cat.to_dict()
      assert 'output_vat_account_id' in d
      assert 'output_vat_account_code' in d
  ```

- [ ] **Step 2: Run test — expect FAIL**

  ```
  pytest tests/unit/test_vat_category_model.py -v -k output_vat
  ```

- [ ] **Step 3: Add field to `app/vat_categories/models.py`**

  After the `input_vat_account_id` block (around line 22), add:

  ```python
  # Output VAT account used for sales journal entries.
  # NULL is correct for zero-rate categories; required when rate > 0.
  output_vat_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'),
                                    nullable=True)
  output_vat_account = db.relationship('Account', foreign_keys=[output_vat_account_id])
  ```

  Update `to_dict()` — add after the `input_vat_account_name` line:

  ```python
  'output_vat_account_id': self.output_vat_account_id,
  'output_vat_account_code': self.output_vat_account.code if self.output_vat_account else None,
  'output_vat_account_name': self.output_vat_account.name if self.output_vat_account else None,
  ```

- [ ] **Step 4: Add field to `app/vat_categories/forms.py`**

  After the `input_vat_account_id` field and its validator, add:

  ```python
  output_vat_account_id = SelectField('Output Tax Account', coerce=int,
                                      validators=[], default=0)

  def validate_output_vat_account_id(self, field):
      """Required when rate > 0; cleared when rate is zero."""
      rate = self.rate.data
      if rate is not None and rate > 0:
          if not field.data or field.data == 0:
              raise ValidationError(
                  'Output Tax account is required for VAT-bearing categories.')
      else:
          field.data = 0
  ```

- [ ] **Step 5: Update `app/vat_categories/views.py`**

  **Add helper** (after `_input_vat_account_choices()`):

  ```python
  def _output_vat_account_choices():
      """Active leaf accounts for the Output Tax picker."""
      accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
      parent_ids = {a.parent_id for a in accounts if a.parent_id is not None}
      choices = [(0, '-- None (zero-rate) --')]
      choices += [(a.id, f'{a.code} : {a.name}') for a in accounts
                  if a.id not in parent_ids]
      return choices
  ```

  **Populate in `create()` and `edit()`** — add after the `input_vat_account_id.choices` line:
  ```python
  form.output_vat_account_id.choices = _output_vat_account_choices()
  ```

  **Include in `change_data` dict** — in both `create()` and `edit()`, add to `change_data`:
  ```python
  'output_vat_account_id': form.output_vat_account_id.data or None
  ```

  **Apply on approval** — in `review_change_request()`, for both `create` and `update` actions, add:
  ```python
  vat_category.output_vat_account_id = proposed_data.get('output_vat_account_id')
  ```

  **Pre-fill on GET in `edit()`** — add after `form.input_vat_account_id.data` line:
  ```python
  form.output_vat_account_id.data = vat_category.output_vat_account_id or 0
  ```

  **Update `model_to_dict` calls** — add `'output_vat_account_id'` to the fields list wherever `'input_vat_account_id'` appears in `model_to_dict(...)` calls.

- [ ] **Step 6: Run test — expect PASS**

  ```
  pytest tests/unit/test_vat_category_model.py -v -k output_vat
  ```

- [ ] **Step 7: Commit**

  ```bash
  git add app/vat_categories/models.py app/vat_categories/forms.py app/vat_categories/views.py tests/unit/test_vat_category_model.py
  git commit -m "feat: add output_vat_account_id to VATCategory"
  ```

---

## Task 3: SalesInvoice model — upgrade fields

**Files:**
- Modify: `app/sales_invoices/models.py`

- [ ] **Step 1: Write the failing test**

  Create `tests/integration/test_sales_invoices.py`:

  ```python
  import pytest
  from decimal import Decimal
  from datetime import date


  @pytest.fixture
  def customer(db_session):
      from app.customers.models import Customer
      c = Customer(code='C001', name='Test Customer')
      db_session.add(c)
      db_session.commit()
      return c


  @pytest.fixture
  def revenue_account(db_session):
      from app.accounts.models import Account
      a = Account(code='40001', name='Service Revenue', account_type='Revenue',
                  normal_balance='credit', is_active=True)
      db_session.add(a)
      db_session.commit()
      return a


  @pytest.fixture
  def wht_code(db_session):
      from app.withholding_tax.models import WithholdingTax
      w = WithholdingTax(code='WC010', name='EWT 10%', rate=Decimal('10.00'),
                         is_active=True)
      db_session.add(w)
      db_session.commit()
      return w


  @pytest.fixture
  def branch(db_session):
      from app.branches.models import Branch
      b = Branch.query.first()
      if not b:
          b = Branch(name='Main Branch', code='MB', is_active=True)
          db_session.add(b)
          db_session.commit()
      return b


  def test_sales_invoice_calculate_totals_vat_inclusive(db_session, customer, revenue_account, branch):
      from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
      inv = SalesInvoice(
          branch_id=branch.id,
          invoice_number='SI-2026-0001',
          invoice_date=date(2026, 6, 14),
          due_date=date(2026, 7, 14),
          customer_id=customer.id,
          customer_name=customer.name,
          notes='',
          status='draft',
          amount_paid=Decimal('0.00'),
      )
      db_session.add(inv)
      db_session.flush()

      # Amount is VAT-inclusive at 12%
      item = SalesInvoiceItem(
          invoice_id=inv.id,
          line_number=1,
          description='Service',
          amount=Decimal('11200.00'),
          vat_rate=Decimal('12.00'),
          account_id=revenue_account.id,
      )
      item.calculate_amounts()
      db_session.add(item)
      db_session.flush()

      inv.calculate_totals()

      net_base = Decimal('11200.00') / Decimal('1.12')
      expected_vat = Decimal('11200.00') - net_base
      assert inv.subtotal == Decimal('11200.00')
      assert abs(inv.vat_amount - expected_vat.quantize(Decimal('0.01'))) < Decimal('0.02')
      assert inv.total_before_wt == Decimal('11200.00')
      assert inv.total_amount == Decimal('11200.00')   # no WHT
      assert inv.balance == Decimal('11200.00')


  def test_sales_invoice_has_required_fields(db_session, customer, branch):
      from app.sales_invoices.models import SalesInvoice
      inv = SalesInvoice(
          branch_id=branch.id,
          invoice_number='SI-2026-0002',
          invoice_date=date(2026, 6, 14),
          due_date=date(2026, 7, 14),
          customer_id=customer.id,
          customer_name='Test Customer',
          notes='',
          status='draft',
          amount_paid=Decimal('0.00'),
      )
      db_session.add(inv)
      db_session.commit()
      assert inv.journal_entry_id is None
      assert inv.withholding_tax_amount == Decimal('0.00')
      assert inv.vat_override is False
      assert inv.wt_override is False
      assert inv.total_before_wt == Decimal('0.00')
      assert inv.customer_po_number is None
  ```

- [ ] **Step 2: Run — expect FAIL** (`AttributeError` on `journal_entry_id` etc.)

  ```
  pytest tests/integration/test_sales_invoices.py -v
  ```

- [ ] **Step 3: Replace `app/sales_invoices/models.py` with the upgraded version**

  ```python
  from app import db
  from app.utils import ph_now
  from decimal import Decimal


  class SalesInvoice(db.Model):
      __tablename__ = 'sales_invoices'

      id = db.Column(db.Integer, primary_key=True)

      branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)
      branch = db.relationship('Branch', foreign_keys=[branch_id])

      invoice_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
      invoice_date = db.Column(db.Date, nullable=False, index=True)
      due_date = db.Column(db.Date, nullable=False)

      customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)
      customer = db.relationship('Customer', backref='sales_invoices')

      customer_name = db.Column(db.String(200), nullable=False)
      customer_tin = db.Column(db.String(20))
      customer_address = db.Column(db.Text)

      customer_po_number = db.Column(db.String(100))
      customer_po_date = db.Column(db.Date)

      payment_terms = db.Column(db.String(50), default='Net 30')
      reference = db.Column(db.String(100))
      notes = db.Column(db.Text, nullable=False, default='')

      # Financial totals (computed from line items)
      subtotal = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
      vat_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
      total_before_wt = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
      withholding_tax_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
      vat_override = db.Column(db.Boolean, default=False, nullable=False)
      wt_override = db.Column(db.Boolean, default=False, nullable=False)
      total_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)

      journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'), nullable=True)
      journal_entry = db.relationship('JournalEntry', foreign_keys=[journal_entry_id])

      status = db.Column(db.String(20), default='draft', nullable=False, index=True)
      # Statuses: draft, posted, partially_paid, paid, cancelled, voided

      amount_paid = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
      balance = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)

      created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
      created_by = db.relationship('User', foreign_keys=[created_by_id], backref='created_sales_invoices')
      posted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
      posted_by = db.relationship('User', foreign_keys=[posted_by_id], backref='posted_sales_invoices')

      created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
      updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)
      posted_at = db.Column(db.DateTime)
      cancelled_at = db.Column(db.DateTime)
      voided_at = db.Column(db.DateTime)
      voided_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
      voided_by = db.relationship('User', foreign_keys=[voided_by_id], backref='voided_sales_invoices')
      void_reason = db.Column(db.String(255))
      cancel_reason = db.Column(db.String(500), nullable=True)

      line_items = db.relationship('SalesInvoiceItem', backref='invoice', lazy='select',
                                   cascade='all, delete-orphan', order_by='SalesInvoiceItem.line_number')
      attachments = db.relationship('SalesInvoiceAttachment', backref='invoice', lazy='select',
                                    cascade='all, delete-orphan', order_by='SalesInvoiceAttachment.uploaded_at')

      def __repr__(self):
          return f'<SalesInvoice {self.invoice_number}>'

      def calculate_totals(self):
          self.subtotal = Decimal('0.00')
          auto_vat = Decimal('0.00')
          auto_wt = Decimal('0.00')
          for item in self.line_items:
              self.subtotal += item.line_total
              auto_vat += item.vat_amount
              auto_wt += (item.wt_amount or Decimal('0.00'))
          self.vat_amount = auto_vat
          self.withholding_tax_amount = auto_wt
          self.total_before_wt = self.subtotal
          self.total_amount = self.subtotal - self.withholding_tax_amount
          self.balance = self.total_amount - self.amount_paid

      def to_dict(self):
          return {
              'id': self.id,
              'invoice_number': self.invoice_number,
              'invoice_date': self.invoice_date.isoformat() if self.invoice_date else None,
              'due_date': self.due_date.isoformat() if self.due_date else None,
              'customer_id': self.customer_id,
              'customer_name': self.customer_name,
              'customer_tin': self.customer_tin,
              'customer_po_number': self.customer_po_number,
              'payment_terms': self.payment_terms,
              'reference': self.reference,
              'subtotal': float(self.subtotal),
              'vat_amount': float(self.vat_amount),
              'total_before_wt': float(self.total_before_wt),
              'withholding_tax_amount': float(self.withholding_tax_amount),
              'total_amount': float(self.total_amount),
              'amount_paid': float(self.amount_paid),
              'balance': float(self.balance),
              'status': self.status,
              'created_at': self.created_at.isoformat() if self.created_at else None,
              'posted_at': self.posted_at.isoformat() if self.posted_at else None,
          }
  ```

  Continue with `SalesInvoiceItem` and `SalesInvoiceAttachment` in the **same file** (see Task 4).

---

## Task 4: SalesInvoiceItem + SalesInvoiceAttachment models

**Files:**
- Modify: `app/sales_invoices/models.py` (append to the file from Task 3)

- [ ] **Step 1: Write failing test** (add to `tests/integration/test_sales_invoices.py`)

  ```python
  def test_invoice_item_calculate_amounts_vat_inclusive(db_session, revenue_account, wht_code):
      from app.sales_invoices.models import SalesInvoiceItem
      item = SalesInvoiceItem(
          line_number=1,
          description='Service',
          amount=Decimal('11200.00'),
          vat_rate=Decimal('12.00'),
          wt_rate=Decimal('10.00'),
      )
      item.calculate_amounts()
      net_base = Decimal('11200.00') / Decimal('1.12')
      expected_vat = (Decimal('11200.00') - net_base).quantize(Decimal('0.01'))
      expected_wt = (net_base * Decimal('0.10')).quantize(Decimal('0.01'))
      assert item.line_total == Decimal('11200.00')
      assert abs(item.vat_amount - expected_vat) < Decimal('0.02')
      assert abs(item.wt_amount - expected_wt) < Decimal('0.02')
      assert not hasattr(item, 'quantity')


  def test_invoice_attachment_model(db_session, customer, branch):
      from app.sales_invoices.models import SalesInvoiceAttachment
      att = SalesInvoiceAttachment.__table__
      col_names = [c.name for c in att.columns]
      assert 'invoice_id' in col_names
      assert 'stored_filename' in col_names
      assert 'mime_type' in col_names
  ```

- [ ] **Step 2: Run — expect FAIL**

  ```
  pytest tests/integration/test_sales_invoices.py -v -k "item or attachment"
  ```

- [ ] **Step 3: Append `SalesInvoiceItem` and `SalesInvoiceAttachment` to `app/sales_invoices/models.py`**

  ```python
  class SalesInvoiceItem(db.Model):
      __tablename__ = 'sales_invoice_items'

      id = db.Column(db.Integer, primary_key=True)
      invoice_id = db.Column(db.Integer, db.ForeignKey('sales_invoices.id'), nullable=False, index=True)
      line_number = db.Column(db.Integer, nullable=False)
      description = db.Column(db.String(500), nullable=False)
      amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)

      vat_category = db.Column(db.String(100))
      vat_rate = db.Column(db.Numeric(5, 2), default=0.00, nullable=False)

      line_total = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
      vat_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)

      account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'))
      account = db.relationship('Account')

      wt_id = db.Column(db.Integer, db.ForeignKey('withholding_tax.id'), nullable=True)
      withholding_tax = db.relationship('WithholdingTax', foreign_keys=[wt_id])
      wt_rate = db.Column(db.Numeric(5, 2), nullable=True)
      wt_amount = db.Column(db.Numeric(15, 2), default=Decimal('0.00'), server_default='0.00', nullable=False)

      def __repr__(self):
          return f'<SalesInvoiceItem {self.invoice_id}-{self.line_number}>'

      def calculate_amounts(self):
          """Extract VAT from VAT-inclusive amount; compute WHT on net base."""
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


  class SalesInvoiceAttachment(db.Model):
      __tablename__ = 'sales_invoice_attachments'

      id = db.Column(db.Integer, primary_key=True)
      invoice_id = db.Column(db.Integer, db.ForeignKey('sales_invoices.id'),
                             nullable=False, index=True)
      original_filename = db.Column(db.String(255), nullable=False)
      stored_filename = db.Column(db.String(255), nullable=False, unique=True)
      mime_type = db.Column(db.String(100), nullable=False)
      file_size = db.Column(db.Integer, nullable=False)
      uploaded_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
      uploaded_by = db.relationship('User', foreign_keys=[uploaded_by_id],
                                    backref='uploaded_invoice_attachments')
      uploaded_at = db.Column(db.DateTime, default=ph_now, nullable=False)

      def __repr__(self):
          return f'<SalesInvoiceAttachment {self.original_filename} invoice={self.invoice_id}>'

      @property
      def is_image(self):
          return self.mime_type.startswith('image/')

      @property
      def file_size_human(self):
          if self.file_size < 1024:
              return f'{self.file_size} B'
          if self.file_size < 1024 * 1024:
              return f'{self.file_size / 1024:.1f} KB'
          return f'{self.file_size / (1024 * 1024):.1f} MB'
  ```

- [ ] **Step 4: Run tests — expect PASS**

  ```
  pytest tests/integration/test_sales_invoices.py -v
  ```

- [ ] **Step 5: Commit**

  ```bash
  git add app/sales_invoices/models.py tests/integration/test_sales_invoices.py
  git commit -m "feat: upgrade SalesInvoice, SalesInvoiceItem, add SalesInvoiceAttachment models"
  ```

---

## Task 5: Migration + `__init__.py` wiring

**Files:**
- Modify: `app/__init__.py` (line 166 — add `SalesInvoiceAttachment` to import)
- Auto-generate: migration file

- [ ] **Step 1: Add `SalesInvoiceAttachment` to model import in `app/__init__.py`**

  Find line 166:
  ```python
  from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
  ```
  Replace with:
  ```python
  from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem, SalesInvoiceAttachment
  ```

- [ ] **Step 2: Generate the migration**

  ```bash
  flask db migrate -m "sales voucher upgrade: wht fields, journal_entry_id, attachments, output vat account"
  ```

- [ ] **Step 3: Verify the generated migration**

  Open the new file in `migrations/versions/`. It must contain:
  - `ADD COLUMN journal_entry_id` on `sales_invoices`
  - `ADD COLUMN total_before_wt` on `sales_invoices`
  - `ADD COLUMN withholding_tax_amount` on `sales_invoices`
  - `ADD COLUMN vat_override` on `sales_invoices`
  - `ADD COLUMN wt_override` on `sales_invoices`
  - `ADD COLUMN cancel_reason` on `sales_invoices`
  - `ADD COLUMN customer_po_number` on `sales_invoices`
  - `ADD COLUMN customer_po_date` on `sales_invoices`
  - `DROP COLUMN quantity` on `sales_invoice_items`
  - `DROP COLUMN unit_price` on `sales_invoice_items`
  - `ADD COLUMN wt_id` on `sales_invoice_items`
  - `ADD COLUMN wt_rate` on `sales_invoice_items`
  - `ADD COLUMN wt_amount` on `sales_invoice_items`
  - `CREATE TABLE sales_invoice_attachments`
  - `ADD COLUMN output_vat_account_id` on `vat_categories`

  If anything is missing, add it manually to the migration's `upgrade()` function.

- [ ] **Step 4: Run migration**

  ```bash
  flask db upgrade
  ```

  Expected: no errors.

- [ ] **Step 5: Commit**

  ```bash
  git add app/__init__.py migrations/
  git commit -m "feat: sales voucher migration — model upgrades and SalesInvoiceAttachment"
  ```

---

## Task 6: Update `SalesInvoiceForm`

**Files:**
- Modify: `app/sales_invoices/forms.py`

- [ ] **Step 1: Replace `app/sales_invoices/forms.py` entirely**

  ```python
  from flask_wtf import FlaskForm
  from wtforms import StringField, DateField, TextAreaField, SelectField
  from wtforms.validators import DataRequired, Length, Optional


  class SalesInvoiceForm(FlaskForm):
      invoice_number = StringField('Invoice #', validators=[
          DataRequired(message='Invoice number is required.'),
          Length(max=50)
      ])
      invoice_date = DateField('Invoice Date', validators=[
          DataRequired(message='Invoice date is required.')
      ], format='%Y-%m-%d')
      due_date = DateField('Due Date', validators=[
          DataRequired(message='Due date is required.')
      ], format='%Y-%m-%d')
      customer_id = SelectField('Customer', validators=[
          DataRequired(message='Customer is required.')
      ], coerce=int)
      customer_po_number = StringField('Customer PO #', validators=[
          Optional(), Length(max=100)
      ])
      customer_po_date = DateField('Customer PO Date', validators=[Optional()],
                                   format='%Y-%m-%d')
      payment_terms = SelectField('Payment Terms', choices=[
          ('Net 15', 'Net 15'), ('Net 30', 'Net 30'), ('Net 45', 'Net 45'),
          ('Net 60', 'Net 60'), ('Cash on Delivery', 'Cash on Delivery'),
          ('Advance Payment', 'Advance Payment'),
      ], default='Net 30')
      reference = StringField('Reference', validators=[Optional(), Length(max=100)])
      notes = TextAreaField('Notes', validators=[Optional()])
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add app/sales_invoices/forms.py
  git commit -m "feat: simplify SalesInvoiceForm — remove qty/unit_price, add customer_po fields"
  ```

---

## Task 7: `views.py` — blueprint skeleton + shared helpers

Set up the new `views.py` with decorators, branch guard, and non-JE helpers.

**Files:**
- Modify: `app/sales_invoices/views.py`

- [ ] **Step 1: Replace the top of `views.py`** (imports, blueprint, decorators, branch guard, `_get_invoice_or_404`, `generate_invoice_number`, `_get_all_accounts_for_select`, `_apply_overrides`, `_invoice_upload_dir`, `_ATTACHMENT_ALLOWED`, `_EXPORT_COLUMNS`, `_EXPORT_HEADERS`)

  ```python
  from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, session, abort, current_app, send_file
  from flask_login import login_required, current_user
  from functools import wraps
  from sqlalchemy.orm import selectinload
  from app import db
  from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem, SalesInvoiceAttachment
  from app.sales_invoices.forms import SalesInvoiceForm
  from app.customers.models import Customer
  from app.vat_categories.models import VATCategory
  from app.accounts.models import Account
  from app.withholding_tax.models import WithholdingTax
  from app.audit.utils import log_create, log_update, log_delete, model_to_dict, log_audit
  from app.utils import ph_now
  from app.utils.export import export_to_excel, export_to_csv
  from app.settings import AppSettings
  from app.periods.utils import validate_transaction_date_with_flash
  from app.journal_entries.utils import generate_entry_number
  from datetime import date, timedelta
  from decimal import Decimal
  import json, os, uuid
  from werkzeug.utils import secure_filename

  sales_invoices_bp = Blueprint('sales_invoices', __name__, template_folder='templates')


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


  VALID_INVOICE_STATUSES = {'draft', 'posted', 'partially_paid', 'paid', 'voided', 'cancelled'}


  @sales_invoices_bp.before_request
  def require_branch_selection():
      if current_user.is_authenticated and not session.get('selected_branch_id'):
          flash('Please select a branch to continue.', 'warning')
          return redirect(url_for('users.select_branch'))


  def generate_invoice_number():
      """SI-YYYY-NNNN, annual reset."""
      now = ph_now()
      prefix = f'SI-{now.year}-'
      latest = SalesInvoice.query.filter(
          SalesInvoice.invoice_number.like(f'{prefix}%')
      ).order_by(SalesInvoice.invoice_number.desc()).first()
      if latest:
          try:
              last_num = int(latest.invoice_number.split('-')[-1])
              next_num = last_num + 1
          except (ValueError, IndexError):
              next_num = 1
      else:
          next_num = 1
      return f'{prefix}{next_num:04d}'


  def _get_invoice_or_404(id):
      invoice = SalesInvoice.query.get_or_404(id)
      if invoice.branch_id != session.get('selected_branch_id'):
          abort(404)
      return invoice


  def _get_all_accounts_for_select():
      """Full COA for account picker — groups shown but non-selectable."""
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


  def _apply_overrides(invoice):
      """Apply VAT/WHT manual overrides from request.form. Returns redirect on error, None on success."""
      import decimal as _decimal
      vat_override = request.form.get('vat_override') == '1'
      wt_override = request.form.get('wt_override') == '1'
      invoice.vat_override = vat_override
      invoice.wt_override = wt_override
      if vat_override:
          try:
              vat_val = Decimal(request.form.get('vat_override_value', '0') or '0')
              if vat_val < 0 or vat_val > invoice.subtotal:
                  raise ValueError('out of range')
          except (_decimal.InvalidOperation, ValueError):
              db.session.rollback()
              flash('Invalid VAT override value.', 'danger')
              return redirect(url_for('sales_invoices.list_invoices'))
          invoice.vat_amount = vat_val
      if wt_override:
          try:
              wt_val = Decimal(request.form.get('wt_override_value', '0') or '0')
              if wt_val < 0 or wt_val > invoice.subtotal:
                  raise ValueError('out of range')
          except (_decimal.InvalidOperation, ValueError):
              db.session.rollback()
              flash('Invalid withholding tax override value.', 'danger')
              return redirect(url_for('sales_invoices.list_invoices'))
          invoice.withholding_tax_amount = wt_val
      invoice.total_amount = invoice.subtotal - invoice.withholding_tax_amount
      invoice.balance = invoice.total_amount - invoice.amount_paid
      return None


  def _invoice_upload_dir(invoice_id):
      path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'sales_invoices', str(invoice_id))
      os.makedirs(path, exist_ok=True)
      return path


  _ATTACHMENT_ALLOWED = {
      '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
      '.gif': 'image/gif', '.webp': 'image/webp', '.pdf': 'application/pdf',
      '.doc': 'application/msword',
      '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      '.xls': 'application/vnd.ms-excel',
      '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      '.csv': 'text/csv', '.txt': 'text/plain',
  }

  _EXPORT_COLUMNS = [
      'invoice_number', 'invoice_date', 'due_date', 'customer_name', 'customer_tin',
      'customer_po_number', 'subtotal', 'vat_amount', 'withholding_tax_amount',
      'total_amount', 'amount_paid', 'balance', 'status',
  ]

  _EXPORT_HEADERS = [
      'Invoice #', 'Invoice Date', 'Due Date', 'Customer', 'TIN', 'Customer PO #',
      'Subtotal', 'VAT', 'Withholding Tax', 'Total', 'Paid', 'Balance', 'Status',
  ]
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add app/sales_invoices/views.py
  git commit -m "feat: sales invoices views — skeleton + shared helpers"
  ```

---

## Task 8: `views.py` — JE helpers

**Files:**
- Modify: `app/sales_invoices/views.py` (append)

- [ ] **Step 1: Append GL account lookup and VAT bucket helpers**

  ```python
  def _get_gl_accounts():
      """AR control and Creditable WHT Receivable GL accounts."""
      ar_acct = Account.query.filter_by(code='10201').first()   # AR - Trade
      wt_acct = Account.query.filter_by(code='10212').first()   # Creditable Withholding Tax
      return {'ar': ar_acct, 'wt': wt_acct}


  def _output_vat_buckets(invoice):
      """Group output VAT by VAT category's output_vat_account (mirrors APV _input_vat_buckets).

      Returns list of (Account, Decimal) ordered by account code.
      Applies VAT override difference to the largest bucket.
      Raises ValueError if a VAT-bearing line's category has no output_vat_account.
      """
      if Decimal(str(invoice.vat_amount)) <= 0:
          return []

      categories = {c.code: c for c in VATCategory.query.all()}
      buckets = {}
      for item in invoice.line_items:
          vat_amt = Decimal(str(item.vat_amount or 0))
          if vat_amt <= 0:
              continue
          cat = categories.get(item.vat_category)
          acct = cat.output_vat_account if cat else None
          if acct is None:
              label = cat.code if cat else (item.vat_category or 'unknown')
              raise ValueError(
                  f"VAT category '{label}' has no Output Tax account configured. "
                  "Set it in VAT Categories.")
          if acct.id not in buckets:
              buckets[acct.id] = [acct, Decimal('0.00')]
          buckets[acct.id][1] += vat_amt

      ordered = [(b[0], b[1]) for b in sorted(buckets.values(), key=lambda b: b[0].code)]
      total = sum((amt for _, amt in ordered), Decimal('0.00'))
      override_diff = Decimal(str(invoice.vat_amount)) - total
      if override_diff != Decimal('0.00') and ordered:
          largest_acct_id = max(ordered, key=lambda b: b[1])[0].id
          ordered = [
              (acct, amt + override_diff if acct.id == largest_acct_id else amt)
              for acct, amt in ordered
          ]
      ordered = [(acct, amt) for acct, amt in ordered if amt != Decimal('0.00')]
      if any(amt < Decimal('0.00') for _, amt in ordered):
          raise ValueError(
              'VAT override is too far below the computed VAT to allocate '
              'across output tax accounts.')
      return ordered


  def _build_je_preview(invoice):
      """Return list of {code, name, debit, credit} for the JE preview section."""
      if invoice.journal_entry:
          return [
              {
                  'code': line.account.code if line.account else '—',
                  'name': line.account.name if line.account else '—',
                  'debit': line.debit_amount,
                  'credit': line.credit_amount,
              }
              for line in invoice.journal_entry.lines.all()
          ]

      accts = _get_gl_accounts()
      entries = []

      for item in invoice.line_items:
          if not item.account_id or not item.account:
              continue
          net_base = Decimal(str(item.line_total)) - Decimal(str(item.vat_amount))
          entries.append({
              'code': item.account.code,
              'name': item.account.name,
              'debit': Decimal('0.00'),
              'credit': net_base,
          })

      try:
          vat_buckets = _output_vat_buckets(invoice)
      except ValueError as e:
          vat_buckets = []
          vat_amount = Decimal(str(invoice.vat_amount))
          if vat_amount > 0:
              entries.append({'code': '—', 'name': str(e),
                              'debit': Decimal('0.00'), 'credit': vat_amount})

      for vat_acct, vat_amt in vat_buckets:
          if vat_amt <= 0:
              continue
          entries.append({'code': vat_acct.code, 'name': vat_acct.name,
                          'debit': Decimal('0.00'), 'credit': vat_amt})

      wt_amount = Decimal(str(invoice.withholding_tax_amount))
      if wt_amount > 0 and accts['wt']:
          entries.append({'code': accts['wt'].code, 'name': accts['wt'].name,
                          'debit': wt_amount, 'credit': Decimal('0.00')})

      if accts['ar']:
          entries.append({'code': accts['ar'].code, 'name': accts['ar'].name,
                          'debit': Decimal(str(invoice.total_amount)),
                          'credit': Decimal('0.00')})

      return entries
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add app/sales_invoices/views.py
  git commit -m "feat: sales invoices — JE helper functions"
  ```

---

## Task 9: `views.py` — `_post_invoice_je` + `_create_reversal_je`

**Files:**
- Modify: `app/sales_invoices/views.py` (append)

- [ ] **Step 1: Write a focused integration test** (add to `tests/integration/test_sales_invoices.py`)

  ```python
  def test_post_invoice_je_creates_balanced_entry(db_session, customer, revenue_account, branch, accountant_user):
      """Posting a Sales Invoice creates a balanced journal entry."""
      from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
      from app.accounts.models import Account

      # Ensure required GL accounts exist
      ar = Account.query.filter_by(code='10201').first()
      if not ar:
          ar = Account(code='10201', name='AR - Trade', account_type='Asset',
                       normal_balance='debit', is_active=True)
          db_session.add(ar)

      wt_recv = Account.query.filter_by(code='10212').first()
      if not wt_recv:
          wt_recv = Account(code='10212', name='Creditable WHT', account_type='Asset',
                            normal_balance='debit', is_active=True)
          db_session.add(wt_recv)

      output_vat = Account.query.filter_by(code='20201').first()
      if not output_vat:
          output_vat = Account(code='20201', name='Output VAT - Sales', account_type='Liability',
                               normal_balance='credit', is_active=True)
          db_session.add(output_vat)

      vat_cat = VATCategory.query.filter_by(code='V12SV').first()
      if not vat_cat:
          from app.vat_categories.models import VATCategory as VATCat
          vat_cat = VATCat(code='V12SV', name='VAT Services', rate=Decimal('12.00'),
                           output_vat_account_id=output_vat.id if output_vat else None)
          db_session.add(vat_cat)
      db_session.flush()

      from app.branches.models import Branch
      inv = SalesInvoice(
          branch_id=branch.id,
          invoice_number='SI-2026-0099',
          invoice_date=date(2026, 6, 14),
          due_date=date(2026, 7, 14),
          customer_id=customer.id,
          customer_name=customer.name,
          notes='Test',
          status='draft',
          amount_paid=Decimal('0.00'),
      )
      db_session.add(inv)
      db_session.flush()

      item = SalesInvoiceItem(
          invoice_id=inv.id,
          line_number=1,
          description='Service',
          amount=Decimal('11200.00'),
          vat_category='V12SV',
          vat_rate=Decimal('12.00'),
          account_id=revenue_account.id,
      )
      item.calculate_amounts()
      db_session.add(item)
      db_session.flush()
      inv.calculate_totals()

      from app.sales_invoices import views as sv_views
      # Temporarily monkeypatch the module's session context
      je = sv_views._post_invoice_je(inv, accountant_user.id)
      db_session.flush()

      assert je.is_balanced
      assert je.total_debit == je.total_credit
  ```

- [ ] **Step 2: Append `_post_invoice_je` and `_create_reversal_je` to `views.py`**

  ```python
  def _post_invoice_je(invoice, user_id):
      """Create a sales JE (reverse of APV): Dr AR + Dr Creditable WHT; Cr Revenue + Cr Output VAT."""
      from app.journal_entries.models import JournalEntry, JournalEntryLine

      accts = _get_gl_accounts()
      ar_account = accts['ar']
      if not ar_account:
          raise ValueError("Accounts Receivable - Trade (10201) not found in COA.")

      wt_account = None
      if invoice.withholding_tax_amount and invoice.withholding_tax_amount > 0:
          wt_account = accts['wt']
          if not wt_account:
              raise ValueError("Creditable Withholding Tax (10212) not found in COA.")

      je_status = 'posted' if invoice.status == 'posted' else 'draft'
      entry_number = generate_entry_number(invoice.branch_id)
      je = JournalEntry(
          entry_number=entry_number,
          entry_date=invoice.invoice_date,
          description=f'Sales Invoice {invoice.invoice_number} — {invoice.customer_name}',
          reference=invoice.invoice_number,
          entry_type='sale',
          branch_id=invoice.branch_id,
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

      # Credit revenue accounts (net base per line)
      for item in invoice.line_items:
          if not item.account_id:
              continue
          net_base = Decimal(str(item.line_total)) - Decimal(str(item.vat_amount))
          entry_line = JournalEntryLine(
              entry_id=je.id, line_number=line_num,
              account_id=item.account_id,
              description=item.description or '',
              debit_amount=Decimal('0.00'),
              credit_amount=net_base,
          )
          db.session.add(entry_line)
          all_lines.append(entry_line)
          if first_revenue_line is None:
              first_revenue_line = entry_line
          line_num += 1

      # Credit output VAT buckets
      for vat_acct, vat_amt in _output_vat_buckets(invoice):
          if vat_amt <= 0:
              continue
          vat_line = JournalEntryLine(
              entry_id=je.id, line_number=line_num,
              account_id=vat_acct.id,
              description=f'Output VAT: {invoice.invoice_number}',
              debit_amount=Decimal('0.00'),
              credit_amount=vat_amt,
          )
          db.session.add(vat_line)
          all_lines.append(vat_line)
          line_num += 1

      # Debit Creditable WHT Receivable
      if wt_account:
          wt_line = JournalEntryLine(
              entry_id=je.id, line_number=line_num,
              account_id=wt_account.id,
              description=f'Creditable WHT: {invoice.invoice_number}',
              debit_amount=Decimal(str(invoice.withholding_tax_amount)),
              credit_amount=Decimal('0.00'),
          )
          db.session.add(wt_line)
          all_lines.append(wt_line)
          line_num += 1

      # Debit Accounts Receivable
      ar_line = JournalEntryLine(
          entry_id=je.id, line_number=line_num,
          account_id=ar_account.id,
          description=f'AR: {invoice.invoice_number} — {invoice.customer_name}',
          debit_amount=Decimal(str(invoice.total_amount)),
          credit_amount=Decimal('0.00'),
      )
      db.session.add(ar_line)
      all_lines.append(ar_line)

      # Absorb rounding residual into first revenue line (credit side)
      sum_debits = sum((l.debit_amount for l in all_lines), Decimal('0.00'))
      sum_credits = sum((l.credit_amount for l in all_lines), Decimal('0.00'))
      residual = sum_debits - sum_credits
      if residual != Decimal('0.00') and first_revenue_line is not None:
          first_revenue_line.credit_amount += residual

      db.session.flush()
      je.calculate_totals()
      if not je.is_balanced:
          raise ValueError(
              f"Sales invoice JE is not balanced "
              f"(debit={je.total_debit}, credit={je.total_credit}). "
              "Ensure every line item has a revenue account assigned.")
      return je


  def _create_reversal_je(invoice, reversal_date, user_id, label='Cancel'):
      """Swap debits/credits of the stored JE — used by cancel and void."""
      from app.journal_entries.models import JournalEntry, JournalEntryLine

      source_je = invoice.journal_entry
      if source_je is None:
          raise ValueError(
              f'Invoice {invoice.invoice_number} has no stored journal entry to reverse.')

      entry_number = generate_entry_number(invoice.branch_id)
      je = JournalEntry(
          entry_number=entry_number,
          entry_date=reversal_date,
          description=f'Sales Invoice {label} — {invoice.invoice_number} (reversal)',
          reference=f'{label.upper()[:6]}-{invoice.invoice_number}',
          entry_type='reversal',
          is_reversing=True,
          reversed_entry_id=source_je.id,
          branch_id=invoice.branch_id,
          created_by_id=user_id,
          status='posted',
          posted_by_id=user_id,
          posted_at=ph_now(),
          is_balanced=False,
          total_debit=Decimal('0.00'),
          total_credit=Decimal('0.00'),
      )
      db.session.add(je)
      db.session.flush()

      for i, src in enumerate(source_je.lines.all(), start=1):
          db.session.add(JournalEntryLine(
              entry_id=je.id, line_number=i,
              account_id=src.account_id,
              description=f'{label}: {src.description}' if src.description else label,
              debit_amount=src.credit_amount,
              credit_amount=src.debit_amount,
          ))
      db.session.flush()
      je.calculate_totals()
      if not je.is_balanced:
          raise ValueError(f'Reversal JE is not balanced '
                           f'(debit={je.total_debit}, credit={je.total_credit}).')
      source_je.reversed_by_id = je.id
      return je
  ```

- [ ] **Step 3: Run JE test**

  ```
  pytest tests/integration/test_sales_invoices.py -v -k je
  ```

- [ ] **Step 4: Commit**

  ```bash
  git add app/sales_invoices/views.py tests/integration/test_sales_invoices.py
  git commit -m "feat: sales invoices — _post_invoice_je and _create_reversal_je"
  ```

---

## Task 10: `utils.py` + `_filtered_invoices_query` + `list_invoices` route

**Files:**
- Create: `app/sales_invoices/utils.py`
- Modify: `app/sales_invoices/views.py` (append)

- [ ] **Step 1: Create `app/sales_invoices/utils.py`**

  ```python
  from decimal import Decimal
  from datetime import timedelta
  from app.utils import ph_now

  OPEN_STATUSES = ('posted', 'partially_paid')


  def compute_invoices_summary(branch_id):
      from app import db
      from app.sales_invoices.models import SalesInvoice
      today = ph_now().date()

      def _agg(*extra_filters):
          total, count = (
              db.session.query(
                  db.func.coalesce(db.func.sum(SalesInvoice.balance), 0),
                  db.func.count(SalesInvoice.id),
              )
              .filter(
                  SalesInvoice.branch_id == branch_id,
                  SalesInvoice.status.in_(OPEN_STATUSES),
                  *extra_filters,
              )
              .one()
          )
          return Decimal(str(total)).quantize(Decimal('0.01')), count

      outstanding_total, outstanding_count = _agg()
      overdue_total, overdue_count = _agg(
          SalesInvoice.due_date.isnot(None),
          SalesInvoice.due_date < today,
      )
      due_soon_total, due_soon_count = _agg(
          SalesInvoice.due_date.isnot(None),
          SalesInvoice.due_date >= today,
          SalesInvoice.due_date <= today + timedelta(days=7),
      )
      draft_count = (
          db.session.query(db.func.count(SalesInvoice.id))
          .filter(SalesInvoice.branch_id == branch_id, SalesInvoice.status == 'draft')
          .scalar()
      )
      return {
          'outstanding_total': outstanding_total,
          'outstanding_count': outstanding_count,
          'overdue_total': overdue_total,
          'overdue_count': overdue_count,
          'due_soon_total': due_soon_total,
          'due_soon_count': due_soon_count,
          'draft_count': draft_count,
      }
  ```

- [ ] **Step 2: Append to `app/sales_invoices/views.py`**

  ```python
  def _filtered_invoices_query(include_ids=False):
      current_branch_id = session.get('selected_branch_id')
      query = SalesInvoice.query.filter_by(branch_id=current_branch_id)

      if include_ids:
          ids_param = request.args.get('ids', '')
          if ids_param:
              ids = [int(x) for x in ids_param.split(',') if x.strip().isdigit()]
              if ids:
                  return query.filter(SalesInvoice.id.in_(ids))

      status_filter = request.args.get('status', 'all')
      if status_filter in VALID_INVOICE_STATUSES:
          query = query.filter_by(status=status_filter)

      customer_filter = request.args.get('customer', 'all')
      if customer_filter != 'all':
          try:
              query = query.filter_by(customer_id=int(customer_filter))
          except ValueError:
              pass

      q = request.args.get('q', '').strip()
      if q:
          like = f'%{q}%'
          query = query.filter(db.or_(SalesInvoice.invoice_number.ilike(like),
                                      SalesInvoice.customer_name.ilike(like)))

      date_from = request.args.get('date_from', '')
      if date_from:
          try:
              query = query.filter(SalesInvoice.invoice_date >= date.fromisoformat(date_from))
          except ValueError:
              pass

      date_to = request.args.get('date_to', '')
      if date_to:
          try:
              query = query.filter(SalesInvoice.invoice_date <= date.fromisoformat(date_to))
          except ValueError:
              pass

      return query


  @sales_invoices_bp.route('/sales-invoices')
  @login_required
  def list_invoices():
      from app.sales_invoices.utils import compute_invoices_summary
      page = request.args.get('page', 1, type=int)
      per_page = 50
      query = _filtered_invoices_query().order_by(SalesInvoice.invoice_date.desc())
      pagination = query.paginate(page=page, per_page=per_page, error_out=False)
      summary = compute_invoices_summary(session.get('selected_branch_id'))
      customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
      return render_template(
          'sales_invoices/list.html',
          invoices=pagination.items,
          pagination=pagination,
          customers=customers,
          summary=summary,
          today=ph_now().date(),
          status_filter=request.args.get('status', 'all'),
          customer_filter=request.args.get('customer', 'all'),
          q=request.args.get('q', ''),
          date_from=request.args.get('date_from', ''),
          date_to=request.args.get('date_to', ''),
      )


  @sales_invoices_bp.route('/sales-invoices/export/excel')
  @login_required
  def export_excel():
      invoices = (_filtered_invoices_query(include_ids=True)
                  .order_by(SalesInvoice.invoice_date.desc()).all())
      log_audit('sales_invoice', 'export_excel', None, f'{len(invoices)} records',
                notes=f'Exported by {current_user.username}; filters: {request.args.to_dict()}')
      timestamp = ph_now().strftime('%Y%m%d_%H%M%S')
      return export_to_excel(data=invoices, columns=_EXPORT_COLUMNS, headers=_EXPORT_HEADERS,
                             filename=f'sales_invoices_{timestamp}.xlsx',
                             title='Sales Invoices Report')


  @sales_invoices_bp.route('/sales-invoices/export/csv')
  @login_required
  def export_csv_route():
      invoices = (_filtered_invoices_query(include_ids=True)
                  .order_by(SalesInvoice.invoice_date.desc()).all())
      log_audit('sales_invoice', 'export_csv', None, f'{len(invoices)} records',
                notes=f'Exported by {current_user.username}; filters: {request.args.to_dict()}')
      timestamp = ph_now().strftime('%Y%m%d_%H%M%S')
      return export_to_csv(data=invoices, columns=_EXPORT_COLUMNS, headers=_EXPORT_HEADERS,
                           filename=f'sales_invoices_{timestamp}.csv')
  ```

- [ ] **Step 3: Commit**

  ```bash
  git add app/sales_invoices/utils.py app/sales_invoices/views.py
  git commit -m "feat: sales invoices — utils, list route, export routes"
  ```

---

## Task 11: `create` and `edit` routes

**Files:**
- Modify: `app/sales_invoices/views.py` (append)

- [ ] **Step 1: Write integration test** (add to `tests/integration/test_sales_invoices.py`)

  ```python
  def test_create_invoice_posts_to_books(client, db_session, accountant_user, customer, revenue_account, branch):
      """Creating an SV saves draft JE and audit log entry."""
      from flask_login import login_user
      from app.accounts.models import Account
      from app.audit.models import AuditLog

      # Ensure GL accounts exist
      if not Account.query.filter_by(code='10201').first():
          db_session.add(Account(code='10201', name='AR - Trade', account_type='Asset',
                                 normal_balance='debit', is_active=True))
      if not Account.query.filter_by(code='20201').first():
          db_session.add(Account(code='20201', name='Output VAT', account_type='Liability',
                                 normal_balance='credit', is_active=True))
      db_session.commit()

      with client.session_transaction() as sess:
          sess['selected_branch_id'] = branch.id
          sess['_user_id'] = str(accountant_user.id)

      line_item = {
          'description': 'Consulting', 'amount': '11200.00',
          'vat_category': '', 'vat_rate': '0', 'wt_id': '', 'account_id': str(revenue_account.id),
      }
      resp = client.post('/sales-invoices/create', data={
          'invoice_number': 'SI-2026-0001',
          'invoice_date': '2026-06-14',
          'due_date': '2026-07-14',
          'customer_id': str(customer.id),
          'payment_terms': 'Net 30',
          'notes': 'Test invoice',
          'line_items': json.dumps([line_item]),
          'csrf_token': 'test',
      }, follow_redirects=True)

      assert resp.status_code == 200
      inv = SalesInvoice.query.filter_by(invoice_number='SI-2026-0001').first()
      assert inv is not None
      assert inv.journal_entry_id is not None
      assert inv.total_amount == Decimal('11200.00')

      audit = AuditLog.query.filter_by(module='sales_invoice', action='create',
                                       record_id=inv.id).first()
      assert audit is not None
      assert audit.user_id == accountant_user.id
  ```

- [ ] **Step 2: Append `create` and `edit` routes to `views.py`**

  ```python
  @sales_invoices_bp.route('/sales-invoices/create', methods=['GET', 'POST'])
  @login_required
  @staff_or_above_required
  def create():
      form = SalesInvoiceForm()
      customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
      form.customer_id.choices = [(0, '-- Select Customer --')] + [
          (c.id, f'{c.code} - {c.name}') for c in customers]

      if form.validate_on_submit():
          if not validate_transaction_date_with_flash(form.invoice_date.data, 'Sales Invoice'):
              return render_template('sales_invoices/form.html', form=form, invoice=None)
          try:
              customer = Customer.query.get(form.customer_id.data)
              if not customer:
                  flash('Selected customer not found.', 'error')
                  return render_template('sales_invoices/form.html', form=form, invoice=None)

              invoice = SalesInvoice(
                  branch_id=session.get('selected_branch_id'),
                  invoice_number=form.invoice_number.data,
                  invoice_date=form.invoice_date.data,
                  due_date=form.due_date.data,
                  customer_id=customer.id,
                  customer_name=customer.name,
                  customer_tin=customer.tin,
                  customer_address=customer.address,
                  customer_po_number=form.customer_po_number.data or None,
                  customer_po_date=form.customer_po_date.data or None,
                  payment_terms=form.payment_terms.data,
                  reference=form.reference.data,
                  notes=form.notes.data or '',
                  status='draft',
                  amount_paid=Decimal('0.00'),
                  balance=Decimal('0.00'),
                  created_by_id=current_user.id,
              )

              line_items_data = request.form.getlist('line_items')
              if line_items_data:
                  items = json.loads(line_items_data[0]) if line_items_data[0] else []
                  for idx, item_data in enumerate(items, start=1):
                      vat_rate = Decimal('0.00')
                      vat_category = item_data.get('vat_category')
                      if vat_category:
                          vat_cat = VATCategory.query.filter_by(code=vat_category, is_active=True).first()
                          if vat_cat:
                              vat_rate = Decimal(str(vat_cat.rate))
                      wt_id = int(item_data['wt_id']) if item_data.get('wt_id') else None
                      wt_rate = None
                      if wt_id:
                          wt_obj = WithholdingTax.query.get(wt_id)
                          if wt_obj:
                              wt_rate = wt_obj.rate
                      line_item = SalesInvoiceItem(
                          line_number=idx,
                          description=item_data.get('description', ''),
                          amount=Decimal(str(item_data.get('amount', 0))),
                          vat_category=vat_category,
                          vat_rate=vat_rate,
                          account_id=int(item_data['account_id']) if item_data.get('account_id') else None,
                          wt_id=wt_id,
                          wt_rate=wt_rate,
                      )
                      line_item.calculate_amounts()
                      invoice.line_items.append(line_item)

              invoice.calculate_totals()
              err = _apply_overrides(invoice)
              if err:
                  return err

              db.session.add(invoice)
              db.session.flush()

              je = _post_invoice_je(invoice, current_user.id)
              invoice.journal_entry_id = je.id
              db.session.commit()

              log_create(
                  module='sales_invoice',
                  record_id=invoice.id,
                  record_identifier=f'{invoice.invoice_number} - {invoice.customer_name}',
                  new_values=model_to_dict(invoice, [
                      'invoice_number', 'invoice_date', 'due_date', 'customer_name',
                      'subtotal', 'vat_amount', 'withholding_tax_amount', 'total_amount', 'status'])
              )

              flash(f'Sales Invoice "{invoice.invoice_number}" entered successfully!', 'success')
              return redirect(url_for('sales_invoices.view', id=invoice.id))

          except Exception as e:
              from app.errors.utils import log_exception
              db.session.rollback()
              current_app.logger.error('Error creating sales invoice', exc_info=True)
              log_exception(e, severity='ERROR', module='sales_invoices.create')
              flash(f'Error entering Sales Invoice: {str(e)}', 'error')

      if request.method == 'GET':
          form.invoice_number.data = generate_invoice_number()
          form.invoice_date.data = ph_now().date()
          form.due_date.data = ph_now().date() + timedelta(days=30)

      vat_categories = [v.to_dict() for v in VATCategory.query.filter_by(is_active=True).order_by(VATCategory.code).all()]
      all_accounts = _get_all_accounts_for_select()
      _accts = _get_gl_accounts()
      gl_accounts = {
          'ar': {'code': _accts['ar'].code, 'name': _accts['ar'].name} if _accts['ar'] else None,
          'wt': {'code': _accts['wt'].code, 'name': _accts['wt'].name} if _accts['wt'] else None,
      }
      return render_template('sales_invoices/form.html', form=form, invoice=None,
                             vat_categories=vat_categories, all_accounts=all_accounts,
                             gl_accounts=gl_accounts)


  @sales_invoices_bp.route('/sales-invoices/<int:id>/edit', methods=['GET', 'POST'])
  @login_required
  @staff_or_above_required
  def edit(id):
      invoice = _get_invoice_or_404(id)
      if invoice.status != 'draft':
          flash('Only draft Sales Invoices can be edited.', 'error')
          return redirect(url_for('sales_invoices.view', id=id))

      form = SalesInvoiceForm(obj=invoice)
      customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
      form.customer_id.choices = [(c.id, f'{c.code} - {c.name}') for c in customers]

      if form.validate_on_submit():
          if not validate_transaction_date_with_flash(form.invoice_date.data, 'Sales Invoice'):
              return render_template('sales_invoices/form.html', form=form, invoice=invoice)
          try:
              old_values = model_to_dict(invoice, [
                  'invoice_number', 'invoice_date', 'due_date', 'customer_name',
                  'subtotal', 'vat_amount', 'withholding_tax_amount', 'total_amount', 'status'])

              customer = Customer.query.get(form.customer_id.data)
              if not customer:
                  flash('Selected customer not found.', 'error')
                  return render_template('sales_invoices/form.html', form=form, invoice=invoice)

              invoice.invoice_number = form.invoice_number.data
              invoice.invoice_date = form.invoice_date.data
              invoice.due_date = form.due_date.data
              invoice.customer_id = customer.id
              invoice.customer_name = customer.name
              invoice.customer_tin = customer.tin
              invoice.customer_address = customer.address
              invoice.customer_po_number = form.customer_po_number.data or None
              invoice.customer_po_date = form.customer_po_date.data or None
              invoice.payment_terms = form.payment_terms.data
              invoice.reference = form.reference.data
              invoice.notes = form.notes.data or ''

              SalesInvoiceItem.query.filter_by(invoice_id=invoice.id).delete()

              line_items_data = request.form.getlist('line_items')
              if line_items_data:
                  items = json.loads(line_items_data[0]) if line_items_data[0] else []
                  for idx, item_data in enumerate(items, start=1):
                      vat_rate = Decimal('0.00')
                      vat_category = item_data.get('vat_category')
                      if vat_category:
                          vat_cat = VATCategory.query.filter_by(code=vat_category, is_active=True).first()
                          if vat_cat:
                              vat_rate = Decimal(str(vat_cat.rate))
                      wt_id = int(item_data['wt_id']) if item_data.get('wt_id') else None
                      wt_rate = None
                      if wt_id:
                          wt_obj = WithholdingTax.query.get(wt_id)
                          if wt_obj:
                              wt_rate = wt_obj.rate
                      line_item = SalesInvoiceItem(
                          invoice_id=invoice.id, line_number=idx,
                          description=item_data.get('description', ''),
                          amount=Decimal(str(item_data.get('amount', 0))),
                          vat_category=vat_category, vat_rate=vat_rate,
                          account_id=int(item_data['account_id']) if item_data.get('account_id') else None,
                          wt_id=wt_id, wt_rate=wt_rate,
                      )
                      line_item.calculate_amounts()
                      db.session.add(line_item)

              invoice.calculate_totals()
              err = _apply_overrides(invoice)
              if err:
                  return err

              if invoice.journal_entry_id:
                  from app.journal_entries.models import JournalEntry as _JE
                  old_je_id = invoice.journal_entry_id
                  invoice.journal_entry_id = None
                  invoice.journal_entry = None
                  db.session.flush()
                  old_je = db.session.get(_JE, old_je_id)
                  if old_je:
                      db.session.delete(old_je)

              db.session.flush()
              je = _post_invoice_je(invoice, current_user.id)
              invoice.journal_entry_id = je.id
              db.session.commit()

              new_values = model_to_dict(invoice, [
                  'invoice_number', 'invoice_date', 'due_date', 'customer_name',
                  'subtotal', 'vat_amount', 'withholding_tax_amount', 'total_amount', 'status'])
              log_update(module='sales_invoice', record_id=invoice.id,
                         record_identifier=f'{invoice.invoice_number} - {invoice.customer_name}',
                         old_values=old_values, new_values=new_values)

              flash(f'Sales Invoice "{invoice.invoice_number}" saved successfully!', 'success')
              return redirect(url_for('sales_invoices.view', id=invoice.id))

          except Exception as e:
              from app.errors.utils import log_exception
              db.session.rollback()
              current_app.logger.error('Error updating sales invoice', exc_info=True)
              log_exception(e, severity='ERROR', module='sales_invoices.edit')
              flash(f'Error saving Sales Invoice: {str(e)}', 'error')

      if request.method == 'GET':
          form.customer_id.data = invoice.customer_id

      vat_categories = [v.to_dict() for v in VATCategory.query.filter_by(is_active=True).order_by(VATCategory.code).all()]
      all_accounts = _get_all_accounts_for_select()
      line_items = [item.to_dict() for item in invoice.line_items]
      _accts = _get_gl_accounts()
      gl_accounts = {
          'ar': {'code': _accts['ar'].code, 'name': _accts['ar'].name} if _accts['ar'] else None,
          'wt': {'code': _accts['wt'].code, 'name': _accts['wt'].name} if _accts['wt'] else None,
      }
      return render_template('sales_invoices/form.html', form=form, invoice=invoice,
                             vat_categories=vat_categories, all_accounts=all_accounts,
                             line_items=line_items, gl_accounts=gl_accounts)
  ```

- [ ] **Step 3: Run create test**

  ```
  pytest tests/integration/test_sales_invoices.py -v -k create
  ```

- [ ] **Step 4: Commit**

  ```bash
  git add app/sales_invoices/views.py tests/integration/test_sales_invoices.py
  git commit -m "feat: sales invoices — create and edit routes"
  ```

---

## Task 12: `view`, `post`, `cancel`, `void` routes

**Files:**
- Modify: `app/sales_invoices/views.py` (append)

- [ ] **Step 1: Write tests** (add to `tests/integration/test_sales_invoices.py`)

  ```python
  def _make_draft_invoice(db_session, customer, revenue_account, branch, user):
      """Helper: create a draft SV with one line item and linked JE."""
      from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
      from app.journal_entries.models import JournalEntry, JournalEntryLine
      from app.accounts.models import Account
      inv = SalesInvoice(
          branch_id=branch.id,
          invoice_number='SI-2026-TEST',
          invoice_date=date(2026, 6, 14),
          due_date=date(2026, 7, 14),
          customer_id=customer.id,
          customer_name=customer.name,
          notes='',
          status='draft',
          subtotal=Decimal('10000.00'),
          vat_amount=Decimal('0.00'),
          total_before_wt=Decimal('10000.00'),
          withholding_tax_amount=Decimal('0.00'),
          total_amount=Decimal('10000.00'),
          amount_paid=Decimal('0.00'),
          balance=Decimal('10000.00'),
          created_by_id=user.id,
      )
      db_session.add(inv)
      db_session.flush()
      item = SalesInvoiceItem(
          invoice_id=inv.id, line_number=1, description='Service',
          amount=Decimal('10000.00'), vat_rate=Decimal('0.00'),
          line_total=Decimal('10000.00'), vat_amount=Decimal('0.00'),
          wt_amount=Decimal('0.00'), account_id=revenue_account.id,
      )
      db_session.add(item)
      ar = Account.query.filter_by(code='10201').first()
      if not ar:
          ar = Account(code='10201', name='AR', account_type='Asset',
                       normal_balance='debit', is_active=True)
          db_session.add(ar)
      db_session.flush()
      je = JournalEntry(
          entry_number='JE-2026-0001', entry_date=date(2026, 6, 14),
          description='Test', reference='SI-2026-TEST', entry_type='sale',
          branch_id=branch.id, created_by_id=user.id, status='draft',
          is_balanced=True, total_debit=Decimal('10000.00'), total_credit=Decimal('10000.00'),
      )
      db_session.add(je)
      db_session.flush()
      inv.journal_entry_id = je.id
      db_session.add(JournalEntryLine(
          entry_id=je.id, line_number=1, account_id=ar.id,
          description='AR', debit_amount=Decimal('10000.00'), credit_amount=Decimal('0.00')))
      db_session.add(JournalEntryLine(
          entry_id=je.id, line_number=2, account_id=revenue_account.id,
          description='Revenue', debit_amount=Decimal('0.00'), credit_amount=Decimal('10000.00')))
      db_session.commit()
      return inv


  def test_post_invoice(client, db_session, accountant_user, customer, revenue_account, branch):
      from app.audit.models import AuditLog
      inv = _make_draft_invoice(db_session, customer, revenue_account, branch, accountant_user)
      with client.session_transaction() as sess:
          sess['selected_branch_id'] = branch.id
          sess['_user_id'] = str(accountant_user.id)
      resp = client.post(f'/sales-invoices/{inv.id}/post', data={'csrf_token': 'test'},
                         follow_redirects=True)
      assert resp.status_code == 200
      db_session.refresh(inv)
      assert inv.status == 'posted'
      assert inv.journal_entry.status == 'posted'
      audit = AuditLog.query.filter_by(module='sales_invoice', action='post', record_id=inv.id).first()
      assert audit is not None


  def test_cancel_posted_invoice(client, db_session, accountant_user, customer, revenue_account, branch):
      from app.audit.models import AuditLog
      inv = _make_draft_invoice(db_session, customer, revenue_account, branch, accountant_user)
      inv.status = 'posted'
      inv.journal_entry.status = 'posted'
      db_session.commit()
      with client.session_transaction() as sess:
          sess['selected_branch_id'] = branch.id
          sess['_user_id'] = str(accountant_user.id)
      resp = client.post(f'/sales-invoices/{inv.id}/cancel',
                         data={'cancel_reason': 'Customer cancelled the order', 'reversal_date': '2026-06-15', 'csrf_token': 'test'},
                         follow_redirects=True)
      assert resp.status_code == 200
      db_session.refresh(inv)
      assert inv.status == 'cancelled'
      audit = AuditLog.query.filter_by(module='sales_invoice', action='cancel', record_id=inv.id).first()
      assert audit is not None


  def test_void_draft_invoice(client, db_session, accountant_user, customer, revenue_account, branch):
      from app.audit.models import AuditLog
      inv = _make_draft_invoice(db_session, customer, revenue_account, branch, accountant_user)
      with client.session_transaction() as sess:
          sess['selected_branch_id'] = branch.id
          sess['_user_id'] = str(accountant_user.id)
      resp = client.post(f'/sales-invoices/{inv.id}/void',
                         data={'void_reason': 'Entered by mistake on wrong date', 'reversal_date': '2026-06-14', 'csrf_token': 'test'},
                         follow_redirects=True)
      assert resp.status_code == 200
      db_session.refresh(inv)
      assert inv.status == 'voided'
      audit = AuditLog.query.filter_by(module='sales_invoice', action='void', record_id=inv.id).first()
      assert audit is not None
  ```

- [ ] **Step 2: Append routes to `views.py`**

  ```python
  @sales_invoices_bp.route('/sales-invoices/<int:id>')
  @login_required
  def view(id):
      invoice = _get_invoice_or_404(id)
      je_entries = _build_je_preview(invoice)
      sv_print_access = AppSettings.get_setting('sv_print_access', 'posted_only')
      return render_template('sales_invoices/detail.html', invoice=invoice,
                             je_entries=je_entries, sv_print_access=sv_print_access)


  @sales_invoices_bp.route('/sales-invoices/<int:id>/post', methods=['POST'])
  @login_required
  @staff_or_above_required
  def post(id):
      invoice = _get_invoice_or_404(id)
      if invoice.status != 'draft':
          flash('Only draft Sales Invoices can be posted.', 'error')
          return redirect(url_for('sales_invoices.view', id=id))
      try:
          invoice.status = 'posted'
          invoice.posted_by_id = current_user.id
          invoice.posted_at = ph_now()
          if invoice.journal_entry:
              invoice.journal_entry.status = 'posted'
              invoice.journal_entry.posted_by_id = current_user.id
              invoice.journal_entry.posted_at = ph_now()
          db.session.commit()
          log_audit('sales_invoice', 'post', invoice.id,
                    f'{invoice.invoice_number} - {invoice.customer_name}',
                    notes=f'Invoice posted by {current_user.username}')
          flash(f'Sales Invoice "{invoice.invoice_number}" posted successfully!', 'success')
      except Exception as e:
          from app.errors.utils import log_exception
          db.session.rollback()
          current_app.logger.error('Error posting sales invoice', exc_info=True)
          log_exception(e, severity='ERROR', module='sales_invoices.post')
          flash(f'Error posting Sales Invoice: {str(e)}', 'error')
      return redirect(url_for('sales_invoices.view', id=id))


  @sales_invoices_bp.route('/sales-invoices/<int:id>/cancel', methods=['POST'])
  @login_required
  @accountant_or_admin_required
  def cancel(id):
      from app.errors.utils import log_exception
      invoice = _get_invoice_or_404(id)
      if invoice.status != 'posted':
          flash('Only posted Sales Invoices can be cancelled.', 'error')
          return redirect(url_for('sales_invoices.view', id=id))
      if invoice.amount_paid > 0:
          flash('Cannot cancel a Sales Invoice with payments applied. Reverse the payments first.', 'error')
          return redirect(url_for('sales_invoices.view', id=id))
      cancel_reason = request.form.get('cancel_reason', '').strip()
      if len(cancel_reason) < 10:
          flash('Cancellation reason must be at least 10 characters.', 'error')
          return redirect(url_for('sales_invoices.view', id=id))
      reversal_date_str = request.form.get('reversal_date', '')
      try:
          reversal_date = date.fromisoformat(reversal_date_str)
      except ValueError:
          flash('Invalid reversal date.', 'error')
          return redirect(url_for('sales_invoices.view', id=id))
      try:
          _create_reversal_je(invoice, reversal_date, current_user.id, label='Cancel')
          invoice.status = 'cancelled'
          invoice.cancelled_at = ph_now()
          invoice.cancel_reason = cancel_reason
          db.session.commit()
          log_audit('sales_invoice', 'cancel', invoice.id,
                    f'{invoice.invoice_number} - {invoice.customer_name}',
                    notes=f'Cancelled by {current_user.username}. Reason: {cancel_reason}')
          flash(f'Sales Invoice "{invoice.invoice_number}" cancelled. Reversal JE created.', 'success')
      except ValueError as e:
          db.session.rollback()
          flash(str(e), 'error')
      except Exception as e:
          db.session.rollback()
          current_app.logger.error('Error cancelling sales invoice', exc_info=True)
          log_exception(e, severity='ERROR', module='sales_invoices.cancel')
          flash(f'Error cancelling Sales Invoice: {str(e)}', 'error')
      return redirect(url_for('sales_invoices.view', id=id))


  @sales_invoices_bp.route('/sales-invoices/<int:id>/void', methods=['POST'])
  @login_required
  @staff_or_above_required
  def void(id):
      invoice = _get_invoice_or_404(id)
      if invoice.status != 'draft':
          flash('Only draft Sales Invoices can be voided.', 'error')
          return redirect(url_for('sales_invoices.view', id=id))
      void_reason = request.form.get('void_reason', '').strip()
      if len(void_reason) < 10:
          flash('Void reason must be at least 10 characters.', 'error')
          return redirect(url_for('sales_invoices.view', id=id))
      reversal_date_str = request.form.get('reversal_date', '')
      try:
          reversal_date = date.fromisoformat(reversal_date_str)
      except ValueError:
          flash('Invalid void date.', 'error')
          return redirect(url_for('sales_invoices.view', id=id))
      try:
          if invoice.journal_entry_id:
              from app.journal_entries.models import JournalEntry as _JE
              je_to_delete = db.session.get(_JE, invoice.journal_entry_id)
              if je_to_delete:
                  db.session.delete(je_to_delete)
              invoice.journal_entry_id = None
              invoice.journal_entry = None

          # Collect paths before deleting DB rows
          attachment_paths = []
          for att in list(invoice.attachments):
              fp = os.path.join(current_app.config['UPLOAD_FOLDER'], 'sales_invoices',
                                str(invoice.id), att.stored_filename)
              attachment_paths.append(fp)
              db.session.delete(att)

          invoice.status = 'voided'
          invoice.voided_at = ph_now()
          invoice.voided_by_id = current_user.id
          invoice.void_reason = void_reason
          db.session.commit()

          for fp in attachment_paths:
              if os.path.isfile(fp):
                  try:
                      os.remove(fp)
                  except OSError:
                      current_app.logger.warning(f'Could not remove attachment during void: {fp}')

          log_audit('sales_invoice', 'void', invoice.id,
                    f'{invoice.invoice_number} - {invoice.customer_name}',
                    notes=f'Draft voided by {current_user.username} on {reversal_date}. Reason: {void_reason}. {len(attachment_paths)} attachment(s) deleted.')
          flash(f'Sales Invoice "{invoice.invoice_number}" voided.', 'warning')
      except Exception as e:
          from app.errors.utils import log_exception
          db.session.rollback()
          current_app.logger.error('Error voiding sales invoice', exc_info=True)
          log_exception(e, severity='ERROR', module='sales_invoices.void')
          flash(f'Error voiding Sales Invoice: {str(e)}', 'error')
      return redirect(url_for('sales_invoices.view', id=id))
  ```

- [ ] **Step 3: Run lifecycle tests**

  ```
  pytest tests/integration/test_sales_invoices.py -v -k "post or cancel or void"
  ```

- [ ] **Step 4: Commit**

  ```bash
  git add app/sales_invoices/views.py tests/integration/test_sales_invoices.py
  git commit -m "feat: sales invoices — view, post, cancel, void routes"
  ```

---

## Task 13: Print + attachment routes

**Files:**
- Modify: `app/sales_invoices/views.py` (append)

- [ ] **Step 1: Append print and attachment routes**

  ```python
  @sales_invoices_bp.route('/sales-invoices/<int:id>/print')
  @login_required
  def print_invoice(id):
      invoice = _get_invoice_or_404(id)
      je_lines = []
      if invoice.journal_entry:
          vat_account_ids = {
              c.output_vat_account_id
              for c in VATCategory.query.all()
              if c.output_vat_account_id
          }
          lines = invoice.journal_entry.lines.all()
          revenue_lines = sorted(
              [l for l in lines if (l.credit_amount or 0) > 0 and l.account_id not in vat_account_ids],
              key=lambda l: l.account.code)
          vat_lines = sorted(
              [l for l in lines if (l.credit_amount or 0) > 0 and l.account_id in vat_account_ids],
              key=lambda l: l.account.code)
          debit_lines = sorted(
              [l for l in lines if (l.debit_amount or 0) > 0],
              key=lambda l: l.account.code)
          je_lines = revenue_lines + vat_lines + debit_lines

      company = {
          'name': AppSettings.get_setting('company_name', ''),
          'address': AppSettings.get_setting('company_address', ''),
          'tin': AppSettings.get_setting('company_tin', ''),
      }
      return render_template('sales_invoices/print.html', invoice=invoice,
                             je_lines=je_lines, company=company, printed_at=ph_now())


  @sales_invoices_bp.route('/sales-invoices/<int:id>/attachments/upload', methods=['POST'])
  @login_required
  @staff_or_above_required
  def upload_attachment(id):
      invoice = _get_invoice_or_404(id)
      if invoice.status != 'draft':
          flash('Attachments can only be uploaded while the Sales Invoice is in draft status.', 'error')
          return redirect(url_for('sales_invoices.edit', id=id))
      uploaded_file = request.files.get('attachment')
      if not uploaded_file or uploaded_file.filename == '':
          flash('No file selected.', 'error')
          return redirect(url_for('sales_invoices.edit', id=id))
      original_name = secure_filename(uploaded_file.filename)
      if not original_name:
          flash('Invalid filename.', 'error')
          return redirect(url_for('sales_invoices.edit', id=id))
      _, ext = os.path.splitext(original_name)
      ext = ext.lower()
      mime_type = _ATTACHMENT_ALLOWED.get(ext)
      if mime_type is None:
          flash(f'File type "{ext or "unknown"}" is not allowed.', 'error')
          return redirect(url_for('sales_invoices.edit', id=id))
      stored_name = uuid.uuid4().hex + ext
      upload_dir = _invoice_upload_dir(id)
      file_path = os.path.join(upload_dir, stored_name)
      try:
          uploaded_file.save(file_path)
          file_size = os.path.getsize(file_path)
          attachment = SalesInvoiceAttachment(
              invoice_id=invoice.id, original_filename=original_name,
              stored_filename=stored_name, mime_type=mime_type,
              file_size=file_size, uploaded_by_id=current_user.id)
          db.session.add(attachment)
          db.session.commit()
          log_create('sales_invoice_attachment', attachment.id,
                     f'{invoice.invoice_number} / {original_name}',
                     new_values={'invoice_id': invoice.id, 'original_filename': original_name,
                                 'mime_type': mime_type, 'file_size': file_size})
          flash(f'File "{original_name}" uploaded successfully.', 'success')
      except Exception as e:
          db.session.rollback()
          if os.path.exists(file_path):
              os.remove(file_path)
          flash(f'Error uploading file: {str(e)}', 'error')
      return redirect(url_for('sales_invoices.edit', id=id))


  @sales_invoices_bp.route('/sales-invoices/attachments/<int:attachment_id>/download')
  @login_required
  def download_attachment(attachment_id):
      attachment = SalesInvoiceAttachment.query.get_or_404(attachment_id)
      invoice = _get_invoice_or_404(attachment.invoice_id)
      file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'sales_invoices',
                               str(invoice.id), attachment.stored_filename)
      if not os.path.isfile(file_path):
          flash('File not found on disk.', 'error')
          return redirect(url_for('sales_invoices.view', id=invoice.id))
      response = send_file(file_path, mimetype=attachment.mime_type, as_attachment=True,
                           download_name=attachment.original_filename)
      response.headers['X-Content-Type-Options'] = 'nosniff'
      return response


  @sales_invoices_bp.route('/sales-invoices/attachments/<int:attachment_id>/preview')
  @login_required
  def preview_attachment(attachment_id):
      attachment = SalesInvoiceAttachment.query.get_or_404(attachment_id)
      if not attachment.is_image:
          abort(404)
      invoice = _get_invoice_or_404(attachment.invoice_id)
      file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'sales_invoices',
                               str(invoice.id), attachment.stored_filename)
      if not os.path.isfile(file_path):
          abort(404)
      response = send_file(file_path, mimetype=attachment.mime_type, as_attachment=False)
      response.headers['X-Content-Type-Options'] = 'nosniff'
      response.headers['Content-Security-Policy'] = "default-src 'none'; sandbox"
      return response


  @sales_invoices_bp.route('/sales-invoices/attachments/<int:attachment_id>/delete', methods=['POST'])
  @login_required
  @accountant_or_admin_required
  def delete_attachment(attachment_id):
      attachment = SalesInvoiceAttachment.query.get_or_404(attachment_id)
      invoice = _get_invoice_or_404(attachment.invoice_id)
      if invoice.status != 'draft':
          flash('Attachments can only be deleted while the Sales Invoice is in draft status.', 'error')
          return redirect(url_for('sales_invoices.edit', id=invoice.id))
      file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'sales_invoices',
                               str(invoice.id), attachment.stored_filename)
      old_values = {'invoice_id': invoice.id, 'original_filename': attachment.original_filename,
                    'mime_type': attachment.mime_type, 'file_size': attachment.file_size}
      original_name = attachment.original_filename
      try:
          db.session.delete(attachment)
          db.session.commit()
          if os.path.isfile(file_path):
              os.remove(file_path)
          log_delete('sales_invoice_attachment', attachment_id,
                     f'{invoice.invoice_number} / {original_name}', old_values=old_values)
          flash(f'File "{original_name}" deleted.', 'success')
      except Exception as e:
          db.session.rollback()
          flash(f'Error deleting file: {str(e)}', 'error')
      return redirect(url_for('sales_invoices.edit', id=invoice.id))
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add app/sales_invoices/views.py
  git commit -m "feat: sales invoices — print and attachment routes"
  ```

---

## Task 14: List template

**Files:**
- Create: `app/sales_invoices/templates/sales_invoices/list.html`

- [ ] **Step 1: Create the template**

  Mirror `app/purchase_bills/templates/purchase_bills/list.html` exactly, making these substitutions:
  - "AP Voucher" / "Purchase Bill" → "Sales Invoice"
  - "Vendor" → "Customer"
  - `purchase_bills.*` URL endpoints → `sales_invoices.*`
  - Summary card labels: Outstanding AR, Overdue, Due Soon, Drafts
  - Filter dropdown: `customers` list, not `vendors`
  - Table column "Vendor Name" → "Customer"
  - "+ Enter Bill" button → "+ Enter Invoice"
  - Export URLs → `sales_invoices.export_excel` / `sales_invoices.export_csv_route`

  Key template structure:
  ```jinja2
  {% extends 'base.html' %}
  {% block content %}
  {# Summary cards #}
  <div class="summary-cards">
    <div class="card {% if status_filter == 'posted' %}active{% endif %}"
         onclick="window.location='{{ url_for('sales_invoices.list_invoices', status='posted') }}'">
      <div class="card-value">{{ summary.outstanding_count }}</div>
      <div class="card-label">Outstanding AR</div>
      <div class="card-amount">{{ '{:,.2f}'.format(summary.outstanding_total) }}</div>
    </div>
    {# Overdue, Due Soon, Drafts cards follow same pattern #}
  </div>

  {# Filter bar #}
  <form method="GET" action="{{ url_for('sales_invoices.list_invoices') }}">
    {# status tabs, customer dropdown, search, date range #}
  </form>

  {# Table #}
  <table>
    <thead>
      <tr><th>Invoice #</th><th>Date</th><th>Due</th><th>Customer</th>
          <th>Subtotal</th><th>VAT</th><th>WHT</th><th>Total</th>
          <th>Balance</th><th>Status</th><th></th></tr>
    </thead>
    <tbody>
      {% for invoice in invoices %}
      <tr>
        <td><a href="{{ url_for('sales_invoices.view', id=invoice.id) }}">{{ invoice.invoice_number }}</a></td>
        <td>{{ invoice.invoice_date }}</td>
        <td class="{% if invoice.due_date < today and invoice.status in ('posted','partially_paid') %}overdue{% endif %}">
            {{ invoice.due_date }}</td>
        <td>{{ invoice.customer_name }}</td>
        <td class="num">{{ '{:,.2f}'.format(invoice.subtotal) }}</td>
        <td class="num">{{ '{:,.2f}'.format(invoice.vat_amount) }}</td>
        <td class="num">{{ '{:,.2f}'.format(invoice.withholding_tax_amount) }}</td>
        <td class="num">{{ '{:,.2f}'.format(invoice.total_amount) }}</td>
        <td class="num">{{ '{:,.2f}'.format(invoice.balance) }}</td>
        <td><span class="badge badge-{{ invoice.status }}">{{ invoice.status }}</span></td>
        <td><a href="{{ url_for('sales_invoices.view', id=invoice.id) }}">View</a></td>
      </tr>
      {% else %}
      <tr><td colspan="11">No sales invoices found.</td></tr>
      {% endfor %}
    </tbody>
  </table>
  {# Pagination, export buttons #}
  {% endblock %}
  ```

- [ ] **Step 2: Test in browser**

  Start the dev server (`python flask_app.py`), go to `/sales-invoices`. Verify:
  - Page loads without error
  - Summary cards show (all zeros is fine)
  - Filter bar renders
  - "+ Enter Invoice" button is present

- [ ] **Step 3: Commit**

  ```bash
  git add app/sales_invoices/templates/
  git commit -m "feat: sales invoices list template"
  ```

---

## Task 15: Form template

**Files:**
- Create: `app/sales_invoices/templates/sales_invoices/form.html`

- [ ] **Step 1: Create the form template**

  Mirror `app/purchase_bills/templates/purchase_bills/form.html` with these changes:
  - Title: "Enter Invoice" / "Edit Sales Invoice"
  - Vendor picker → Customer picker (same Choices.js pattern, `code + name`)
  - "Bill Date" → "Invoice Date", "AP Voucher #" → "Invoice #"
  - "Vendor Invoice #" / "Vendor Invoice Date" → "Customer PO #" / "Customer PO Date" (both optional, no asterisk)
  - Line item table columns: Description, Amount, VAT Category, WHT Code, Account Title
    (remove Qty and Unit Price columns)
  - Submit button: "Enter Invoice" (create) / "Save Changes" (edit)
  - GL accounts preview footer: "AR - Trade" and "Creditable WHT" instead of "AP" and "WHT Payable"
  - Invoice Summary panel: Subtotal → VAT → Total Before WHT → WHT → Total

  Key JS section — initialize Choices.js on the customer picker:
  ```javascript
  const customerChoices = new Choices('#customer_id', {
    searchEnabled: true,
    searchResultLimit: 100,
    allowHTML: false,
    itemSelectText: '',
    placeholder: true,
    placeholderValue: '-- Select Customer --',
  });
  ```

  Line item JS: copy from APV form template — replace `amount` input (drop `qty` and `unit_price` inputs). The `addLineItem()` JS function creates a row with: description text, amount number input, VAT category Choices select, WHT code Choices select, account title Choices select.

- [ ] **Step 2: Test in browser**

  Go to `/sales-invoices/create`. Verify:
  - Customer picker loads and is searchable
  - Adding a line item shows Description, Amount, VAT Category, WHT Code, Account Title
  - Invoice Summary panel updates as amounts are entered
  - Form submits and creates an invoice (check `/sales-invoices` list)

- [ ] **Step 3: Commit**

  ```bash
  git add app/sales_invoices/templates/
  git commit -m "feat: sales invoices form template"
  ```

---

## Task 16: Detail template

**Files:**
- Create: `app/sales_invoices/templates/sales_invoices/detail.html`

- [ ] **Step 1: Create the detail template**

  Mirror `app/purchase_bills/templates/purchase_bills/detail.html` with these substitutions:
  - Title: invoice number
  - Header panel fields: Invoice #, Invoice Date, Due Date, Status, Customer (name/TIN/address),
    Customer PO # and Date (show only if present), Payment Terms, Reference, Notes
  - Line items table: Description, Amount, VAT Category, VAT Amount, WHT Code, WHT Amount, Account
  - Invoice Summary panel (CSS grid `.bsr`/`.bsr-amt` classes):
    ```
    Subtotal            ₱ xxx
    VAT        [pencil] ₱ xxx   ← only show pencil if vat_override
    ───────────────────────────
    Total Before WHT    ₱ xxx
    WHT        [pencil] ₱ xxx   ← only show pencil if wt_override
    ═══════════════════════════
    Total               ₱ xxx
    Amount Paid         ₱ xxx
    Balance Due         ₱ xxx
    ```
  - JE preview section: collapsible `<details>` with code / name / debit / credit table.
    Label "Journal Entry Preview" if draft, "Posted Journal Entry" if posted.
  - Action buttons (role-gated):
    - Draft: Edit, Post, Void
    - Posted: Cancel, Print
    - Cancelled/Voided: Print (if `sv_print_access != 'posted_only'`)
  - Cancel modal and Void modal — each a hidden `<div class="modal">` with:
    - Reason textarea (min 10 chars, validated client-side before submit)
    - Reversal date input
    - CSRF hidden input `{{ csrf_token() }}`
    - Confirm and Cancel buttons
  - Attachments panel (same as APV detail): list uploaded files, download links, image preview thumbnails

- [ ] **Step 2: Test in browser**

  Create a draft invoice, open its detail page. Verify:
  - All header fields display correctly
  - Line items table renders
  - Invoice Summary shows correct totals
  - JE Preview section is visible (even for drafts)
  - Post/Void buttons visible, Edit button present
  - Click Post — verify status changes to "posted" and action buttons update

- [ ] **Step 3: Commit**

  ```bash
  git add app/sales_invoices/templates/
  git commit -m "feat: sales invoices detail template"
  ```

---

## Task 17: Print template

**Files:**
- Create: `app/sales_invoices/templates/sales_invoices/print.html`

- [ ] **Step 1: Create the print template**

  Mirror `app/purchase_bills/templates/purchase_bills/print.html` with these changes:
  - Title block: **SALES INVOICE**
  - Company header at top (name, address, TIN from `company` dict)
  - Customer block (not vendor)
  - Customer PO # if present
  - Line items table: Description, Amount, VAT Rate, VAT Amount, WHT, Net
  - Summary totals: Subtotal, VAT, WHT, Total
  - JE lines table
  - Notes
  - Signature lines: Prepared by / Approved by / Received by (customer signs this)
  - `<style>@media print { ... }</style>` to hide browser chrome
  - `<script>window.onload = function() { window.print(); }</script>` for auto-print

- [ ] **Step 2: Test in browser**

  Post an invoice, click Print. Verify:
  - Print preview opens
  - Company header, customer block, line items, totals all show
  - "Received by" signature line present

- [ ] **Step 3: Commit**

  ```bash
  git add app/sales_invoices/templates/
  git commit -m "feat: sales invoices print template"
  ```

---

## Task 18: Register `sv_print_access` setting + final smoke test

**Files:**
- No file change needed (AppSettings reads key-value rows dynamically)

- [ ] **Step 1: Verify `AppSettings.get_setting` fallback works**

  The `view()` route calls `AppSettings.get_setting('sv_print_access', 'posted_only')`. If the key doesn't exist, it returns the default. No DB seed needed — the fallback handles it.

- [ ] **Step 2: Run the full test suite**

  ```
  pytest tests/integration/test_sales_invoices.py -v
  ```

  All tests should pass.

- [ ] **Step 3: Run the full project test suite for regressions**

  ```
  pytest -m "not slow" -x
  ```

  Fix any failures before continuing.

- [ ] **Step 4: Manual smoke test in browser**

  1. Log in as `accountant` / `Acct@2024!`
  2. Go to `/sales-invoices` — list loads with summary cards
  3. Click "+ Enter Invoice" — form loads with Customer picker
  4. Select a customer, add a line item (amount ₱11,200, VAT category V12SV, a revenue account)
  5. Submit — detail page shows draft status, JE Preview visible
  6. Click Post — status changes to "posted", JE marked posted
  7. Click Print — print view opens
  8. Click Cancel — modal opens, enter reason + reversal date, confirm — status "cancelled"
  9. Go to `/sales-invoices` — invoice appears in list with correct balance

- [ ] **Step 5: Final commit**

  ```bash
  git add -A
  git commit -m "feat: sales invoices — complete Sales Voucher module"
  git push
  ```

---

## Regression Checklist

After all tasks are complete, verify these areas were not broken:

- [ ] AP Voucher list and create still work (`/purchase-bills`)
- [ ] VAT Categories form now shows Output Tax Account field
- [ ] Approving a VAT Category change request still saves `output_vat_account_id`
- [ ] AP Journal at `/journals/ap` still renders correctly
- [ ] Audit log at `/audit` shows `sales_invoice` entries
