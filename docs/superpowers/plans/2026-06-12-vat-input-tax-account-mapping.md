# VAT Category → Input Tax Account Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each VAT category selects the Input VAT account its journal entries debit; purchase-bill JEs split input VAT into per-account buckets (resolves B-014).

**Architecture:** New nullable FK `VATCategory.input_vat_account_id` (required by the form when rate > 0), carried through the existing change-request approval workflow. `app/purchase_bills/views.py` gains a `_input_vat_buckets(bill)` helper used by `_post_bill_je` and `_build_je_preview`; `_create_reversal_je` is rewritten to mirror the stored JE lines. The client JE preview mirrors the bucket logic.

**Tech Stack:** Flask + SQLAlchemy + Flask-Migrate (Alembic), WTForms, Jinja2, Choices.js (bundled), pytest.

**Spec:** `docs/superpowers/specs/2026-06-12-vat-input-tax-account-mapping-design.md`

**Conventions that apply (from CLAUDE.md):** audit log assertions in every CRUD test; no JS popups; design tokens only; `pytest -q --no-cov` for quick runs. The repo root is `C:\envs\cas`. A `.env` with `SECRET_KEY` exists — `flask` CLI commands work from the repo root.

---

### Task 1: Model field + migration

**Files:**
- Modify: `app/vat_categories/models.py` (VATCategory, ~line 18 and to_dict ~line 33)
- Create: migration via `flask db migrate`
- Test: `tests/unit/test_vat_category_model.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_vat_category_model.py`:

```python
"""VATCategory.input_vat_account mapping (B-014)."""
from app.accounts.models import Account
from app.vat_categories.models import VATCategory


def make_account(db_session, code='10502', name='Input VAT - Domestic Goods'):
    a = Account(code=code, name=name, account_type='Asset',
                normal_balance='debit', is_active=True)
    db_session.add(a)
    db_session.commit()
    return a


class TestInputVatAccountField:
    def test_field_and_relationship(self, db_session):
        acct = make_account(db_session)
        cat = VATCategory(code='V12T', name='Test 12%', rate=12.00,
                          is_active=True, input_vat_account_id=acct.id)
        db_session.add(cat)
        db_session.commit()
        assert cat.input_vat_account.code == '10502'

    def test_nullable_for_zero_rate(self, db_session):
        cat = VATCategory(code='V0T', name='Test 0%', rate=0.00, is_active=True)
        db_session.add(cat)
        db_session.commit()
        assert cat.input_vat_account_id is None

    def test_to_dict_includes_account(self, db_session):
        acct = make_account(db_session, code='10503', name='Input VAT - Services')
        cat = VATCategory(code='V12S', name='Svc 12%', rate=12.00,
                          is_active=True, input_vat_account_id=acct.id)
        db_session.add(cat)
        db_session.commit()
        d = cat.to_dict()
        assert d['input_vat_account_id'] == acct.id
        assert d['input_vat_account_code'] == '10503'
        assert d['input_vat_account_name'] == 'Input VAT - Services'

    def test_to_dict_unmapped(self, db_session):
        cat = VATCategory(code='V0U', name='Zero', rate=0.00, is_active=True)
        db_session.add(cat)
        db_session.commit()
        d = cat.to_dict()
        assert d['input_vat_account_id'] is None
        assert d['input_vat_account_code'] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_vat_category_model.py -q --no-cov`
Expected: FAIL — `TypeError: 'input_vat_account_id' is an invalid keyword argument`

- [ ] **Step 3: Add the column, relationship, and to_dict keys**

In `app/vat_categories/models.py`, after `is_active` (line 18):

```python
    # Input VAT account used for purchase journal entries (B-014).
    # NULL is correct for zero-rate categories; the form requires it when rate > 0.
    input_vat_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'),
                                     nullable=True)
```

In the Relationships block (after `updated_by`, line 28):

```python
    input_vat_account = db.relationship('Account', foreign_keys=[input_vat_account_id])
```

In `to_dict()` add after `'rate': ...`:

```python
            'input_vat_account_id': self.input_vat_account_id,
            'input_vat_account_code': self.input_vat_account.code if self.input_vat_account else None,
            'input_vat_account_name': self.input_vat_account.name if self.input_vat_account else None,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_vat_category_model.py -q --no-cov`
Expected: 4 passed (tests use in-memory DB with `create_all`, no migration needed)

- [ ] **Step 5: Generate and apply the migration (dev DB)**

```powershell
flask db migrate -m "vat_categories.input_vat_account_id (B-014)"
flask db upgrade
```

Expected: new file under `migrations/versions/` adding `input_vat_account_id` with FK to `accounts.id`. Open it and confirm it contains exactly one `add_column` on `vat_categories` (and the FK constraint); remove any unrelated autodetected noise if present.

- [ ] **Step 6: Commit**

```powershell
git add app/vat_categories/models.py migrations/versions tests/unit/test_vat_category_model.py
git commit -m "feat: VATCategory.input_vat_account_id column + migration (B-014)"
```

