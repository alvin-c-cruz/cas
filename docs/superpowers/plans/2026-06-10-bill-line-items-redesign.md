# Bill Line Items Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace qty×unit_cost line items with a single VAT-inclusive Amount, add pencil-click overrides for Input VAT and WHT, post a balanced purchase JE to the GL on save, and show a live JE preview on the form.

**Architecture:** Model rename/field additions → Alembic migration → view layer (parsing, override logic, `_post_bill_je`) → form template (new JS, JE preview, override UX) → detail template cleanup → test updates.

**Tech Stack:** Flask + SQLAlchemy + SQLite (Alembic batch_alter_table for column ops), WTForms, vanilla JS, Jinja2.

---

## Files Changed

| File | Change |
|------|--------|
| `app/purchase_bills/models.py` | Rename `unit_cost`→`amount`, drop `quantity`, add 3 fields, rewrite calc methods |
| `app/journal_entries/models.py` | Update `entry_type` docstring |
| `app/journal_entries/forms.py` | Add `'purchase'` choice to `entry_type` SelectField |
| `app/purchase_bills/views.py` | Parse `amount`, handle overrides, add `_post_bill_je`, fix `_create_reversal_je` |
| `app/purchase_bills/templates/purchase_bills/form.html` | New 5-col table, override UX, JE preview |
| `app/purchase_bills/templates/purchase_bills/detail.html` | Remove Qty/Unit Cost columns |
| `tests/integration/test_purchase_bill_views.py` | Keep existing; no line-item constructors affected |
| `tests/unit/test_purchase_bill_models.py` | New file — unit tests for new calc methods |
| `tests/integration/test_purchase_bill_je.py` | New file — JE posting integration tests |

---

## Task 1: Update Models

**Files:**
- Modify: `app/purchase_bills/models.py`
- Modify: `app/journal_entries/models.py`
- Modify: `app/journal_entries/forms.py`
- Create: `tests/unit/test_purchase_bill_models.py`

- [ ] **Step 1: Write failing unit tests**

Create `tests/unit/test_purchase_bill_models.py`:

```python
"""Unit tests for PurchaseBill and PurchaseBillItem model changes."""
import pytest
from decimal import Decimal
from app.purchase_bills.models import PurchaseBill, PurchaseBillItem


class TestPurchaseBillItemCalculateAmounts:
    """Tests for PurchaseBillItem.calculate_amounts() with new VAT-inclusive Amount field."""

    def _make_item(self, amount, vat_rate=Decimal('0'), wt_rate=None):
        item = PurchaseBillItem()
        item.amount = Decimal(str(amount))
        item.vat_rate = vat_rate
        item.wt_rate = Decimal(str(wt_rate)) if wt_rate is not None else None
        item.calculate_amounts()
        return item

    def test_zero_vat_amount_equals_line_total(self):
        item = self._make_item(amount='1000.00', vat_rate=Decimal('0'))
        assert item.line_total == Decimal('1000.00')
        assert item.vat_amount == Decimal('0.00')

    def test_twelve_percent_vat_extracts_correctly(self):
        # 11200 VAT-inclusive at 12%: net = 11200/1.12 = 10000; vat = 1200
        item = self._make_item(amount='11200.00', vat_rate=Decimal('12'))
        assert item.line_total == Decimal('11200.00')
        assert item.vat_amount == Decimal('1200.00')

    def test_line_total_equals_amount(self):
        item = self._make_item(amount='5000.00', vat_rate=Decimal('12'))
        assert item.line_total == item.amount

    def test_wht_computed_on_net_base(self):
        # 11200 at 12% VAT → net_base = 10000; WHT at 2% = 200
        item = self._make_item(amount='11200.00', vat_rate=Decimal('12'), wt_rate='2')
        assert item.wt_amount == Decimal('200.00')

    def test_wht_zero_when_no_rate(self):
        item = self._make_item(amount='5000.00', vat_rate=Decimal('0'), wt_rate=None)
        assert item.wt_amount == Decimal('0.00')

    def test_no_quantity_or_unit_cost_attributes(self):
        item = PurchaseBillItem()
        assert not hasattr(item, 'quantity')
        assert not hasattr(item, 'unit_cost')


class TestPurchaseBillCalculateTotals:
    """Tests for PurchaseBill.calculate_totals() with new VAT-inclusive design."""

    def _make_item(self, amount, vat_rate=Decimal('0'), wt_rate=None):
        item = PurchaseBillItem()
        item.amount = Decimal(str(amount))
        item.vat_rate = Decimal(str(vat_rate))
        item.wt_rate = Decimal(str(wt_rate)) if wt_rate is not None else None
        item.calculate_amounts()
        return item

    def test_subtotal_is_sum_of_vat_inclusive_amounts(self):
        bill = PurchaseBill()
        bill.amount_paid = Decimal('0.00')
        item1 = self._make_item('11200.00', vat_rate=Decimal('12'))
        item2 = self._make_item('2240.00', vat_rate=Decimal('12'))
        bill.line_items = [item1, item2]
        bill.calculate_totals()
        assert bill.subtotal == Decimal('13440.00')

    def test_vat_amount_extracted_not_added(self):
        bill = PurchaseBill()
        bill.amount_paid = Decimal('0.00')
        item = self._make_item('11200.00', vat_rate=Decimal('12'))
        bill.line_items = [item]
        bill.calculate_totals()
        # vat is extracted FROM the 11200, not added on top
        assert bill.vat_amount == Decimal('1200.00')
        assert bill.subtotal == Decimal('11200.00')
        assert bill.total_before_wt == Decimal('11200.00')  # equals subtotal, not subtotal+vat

    def test_total_amount_is_subtotal_minus_wht(self):
        bill = PurchaseBill()
        bill.amount_paid = Decimal('0.00')
        # 11200 at 12% VAT, 2% WHT: net_base=10000, wht=200, net_payable=11200-200=11000
        item = self._make_item('11200.00', vat_rate=Decimal('12'), wt_rate='2')
        bill.line_items = [item]
        bill.calculate_totals()
        assert bill.withholding_tax_amount == Decimal('200.00')
        assert bill.total_amount == Decimal('11000.00')

    def test_balance_equals_total_minus_amount_paid(self):
        bill = PurchaseBill()
        bill.amount_paid = Decimal('500.00')
        item = self._make_item('11200.00', vat_rate=Decimal('12'), wt_rate='2')
        bill.line_items = [item]
        bill.calculate_totals()
        assert bill.balance == Decimal('10500.00')


class TestPurchaseBillItemToDict:
    def test_to_dict_has_amount_not_quantity_or_unit_cost(self):
        item = PurchaseBillItem()
        item.id = 1
        item.line_number = 1
        item.description = 'Test'
        item.amount = Decimal('11200.00')
        item.vat_category = 'VAT12'
        item.vat_rate = Decimal('12')
        item.line_total = Decimal('11200.00')
        item.vat_amount = Decimal('1200.00')
        item.account_id = None
        item.wt_id = None
        item.wt_rate = None
        item.wt_amount = Decimal('0.00')
        d = item.to_dict()
        assert 'amount' in d
        assert 'quantity' not in d
        assert 'unit_cost' not in d
        assert d['amount'] == 11200.0
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/unit/test_purchase_bill_models.py -v
```

Expected: many failures — `amount` attribute doesn't exist, `quantity`/`unit_cost` still present, `calculate_amounts()` uses old formula.

- [ ] **Step 3: Update `PurchaseBillItem` in `app/purchase_bills/models.py`**

Replace the `PurchaseBillItem` class body. Change these lines:

