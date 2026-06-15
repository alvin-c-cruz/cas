# Accounts Payable Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the `purchase_bills` module and all "bill" identifiers to `accounts_payable`/`ap_` throughout the entire codebase — models, DB tables/columns, routes, templates, CSS, and tests.

**Architecture:** Task 1 (sequential) scaffolds the new `app/accounts_payable/` directory by copying files from the old module; Tasks 2–5 run in parallel rewriting each layer; Task 6 (sequential last) runs the DB migration, renames test files, runs the full suite, then deletes the old `app/purchase_bills/` module.

**Tech Stack:** Flask, SQLAlchemy, SQLite, Alembic (Flask-Migrate), Jinja2, Python 3

**Spec:** `docs/superpowers/specs/2026-06-15-accounts-payable-rename-design.md`

---

## Task 1: Module Scaffold (sequential — do first)

**Files:**
- Create directory: `app/accounts_payable/`
- Create directory: `app/accounts_payable/templates/accounts_payable/`
- Copy CSS: `app/static/accounts_payable_form.css` (copy of `purchase_bills_form.css`)

- [ ] **Step 1: Copy the old module to the new location**

```powershell
# Copy everything from old module
Copy-Item -Recurse app\purchase_bills app\accounts_payable

# Fix the nested template folder name: purchase_bills → accounts_payable
Rename-Item app\accounts_payable\templates\purchase_bills app\accounts_payable\templates\accounts_payable

# Copy CSS file under the new name (keep old file — it's referenced until Task 5 is done)
Copy-Item app\static\purchase_bills_form.css app\static\accounts_payable_form.css
```

- [ ] **Step 2: Verify the scaffold**

```powershell
Get-ChildItem app\accounts_payable -Recurse | Select-Object FullName
```

Expected: see `__init__.py`, `models.py`, `forms.py`, `views.py`, `utils.py`, and all HTML files under `templates/accounts_payable/`.

- [ ] **Step 3: Commit the scaffold**

```bash
git add app/accounts_payable/ app/static/accounts_payable_form.css
git commit -m "chore: scaffold app/accounts_payable from purchase_bills (pre-rename)"
```

---

## Task 2: Python Core — models, forms, utils (parallel after Task 1)

**Files:**
- Modify: `app/accounts_payable/__init__.py` (ensure empty)
- Rewrite: `app/accounts_payable/models.py`
- Rewrite: `app/accounts_payable/forms.py`
- Rewrite: `app/accounts_payable/utils.py`

### Step 2a: models.py

- [ ] **Rewrite `app/accounts_payable/models.py`**

Replace the entire file content. Key changes from the old `purchase_bills/models.py`:
- `class PurchaseBill` → `class AccountsPayable`
- `__tablename__ = 'purchase_bills'` → `__tablename__ = 'accounts_payable'`
- `bill_number = db.Column(...)` → `ap_number = db.Column(...)`
- `bill_date = db.Column(...)` → `ap_date = db.Column(...)`
- `class PurchaseBillItem` → `class AccountsPayableItem`
- `__tablename__ = 'purchase_bill_items'` → `__tablename__ = 'accounts_payable_items'`
- `bill_id` FK column → `ap_id`; FK target `'purchase_bills.id'` → `'accounts_payable.id'`
- `db.relationship('PurchaseBillItem', backref='bill', ...)` → `db.relationship('AccountsPayableItem', backref='ap', ...)`
- `class PurchaseBillAttachment` → `class AccountsPayableAttachment`
- `__tablename__ = 'purchase_bill_attachments'` → `__tablename__ = 'accounts_payable_attachments'`
- Attachment `bill_id` FK → `ap_id`; FK target `'purchase_bills.id'` → `'accounts_payable.id'`
- Attachment relationship `backref='bill'` → `backref='ap'`
- `generate_bill_number()` → `generate_ap_number()`; internal query uses `AccountsPayable.ap_number`
- `to_dict()` returns `'ap_number'` and `'ap_date'` keys (was `'bill_number'`, `'bill_date'`)
- `__repr__` uses `self.ap_number` (was `self.bill_number`)

Open `app/purchase_bills/models.py` and port every method — do NOT leave any `bill_number`, `bill_date`, `PurchaseBill`, `PurchaseBillItem`, `PurchaseBillAttachment` references. The `generate_ap_number()` function should still produce `AP-YYYY-MM-NNNN` format (the output format is unchanged; only the function name changes).