---

### Task 2: Form field with rate-conditional validation

**Files:**
- Modify: `app/vat_categories/forms.py`
- Test: `tests/unit/test_vat_category_form.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_vat_category_form.py`:

```python
"""VATCategoryForm: input_vat_account_id required when rate > 0 (B-014)."""
from app.vat_categories.forms import VATCategoryForm


def make_form(app, rate, account_id):
    with app.test_request_context(method='POST', data={
        'code': 'VX', 'name': 'X', 'rate': str(rate),
        'is_active': '1', 'request_reason': 'test reason',
        'input_vat_account_id': str(account_id) if account_id is not None else '0',
    }):
        form = VATCategoryForm(meta={'csrf': False})
        # choices are populated by the view; emulate
        form.input_vat_account_id.choices = [(0, '-- None --'), (5, '10502 : Input VAT - Domestic Goods')]
        return form, form.validate()


class TestRateConditionalAccount:
    def test_rate_positive_without_account_rejected(self, app):
        form, ok = make_form(app, 12, None)
        assert ok is False
        assert any('Input Tax account' in e for e in form.input_vat_account_id.errors)

    def test_rate_positive_with_account_ok(self, app):
        form, ok = make_form(app, 12, 5)
        assert ok is True

    def test_rate_zero_without_account_ok(self, app):
        form, ok = make_form(app, 0, None)
        assert ok is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_vat_category_form.py -q --no-cov`
Expected: FAIL — `AttributeError: ... no attribute 'input_vat_account_id'`

- [ ] **Step 3: Add the field and validator**

In `app/vat_categories/forms.py`: extend imports

```python
from wtforms import StringField, TextAreaField, DecimalField, SelectField
from wtforms.validators import DataRequired, InputRequired, Length, NumberRange, Optional, ValidationError
```

Add to `VATCategoryForm` after `rate`:

```python
    input_vat_account_id = SelectField('Input Tax Account', coerce=int,
                                       validators=[Optional()], default=0)

    def validate_input_vat_account_id(self, field):
        """Required when rate > 0; cleared when rate is zero (no input tax)."""
        if self.rate.data and self.rate.data > 0:
            if not field.data or field.data == 0:
                raise ValidationError(
                    'Input Tax account is required for VAT-bearing categories.')
        else:
            field.data = 0
```