```python
# REMOVE these two columns:
quantity = db.Column(db.Numeric(15, 4), default=1.0000, nullable=False)
unit_cost = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)

# ADD this column in their place:
amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
```

Rewrite `calculate_amounts()`:

```python
def calculate_amounts(self):
    """Calculate line total, extracted VAT, and WHT on net base."""
    vat_rate = Decimal(str(self.vat_rate)) if self.vat_rate else Decimal('0')
    if vat_rate > 0:
        net_base = Decimal(str(self.amount)) / (1 + vat_rate / Decimal('100'))
    else:
        net_base = Decimal(str(self.amount))
    self.line_total = Decimal(str(self.amount))
    self.vat_amount = round(Decimal(str(self.amount)) - net_base, 2)
    wt_rate = Decimal(str(self.wt_rate)) if self.wt_rate else Decimal('0')
    self.wt_amount = round(net_base * wt_rate / Decimal('100'), 2)
```

Update `to_dict()` — replace the `quantity` and `unit_cost` keys:

```python
def to_dict(self):
    """Convert line item to dictionary."""
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

- [ ] **Step 4: Update `PurchaseBill` in `app/purchase_bills/models.py`**

After the `withholding_tax_rate` field (around line 68), add:

```python
# Override flags — when True, vat_amount / withholding_tax_amount were manually set
vat_override = db.Column(db.Boolean, default=False, nullable=False)
wt_override = db.Column(db.Boolean, default=False, nullable=False)

# Linked journal entry (posted on save; recreated on edit)
journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'), nullable=True)
journal_entry = db.relationship('JournalEntry', foreign_keys=[journal_entry_id])
```

Rewrite `calculate_totals()`:

```python
def calculate_totals(self):
    """Compute bill totals from VAT-inclusive line amounts."""
    self.subtotal = Decimal('0.00')
    auto_vat = Decimal('0.00')
    auto_wt = Decimal('0.00')

    for item in self.line_items:
        self.subtotal += item.line_total
        auto_vat += item.vat_amount
        auto_wt += (item.wt_amount or Decimal('0.00'))

    self.vat_amount = auto_vat
    self.withholding_tax_amount = auto_wt
    self.total_before_wt = self.subtotal   # VAT is extracted from subtotal, not added
    self.total_amount = self.subtotal - self.withholding_tax_amount
    self.balance = self.total_amount - self.amount_paid
```

- [ ] **Step 5: Add `'purchase'` to `entry_type` choices in `app/journal_entries/forms.py`**

In `forms.py`, add `('purchase', 'Purchase Bill')` to the `entry_type` choices list:

```python
entry_type = SelectField('Entry Type', choices=[
    ('adjustment', 'Adjustment'),
    ('closing', 'Closing Entry'),
    ('opening', 'Opening Entry'),
    ('purchase', 'Purchase Bill'),
    ('reversal', 'Reversal'),
    ('reclassification', 'Reclassification')
], default='adjustment')
```

Also update the comment on line 39 of `app/journal_entries/models.py` to include `'purchase'`:

```python
# Entry type: 'adjustment', 'closing', 'opening', 'purchase', 'reversal', 'reclassification'
```

- [ ] **Step 6: Run tests to verify they pass**

```
pytest tests/unit/test_purchase_bill_models.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```
git add app/purchase_bills/models.py app/journal_entries/models.py app/journal_entries/forms.py tests/unit/test_purchase_bill_models.py
git commit -m "feat: rename unit_cost->amount, drop quantity, add override fields and JE FK to PurchaseBill"
```

---

## Task 2: Database Migration

**Files:**
- Create: `migrations/versions/<hash>_bill_line_items_redesign.py`

- [ ] **Step 1: Generate migration skeleton**

```
flask db migrate -m "bill line items redesign - amount field, override flags, je fk"
```

- [ ] **Step 2: Review the generated migration file**

Open the new file in `migrations/versions/`. Alembic may not auto-detect a column rename (it often sees it as drop+add). The migration must use `batch_alter_table` (required for SQLite). Verify it contains the following operations — edit manually if needed:

```python
def upgrade():
    with op.batch_alter_table('purchase_bill_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('amount', sa.Numeric(precision=15, scale=2),
                                      nullable=False, server_default='0.00'))
        batch_op.drop_column('quantity')
        batch_op.drop_column('unit_cost')

    with op.batch_alter_table('purchase_bills', schema=None) as batch_op:
        batch_op.add_column(sa.Column('vat_override', sa.Boolean(),
                                      nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('wt_override', sa.Boolean(),
                                      nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('journal_entry_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_purchase_bills_je', 'journal_entries',
                                    ['journal_entry_id'], ['id'])


def downgrade():
    with op.batch_alter_table('purchase_bills', schema=None) as batch_op:
        batch_op.drop_constraint('fk_purchase_bills_je', type_='foreignkey')
        batch_op.drop_column('journal_entry_id')
        batch_op.drop_column('wt_override')
        batch_op.drop_column('vat_override')

    with op.batch_alter_table('purchase_bill_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('unit_cost', sa.Numeric(precision=15, scale=2),
                                      nullable=False, server_default='0.00'))
        batch_op.add_column(sa.Column('quantity', sa.Numeric(precision=15, scale=4),
                                      nullable=False, server_default='1.0000'))
        batch_op.drop_column('amount')
```

Note: `server_default` is required for `NOT NULL` columns added to existing tables.

- [ ] **Step 3: Run migration**

```
flask db upgrade
```

Expected: no errors. Confirm with:

```
flask shell -c "from app import db; from app.purchase_bills.models import PurchaseBillItem; print([c.name for c in PurchaseBillItem.__table__.columns])"
```

Expected output includes `amount` and excludes `quantity`, `unit_cost`.

- [ ] **Step 4: Run existing tests to confirm no regressions**

```
pytest tests/unit/test_purchase_bill_models.py tests/integration/test_purchase_bill_views.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```
git add migrations/
git commit -m "feat: migration — rename unit_cost->amount, drop quantity, add override flags and je_fk to purchase_bills"
```

---

## Task 3: Update Views

**Files:**
- Modify: `app/purchase_bills/views.py`
- Create: `tests/integration/test_purchase_bill_je.py`

- [ ] **Step 1: Write failing integration tests for JE creation**

Create `tests/integration/test_purchase_bill_je.py`:

```python
"""Integration tests — purchase JE auto-posted on bill create/edit."""
import json
import pytest
from decimal import Decimal
from datetime import date
from app.purchase_bills.models import PurchaseBill, PurchaseBillItem
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.vendors.models import Vendor
from app.accounts.models import Account
from app.vat_categories.models import VATCategory
from app.withholding_tax.models import WithholdingTax