Critical snippet for `generate_ap_number`:

```python
def generate_ap_number(branch_id=None):
    from app.utils import ph_now
    now = ph_now()
    prefix = f"AP-{now.year}-{now.month:02d}-"
    last = AccountsPayable.query.filter(
        AccountsPayable.ap_number.like(f"{prefix}%")
    ).order_by(AccountsPayable.ap_number.desc()).first()
    if last and last.ap_number:
        try:
            seq = int(last.ap_number.rsplit('-', 1)[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1
    return f"{prefix}{seq:04d}"
```

### Step 2b: forms.py

- [ ] **Rewrite `app/accounts_payable/forms.py`**

Key changes:
- `class PurchaseBillForm(FlaskForm)` → `class AccountsPayableForm(FlaskForm)`
- Field `bill_number = StringField(...)` → `ap_number = StringField(...)`
- Field `bill_date = DateField(...)` → `ap_date = DateField(...)`
- `validate_due_date` references `self.bill_date.data` → `self.ap_date.data`

### Step 2c: utils.py

- [ ] **Rewrite `app/accounts_payable/utils.py`**

Key changes:
- `from app.purchase_bills.models import PurchaseBill` → `from app.accounts_payable.models import AccountsPayable`
- `def compute_bills_summary(branch_id)` → `def compute_ap_summary(branch_id)`
- All `PurchaseBill.` references → `AccountsPayable.`
- `PurchaseBill.bill_date` → `AccountsPayable.ap_date`
- `PurchaseBill.balance`, `.due_date`, `.status`, `.vendor_name`, `.branch_id` — these field names are unchanged; only `bill_date` → `ap_date`

- [ ] **Step 2d: Commit**

```bash
git add app/accounts_payable/models.py app/accounts_payable/forms.py app/accounts_payable/utils.py app/accounts_payable/__init__.py
git commit -m "feat: rewrite accounts_payable models, forms, utils (renamed from purchase_bills)"
```

---

## Task 3: Views (parallel after Task 1)

**Files:**
- Rewrite: `app/accounts_payable/views.py`

- [ ] **Rewrite `app/accounts_payable/views.py`**

Open `app/purchase_bills/views.py` as the base. Apply ALL of the following renames:

**Imports:**
```python
# Old
from app.purchase_bills.models import PurchaseBill, PurchaseBillItem, PurchaseBillAttachment
from app.purchase_bills.forms import PurchaseBillForm
from app.purchase_bills.utils import compute_bills_summary

# New
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem, AccountsPayableAttachment, generate_ap_number
from app.accounts_payable.forms import AccountsPayableForm
from app.accounts_payable.utils import compute_ap_summary
```

**Blueprint:**
```python
# Old
purchase_bills_bp = Blueprint('purchase_bills', __name__, template_folder='templates')

# New
accounts_payable_bp = Blueprint('accounts_payable', __name__, template_folder='templates')
```

**Constants and helpers:**
```python
# Old
VALID_BILL_STATUSES = {...}
def _get_bill_or_404(id): ...
def _bill_upload_dir(ap_id): ...
def _input_vat_buckets(bill): ...

# New
VALID_AP_STATUSES = {...}
def _get_ap_or_404(id): ...
def _ap_upload_dir(ap_id): ...
def _input_vat_buckets(ap): ...
```

**Route URLs:** Replace ALL `/purchase-bills` URL prefixes → `/accounts-payable`:
```python
@accounts_payable_bp.route('/accounts-payable')                        # list
@accounts_payable_bp.route('/accounts-payable/create', ...)            # create
@accounts_payable_bp.route('/accounts-payable/<int:id>')               # view
@accounts_payable_bp.route('/accounts-payable/<int:id>/edit', ...)     # edit
@accounts_payable_bp.route('/accounts-payable/<int:id>/post', ...)     # post
@accounts_payable_bp.route('/accounts-payable/<int:id>/cancel', ...)   # cancel
@accounts_payable_bp.route('/accounts-payable/<int:id>/void', ...)     # void
@accounts_payable_bp.route('/accounts-payable/<int:id>/print')         # print_ap
@accounts_payable_bp.route('/accounts-payable/export/excel')
@accounts_payable_bp.route('/accounts-payable/export/csv')
@accounts_payable_bp.route('/accounts-payable/print')                  # print_list
@accounts_payable_bp.route('/accounts-payable/<int:id>/attachments/upload', ...)
@accounts_payable_bp.route('/accounts-payable/attachments/<int:id>/download')
@accounts_payable_bp.route('/accounts-payable/attachments/<int:id>/preview')
@accounts_payable_bp.route('/accounts-payable/attachments/<int:id>/delete', ...)
```