(`0` is the "none" sentinel because `coerce=int` cannot produce None from an empty string; views translate 0 → NULL.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_vat_category_form.py -q --no-cov`
Expected: 3 passed

- [ ] **Step 5: Commit**

```powershell
git add app/vat_categories/forms.py tests/unit/test_vat_category_form.py
git commit -m "feat: VAT category form requires Input Tax account when rate > 0"
```

---

### Task 3: Views — choices, change_data, auto-approve and apply-on-approval

**Files:**
- Modify: `app/vat_categories/views.py` (create ~line 101, edit ~line 204, review apply ~line 456)
- Test: `tests/integration/test_vat_input_account_workflow.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_vat_input_account_workflow.py`:

```python
"""Input-tax account flows through the VAT change-request workflow (B-014)."""
import json

from app.accounts.models import Account
from app.audit.models import AuditLog
from app.vat_categories.models import VATCategory, VATCategoryChangeRequest


def login(client, username, password):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def make_account(db_session, code='10502', name='Input VAT - Domestic Goods'):
    a = Account(code=code, name=name, account_type='Asset',
                normal_balance='debit', is_active=True)
    db_session.add(a)
    db_session.commit()
    return a


def vat_data(account_id, code='V12T', rate='12.00'):
    return {
        'code': code, 'name': f'Test {code}', 'description': 'test',
        'rate': rate, 'is_active': '1',
        'input_vat_account_id': str(account_id),
        'request_reason': 'B-014 workflow test',
    }


class TestInputAccountWorkflow:
    def test_admin_create_pending_then_approved_applies_account(
            self, client, db_session, admin_user, accountant_user, main_branch):
        acct = make_account(db_session)
        login(client, 'admin', 'admin123')
        client.post('/vat-categories/create', data=vat_data(acct.id),
                    follow_redirects=True)

        req = VATCategoryChangeRequest.query.order_by(
            VATCategoryChangeRequest.id.desc()).first()
        assert req.status == 'pending'
        assert json.loads(req.proposed_data)['input_vat_account_id'] == acct.id

        login(client, 'accountant', 'accountant123')
        client.post(f'/vat-categories/change-requests/{req.id}/review',
                    data={'action': 'approve', 'review_notes': 'ok'},
                    follow_redirects=True)

        cat = VATCategory.query.filter_by(code='V12T').first()
        assert cat is not None
        assert cat.input_vat_account_id == acct.id

        audit = AuditLog.query.filter_by(module='vat_category', action='create',
                                         record_id=cat.id).first()
        assert audit is not None

    def test_sole_accountant_autoapprove_sets_account(
            self, client, db_session, admin_user, accountant_user, main_branch):
        acct = make_account(db_session, code='10503', name='Input VAT - Services')
        login(client, 'accountant', 'accountant123')
        client.post('/vat-categories/create', data=vat_data(acct.id, code='V12S'),
                    follow_redirects=True)
        cat = VATCategory.query.filter_by(code='V12S').first()
        assert cat is not None
        assert cat.input_vat_account_id == acct.id

    def test_update_changes_account_through_workflow(
            self, client, db_session, admin_user, accountant_user, main_branch):
        a1 = make_account(db_session, code='10501', name='Input VAT - Capital Goods')
        a2 = make_account(db_session, code='10502', name='Input VAT - Domestic Goods')
        cat = VATCategory(code='V12U', name='Upd 12%', rate=12.00, is_active=True,
                          input_vat_account_id=a1.id)
        db_session.add(cat)
        db_session.commit()

        login(client, 'admin', 'admin123')
        data = vat_data(a2.id, code='V12U')
        data['name'] = 'Upd 12%'
        client.post(f'/vat-categories/{cat.id}/edit', data=data,
                    follow_redirects=True)
        req = VATCategoryChangeRequest.query.order_by(
            VATCategoryChangeRequest.id.desc()).first()
        assert req.status == 'pending'

        login(client, 'accountant', 'accountant123')
        client.post(f'/vat-categories/change-requests/{req.id}/review',
                    data={'action': 'approve', 'review_notes': 'ok'},
                    follow_redirects=True)
        assert db_session.get(VATCategory, cat.id).input_vat_account_id == a2.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_vat_input_account_workflow.py -q --no-cov`
Expected: FAIL (proposed_data lacks `input_vat_account_id`; applied category has None)

- [ ] **Step 3: Populate choices in every route that renders the form**

In `app/vat_categories/views.py` add a helper near the top (after `flash_duplicate_pending`):

```python
def _input_vat_account_choices():
    """Active leaf accounts for the Input Tax picker (groups are not postable)."""
    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    parent_ids = {a.parent_id for a in accounts if a.parent_id is not None}
    choices = [(0, '-- None (zero-rate) --')]
    choices += [(a.id, f'{a.code} : {a.name}') for a in accounts
                if a.id not in parent_ids]
    return choices
```

Add the import at the top of the file: `from app.accounts.models import Account`.

In `create()` and `edit()` set `form.input_vat_account_id.choices = _input_vat_account_choices()` immediately after constructing the form (before `validate_on_submit`). In `edit()`'s GET pre-population, set `form.input_vat_account_id.data = vat_category.input_vat_account_id or 0`.

- [ ] **Step 4: Carry the field through change_data and both apply paths**

In `create()` extend `change_data` (line ~129):

```python
            change_data = {
                'code': form.code.data,
                'name': form.name.data,
                'description': form.description.data,
                'rate': float(form.rate.data),
                'is_active': bool(int(form.is_active.data)) if form.is_active.data else True,
                'input_vat_account_id': form.input_vat_account_id.data or None,
            }
```

In the auto-approve branch add `input_vat_account_id=change_data['input_vat_account_id'],` to the `VATCategory(...)` constructor. Mirror both edits in `edit()`'s change_data and (if it has an auto-approve branch) its direct-apply assignments (`vat_category.input_vat_account_id = change_data['input_vat_account_id']`).

In `review_change_request()` (line ~456): the create-apply `VATCategory(...)` constructor gains
`input_vat_account_id=proposed_data.get('input_vat_account_id'),` and the update-apply block gains
`vat_category.input_vat_account_id = proposed_data.get('input_vat_account_id')`.

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/integration/test_vat_input_account_workflow.py -q --no-cov`
Expected: 3 passed

- [ ] **Step 6: Run the existing workflow suite**

Run: `python -m pytest tests/integration/test_change_request_workflow.py -q --no-cov`
Expected: 25 passed. If a test posts VAT forms with rate > 0 and no `input_vat_account_id`, those tests now legitimately fail — add `'input_vat_account_id': str(<account id>)` to their form payloads (create the account in the test setup with the `make_account` pattern above).

- [ ] **Step 7: Commit**

```powershell
git add app/vat_categories/views.py tests/integration/test_vat_input_account_workflow.py tests/integration/test_change_request_workflow.py
git commit -m "feat: input-tax account flows through VAT change-request workflow"
```

---

### Task 4: Templates — form picker, list column, review displays

**Files:**
- Modify: `app/vat_categories/templates/vat_categories/form.html` (Tax Configuration section, ~line 44; script block ~line 230)
- Modify: `app/vat_categories/templates/vat_categories/list.html` (add column)
- Modify: `app/vat_categories/templates/vat_categories/review_change_request.html` and `change_requests.html` (show proposed account)

- [ ] **Step 1: Form picker (hidden at rate 0) — form.html**

Inside the Tax Configuration `form-row-2` (after the `is_active` form-group, line ~77) add:

```html
                <div class="form-group" id="inputVatAccountGroup">
                    {{ form.input_vat_account_id.label(class="form-label") }}
                    {{ form.input_vat_account_id(class="form-control", id="inputVatAccountSelect") }}
                    {% if form.input_vat_account_id.errors %}
                        {% for error in form.input_vat_account_id.errors %}
                            <div class="form-error">{{ error }}</div>
                        {% endfor %}
                    {% endif %}
                    <small class="form-hint">Journal entries debit this account for the category's input VAT. Required when the rate is above 0%.</small>
                </div>
```

In the `<script>` block, inside `DOMContentLoaded`, extend the rate handler:

```javascript
    // Input Tax account picker — searchable; hidden when rate is 0
    const acctSelect = document.getElementById('inputVatAccountSelect');
    const acctGroup = document.getElementById('inputVatAccountGroup');
    let acctChoices = null;
    if (acctSelect && window.Choices) {
        acctChoices = new Choices(acctSelect, {searchEnabled: true, itemSelectText: '', shouldSort: false, allowHTML: false});
    }
    function syncAcctVisibility() {
        const rate = parseFloat(rateInput ? rateInput.value : '0') || 0;
        if (acctGroup) acctGroup.style.display = rate > 0 ? '' : 'none';
    }
    if (rateInput) rateInput.addEventListener('input', syncAcctVisibility);
    syncAcctVisibility();
```

Check the base template loads Choices.js globally (the APV form uses it); if it is page-local there, copy the same `<link>`/`<script>` includes used by `app/purchase_bills/templates/purchase_bills/form.html`.

- [ ] **Step 2: List column — list.html**

In the categories table add a header `<th>Input Tax Account</th>` after the Rate column and the matching cell:

```html
                    <td>
                        {% if category.input_vat_account %}
                            {{ category.input_vat_account.code }} : {{ category.input_vat_account.name }}
                        {% else %}—{% endif %}
                    </td>
```

(Match the actual loop variable name used in the template — read it first.)

- [ ] **Step 3: Review + change_requests templates**

Both templates render `proposed_data`. Where the rate is displayed for create/update requests, add a line:

```html
                            {% if proposed.get('input_vat_account_id') %}
                            <br><span style="font-size: 12px; color: #64748b;">Input Tax acct ID: {{ proposed.get('input_vat_account_id') }}</span>
                            {% endif %}
```

Better: in `review_change_request()` view, resolve the account and pass `proposed_account` (`Account.query.get(proposed_data['input_vat_account_id'])`) to the template, displaying `{{ proposed_account.code }} : {{ proposed_account.name }}` when set. Use that approach for the review page; the list page can show the raw id-to-account lookup the same way via a dict passed from `change_requests()`.

- [ ] **Step 4: Render check**

Run: `python -m pytest tests/integration/test_vat_input_account_workflow.py tests/integration/test_change_request_workflow.py -q --no-cov`
Expected: all pass (templates render without Jinja errors during these flows).

- [ ] **Step 5: Commit**

```powershell
git add app/vat_categories/templates
git commit -m "feat: input-tax account picker on VAT form; shown in list and review pages"
```

---

### Task 5: Purchase-bill JE buckets

**Files:**
- Modify: `app/purchase_bills/views.py` — `_get_gl_accounts` (line ~30), `_build_je_preview` (line ~42), `_post_bill_je` (line ~826)
- Test: `tests/integration/test_purchase_bill_vat_buckets.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_purchase_bill_vat_buckets.py`:

```python
"""Per-category input-VAT buckets in purchase JEs (B-014)."""
import json
from decimal import Decimal

from app.accounts.models import Account
from app.vat_categories.models import VATCategory
from app.vendors.models import Vendor
from app.purchase_bills.models import PurchaseBill
from app.journal_entries.models import JournalEntry


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def setup_world(db_session):
    accts = {}
    for code, name, typ, bal in [
        ('20101', 'Accounts Payable - Trade', 'Liability', 'credit'),
        ('20301', 'Withholding Tax Payable - Expanded', 'Liability', 'credit'),
        ('10502', 'Input VAT - Domestic Goods', 'Asset', 'debit'),
        ('10503', 'Input VAT - Services', 'Asset', 'debit'),
        ('69903', 'Bucket Test Expense', 'Expense', 'debit'),
    ]:
        a = Account(code=code, name=name, account_type=typ,
                    normal_balance=bal, is_active=True)
        db_session.add(a)
    db_session.commit()
    for code in ['20101', '20301', '10502', '10503', '69903']:
        accts[code] = Account.query.filter_by(code=code).first()

    dg = VATCategory(code='V12DG', name='Input Tax Domestic Goods', rate=12.00,
                     is_active=True, input_vat_account_id=accts['10502'].id)
    sv = VATCategory(code='V12SV', name='Input Tax Services', rate=12.00,
                     is_active=True, input_vat_account_id=accts['10503'].id)
    un = VATCategory(code='V12UN', name='Unmapped 12%', rate=12.00, is_active=True)
    db_session.add_all([dg, sv, un])
    vendor = Vendor(code='BKT01', name='Bucket Vendor',
                    check_payee_name='Bucket Vendor', is_active=True)
    db_session.add(vendor)
    db_session.commit()
    accts['vendor'] = vendor
    return accts


def post_bill(client, vendor, lines, number='AP-BKT-0001',
              vat_override='0', vat_override_value='0'):
    return client.post('/purchase-bills/create', data={
        'bill_number': number,
        'bill_date': '2026-06-12', 'due_date': '2026-06-12',
        'vendor_id': vendor.id, 'payment_terms': 'Net 30',
        'line_items': json.dumps(lines),
        'vat_override': vat_override, 'vat_override_value': vat_override_value,
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=True)


def je_lines_by_code(db_session, number):
    bill = PurchaseBill.query.filter_by(bill_number=number).first()
    je = db_session.get(JournalEntry, bill.journal_entry_id)
    out = {}
    for l in je.lines.all():
        code = l.account.code
        out.setdefault(code, Decimal('0.00'))
        out[code] += l.debit_amount - l.credit_amount
    return out


class TestVatBuckets:
    def test_two_categories_two_input_vat_lines(self, client, db_session,
                                                admin_user, main_branch):
        w = setup_world(db_session)
        login(client)
        post_bill(client, w['vendor'], [
            {'description': 'goods', 'amount': 2240.0, 'vat_category': 'V12DG',
             'account_id': w['69903'].id, 'wt_id': None, 'wt_rate': None},
            {'description': 'services', 'amount': 560.0, 'vat_category': 'V12SV',
             'account_id': w['69903'].id, 'wt_id': None, 'wt_rate': None},
        ])
        sums = je_lines_by_code(db_session, 'AP-BKT-0001')
        assert sums['10502'] == Decimal('240.00')
        assert sums['10503'] == Decimal('60.00')

    def test_override_difference_lands_on_largest_bucket(self, client, db_session,
                                                         admin_user, main_branch):
        w = setup_world(db_session)
        login(client)
        # computed VAT: 240 + 60 = 300; override to 301 → +1 on the 10502 bucket
        post_bill(client, w['vendor'], [
            {'description': 'goods', 'amount': 2240.0, 'vat_category': 'V12DG',
             'account_id': w['69903'].id, 'wt_id': None, 'wt_rate': None},
            {'description': 'services', 'amount': 560.0, 'vat_category': 'V12SV',
             'account_id': w['69903'].id, 'wt_id': None, 'wt_rate': None},
        ], number='AP-BKT-0002', vat_override='1', vat_override_value='301')
        sums = je_lines_by_code(db_session, 'AP-BKT-0002')
        assert sums['10502'] == Decimal('241.00')
        assert sums['10503'] == Decimal('60.00')

    def test_unmapped_vat_bearing_category_blocks_save(self, client, db_session,
                                                       admin_user, main_branch):
        w = setup_world(db_session)
        login(client)
        resp = post_bill(client, w['vendor'], [
            {'description': 'x', 'amount': 1120.0, 'vat_category': 'V12UN',
             'account_id': w['69903'].id, 'wt_id': None, 'wt_rate': None},
        ], number='AP-BKT-0003')
        html = resp.data.decode('utf-8')
        assert 'has no Input Tax account configured' in html
        assert PurchaseBill.query.filter_by(bill_number='AP-BKT-0003').first() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_purchase_bill_vat_buckets.py -q --no-cov`
Expected: FAIL (single 10501 line / no error raised). The first two tests may ERROR with "Input VAT - Current (10501) not found" — that is the hardcode being removed in this task.

- [ ] **Step 3: Implement the bucket helper and rewire `_post_bill_je`**

In `app/purchase_bills/views.py` add near `_get_gl_accounts` (import `VATCategory` is already present in this module — verify; if not: `from app.vat_categories.models import VATCategory`):

```python
def _input_vat_buckets(bill):
    """Group the bill's input VAT by each line's VAT-category account.

    Returns an ordered list of (Account, Decimal) pairs (by account code).
    The whole-bill VAT override difference is applied to the largest bucket.
    Raises ValueError if a VAT-bearing line's category has no account.
    """
    categories = {c.code: c for c in VATCategory.query.all()}
    buckets = {}  # account_id -> [Account, Decimal]
    for item in bill.line_items:
        vat_amt = Decimal(str(item.vat_amount or 0))
        if vat_amt <= 0:
            continue
        cat = categories.get(item.vat_category)
        acct = cat.input_vat_account if cat else None
        if acct is None:
            label = cat.code if cat else (item.vat_category or 'unknown')
            raise ValueError(
                f"VAT category '{label}' has no Input Tax account configured. "
                "Set it in VAT Categories.")
        if acct.id not in buckets:
            buckets[acct.id] = [acct, Decimal('0.00')]
        buckets[acct.id][1] += vat_amt

    ordered = sorted(buckets.values(), key=lambda b: b[0].code)
    total = sum((b[1] for b in ordered), Decimal('0.00'))
    override_diff = Decimal(str(bill.vat_amount)) - total
    if override_diff != Decimal('0.00') and ordered:
        largest = max(ordered, key=lambda b: b[1])
        largest[1] += override_diff
    return [(b[0], b[1]) for b in ordered]
```

In `_get_gl_accounts()` delete the `input_vat_acct` lookup and the `'input_vat'` key (keep `ap` and `wt`). Fix its docstring to "Return the AP and WHT GL accounts used for purchase bill journal entries."

In `_post_bill_je()`: delete the `input_vat_account` block (lines ~834-838, the 10501 ValueError) and replace the single `if input_vat_account:` vat_line block with:

```python
    for vat_acct, vat_amt in _input_vat_buckets(bill):
        if vat_amt <= 0:
            continue
        vat_line = JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=vat_acct.id,
            description=f'Input VAT: {bill.bill_number}',
            debit_amount=vat_amt,
            credit_amount=Decimal('0.00')
        )
        db.session.add(vat_line)
        all_lines.append(vat_line)
        line_num += 1
```

Also delete the now-unused `vat_used = Decimal(str(bill.vat_amount))` line.

- [ ] **Step 4: Rewire `_build_je_preview` (draft branch)**

Replace its aggregate input-VAT block (lines ~73-80) with:

```python
    for vat_acct, vat_amt in _input_vat_buckets(bill):
        if vat_amt <= 0:
            continue
        entries.append({
            'code': vat_acct.code,
            'name': vat_acct.name,
            'debit': vat_amt,
            'credit': Decimal('0.00'),
        })
```

`accts['input_vat']` no longer exists — confirm nothing else in the file references it (grep `accts['input_vat']` and `gl_accounts['input_vat']`; the `gl_accounts` dict passed to the form template is updated in Task 7).

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/integration/test_purchase_bill_vat_buckets.py -q --no-cov`
Expected: 3 passed

Run: `python -m pytest tests/integration/test_purchase_bill_je.py tests/integration/test_purchase_bill_je_lifecycle.py tests/integration/test_purchase_bill_dates.py tests/integration/test_purchase_bill_void.py -q --no-cov`
Expected: these suites create bills with VAT categories that have NO account mapping (e.g. `VAT12` in `test_purchase_bill_je.py`) — those tests now fail the unmapped guard. Fix each test's setup to give its 12% category an `input_vat_account_id` pointing at the suite's existing `10501` account (the suites already create `10501`). Bills with no VAT category (`vat_category: ''`) produce no VAT and are unaffected.

- [ ] **Step 6: Commit**

```powershell
git add app/purchase_bills/views.py tests/integration/test_purchase_bill_vat_buckets.py tests/integration/test_purchase_bill_je.py tests/integration/test_purchase_bill_je_lifecycle.py
git commit -m "feat: per-category input VAT buckets in purchase JEs (B-014)"
```

---

### Task 6: Reversal JE mirrors stored lines

**Files:**
- Modify: `app/purchase_bills/views.py` — `_create_reversal_je` (line ~952)
- Test: extend `tests/integration/test_purchase_bill_vat_buckets.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_purchase_bill_vat_buckets.py`:

```python
class TestReversalMirrorsJE:
    def test_cancel_reverses_bucketed_lines(self, client, db_session,
                                            admin_user, main_branch):
        w = setup_world(db_session)
        login(client)
        post_bill(client, w['vendor'], [
            {'description': 'goods', 'amount': 2240.0, 'vat_category': 'V12DG',
             'account_id': w['69903'].id, 'wt_id': None, 'wt_rate': None},
            {'description': 'services', 'amount': 560.0, 'vat_category': 'V12SV',
             'account_id': w['69903'].id, 'wt_id': None, 'wt_rate': None},
        ], number='AP-BKT-0004')
        bill = PurchaseBill.query.filter_by(bill_number='AP-BKT-0004').first()
        bill.vendor_invoice_number = 'SI-1'
        from datetime import date
        bill.vendor_invoice_date = date(2026, 6, 12)
        db_session.commit()
        client.post(f'/purchase-bills/{bill.id}/post', follow_redirects=True)
        client.post(f'/purchase-bills/{bill.id}/cancel', data={
            'cancel_reason': 'bucket reversal test reason',
            'reversal_date': '2026-06-12',
        }, follow_redirects=True)

        reversal = (JournalEntry.query
                    .filter(JournalEntry.reference.like('%AP-BKT-0004%'),
                            JournalEntry.entry_type == 'reversal').first())
        assert reversal is not None
        sums = {}
        for l in reversal.lines.all():
            sums.setdefault(l.account.code, Decimal('0.00'))
            sums[l.account.code] += l.credit_amount - l.debit_amount
        # reversal CREDITS what the original debited
        assert sums['10502'] == Decimal('240.00')
        assert sums['10503'] == Decimal('60.00')
        # AP was credited originally -> the reversal debits it, so credit - debit < 0
        assert sums['20101'] < 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_purchase_bill_vat_buckets.py::TestReversalMirrorsJE -q --no-cov`
Expected: FAIL (reversal books 10501 / errors on missing 10501)

- [ ] **Step 3: Rewrite `_create_reversal_je`**

Replace the entire body of `_create_reversal_je(bill, reversal_date, user_id, label='Void')` with:

```python
def _create_reversal_je(bill, reversal_date, user_id, label='Void'):
    """Mirror the bill's stored JE with debits and credits swapped.

    Reverses exactly what was booked — per-category VAT buckets, overrides
    and all. Raises ValueError if the bill has no stored journal entry.
    """
    from app.journal_entries.models import JournalEntry, JournalEntryLine

    source_je = bill.journal_entry
    if source_je is None:
        raise ValueError(
            f'Cannot {label.lower()}: bill {bill.bill_number} has no stored '
            'journal entry to reverse.')

    entry_number = generate_entry_number(bill.branch_id)
    je = JournalEntry(
        entry_number=entry_number,
        entry_date=reversal_date,
        description=f'Purchase Bill {label} — {bill.bill_number} (reversal)',
        reference=f'{label.upper()[:6]}-{bill.bill_number}',
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

    for i, src in enumerate(source_je.lines.all(), start=1):
        db.session.add(JournalEntryLine(
            entry_id=je.id, line_number=i,
            account_id=src.account_id,
            description=f'{label}: {src.description}',
            debit_amount=src.credit_amount,
            credit_amount=src.debit_amount,
        ))
    db.session.flush()

    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(
            f'Reversal JE is not balanced (debit={je.total_debit}, '
            f'credit={je.total_credit}).')
    return je
```

Check call sites: the cancel route calls `_create_reversal_je(bill, ...)` — it must run **before** anything detaches `bill.journal_entry`. Read the cancel route and confirm order; adjust if it nulls the JE reference first.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/integration/test_purchase_bill_vat_buckets.py tests/integration/test_purchase_bill_views.py -q --no-cov`
Expected: all pass (update any `test_purchase_bill_views.py` cancel tests that asserted the old 10501-based reversal shape).

- [ ] **Step 5: Commit**

```powershell
git add app/purchase_bills/views.py tests/integration/test_purchase_bill_vat_buckets.py tests/integration/test_purchase_bill_views.py
git commit -m "feat: reversal JE mirrors stored lines instead of rebuilding from totals"
```

---

### Task 7: Client-side JE preview buckets

**Files:**
- Modify: `app/purchase_bills/templates/purchase_bills/form.html` — `renderJEPreview` (line ~708)
- Modify: `app/purchase_bills/views.py` — `gl_accounts` dicts passed to the template (two places, create ~line 700 and edit; remove the `input_vat` key)

- [ ] **Step 1: Update `renderJEPreview`**

The template receives `vat_categories` (from `VATCategory.to_dict()`, which now includes `input_vat_account_id/_code/_name` from Task 1). Replace the aggregate input-VAT push (lines ~733-735) with bucket logic:

```javascript
    // Per-category input VAT buckets (B-014)
    const vatBuckets = {};  // account code -> {code, name, amt}
    lineItems.forEach(item => {
        if (!item.account_id) return;
        const vat = vatCategories.find(v => v.code === item.vat_category);
        const vatRate = vat ? vat.rate : 0;
        const amt = item.amount || 0;
        const vatAmt = vatRate > 0 ? Math.round((amt - amt / (1 + vatRate / 100)) * 100) / 100 : 0;
        if (vatAmt <= 0) return;
        const code = vat && vat.input_vat_account_code ? vat.input_vat_account_code : '??';
        const name = vat && vat.input_vat_account_name ? vat.input_vat_account_name : 'No Input Tax account configured';
        if (!vatBuckets[code]) vatBuckets[code] = {code, name, amt: 0};
        vatBuckets[code].amt += vatAmt;
    });
    const bucketList = Object.values(vatBuckets).sort((a, b) => a.code.localeCompare(b.code));
    const bucketTotal = bucketList.reduce((s, b) => s + b.amt, 0);
    const overrideDiff = vatUsed - bucketTotal;
    if (Math.abs(overrideDiff) > 0.004 && bucketList.length) {
        bucketList.reduce((max, b) => (b.amt > max.amt ? b : max), bucketList[0]).amt += overrideDiff;
    }
    bucketList.forEach(b => rows.push({code: b.code, name: b.name, debit: b.amt, credit: 0}));
```

Note: the existing per-line VAT math in `renderJEPreview` already computes `vatAmt` per line — reuse it rather than duplicating, by accumulating into `vatBuckets` inside the existing `lineItems.forEach` and dropping the separate `glAccounts.input_vat` push. Whichever shape is cleaner in the actual code, the result must be: one preview row per distinct `input_vat_account_code`, override difference on the largest bucket, `??` row when a category is unmapped.

- [ ] **Step 2: Remove `input_vat` from `gl_accounts` payloads**

In `app/purchase_bills/views.py`, both `gl_accounts = {...}` dicts (create and edit routes) drop the `'input_vat'` entry. Grep the template for `glAccounts.input_vat` and remove remaining uses.

- [ ] **Step 3: Manual verification (live)**

With the dev server running, open `/purchase-bills/create` as an accountant, pick the vendor, add one V12DG line (2,240.00) and one V12SV line (560.00): the Journal Entry panel must show `10502 … 240.00` and `10503 … 60.00` as separate debit rows and balance. This is also re-verified in the main session after data setup.

- [ ] **Step 4: Commit**

```powershell
git add app/purchase_bills/templates/purchase_bills/form.html app/purchase_bills/views.py
git commit -m "feat: JE preview groups input VAT by category account"
```

---

### Task 8: Seed/fixture consistency

**Files:**
- Modify: `app/seeds/seed_data.py` (`seed_vat_categories`, line ~321)
- Modify: `app/fixtures.py` (line ~258)

- [ ] **Step 1: Map seeded 12% categories to the seed COA's input VAT account**

`seed_vat_categories()` runs after the COA seed, which creates `10501 Input VAT - Current`. Change the function body:

```python
    input_vat_acct = Account.query.filter_by(code='10501').first()
    input_vat_id = input_vat_acct.id if input_vat_acct else None

    vat_categories = [
        {'code': 'VATABLE', 'name': 'Vatable (12%)', 'rate': 12.00,
         'description': 'Standard VAT rate', 'input_vat_account_id': input_vat_id},
        {'code': 'VAT-EXEMPT', 'name': 'VAT-Exempt', 'rate': 0.00,
         'description': 'Transactions exempt from VAT', 'input_vat_account_id': None},
        {'code': 'ZERO-RATED', 'name': 'Zero-Rated', 'rate': 0.00,
         'description': 'Zero-rated transactions (exports, etc.)', 'input_vat_account_id': None},
        {'code': 'NON-VAT', 'name': 'Non-VAT', 'rate': 0.00,
         'description': 'Non-VAT transactions', 'input_vat_account_id': None},
    ]
```

and add `input_vat_account_id=cat_data['input_vat_account_id'],` to the `VATCategory(...)` constructor. Add `from app.accounts.models import Account` to the module imports if missing.

- [ ] **Step 2: Same for `app/fixtures.py`**

Lines 258-260 create three 12% categories. Look up the input VAT account the fixture COA creates (grep `10501` in `app/fixtures.py`); set `input_vat_account_id` on the three 12% categories the same way (None fallback if the fixture COA lacks one — model allows NULL; the form rule only gates new submissions).

- [ ] **Step 3: Full-suite check + commit**

Run: `python -m pytest -q --no-cov -m "not slow"`
Expected: only the pre-existing `test_bill_summary_label_present` failure (purchase-bill redesign workstream) remains.

```powershell
git add app/seeds/seed_data.py app/fixtures.py
git commit -m "chore: seeded/fixture 12% VAT categories map to seed COA input VAT account"
```

---

### Task 9: Live data changes + runbook (MAIN SESSION — not a subagent task)

Performed in the main session via the running app and Playwright browser (subagents don't share the browser session). Under the B-011 rule both accountants are active, so requests go pending and are cross-approved.

- [ ] **Step 1:** `flask db upgrade` against the dev DB (if not already run in Task 1), restart the dev server.
- [ ] **Step 2:** As `msantos`: submit UPDATE for V12 → input account 10502; submit CREATEs for V12CG→10501, V12DG→10502, V12SV→10503, V12IM→10504 (all 12%, names "Input Tax Capital Goods" etc., reason "Approved B-014 design 2026-06-12").
- [ ] **Step 3:** As `jreyes`: approve all five from the review pages.
- [ ] **Step 4:** Verify in DB (`scripts/audit_check.py`): vat_categories rows have the right `input_vat_account_id`; audit rows exist for each submission + approval.
- [ ] **Step 5:** Live JE check: new draft APV with one V12DG line and one V12SV line shows two input-VAT preview rows (10502/10503); save; stored JE matches; void it to keep the books clean (or keep as a test artifact — record either way in the runbook appendix).
- [ ] **Step 6:** Runbook: mark B-014 **Fixed** in the Bug Log (cite spec + commits); update the Appendix VAT Categories table with the four new categories and V12's mapping; note the JE-bucket regression check in scenario 19.
- [ ] **Step 7:** Commit + push all documentation.