def login(client, username='accountant', password='acct123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def make_vendor(db_session):
    v = Vendor(code='JEV001', name='JE Test Vendor', check_payee_name='JE Test Vendor',
               is_active=True, payment_terms='Net 30')
    db_session.add(v)
    db_session.commit()
    return v


def get_or_create_account(db_session, code, name, acct_type):
    a = Account.query.filter_by(code=code).first()
    if not a:
        # Find a parent or create root-level
        a = Account(code=code, name=name, account_type=acct_type,
                    normal_balance='debit' if acct_type == 'Expense' else 'credit',
                    is_active=True)
        db_session.add(a)
        db_session.commit()
    return a


def make_line_items_payload(amount=11200.00, vat_code='VAT12', account_id=None,
                             wt_id=None, wt_rate=None):
    return json.dumps([{
        'description': 'Test Service',
        'amount': amount,
        'vat_category': vat_code,
        'account_id': account_id,
        'wt_id': wt_id,
        'wt_rate': wt_rate,
    }])


class TestBillCreatePostsJE:
    def test_create_bill_posts_je_with_purchase_type(
            self, client, db_session, accountant_user, main_branch):
        login(client)
        vendor = make_vendor(db_session)

        # Ensure required GL accounts exist
        ap = get_or_create_account(db_session, '20101', 'Accounts Payable - Trade', 'Liability')
        vat_acct = get_or_create_account(db_session, '10501', 'Input VAT - Current', 'Asset')
        exp = get_or_create_account(db_session, '61001', 'Rent Expense', 'Expense')

        vat_cat = VATCategory(code='VAT12', name='VAT 12%', rate=Decimal('12'), is_active=True)
        db_session.add(vat_cat)
        db_session.commit()

        resp = client.post('/purchase-bills/create', data={
            'csrf_token': 'test',
            'bill_number': 'PBJ-001',
            'bill_date': date.today().isoformat(),
            'due_date': date.today().isoformat(),
            'vendor_id': vendor.id,
            'payment_terms': 'Net 30',
            'line_items': make_line_items_payload(
                amount=11200.00, vat_code='VAT12', account_id=exp.id),
            'vat_override': '0',
            'vat_override_value': '0',
            'wt_override': '0',
            'wt_override_value': '0',
        }, follow_redirects=True)

        assert resp.status_code == 200

        bill = PurchaseBill.query.filter_by(bill_number='PBJ-001').first()
        assert bill is not None
        assert bill.journal_entry_id is not None

        je = JournalEntry.query.get(bill.journal_entry_id)
        assert je is not None
        assert je.entry_type == 'purchase'
        assert je.status == 'posted'
        assert je.is_balanced is True

    def test_je_lines_correct_for_12pct_vat(
            self, client, db_session, accountant_user, main_branch):
        login(client)
        vendor = make_vendor(db_session)

        ap = get_or_create_account(db_session, '20101', 'Accounts Payable - Trade', 'Liability')
        vat_acct = get_or_create_account(db_session, '10501', 'Input VAT - Current', 'Asset')
        exp = get_or_create_account(db_session, '61001', 'Rent Expense', 'Expense')

        vat_cat = VATCategory(code='VAT12B', name='VAT 12%', rate=Decimal('12'), is_active=True)
        db_session.add(vat_cat)
        db_session.commit()

        client.post('/purchase-bills/create', data={
            'csrf_token': 'test',
            'bill_number': 'PBJ-002',
            'bill_date': date.today().isoformat(),
            'due_date': date.today().isoformat(),
            'vendor_id': vendor.id,
            'payment_terms': 'Net 30',
            'line_items': make_line_items_payload(
                amount=11200.00, vat_code='VAT12B', account_id=exp.id),
            'vat_override': '0',
            'vat_override_value': '0',
            'wt_override': '0',
            'wt_override_value': '0',
        }, follow_redirects=True)

        bill = PurchaseBill.query.filter_by(bill_number='PBJ-002').first()
        je = JournalEntry.query.get(bill.journal_entry_id)
        lines = JournalEntryLine.query.filter_by(entry_id=je.id).all()

        # Dr Expense (net_base = 11200/1.12 = 10000)
        exp_line = next(l for l in lines if l.account_id == exp.id)
        assert exp_line.debit_amount == Decimal('10000.00')

        # Dr Input VAT (1200)
        vat_line = next(l for l in lines if l.account_id == vat_acct.id)
        assert vat_line.debit_amount == Decimal('1200.00')

        # Cr AP (11200 — no WHT)
        ap_line = next(l for l in lines if l.account_id == ap.id)
        assert ap_line.credit_amount == Decimal('11200.00')

        # JE balances
        total_dr = sum(l.debit_amount for l in lines)
        total_cr = sum(l.credit_amount for l in lines)
        assert total_dr == total_cr

    def test_edit_bill_recreates_je(
            self, client, db_session, accountant_user, main_branch):
        """Editing a bill deletes the old JE and creates a new one."""
        login(client)
        vendor = make_vendor(db_session)
        ap = get_or_create_account(db_session, '20101', 'Accounts Payable - Trade', 'Liability')
        exp = get_or_create_account(db_session, '61001', 'Rent Expense', 'Expense')

        # Create the bill
        client.post('/purchase-bills/create', data={
            'csrf_token': 'test',
            'bill_number': 'PBJ-003',
            'bill_date': date.today().isoformat(),
            'due_date': date.today().isoformat(),
            'vendor_id': vendor.id,
            'payment_terms': 'Net 30',
            'line_items': make_line_items_payload(
                amount=5000.00, vat_code='', account_id=exp.id),
            'vat_override': '0', 'vat_override_value': '0',
            'wt_override': '0', 'wt_override_value': '0',
        }, follow_redirects=True)

        bill = PurchaseBill.query.filter_by(bill_number='PBJ-003').first()
        old_je_id = bill.journal_entry_id
        assert old_je_id is not None

        # Edit the bill
        client.post(f'/purchase-bills/{bill.id}/edit', data={
            'csrf_token': 'test',
            'bill_number': 'PBJ-003',
            'bill_date': date.today().isoformat(),
            'due_date': date.today().isoformat(),
            'vendor_id': vendor.id,
            'payment_terms': 'Net 30',
            'line_items': make_line_items_payload(
                amount=6000.00, vat_code='', account_id=exp.id),
            'vat_override': '0', 'vat_override_value': '0',
            'wt_override': '0', 'wt_override_value': '0',
        }, follow_redirects=True)

        db_session.expire_all()
        bill = PurchaseBill.query.filter_by(bill_number='PBJ-003').first()
        assert bill.journal_entry_id != old_je_id
        assert JournalEntry.query.get(old_je_id) is None  # old JE deleted

        new_je = JournalEntry.query.get(bill.journal_entry_id)
        ap_line = next(l for l in new_je.lines if l.account_id == ap.id)
        assert ap_line.credit_amount == Decimal('6000.00')
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/integration/test_purchase_bill_je.py -v
```

Expected: failures — JE not created, `vat_override` field doesn't exist on model, etc.

- [ ] **Step 3: Add `_post_bill_je()` helper to `app/purchase_bills/views.py`**

Add this function above `_create_reversal_je` (around line 599):

```python
def _post_bill_je(bill, user_id):
    """Create and immediately post a purchase JE for a bill. Raises ValueError if required accounts missing."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine

    ap_account = Account.query.filter_by(code='20101').first()
    if not ap_account:
        raise ValueError("Accounts Payable - Trade (20101) not found in COA.")

    input_vat_account = None
    if bill.vat_amount and bill.vat_amount > 0:
        input_vat_account = Account.query.filter_by(code='10501').first()
        if not input_vat_account:
            raise ValueError("Input VAT - Current (10501) not found in COA.")

    wt_account = None
    if bill.withholding_tax_amount and bill.withholding_tax_amount > 0:
        wt_account = Account.query.filter_by(code='20301').first()
        if not wt_account:
            raise ValueError("WHT Payable - Expanded (20301) not found in COA.")

    entry_number = generate_entry_number(bill.branch_id)
    je = JournalEntry(
        entry_number=entry_number,
        entry_date=bill.bill_date,
        description=f'Purchase Bill {bill.bill_number} — {bill.vendor_name}',
        reference=bill.bill_number,
        entry_type='purchase',
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

    # Compute VAT adjustment for override case
    vat_auto = sum((item.vat_amount for item in bill.line_items), Decimal('0.00'))
    vat_used = Decimal(str(bill.vat_amount))
    vat_diff = vat_used - vat_auto  # non-zero only when VAT was overridden

    line_num = 1
    first_expense_line = None

    for item in bill.line_items:
        if not item.account_id:
            continue
        net_base = Decimal(str(item.line_total)) - Decimal(str(item.vat_amount))
        entry_line = JournalEntryLine(
            entry_id=je.id,
            line_number=line_num,
            account_id=item.account_id,
            description=item.description or '',
            debit_amount=net_base,
            credit_amount=Decimal('0.00')
        )
        db.session.add(entry_line)
        if first_expense_line is None:
            first_expense_line = entry_line
        line_num += 1

    # Absorb any VAT override rounding difference into the first expense line
    if first_expense_line is not None and vat_diff != Decimal('0.00'):
        first_expense_line.debit_amount -= vat_diff

    if input_vat_account:
        db.session.add(JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=input_vat_account.id,
            description=f'Input VAT: {bill.bill_number}',
            debit_amount=vat_used,
            credit_amount=Decimal('0.00')
        ))
        line_num += 1

    if wt_account:
        db.session.add(JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=wt_account.id,
            description=f'WHT Payable: {bill.bill_number}',
            debit_amount=Decimal('0.00'),
            credit_amount=Decimal(str(bill.withholding_tax_amount))
        ))
        line_num += 1

    db.session.add(JournalEntryLine(
        entry_id=je.id, line_number=line_num,
        account_id=ap_account.id,
        description=f'AP: {bill.bill_number} — {bill.vendor_name}',
        debit_amount=Decimal('0.00'),
        credit_amount=Decimal(str(bill.total_amount))
    ))

    je.calculate_totals()
    return je
```

- [ ] **Step 4: Update `_create_reversal_je()` — fix expense credit amounts**

The reversal must credit `net_base` (not VAT-inclusive `line_total`) for expense accounts to balance. In `_create_reversal_je`, find the loop that credits expense lines (around line 660):

```python
# BEFORE:
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

# AFTER — credit net_base = line_total - vat_amount:
vat_auto = sum(
    (Decimal(str(item.vat_amount)) for item in bill.line_items if item.account_id),
    Decimal('0.00')
)
vat_diff = Decimal(str(bill.vat_amount)) - vat_auto
first_expense_reversal = None
for item in bill.line_items:
    if item.account_id and item.line_total > 0:
        net_base = Decimal(str(item.line_total)) - Decimal(str(item.vat_amount))
        entry_line = JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=item.account_id,
            description=item.description,
            debit_amount=Decimal('0.00'),
            credit_amount=net_base
        )
        db.session.add(entry_line)
        if first_expense_reversal is None:
            first_expense_reversal = entry_line
        line_num += 1
if first_expense_reversal is not None and vat_diff != Decimal('0.00'):
    first_expense_reversal.credit_amount -= vat_diff
```

- [ ] **Step 5: Update `create` view — line item parsing and JE posting**

In the `create` view, around line 327, replace:

```python
# REMOVE:
line_item = PurchaseBillItem(
    line_number=idx,
    description=item_data.get('description', ''),
    quantity=Decimal(str(item_data.get('quantity', 1))),
    unit_cost=Decimal(str(item_data.get('unit_cost', 0))),
    vat_category=vat_category,
    vat_rate=vat_rate,
    account_id=int(item_data.get('account_id')) if item_data.get('account_id') else None,
    wt_id=wt_id,
    wt_rate=wt_rate,
)
```

Replace with:

```python
line_item = PurchaseBillItem(
    line_number=idx,
    description=item_data.get('description', ''),
    amount=Decimal(str(item_data.get('amount', 0))),
    vat_category=vat_category,
    vat_rate=vat_rate,
    account_id=int(item_data.get('account_id')) if item_data.get('account_id') else None,
    wt_id=wt_id,
    wt_rate=wt_rate,
)
```

After `bill.calculate_totals()` (around line 341), add override logic and JE posting:

```python
bill.calculate_totals()

# Apply manual overrides
vat_override = request.form.get('vat_override') == '1'
wt_override = request.form.get('wt_override') == '1'
bill.vat_override = vat_override
bill.wt_override = wt_override
if vat_override:
    bill.vat_amount = Decimal(request.form.get('vat_override_value', '0') or '0')
if wt_override:
    bill.withholding_tax_amount = Decimal(request.form.get('wt_override_value', '0') or '0')
# Recompute net payable after potential overrides
bill.total_amount = bill.subtotal - bill.withholding_tax_amount
bill.balance = bill.total_amount - bill.amount_paid

db.session.add(bill)
db.session.flush()  # get bill.id before creating JE

je = _post_bill_je(bill, current_user.id)
bill.journal_entry_id = je.id
db.session.commit()
```

Remove the original `db.session.add(bill)` / `db.session.commit()` that was there before.

Also add `gl_accounts` to the `render_template` call at the bottom of the create view:

```python
ap_account = Account.query.filter_by(code='20101').first()
input_vat_account = Account.query.filter_by(code='10501').first()
wt_gl_account = Account.query.filter_by(code='20301').first()
gl_accounts = {
    'ap': {'code': ap_account.code, 'name': ap_account.name} if ap_account else None,
    'input_vat': {'code': input_vat_account.code, 'name': input_vat_account.name} if input_vat_account else None,
    'wt': {'code': wt_gl_account.code, 'name': wt_gl_account.name} if wt_gl_account else None,
}
return render_template('purchase_bills/form.html',
                       form=form,
                       bill=None,
                       vat_categories=vat_categories,
                       expense_accounts=expense_accounts,
                       gl_accounts=gl_accounts)
```

- [ ] **Step 6: Update `edit` view — same changes plus JE delete/recreate**

In the edit view, around line 451, apply the same `quantity`/`unit_cost` → `amount` change to the `PurchaseBillItem` constructor.

After `bill.calculate_totals()` (around line 466), add override logic and JE recreation:

```python
bill.calculate_totals()

# Apply manual overrides
vat_override = request.form.get('vat_override') == '1'
wt_override = request.form.get('wt_override') == '1'
bill.vat_override = vat_override
bill.wt_override = wt_override
if vat_override:
    bill.vat_amount = Decimal(request.form.get('vat_override_value', '0') or '0')
if wt_override:
    bill.withholding_tax_amount = Decimal(request.form.get('wt_override_value', '0') or '0')
bill.total_amount = bill.subtotal - bill.withholding_tax_amount
bill.balance = bill.total_amount - bill.amount_paid

# Delete old JE and create a fresh one
if bill.journal_entry_id:
    from app.journal_entries.models import JournalEntry as _JE
    old_je = db.session.get(_JE, bill.journal_entry_id)
    if old_je:
        db.session.delete(old_je)
    bill.journal_entry_id = None

db.session.flush()

je = _post_bill_je(bill, current_user.id)
bill.journal_entry_id = je.id
db.session.commit()
```

Replace the original `db.session.commit()`.

Also add `gl_accounts` to the `render_template` call at the bottom of the edit view (same snippet as create view).

- [ ] **Step 7: Run JE integration tests**

```
pytest tests/integration/test_purchase_bill_je.py -v
```

Expected: all pass.

- [ ] **Step 8: Run full test suite to check for regressions**

```
pytest -v --tb=short
```

Expected: all existing tests pass.

- [ ] **Step 9: Commit**

```
git add app/purchase_bills/views.py tests/integration/test_purchase_bill_je.py
git commit -m "feat: add _post_bill_je, parse amount field, handle vat/wt overrides, fix reversal JE expense credits"
```

---

## Task 4: Update Form Template

**Files:**
- Modify: `app/purchase_bills/templates/purchase_bills/form.html`

- [ ] **Step 1: Update table header — 5 columns**

Find the `<thead>` inside `#lineItemsTable` (around line 74) and replace:

```html
<!-- BEFORE: -->
<tr>
    <th style="width: 30%;">Description</th>
    <th style="width: 8%; text-align: right;">Qty</th>
    <th style="width: 12%; text-align: right;">Unit Cost</th>
    <th style="width: 12%;">VAT Category</th>
    <th style="width: 18%;">WHT</th>
    <th style="width: 15%;">Expense Account</th>
    <th style="width: 5%;"></th>
</tr>

<!-- AFTER: -->
<tr>
    <th style="width: 32%;">Description</th>
    <th style="width: 14%; text-align: right;">Amount (VAT-incl.)</th>
    <th style="width: 12%;">VT</th>
    <th style="width: 18%;">WT</th>
    <th style="width: 19%;">Account Title</th>
    <th style="width: 5%;"></th>
</tr>
```

- [ ] **Step 2: Add override hidden fields before `</form>`**

Add these four hidden inputs inside the `<form>` tag, just before the closing `</form>`:

```html
<input type="hidden" name="vat_override" id="vatOverrideFlag" value="0">
<input type="hidden" name="vat_override_value" id="vatOverrideValue" value="0">
<input type="hidden" name="wt_override" id="wtOverrideFlag" value="0">
<input type="hidden" name="wt_override_value" id="wtOverrideValue" value="0">
```

- [ ] **Step 3: Replace the totals panel + add JE preview section**

Find the `<!-- ⑤ Totals Panel -->` div (around line 92) and replace the entire block from `<div style="display: flex; justify-content: flex-end; margin-top: 24px;">` through its closing `</div></div>` with:

```html
<!-- ⑤ Bottom: JE Preview (left) + Totals Panel (right) -->
<div style="display: grid; grid-template-columns: 1fr auto; gap: 24px; margin-top: 24px; align-items: start;">

    <!-- JE Preview -->
    <div id="jePreviewSection">
        <div style="font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; color: var(--text-2); margin-bottom: 10px;">Journal Entry Preview</div>
        <table class="table" style="font-size: 12px;" id="jePreviewTable">
            <thead>
                <tr>
                    <th style="width: 14%; color: var(--text-2);">Code</th>
                    <th>Account Title</th>
                    <th style="text-align: right; width: 18%;">Debit</th>
                    <th style="text-align: right; width: 18%;">Credit</th>
                </tr>
            </thead>
            <tbody id="jePreviewBody"></tbody>
            <tfoot id="jePreviewFoot"></tfoot>
        </table>
        <p style="font-size: 11px; color: var(--text-2); margin-top: 6px;">JE will be posted to the general ledger on save.</p>
    </div>

    <!-- Totals Panel -->
    <div style="background: var(--bg); padding: 20px; border-radius: 6px; min-width: 320px;">
        <div style="display: flex; justify-content: space-between; margin-bottom: 12px;">
            <span style="color: var(--text-2);">Subtotal:</span>
            <span id="subtotalDisplay" style="font-family: var(--mono); font-weight: 600;">₱0.00</span>
        </div>

        <!-- Input VAT — pencil-click override -->
        <div style="margin-bottom: 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="color: var(--text-2);">Input VAT:</span>
                <div id="vatDisplayMode" style="display: flex; align-items: center; gap: 6px;">
                    <span id="vatDisplay" style="font-family: var(--mono); font-weight: 600;">₱0.00</span>
                    <button type="button" class="totals-pencil" onclick="startVatOverride()" title="Click to override">✏️</button>
                </div>
                <div id="vatEditMode" style="display: none; flex-direction: column; align-items: flex-end;">
                    <div style="display: flex; align-items: center; gap: 6px;">
                        <input type="number" id="vatOverrideInput" step="0.01" min="0"
                               style="width: 110px; text-align: right; font-family: var(--mono); border: 1px solid var(--blue); border-radius: 4px; padding: 3px 7px;"
                               oninput="onVatOverrideInput(this.value)">
                        <button type="button" class="totals-revert" onclick="revertVatOverride()" title="Revert to auto">↺</button>
                    </div>
                    <div id="vatAutoHint" style="font-size: 11px; color: var(--text-2); margin-top: 2px;"></div>
                </div>
            </div>
        </div>

        <div style="margin-bottom: 12px; padding-top: 8px; border-top: 1px solid var(--border);">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="color: var(--text-2);">Withholding Tax:</span>
                <div id="wtDisplayMode" style="display: flex; align-items: center; gap: 6px;">
                    <span id="wtDisplay" style="font-family: var(--mono); font-weight: 600; color: var(--red);">-₱0.00</span>
                    <button type="button" class="totals-pencil" onclick="startWtOverride()" title="Click to override">✏️</button>
                </div>
                <div id="wtEditMode" style="display: none; flex-direction: column; align-items: flex-end;">
                    <div style="display: flex; align-items: center; gap: 6px;">
                        <input type="number" id="wtOverrideInput" step="0.01" min="0"
                               style="width: 110px; text-align: right; font-family: var(--mono); border: 1px solid var(--blue); border-radius: 4px; padding: 3px 7px;"
                               oninput="onWtOverrideInput(this.value)">
                        <button type="button" class="totals-revert" onclick="revertWtOverride()" title="Revert to auto">↺</button>
                    </div>
                    <div id="wtAutoHint" style="font-size: 11px; color: var(--text-2); margin-top: 2px;"></div>
                </div>
            </div>
        </div>

        <div style="display: flex; justify-content: space-between; padding-top: 12px; border-top: 2px solid var(--border);">
            <span style="font-size: 16px; font-weight: 700;">Net Payable:</span>
            <span id="totalDisplay" style="font-family: var(--mono); font-size: 18px; font-weight: 700; color: var(--blue);">₱0.00</span>
        </div>
    </div>

</div>
```

- [ ] **Step 4: Rewrite the `<script>` block — JS variables and helpers**

In the `<script>` block, update global variable declarations and helper functions. Replace from `const vatCategories = ...` through `let lineCounter = 0;`:

```javascript
const vatCategories = {{ vat_categories | tojson }};
const expenseAccounts = {{ expense_accounts | tojson }};
const glAccounts = {{ gl_accounts | tojson }};

let currentVendorWHTs = [];
let currentVendorVatCategory = '';
let currentVendorName = '';
let lineItems = [];
let lineCounter = 0;
let autoVat = 0;
let autoWt = 0;
let vatOverrideActive = false;
let wtOverrideActive = false;

const fmt = n => '₱' + n.toLocaleString('en-PH', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtNum = n => n > 0
    ? n.toLocaleString('en-PH', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : '—';
```

- [ ] **Step 5: Replace `addLineItem()` — use `amount` not `quantity`/`unit_cost`**

Replace the entire `addLineItem` function:

```javascript
function addLineItem(existingItem) {
    lineCounter++;
    const id = lineCounter;
    const autoWht = currentVendorWHTs.length === 1 ? currentVendorWHTs[0] : null;
    const item = existingItem
        ? { ...existingItem, id }
        : {
            id,
            description: '',
            amount: 0.00,
            vat_category: currentVendorVatCategory || '',
            account_id: null,
            wt_id: autoWht ? autoWht.id : null,
            wt_rate: autoWht ? autoWht.rate : null,
          };

    const row = document.createElement('tr');
    row.id = `line-${id}`;
    row.innerHTML = `
        <td><input type="text" class="form-control" value="${(item.description || '').replace(/"/g, '&quot;')}"
                   onchange="updateLineItem(${id}, 'description', this.value)"></td>
        <td><input type="number" class="form-control" value="${item.amount || 0}" step="0.01" min="0"
                   style="text-align:right;" onchange="updateLineItem(${id}, 'amount', parseFloat(this.value)||0)"></td>
        <td>
            <select class="form-control vat-select" onchange="updateLineItem(${id}, 'vat_category', this.value)">
                <option value="">No VAT</option>
                ${vatCategories.map(v => `<option value="${v.code}" ${item.vat_category === v.code ? 'selected' : ''}>${v.code} (${v.rate}%)</option>`).join('')}
            </select>
        </td>
        <td>
            <select class="form-control wht-select" onchange="updateWht(${id}, this)">
                ${buildWhtOptions(item.wt_id)}
            </select>
        </td>
        <td>
            <select class="form-control" onchange="updateLineItem(${id}, 'account_id', parseInt(this.value)||null)">
                <option value="">Select Account</option>
                ${expenseAccounts.map(a => `<option value="${a.id}" ${item.account_id === a.id ? 'selected' : ''}>${a.code} - ${a.name}</option>`).join('')}
            </select>
        </td>
        <td><button type="button" class="btn-action" onclick="removeLineItem(${id})" title="Remove">🗑️</button></td>
    `;
    document.getElementById('lineItemsBody').appendChild(row);
    lineItems.push(item);
    calculateTotals();
}
```

- [ ] **Step 6: Replace `updateLineItem()` — reset overrides on relevant field changes**

```javascript
function updateLineItem(id, field, value) {
    const item = lineItems.find(i => i.id === id);
    if (!item) return;
    item[field] = value;
    // Reset VAT override when line amount or VAT category changes
    if (['amount', 'vat_category'].includes(field)) revertVatOverride();
    calculateTotals();
}
```

- [ ] **Step 7: Replace `calculateTotals()` — new VAT-inclusive formula**

```javascript
function calculateTotals() {
    let subtotal = 0;
    autoVat = 0;
    autoWt = 0;

    lineItems.forEach(item => {
        const amt = item.amount || 0;
        subtotal += amt;
        const vat = vatCategories.find(v => v.code === item.vat_category);
        const vatRate = vat ? vat.rate : 0;
        if (vatRate > 0) {
            const netBase = amt / (1 + vatRate / 100);
            autoVat += amt - netBase;
            if (item.wt_rate) autoWt += netBase * (item.wt_rate / 100);
        } else {
            if (item.wt_rate) autoWt += amt * (item.wt_rate / 100);
        }
    });

    // Round auto values to 2dp
    autoVat = Math.round(autoVat * 100) / 100;
    autoWt = Math.round(autoWt * 100) / 100;

    const vatUsed = vatOverrideActive
        ? (parseFloat(document.getElementById('vatOverrideInput').value) || 0)
        : autoVat;
    const wtUsed = wtOverrideActive
        ? (parseFloat(document.getElementById('wtOverrideInput').value) || 0)
        : autoWt;
    const netPayable = subtotal - wtUsed;

    document.getElementById('subtotalDisplay').textContent = fmt(subtotal);

    if (!vatOverrideActive) {
        document.getElementById('vatDisplay').textContent = fmt(autoVat);
    }
    if (!wtOverrideActive) {
        document.getElementById('wtDisplay').textContent = '-' + fmt(autoWt);
    }
    document.getElementById('totalDisplay').textContent = fmt(netPayable);

    renderJEPreview(subtotal, vatUsed, wtUsed);
}
```

- [ ] **Step 8: Add override UX functions**

Add these functions after `calculateTotals()`:

```javascript
function startVatOverride() {
    vatOverrideActive = true;
    const input = document.getElementById('vatOverrideInput');
    input.value = autoVat.toFixed(2);
    document.getElementById('vatAutoHint').textContent = 'auto: ' + fmt(autoVat);
    document.getElementById('vatDisplayMode').style.display = 'none';
    document.getElementById('vatEditMode').style.display = 'flex';
    document.getElementById('vatOverrideFlag').value = '1';
    document.getElementById('vatOverrideValue').value = autoVat.toFixed(2);
    input.focus();
    input.select();
    calculateTotals();
}

function onVatOverrideInput(val) {
    const v = parseFloat(val) || 0;
    document.getElementById('vatOverrideFlag').value = '1';
    document.getElementById('vatOverrideValue').value = v.toFixed(2);
    document.getElementById('vatDisplay').textContent = fmt(v);
    calculateTotals();
}

function revertVatOverride() {
    vatOverrideActive = false;
    document.getElementById('vatOverrideFlag').value = '0';
    document.getElementById('vatOverrideValue').value = '0';
    document.getElementById('vatDisplayMode').style.display = 'flex';
    document.getElementById('vatEditMode').style.display = 'none';
    document.getElementById('vatDisplay').textContent = fmt(autoVat);
    calculateTotals();
}

function startWtOverride() {
    wtOverrideActive = true;
    const input = document.getElementById('wtOverrideInput');
    input.value = autoWt.toFixed(2);
    document.getElementById('wtAutoHint').textContent = 'auto: ' + fmt(autoWt);
    document.getElementById('wtDisplayMode').style.display = 'none';
    document.getElementById('wtEditMode').style.display = 'flex';
    document.getElementById('wtOverrideFlag').value = '1';
    document.getElementById('wtOverrideValue').value = autoWt.toFixed(2);
    input.focus();
    input.select();
    calculateTotals();
}

function onWtOverrideInput(val) {
    const v = parseFloat(val) || 0;
    document.getElementById('wtOverrideFlag').value = '1';
    document.getElementById('wtOverrideValue').value = v.toFixed(2);
    document.getElementById('wtDisplay').textContent = '-' + fmt(v);
    calculateTotals();
}

function revertWtOverride() {
    wtOverrideActive = false;
    document.getElementById('wtOverrideFlag').value = '0';
    document.getElementById('wtOverrideValue').value = '0';
    document.getElementById('wtDisplayMode').style.display = 'flex';
    document.getElementById('wtEditMode').style.display = 'none';
    document.getElementById('wtDisplay').textContent = '-' + fmt(autoWt);
    calculateTotals();
}
```

- [ ] **Step 9: Add `renderJEPreview()` function**

```javascript
function renderJEPreview(subtotal, vatUsed, wtUsed) {
    const rows = [];
    let firstExpenseIdx = -1;

    lineItems.forEach(item => {
        if (!item.account_id) return;
        const acct = expenseAccounts.find(a => a.id === item.account_id);
        const vat = vatCategories.find(v => v.code === item.vat_category);
        const vatRate = vat ? vat.rate : 0;
        const amt = item.amount || 0;
        const netBase = vatRate > 0 ? amt / (1 + vatRate / 100) : amt;
        if (firstExpenseIdx === -1) firstExpenseIdx = rows.length;
        rows.push({
            code: acct ? acct.code : '—',
            name: item.description || (acct ? acct.name : '—'),
            debit: netBase,
            credit: 0
        });
    });

    // Absorb VAT override diff into first expense line
    if (firstExpenseIdx >= 0) {
        const vatAuto = lineItems.reduce((s, item) => {
            const vat = vatCategories.find(v => v.code === item.vat_category);
            const vatRate = vat ? vat.rate : 0;
            const amt = item.amount || 0;
            return s + (vatRate > 0 ? amt - amt / (1 + vatRate / 100) : 0);
        }, 0);
        rows[firstExpenseIdx].debit -= (vatUsed - vatAuto);
    }

    if (vatUsed > 0 && glAccounts && glAccounts.input_vat) {
        rows.push({ code: glAccounts.input_vat.code, name: glAccounts.input_vat.name, debit: vatUsed, credit: 0 });
    }
    if (wtUsed > 0 && glAccounts && glAccounts.wt) {
        rows.push({ code: glAccounts.wt.code, name: glAccounts.wt.name, debit: 0, credit: wtUsed });
    }
    const netPayable = subtotal - wtUsed;
    if (glAccounts && glAccounts.ap) {
        const apName = glAccounts.ap.name + (currentVendorName ? ' — ' + currentVendorName : '');
        rows.push({ code: glAccounts.ap.code, name: apName, debit: 0, credit: netPayable });
    }

    const totalDebit = rows.reduce((s, r) => s + r.debit, 0);
    const totalCredit = rows.reduce((s, r) => s + r.credit, 0);

    document.getElementById('jePreviewBody').innerHTML = rows.map(r => `
        <tr>
            <td style="color: var(--text-2); font-family: var(--mono); font-size: 11px;">${r.code}</td>
            <td>${r.name}</td>
            <td style="text-align: right; font-family: var(--mono);">${fmtNum(r.debit)}</td>
            <td style="text-align: right; font-family: var(--mono);">${fmtNum(r.credit)}</td>
        </tr>`).join('');

    document.getElementById('jePreviewFoot').innerHTML = `
        <tr style="border-top: 2px solid var(--border); font-weight: 700;">
            <td colspan="2" style="font-size: 11px; color: var(--text-2);">Total</td>
            <td style="text-align: right; font-family: var(--mono);">${totalDebit.toLocaleString('en-PH', {minimumFractionDigits: 2})}</td>
            <td style="text-align: right; font-family: var(--mono);">${totalCredit.toLocaleString('en-PH', {minimumFractionDigits: 2})}</td>
        </tr>`;
}
```

- [ ] **Step 10: Update form submit serialization**

Replace the submit event listener:

```javascript
document.getElementById('billForm').addEventListener('submit', function () {
    document.getElementById('lineItemsData').value = JSON.stringify(lineItems.map(item => ({
        description: item.description,
        amount: item.amount,
        vat_category: item.vat_category,
        account_id: item.account_id,
        wt_id: item.wt_id,
        wt_rate: item.wt_rate,
    })));
});
```

- [ ] **Step 11: Update `setVendorDone()` to track vendor name**

In `setVendorDone`, add at the start of the function body:

```javascript
currentVendorName = vendorName;
```

- [ ] **Step 12: Add edit-mode override restore after `initItems()`**

Inside the `{% if bill %}` init block, after `initItems()` is called (after the fetch resolves), add an `initOverrides()` call:

```javascript
function initOverrides() {
    {% if bill and bill.vat_override %}
    vatOverrideActive = true;
    document.getElementById('vatOverrideFlag').value = '1';
    const savedVat = {{ bill.vat_amount | float }};
    document.getElementById('vatOverrideValue').value = savedVat.toFixed(2);
    document.getElementById('vatAutoHint').textContent = 'auto: ' + fmt(autoVat);
    document.getElementById('vatDisplayMode').style.display = 'none';
    document.getElementById('vatEditMode').style.display = 'flex';
    document.getElementById('vatOverrideInput').value = savedVat.toFixed(2);
    {% endif %}
    {% if bill and bill.wt_override %}
    wtOverrideActive = true;
    document.getElementById('wtOverrideFlag').value = '1';
    const savedWt = {{ bill.withholding_tax_amount | float }};
    document.getElementById('wtOverrideValue').value = savedWt.toFixed(2);
    document.getElementById('wtAutoHint').textContent = 'auto: ' + fmt(autoWt);
    document.getElementById('wtDisplayMode').style.display = 'none';
    document.getElementById('wtEditMode').style.display = 'flex';
    document.getElementById('wtOverrideInput').value = savedWt.toFixed(2);
    {% endif %}
    calculateTotals();
}
```

In the `{% if bill %}` init block, add `initOverrides()` at the end of the `.then(data => { ... initItems(); initOverrides(); })` callback, and also in the `.catch(() => { initItems(); initOverrides(); })` branch.

- [ ] **Step 13: Also set `currentVendorName` in edit-mode init**

Inside `{% if bill %}`, after `const initVendorName = ...`, add:

```javascript
currentVendorName = initVendorName;
```

- [ ] **Step 14: Add CSS for pencil/revert buttons**

In the `<style>` block, add:

```css
.totals-pencil {
    background: none;
    border: none;
    cursor: pointer;
    font-size: 12px;
    opacity: 0.35;
    padding: 0;
    transition: opacity 0.15s;
}
.totals-pencil:hover { opacity: 0.9; }
.totals-revert {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 3px;
    cursor: pointer;
    font-size: 11px;
    padding: 1px 5px;
    color: var(--text-2);
}
.totals-revert:hover { background: var(--border); }
```

- [ ] **Step 15: Start dev server and visually verify the form**

```
python flask_app.py
```

Open `http://localhost:5000/purchase-bills/create`. Verify:
- Table has 5 columns: Description, Amount, VT, WT, Account Title
- Totals panel shows Subtotal / Input VAT ✏️ / Withholding Tax ✏️ / Net Payable
- Clicking ✏️ on Input VAT switches to inline input with ↺ revert button
- JE preview appears to the left of the totals panel and updates live
- Submit creates a bill and redirects to detail page

- [ ] **Step 16: Commit**

```
git add app/purchase_bills/templates/purchase_bills/form.html
git commit -m "feat: 5-col line items table, pencil-click VAT/WHT overrides, live JE preview"
```

---

## Task 5: Update Detail Template

**Files:**
- Modify: `app/purchase_bills/templates/purchase_bills/detail.html`

- [ ] **Step 1: Update line items table header**

Find the `<thead>` (around line 155). Replace:

```html
<tr>
    <th>#</th>
    <th>Description</th>
    <th style="text-align:right;">Qty</th>
    <th style="text-align:right;">Unit Cost</th>
    <th>VAT</th>
    <th>WHT</th>
    <th>Account</th>
    <th style="text-align:right;">Amount</th>
    <th style="text-align:right;">VAT Amt</th>
    <th style="text-align:right;">WHT Amt</th>
</tr>
```

Replace with:

```html
<tr>
    <th>#</th>
    <th>Description</th>
    <th style="text-align:right;">Amount (VAT-incl.)</th>
    <th>VAT</th>
    <th>WHT</th>
    <th>Account</th>
    <th style="text-align:right;">Input VAT</th>
    <th style="text-align:right;">WHT Amt</th>
</tr>
```

- [ ] **Step 2: Update line item rows**

Find the `{% for item in bill.line_items %}` loop (around line 170). Replace:

```html
<tr>
    <td>{{ item.line_number }}</td>
    <td>{{ item.description }}</td>
    <td style="text-align:right; font-family:var(--mono);">{{ '{:,.4f}'.format(item.quantity) }}</td>
    <td style="text-align:right; font-family:var(--mono);">₱{{ '{:,.2f}'.format(item.unit_cost) }}</td>
    <td>{{ item.vat_category or 'N/A' }} ({{ '{:.2f}'.format(item.vat_rate) }}%)</td>
    <td style="font-size:12px;">
        {% if item.withholding_tax %}{{ item.withholding_tax.code }} ({{ '{:.2f}'.format(item.wt_rate) }}%){% else %}—{% endif %}
    </td>
    <td style="font-size:12px; color:var(--text-2);">{{ item.account.code ~ ' - ' ~ item.account.name if item.account else '—' }}</td>
    <td style="text-align:right; font-family:var(--mono); font-weight:600;">₱{{ '{:,.2f}'.format(item.line_total) }}</td>
    <td style="text-align:right; font-family:var(--mono);">₱{{ '{:,.2f}'.format(item.vat_amount) }}</td>
    <td style="text-align:right; font-family:var(--mono); color:var(--red);">
        {% if item.wt_amount and item.wt_amount > 0 %}-₱{{ '{:,.2f}'.format(item.wt_amount) }}{% else %}—{% endif %}
    </td>
</tr>
```

Replace with:

```html
<tr>
    <td>{{ item.line_number }}</td>
    <td>{{ item.description }}</td>
    <td style="text-align:right; font-family:var(--mono); font-weight:600;">₱{{ '{:,.2f}'.format(item.line_total) }}</td>
    <td>{{ item.vat_category or 'N/A' }} ({{ '{:.2f}'.format(item.vat_rate) }}%)</td>
    <td style="font-size:12px;">
        {% if item.withholding_tax %}{{ item.withholding_tax.code }} ({{ '{:.2f}'.format(item.wt_rate) }}%){% else %}—{% endif %}
    </td>
    <td style="font-size:12px; color:var(--text-2);">{{ item.account.code ~ ' - ' ~ item.account.name if item.account else '—' }}</td>
    <td style="text-align:right; font-family:var(--mono);">₱{{ '{:,.2f}'.format(item.vat_amount) }}</td>
    <td style="text-align:right; font-family:var(--mono); color:var(--red);">
        {% if item.wt_amount and item.wt_amount > 0 %}-₱{{ '{:,.2f}'.format(item.wt_amount) }}{% else %}—{% endif %}
    </td>
</tr>
```

- [ ] **Step 3: Update totals panel — remove "Total before WT" row, add override badges**

Find the totals panel (around line 192). Update the Input VAT row and remove the "Total before WT" row:

```html
<!-- REPLACE the full totals block: -->
<div style="display:flex; justify-content:flex-end;">
    <div style="background:var(--bg); padding:20px; border-radius:6px; min-width:340px;">
        <div style="display:flex; justify-content:space-between; margin-bottom:12px;">
            <span style="color:var(--text-2);">Subtotal (VAT-incl.):</span>
            <span style="font-family:var(--mono); font-weight:600;">₱{{ '{:,.2f}'.format(bill.subtotal) }}</span>
        </div>
        <div style="display:flex; justify-content:space-between; margin-bottom:12px;">
            <span style="color:var(--text-2);">
                Input VAT:
                {% if bill.vat_override %}<span style="font-size:10px; font-weight:700; color:var(--amber); margin-left:4px;">MANUAL</span>{% endif %}
            </span>
            <span style="font-family:var(--mono); font-weight:600;">₱{{ '{:,.2f}'.format(bill.vat_amount) }}</span>
        </div>
        <div style="display:flex; justify-content:space-between; margin-bottom:12px; padding-top:8px; border-top:1px solid var(--border);">
            <span style="color:var(--text-2);">
                Withholding Tax:
                {% if bill.wt_override %}<span style="font-size:10px; font-weight:700; color:var(--amber); margin-left:4px;">MANUAL</span>{% endif %}
            </span>
            <span style="font-family:var(--mono); font-weight:600; color:var(--red);">-₱{{ '{:,.2f}'.format(bill.withholding_tax_amount) }}</span>
        </div>
        <div style="display:flex; justify-content:space-between; padding-top:12px; border-top:2px solid var(--border); margin-bottom:12px;">
            <span style="font-size:16px; font-weight:700;">Net Payable:</span>
            <span style="font-family:var(--mono); font-size:18px; font-weight:700; color:var(--blue);">₱{{ '{:,.2f}'.format(bill.total_amount) }}</span>
        </div>
        {% if bill.amount_paid > 0 %}
        <!-- ... keep the amount_paid / balance rows unchanged ... -->
        {% endif %}
    </div>
</div>
```

- [ ] **Step 4: View the detail page in browser**

Navigate to a bill's detail page and confirm: 8 columns (no Qty/Unit Cost), correct amounts, MANUAL badge shows on overridden rows.

- [ ] **Step 5: Commit**

```
git add app/purchase_bills/templates/purchase_bills/detail.html
git commit -m "feat: update bill detail — remove qty/unit_cost columns, show override badges"
```

---

## Task 6: Update Tests

**Files:**
- Modify: `tests/integration/test_purchase_bill_views.py`

- [ ] **Step 1: Verify existing tests still pass**

```
pytest tests/integration/test_purchase_bill_views.py -v
```

`make_bill()` uses `total_before_wt=total_amount` which is still valid (after redesign `total_before_wt = subtotal = total_amount` in zero-VAT bills). No `PurchaseBillItem` constructors exist in these tests, so no changes required.

Expected: all tests pass. If any use `total_before_wt == subtotal + vat_amount`, update the assertion to `total_before_wt == subtotal`.

- [ ] **Step 2: Run full test suite**

```
pytest -v --tb=short
```

Expected: all tests pass.

- [ ] **Step 3: Run both new test files to confirm**

```
pytest tests/unit/test_purchase_bill_models.py tests/integration/test_purchase_bill_je.py -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```
git add tests/
git commit -m "test: confirm all tests pass post-redesign; no line-item constructor changes needed in existing suite"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|-----------------|------|
| 5-col table: Description, Amount, VT, WT, Account Title | Task 4 Step 1 |
| `net_base = amount / (1 + vat_rate/100)` | Task 1 Step 3 |
| `vat_amount = amount - net_base` | Task 1 Step 3 |
| `wht_amount = net_base × wt_rate/100` | Task 1 Step 3 |
| `subtotal = sum(line_total)` VAT-inclusive | Task 1 Step 4 |
| `net_payable = subtotal − wht_total` | Task 1 Step 4 |
| Pencil-click override UX for Input VAT and WHT | Task 4 Steps 8–9 |
| Revert button (↺) restores auto value | Task 4 Step 8 |
| Auto hint shown while in edit mode | Task 4 Step 8 |
| Live JE preview (left of totals panel) | Task 4 Steps 3, 9 |
| JE balance fix for override case | Task 4 Step 9 (vat_diff) |
| entry_type = 'purchase' | Task 1 Step 5, Task 3 Step 3 |
| JE posted on create | Task 3 Step 5 |
| JE deleted + recreated on edit | Task 3 Step 6 |
| `vat_override`, `wt_override`, `journal_entry_id` fields on PurchaseBill | Task 1 Step 4 |
| Migration: rename unit_cost→amount, drop quantity, add 3 fields | Task 2 |
| `_create_reversal_je` credit net_base not line_total | Task 3 Step 4 |
| Detail: remove Qty/Unit Cost columns | Task 5 |
| MANUAL badge on overridden amounts in detail | Task 5 Step 3 |
| Vendor WHT/VAT defaults unchanged | Not touched |
| Void/cancel flow unchanged | Only fix in Step 4 (balance, not logic change) |

**No placeholders present.** All steps contain actual code.

**Type consistency:**
- `item.amount` used throughout (model, views, JS, tests) — consistent
- `gl_accounts` dict passed from views, consumed as `glAccounts` in JS — consistent
- `vatOverrideActive` / `wtOverrideActive` JS booleans control display logic — consistent
- `vat_override` / `wt_override` model Booleans match form field names `vat_override` / `wt_override` — consistent