**View function renames:**
```python
# Old → New
list_bills()      → list_ap()
print_bill()      → print_ap()
```

**Internal variable renames** (ALL occurrences in every view function):
```python
# Old → New
bill      → ap
bills     → ap_list
PurchaseBill  → AccountsPayable
PurchaseBillItem → AccountsPayableItem
PurchaseBillAttachment → AccountsPayableAttachment
PurchaseBillForm → AccountsPayableForm
generate_bill_number() → generate_ap_number()
compute_bills_summary() → compute_ap_summary()
_get_bill_or_404() → _get_ap_or_404()
_bill_upload_dir() → _ap_upload_dir()
_input_vat_buckets(bill) → _input_vat_buckets(ap)
VALID_BILL_STATUSES → VALID_AP_STATUSES
```

**Model field references** inside view functions:
```python
ap.bill_number → ap.ap_number
ap.bill_date   → ap.ap_date
```

**Upload path:**
```python
# Old
os.path.join(current_app.config['UPLOAD_FOLDER'], 'purchase_bills', str(ap_id))
# New
os.path.join(current_app.config['UPLOAD_FOLDER'], 'accounts_payable', str(ap_id))
```

**Template render calls** — change folder name `purchase_bills/` → `accounts_payable/`:
```python
render_template('accounts_payable/list.html', ...)
render_template('accounts_payable/form.html', ...)
render_template('accounts_payable/detail.html', ...)
render_template('accounts_payable/print.html', ...)
render_template('accounts_payable/print_list.html', ...)
```

**url_for calls inside views.py:**
```python
# Old → New
url_for('purchase_bills.list_ap')    # (these become accounts_payable.list_ap, accounts_payable.view, etc.)
url_for('purchase_bills.view', id=...) → url_for('accounts_payable.view', id=...)
url_for('purchase_bills.edit', id=...) → url_for('accounts_payable.edit', id=...)
# ... and all other url_for('purchase_bills.*') references
```

**Context variable passed to templates** — rename the template context key:
```python
# Old
render_template('...', bill=bill, ...)
# New
render_template('...', ap=ap, ...)
```

- [ ] **Commit**

```bash
git add app/accounts_payable/views.py
git commit -m "feat: rewrite accounts_payable views (renamed routes, functions, variables)"
```

---

## Task 4: Module Templates + CSS (parallel after Task 1)

**Files:**
- Modify: `app/accounts_payable/templates/accounts_payable/list.html`
- Modify: `app/accounts_payable/templates/accounts_payable/form.html`
- Modify: `app/accounts_payable/templates/accounts_payable/detail.html`
- Modify: `app/accounts_payable/templates/accounts_payable/print.html`
- Modify: `app/accounts_payable/templates/accounts_payable/print_list.html`
- Modify: `app/static/accounts_payable_form.css`

Note: These files were copied from `app/purchase_bills/` in Task 1. Edit them in-place.

### Template global substitutions (apply to ALL 5 HTML files)

In every template file under `app/accounts_payable/templates/accounts_payable/`, make the following replacements:

| Old | New |
|-----|-----|
| `url_for('purchase_bills.` | `url_for('accounts_payable.` |
| `url_for('purchase_bills.list_bills'` | `url_for('accounts_payable.list_ap'` |
| `url_for('purchase_bills.print_bill'` | `url_for('accounts_payable.print_ap'` |
| `{{ bill.bill_number }}` | `{{ ap.ap_number }}` |
| `{{ bill.bill_date` | `{{ ap.ap_date` |
| `{{ bill.` | `{{ ap.` |
| `{% if bill %}` | `{% if ap %}` |
| `{% if bill.` | `{% if ap.` |
| `bill.bill_number` | `ap.ap_number` |
| `bill.bill_date` | `ap.ap_date` |
| `bill.id` | `ap.id` |
| `form.bill_number` | `form.ap_number` |
| `form.bill_date` | `form.ap_date` |
| `purchase_bills_form.css` | `accounts_payable_form.css` |

### form.html specific

- [ ] **Update CSS link** (line ~14):
```html
<link rel="stylesheet" href="{{ url_for('static', filename='accounts_payable_form.css') }}">
```

- [ ] **Rename all `bill` template variables to `ap`** — these come from the view context. Replace `{{ bill.` → `{{ ap.`, `{% if bill %}` → `{% if ap %}`, `{% if bill.` → `{% if ap.`, `name="bill_number"` → `name="ap_number"`, `name="bill_date"` → `name="ap_date"` etc.

### CSS file: accounts_payable_form.css

- [ ] **Rename CSS classes** in `app/static/accounts_payable_form.css`:

```
.bill-summary-panel  → .ap-summary-panel
.page-purchase-bill  → .page-accounts-payable
```

Also update any occurrence of `purchase_bills` inside the CSS (e.g., in comments or class names).

- [ ] **Commit**

```bash
git add app/accounts_payable/templates/ app/static/accounts_payable_form.css
git commit -m "feat: rewrite accounts_payable templates and CSS (renamed from purchase_bills)"
```

---

## Task 5: Cross-Module References (parallel after Task 1)

**Files:**
- Modify: `app/__init__.py`
- Modify: `app/cash_disbursements/models.py`
- Modify: `app/journals/views.py`
- Modify: `app/journals/ap_journal_data.py`
- Modify: `app/reports/views.py`
- Modify: `app/templates/base.html`
- Modify: `app/dashboard/templates/dashboard/index.html`
- Modify: `app/vendors/templates/vendors/detail.html`
- Modify: `app/cash_disbursements/templates/cash_disbursements/detail.html`
- Modify: `app/journals/templates/journals/ap_journal.html`
- Modify: `app/journals/templates/journals/ap_journal_print.html`
- Modify: `app/reports/templates/reports/ap_aging.html`
- Modify: `app/sales_invoices/templates/sales_invoices/form.html`

### 5a: app/__init__.py

- [ ] **Update three lines in `app/__init__.py`**

Line 133 — upload folder creation:
```python
# Old
_os.makedirs(_os.path.join(app.config['UPLOAD_FOLDER'], 'purchase_bills'), exist_ok=True)
# New
_os.makedirs(_os.path.join(app.config['UPLOAD_FOLDER'], 'accounts_payable'), exist_ok=True)
```

Line 167 — model imports:
```python
# Old
from app.purchase_bills.models import PurchaseBill, PurchaseBillItem, PurchaseBillAttachment
# New
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem, AccountsPayableAttachment
```

Line 186 — blueprint import:
```python
# Old
from app.purchase_bills.views import purchase_bills_bp
# New
from app.accounts_payable.views import accounts_payable_bp
```

Line 207 — blueprint registration:
```python
# Old
app.register_blueprint(purchase_bills_bp)
# New
app.register_blueprint(accounts_payable_bp)
```

### 5b: app/cash_disbursements/models.py — CDVApLine

- [ ] **Update the `CDVApLine` model**

Find the `CDVApLine` class and change these fields:

```python
# Old
bill_id = db.Column(db.Integer, db.ForeignKey('purchase_bills.id'), nullable=False)
bill = db.relationship('PurchaseBill', foreign_keys=[bill_id])
bill_number = db.Column(db.String(50), nullable=False)

# New
ap_id = db.Column(db.Integer, db.ForeignKey('accounts_payable.id'), nullable=False)
accounts_payable = db.relationship('AccountsPayable', foreign_keys=[ap_id])
ap_number = db.Column(db.String(50), nullable=False)
```

Update `__repr__`:
```python
# Old
def __repr__(self): return f'<CDVApLine {self.bill_number}>'
# New
def __repr__(self): return f'<CDVApLine {self.ap_number}>'
```

Update `to_dict()`:
```python
# Old
'bill_id': self.bill_id,
'bill_number': self.bill_number,
# New
'ap_id': self.ap_id,
'ap_number': self.ap_number,
```

### 5c: app/journals/views.py — AP journal context

- [ ] **Update `_ap_journal_context` and `_entry_identity`** (lines 62–98):

```python
# Old (line 62)
from app.purchase_bills.models import PurchaseBill
# New
from app.accounts_payable.models import AccountsPayable
```

```python
# Old (lines 74–79)
voided_bills = PurchaseBill.query.filter(
    PurchaseBill.branch_id == branch_id,
    PurchaseBill.status == 'voided',
    PurchaseBill.bill_date >= period['date_from'],
    PurchaseBill.bill_date <= period['date_to'],
).order_by(PurchaseBill.bill_date, PurchaseBill.bill_number).all()
# New
voided_aps = AccountsPayable.query.filter(
    AccountsPayable.branch_id == branch_id,
    AccountsPayable.status == 'voided',
    AccountsPayable.ap_date >= period['date_from'],
    AccountsPayable.ap_date <= period['date_to'],
).order_by(AccountsPayable.ap_date, AccountsPayable.ap_number).all()
```

```python
# Old (lines 84–87)
refs = [e.reference for e in entries if e.reference]
bills = PurchaseBill.query.filter(PurchaseBill.bill_number.in_(refs)).all() if refs else []
bill_map = {b.bill_number: b for b in bills}
return period, matrix, bill_map
# New
refs = [e.reference for e in entries if e.reference]
aps = AccountsPayable.query.filter(AccountsPayable.ap_number.in_(refs)).all() if refs else []
ap_map = {a.ap_number: a for a in aps}
return period, matrix, ap_map
```

Also update the call to `build_columnar` on line 82 to pass `voided_aps` instead of `voided_bills`:
```python
matrix = build_columnar(posted, drafts, ap_id, wt_id, vat_ids, voided_bills=voided_aps)
```

Update `_entry_identity`:
```python
# Old (lines 90–98)
def _entry_identity(entry, bill_map):
    bill = bill_map.get(entry.reference)
    return (
        entry.reference or '—',
        (bill.vendor_invoice_number if bill else '') or '',
        (bill.vendor_name if bill else '') or '—',
        (bill.notes if bill else '') or '',
    )
# New
def _entry_identity(entry, ap_map):
    ap = ap_map.get(entry.reference)
    return (
        entry.reference or '—',
        (ap.vendor_invoice_number if ap else '') or '',
        (ap.vendor_name if ap else '') or '—',
        (ap.notes if ap else '') or '',
    )
```

Also update the caller of `_entry_identity` to pass `ap_map` and update the render_template call to pass `ap_map=ap_map` instead of `bill_map=bill_map`.

### 5d: app/journals/ap_journal_data.py

- [ ] **Update row dict key and field accesses**

Line 132 — where voided rows are appended:
```python
# Old
for bill in voided_bills:
    rows.append({'bill': bill, 'entry': None, 'cells': {}, 'is_draft': False, 'is_voided': True})
# New
for ap in voided_bills:
    rows.append({'ap': ap, 'entry': None, 'cells': {}, 'is_draft': False, 'is_voided': True})
```

Line 147 — `_row_sort_key`:
```python
# Old
if r['is_voided']:
    return (r['bill'].bill_date, r['bill'].bill_number)
# New
if r['is_voided']:
    return (r['ap'].ap_date, r['ap'].ap_number)
```

Lines ~220–224 — inside the xlsx builder where voided rows are serialized:
```python
# Old
if r.get('is_voided'):
    b = r['bill']
    line = [
        b.bill_date.strftime('%d-%b-%Y'),
        b.bill_number or '',
# New
if r.get('is_voided'):
    b = r['ap']
    line = [
        b.ap_date.strftime('%d-%b-%Y'),
        b.ap_number or '',
```

### 5e: app/reports/views.py

- [ ] **Update the AP aging report view**

Line 10:
```python
# Old
from app.purchase_bills.models import PurchaseBill
# New
from app.accounts_payable.models import AccountsPayable
```

All three query blocks (lines ~159, ~525, ~558) follow the same pattern — replace each:
```python
# Old
bills = PurchaseBill.query.filter(
    PurchaseBill.status.in_(['posted', 'partially_paid']),
    PurchaseBill.balance > 0,
    PurchaseBill.branch_id == current_branch_id
).order_by(PurchaseBill.vendor_name, PurchaseBill.due_date).all()
# New
bills = AccountsPayable.query.filter(
    AccountsPayable.status.in_(['posted', 'partially_paid']),
    AccountsPayable.balance > 0,
    AccountsPayable.branch_id == current_branch_id
).order_by(AccountsPayable.vendor_name, AccountsPayable.due_date).all()
```

Lines ~180–188 — dict construction for AP aging template:
```python
# Old
vendors[key]['bills'].append({
    'bill_id': bill.id,
    'bill_number': bill.bill_number,
    'bill_date': bill.bill_date,
    ...
})
# New
vendors[key]['bills'].append({
    'ap_id': bill.id,
    'ap_number': bill.ap_number,
    'ap_date': bill.ap_date,
    ...
})
```

(The loop variable `bill` can remain as-is since it's local to the loop; only the field accesses change.)

Lines 543, 576 — export column lists:
```python
# Old
columns = ['bill_number', 'vendor_name', 'bill_date', ...]
# New
columns = ['ap_number', 'vendor_name', 'ap_date', ...]
```

Lines ~534–536 and ~567–569 — similar dict constructions for export:
```python
# Old
'bill_number': bill.bill_number,
'bill_date': bill.bill_date,
# New
'ap_number': bill.ap_number,
'ap_date': bill.ap_date,
```

### 5f: Cross-module templates

- [ ] **`app/templates/base.html`** — sidebar + topbar nav links (lines ~1131, ~1361):

Replace all occurrences of:
```
url_for('purchase_bills.list_bills')  →  url_for('accounts_payable.list_ap')
url_for('purchase_bills.create')      →  url_for('accounts_payable.create')
request.endpoint.startswith('purchase_bills.')  →  request.endpoint.startswith('accounts_payable.')
```

- [ ] **`app/dashboard/templates/dashboard/index.html`** (line ~104):

```
url_for('purchase_bills.list_bills')  →  url_for('accounts_payable.list_ap')
```

- [ ] **`app/vendors/templates/vendors/detail.html`** (line ~160):

```
url_for('purchase_bills.view', id=bill.id)  →  url_for('accounts_payable.view', id=bill.id)
```

(The loop variable `bill` here refers to the vendor's bills list — `bill.id` is its primary key; the route name changes but the variable can stay.)

- [ ] **`app/cash_disbursements/templates/cash_disbursements/detail.html`** (line ~148):

```
url_for('purchase_bills.view', ...)  →  url_for('accounts_payable.view', ...)
ap_line.bill_id                      →  ap_line.ap_id
ap_line.bill_number                  →  ap_line.ap_number
```

- [ ] **`app/journals/templates/journals/ap_journal.html`** (lines 106–128):

```
row.bill.bill_date          →  row.ap.ap_date
row.bill.id                 →  row.ap.id
row.bill.bill_number        →  row.ap.ap_number
row.bill.vendor_invoice_number → row.ap.vendor_invoice_number
row.bill.vendor_name        →  row.ap.vendor_name
row.bill.notes              →  row.ap.notes
url_for('purchase_bills.view', id=row.bill.id)  →  url_for('accounts_payable.view', id=row.ap.id)
{% set bill = bill_map.get(...) %}  →  {% set ap = ap_map.get(...) %}
url_for('purchase_bills.view', id=bill.id)  →  url_for('accounts_payable.view', id=ap.id)
bill.vendor_invoice_number  →  ap.vendor_invoice_number
bill.vendor_name            →  ap.vendor_name
bill.notes                  →  ap.notes
```

Also update the template variable passed from views: `bill_map` context variable is now called `ap_map`. The template accesses it via `bill_map.get(...)` → change to `ap_map.get(...)`.

- [ ] **`app/journals/templates/journals/ap_journal_print.html`** (lines 94–98):

```
row.bill.bill_date          →  row.ap.ap_date
row.bill.bill_number        →  row.ap.ap_number
row.bill.vendor_invoice_number → row.ap.vendor_invoice_number
row.bill.vendor_name        →  row.ap.vendor_name
row.bill.notes              →  row.ap.notes
```

Also update `{% set bill = bill_map.get(...) %}` → `{% set ap = ap_map.get(...) %}` and all `bill.` → `ap.` in the non-voided rows, plus `url_for('purchase_bills.view', ...)` → `url_for('accounts_payable.view', ...)`.

- [ ] **`app/reports/templates/reports/ap_aging.html`** (line 91):

```
url_for('purchase_bills.view', id=bill.bill_id)  →  url_for('accounts_payable.view', id=bill.ap_id)
{{ bill.bill_number }}  →  {{ bill.ap_number }}
{{ bill.bill_date  }}   →  {{ bill.ap_date }}
```

(The loop variable `bill` here iterates `vendor.bills` — the list of dicts from `reports/views.py`. These dicts now have `ap_id`, `ap_number`, `ap_date` keys per the change in step 5e.)

- [ ] **`app/sales_invoices/templates/sales_invoices/form.html`** (line ~14):

```html
<!-- Old -->
<link rel="stylesheet" href="{{ url_for('static', filename='purchase_bills_form.css') }}">
<!-- New -->
<link rel="stylesheet" href="{{ url_for('static', filename='accounts_payable_form.css') }}">
```

- [ ] **Commit all cross-module changes**

```bash
git add app/__init__.py
git add app/cash_disbursements/models.py
git add app/journals/views.py app/journals/ap_journal_data.py
git add app/reports/views.py
git add app/templates/base.html
git add app/dashboard/templates/dashboard/index.html
git add app/vendors/templates/vendors/detail.html
git add "app/cash_disbursements/templates/cash_disbursements/detail.html"
git add app/journals/templates/journals/ap_journal.html
git add app/journals/templates/journals/ap_journal_print.html
git add app/reports/templates/reports/ap_aging.html
git add "app/sales_invoices/templates/sales_invoices/form.html"
git commit -m "feat: update all cross-module references for accounts_payable rename"
```

---

## Task 6: Migration + Tests + Cleanup (sequential — do last)

**Files:**
- Create: `migrations/versions/<hash>_rename_purchase_bills_to_accounts_payable.py` (auto-generated)
- Rename + modify: `tests/integration/test_accounts_payable_*.py` (8 files)
- Delete: `app/purchase_bills/` directory
- Delete: `app/static/purchase_bills_form.css`

### 6a: Generate and verify the migration

- [ ] **Generate migration**

```bash
flask db migrate -m "rename purchase_bills to accounts_payable"
```

- [ ] **Inspect the generated migration file**

Open the new file in `migrations/versions/`. Alembic auto-generates may not correctly handle table renames with column renames on SQLite. Verify the upgrade function contains EXACTLY this logic (rewrite it if needed):

```python
def upgrade():
    # 1. Rename purchase_bills table + 2 columns
    with op.batch_alter_table('purchase_bills',
                               new_table_name='accounts_payable') as batch_op:
        batch_op.alter_column('bill_number', new_column_name='ap_number')
        batch_op.alter_column('bill_date', new_column_name='ap_date')

    # 2. Rename purchase_bill_items + bill_id column
    with op.batch_alter_table('purchase_bill_items',
                               new_table_name='accounts_payable_items') as batch_op:
        batch_op.alter_column('bill_id', new_column_name='ap_id')

    # 3. Rename purchase_bill_attachments + bill_id column
    with op.batch_alter_table('purchase_bill_attachments',
                               new_table_name='accounts_payable_attachments') as batch_op:
        batch_op.alter_column('bill_id', new_column_name='ap_id')

    # 4. cdv_ap_lines — column renames only (table name unchanged)
    with op.batch_alter_table('cdv_ap_lines') as batch_op:
        batch_op.alter_column('bill_id', new_column_name='ap_id')
        batch_op.alter_column('bill_number', new_column_name='ap_number')


def downgrade():
    with op.batch_alter_table('cdv_ap_lines') as batch_op:
        batch_op.alter_column('ap_id', new_column_name='bill_id')
        batch_op.alter_column('ap_number', new_column_name='bill_number')

    with op.batch_alter_table('accounts_payable_attachments',
                               new_table_name='purchase_bill_attachments') as batch_op:
        batch_op.alter_column('ap_id', new_column_name='bill_id')

    with op.batch_alter_table('accounts_payable_items',
                               new_table_name='purchase_bill_items') as batch_op:
        batch_op.alter_column('ap_id', new_column_name='bill_id')

    with op.batch_alter_table('accounts_payable',
                               new_table_name='purchase_bills') as batch_op:
        batch_op.alter_column('ap_number', new_column_name='bill_number')
        batch_op.alter_column('ap_date', new_column_name='bill_date')
```

- [ ] **Run the migration**

```bash
flask db upgrade
```

Expected: no errors; the dev SQLite database now has `accounts_payable`, `accounts_payable_items`, `accounts_payable_attachments` tables with the renamed columns.

- [ ] **Start the dev server and smoke-test**

```bash
python flask_app.py
```

Verify:
1. `/accounts-payable` loads the AP list (old `/purchase-bills` should 404)
2. AP sidebar link works
3. AP aging report loads
4. AP Journal loads

### 6b: Rename and update test files

There are 8 test files. For each, perform the rename and update all internal references.

- [ ] **Rename files**

```bash
# Run from tests/integration/
git mv tests/integration/test_purchase_bill_views.py         tests/integration/test_accounts_payable_views.py
git mv tests/integration/test_purchase_bill_dates.py         tests/integration/test_accounts_payable_dates.py
git mv tests/integration/test_purchase_bill_je.py            tests/integration/test_accounts_payable_je.py
git mv tests/integration/test_purchase_bill_je_lifecycle.py  tests/integration/test_accounts_payable_je_lifecycle.py
git mv tests/integration/test_purchase_bill_override.py      tests/integration/test_accounts_payable_override.py
git mv tests/integration/test_purchase_bill_vat_buckets.py   tests/integration/test_accounts_payable_vat_buckets.py
git mv tests/integration/test_purchase_bill_detail.py        tests/integration/test_accounts_payable_detail.py
git mv tests/integration/test_purchase_bill_void.py          tests/integration/test_accounts_payable_void.py
```

- [ ] **Update each test file — apply these substitutions uniformly to all 8 files**

| Old | New |
|-----|-----|
| `from app.purchase_bills.models import PurchaseBill` | `from app.accounts_payable.models import AccountsPayable` |
| `from app.purchase_bills.models import PurchaseBill, PurchaseBillItem` | `from app.accounts_payable.models import AccountsPayable, AccountsPayableItem` |
| `pytestmark = [pytest.mark.purchase_bills` | `pytestmark = [pytest.mark.accounts_payable` |
| `PurchaseBill(` | `AccountsPayable(` |
| `PurchaseBillItem(` | `AccountsPayableItem(` |
| `bill_number=` | `ap_number=` |
| `bill_date=` | `ap_date=` |
| `b.bill_number` | `b.ap_number` |
| `b.bill_date` | `b.ap_date` |
| `bill.bill_number` | `ap.ap_number` |
| `bill.bill_date` | `ap.ap_date` |
| `'purchase_bills.` | `'accounts_payable.` |
| `'/purchase-bills` | `'/accounts-payable` |
| `purchase_bills/` | `accounts_payable/` |
| `make_bill(` | `make_ap(` |
| `def make_bill(` | `def make_ap(` |

Example of the renamed helper function in `test_accounts_payable_views.py`:

```python
# Old
def make_bill(db_session, vendor, branch, bill_number, status='posted',
              days_until_due=30, total_amount=Decimal('1000.00'), balance=None,
              bill_date=None):
    today = ph_now().date()
    b = PurchaseBill(
        bill_number=bill_number, vendor_id=vendor.id,
        ...
        bill_date=bill_date or today,
        ...
    )
    db_session.add(b)
    db_session.commit()
    return b

# New
def make_ap(db_session, vendor, branch, ap_number, status='posted',
            days_until_due=30, total_amount=Decimal('1000.00'), balance=None,
            ap_date=None):
    today = ph_now().date()
    b = AccountsPayable(
        ap_number=ap_number, vendor_id=vendor.id,
        ...
        ap_date=ap_date or today,
        ...
    )
    db_session.add(b)
    db_session.commit()
    return b
```

Update all call-sites of `make_bill(...)` → `make_ap(...)` throughout the test files.

### 6c: Run the test suite

- [ ] **Run all purchase-bill-related tests**

```bash
pytest tests/integration/test_accounts_payable_views.py -v
pytest tests/integration/test_accounts_payable_je.py -v
pytest tests/integration/test_accounts_payable_je_lifecycle.py -v
```

Fix any failures before continuing.

- [ ] **Run the full test suite**

```bash
pytest
```

Expected: same pass/fail counts as before the rename (no regressions).

### 6d: Cleanup — delete old module and CSS

- [ ] **Delete old module and CSS**

```bash
git rm -r app/purchase_bills/
git rm app/static/purchase_bills_form.css
```

- [ ] **Verify no remaining references to the old names**

```bash
grep -r "purchase_bills" app/ --include="*.py" --include="*.html" --include="*.css"
grep -r "PurchaseBill" app/ --include="*.py" --include="*.html"
grep -r "bill_number\|bill_date" app/ --include="*.py" --include="*.html"
```

Expected: zero results from the first two commands. The third may return legitimate hits (e.g., `check_number`, `phone_number`) — review each manually.

- [ ] **Final commit**

```bash
git add -A
git commit -m "feat: complete purchase_bills → accounts_payable rename

- Renamed module, models, forms, views, CSS, templates
- DB migration: purchase_bills→accounts_payable, bill_number→ap_number, bill_date→ap_date
- CDVApLine: bill_id→ap_id, bill_number→ap_number
- All cross-module imports and url_for calls updated
- 8 test files renamed and updated
- Old purchase_bills module deleted"
```

- [ ] **Push**

```bash
git push
```
