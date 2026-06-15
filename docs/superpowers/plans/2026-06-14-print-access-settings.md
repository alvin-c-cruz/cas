# Print Access Settings (SV + CD) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose `sv_print_access` and `cd_print_access` in the Company Settings form, add them to the seed, and gate the CDV Print button — while renaming the SV template's stale `'all'` value to `'draft_and_posted'`.

**Architecture:** All settings are stored as key-value rows in `app_settings` via `AppSettings`. The company settings form reads and writes them through `SETTINGS_KEYS`. Template gates read the setting value passed down from the view function and conditionally render the Print button.

**Tech Stack:** Flask, Flask-WTF (WTForms SelectField), Jinja2, SQLite via SQLAlchemy, pytest

---

## File Map

| File | Change |
|------|--------|
| `app/company_settings/forms.py` | Replace `APV_PRINT_ACCESS_CHOICES` with shared `PRINT_ACCESS_CHOICES`; add `sv_print_access` + `cd_print_access` SelectFields |
| `app/company_settings/views.py` | Append `'sv_print_access'`, `'cd_print_access'` to `SETTINGS_KEYS` |
| `app/company_settings/templates/company_settings/form.html` | Change Documents card to `settings-grid-3`; add two `render_field` calls |
| `app/seeds/seed_data.py` | Add 2 seed rows; update count comment and print statement 15 → 17 |
| `app/sales_invoices/templates/sales_invoices/detail.html` | Rename `'all'` → `'draft_and_posted'` in the print-access gate (line 109) |
| `app/cash_disbursements/views.py` | Read `cd_print_access` in `view()`; pass to `detail.html` |
| `app/cash_disbursements/templates/cash_disbursements/detail.html` | Wrap the Print link (line 76–77) in `cd_print_access` gate |
| `tests/integration/test_company_settings_views.py` | Add `TestPrintAccessSettings` class |
| `tests/integration/test_sv_print_access.py` | New — gate behaviour for SV |
| `tests/integration/test_cdv_print_access.py` | New — gate behaviour for CDV |

---

## Task 1: Add sv_print_access + cd_print_access to the settings form

**Files:**
- Modify: `app/company_settings/forms.py`
- Modify: `app/company_settings/views.py`
- Modify: `app/company_settings/templates/company_settings/form.html`
- Test: `tests/integration/test_company_settings_views.py`

- [ ] **Step 1.1 — Write failing tests**

Append this class to `tests/integration/test_company_settings_views.py`:

```python
class TestPrintAccessSettings:
    def test_sv_print_access_saved_when_posted(
            self, client, db_session, admin_user, main_branch):
        login(client)
        data = dict(VALID_FORM_DATA)
        data['apv_print_access'] = 'posted_only'
        data['sv_print_access'] = 'draft_and_posted'
        data['cd_print_access'] = 'draft_and_posted'
        resp = client.post('/settings', data=data, follow_redirects=True)
        assert resp.status_code == 200
        assert b'saved successfully' in resp.data
        assert AppSettings.get_setting('sv_print_access') == 'draft_and_posted'
        assert AppSettings.get_setting('cd_print_access') == 'draft_and_posted'

    def test_sv_cd_print_access_fields_rendered_on_settings_page(
            self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.get('/settings')
        html = resp.data.decode()
        assert 'sv_print_access' in html
        assert 'cd_print_access' in html
```

- [ ] **Step 1.2 — Run tests to confirm RED**

```
pytest tests/integration/test_company_settings_views.py::TestPrintAccessSettings -v
```

Expected: FAIL — `sv_print_access` field not in form or SETTINGS_KEYS.

- [ ] **Step 1.3 — Implement: forms.py**

Replace the existing `APV_PRINT_ACCESS_CHOICES` constant and update the form:

```python
# Replace this:
APV_PRINT_ACCESS_CHOICES = [
    ('posted_only', 'Posted only'),
    ('draft_and_posted', 'Draft and posted'),
]

# With this:
PRINT_ACCESS_CHOICES = [
    ('posted_only',      'Posted only'),
    ('draft_and_posted', 'Draft and posted'),
]
```

Update `apv_print_access` field to use `PRINT_ACCESS_CHOICES`:

```python
apv_print_access = SelectField(
    'APV Print Access', choices=PRINT_ACCESS_CHOICES, default='posted_only'
)
```

Add the two new fields after `apv_print_access`:

```python
sv_print_access = SelectField(
    'Sales Invoice Print Access', choices=PRINT_ACCESS_CHOICES, default='posted_only'
)
cd_print_access = SelectField(
    'CDV Print Access', choices=PRINT_ACCESS_CHOICES, default='posted_only'
)
```

- [ ] **Step 1.4 — Implement: views.py SETTINGS_KEYS**

In `app/company_settings/views.py`, find `SETTINGS_KEYS` and append after `'apv_print_access'`:

```python
SETTINGS_KEYS = [
    'company_name',
    'trade_name',
    'company_tin',
    'tin_branch_code',
    'rdo_code',
    'vat_registration_type',
    'company_address',
    'postal_code',
    'phone',
    'email',
    'fiscal_year_start',
    'officer_president',
    'officer_treasurer',
    'officer_secretary',
    'apv_print_access',
    'sv_print_access',
    'cd_print_access',
]
```

- [ ] **Step 1.5 — Implement: form.html template**

In `app/company_settings/templates/company_settings/form.html`, find the Documents card and update it:

```html
<h3 class="settings-section-label">Documents</h3>
<div class="card settings-card">
    <div class="card-body">
        <div class="settings-grid-3">
            {{ render_field(form.apv_print_access) }}
            {{ render_field(form.sv_print_access) }}
            {{ render_field(form.cd_print_access) }}
        </div>
    </div>
</div>
```

- [ ] **Step 1.6 — Run tests to confirm GREEN**

```
pytest tests/integration/test_company_settings_views.py::TestPrintAccessSettings -v
```

Expected: PASS.

- [ ] **Step 1.7 — Run full company settings test suite**

```
pytest tests/integration/test_company_settings_views.py -v
```

Expected: all existing tests still pass.

- [ ] **Step 1.8 — Commit**

```
git add app/company_settings/forms.py app/company_settings/views.py
git add "app/company_settings/templates/company_settings/form.html"
git add tests/integration/test_company_settings_views.py
git commit -m "feat: add sv_print_access and cd_print_access to company settings form"
```

---

## Task 2: Update seed_minimal()

**Files:**
- Modify: `app/seeds/seed_data.py`

- [ ] **Step 2.1 — Update seed_minimal() docstring**

Change the comment line:

```python
    - 15 app settings
```
to:
```python
    - 17 app settings
```

- [ ] **Step 2.2 — Add two seed rows**

After the `'apv_print_access'` row in the settings list:

```python
                {'key': 'apv_print_access',     'value': 'posted_only'},
                {'key': 'sv_print_access',      'value': 'posted_only'},
                {'key': 'cd_print_access',      'value': 'posted_only'},
```

- [ ] **Step 2.3 — Update the OK print statement**

Change:
```python
            print(f"  [OK] 15 app settings created")
```
to:
```python
            print(f"  [OK] 17 app settings created")
```

- [ ] **Step 2.4 — Commit**

```
git add app/seeds/seed_data.py
git commit -m "seed: add sv_print_access and cd_print_access to seed_minimal (15 → 17)"
```

---

## Task 3: SV gate — rename 'all' → 'draft_and_posted'

**Files:**
- Create: `tests/integration/test_sv_print_access.py`
- Modify: `app/sales_invoices/templates/sales_invoices/detail.html`

- [ ] **Step 3.1 — Write failing test**

Create `tests/integration/test_sv_print_access.py`:

```python
"""Integration tests for sv_print_access gate on the Sales Invoice detail page."""
import pytest
from decimal import Decimal
from datetime import date

from app.settings import AppSettings
from app.customers.models import Customer
from app.accounts.models import Account
from app.branches.models import Branch
from app.sales_invoices.models import SalesInvoice

pytestmark = [pytest.mark.sales_invoices, pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


@pytest.fixture
def _customer(db_session):
    c = Customer(code='C001', name='Test Customer', is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


@pytest.fixture
def _invoice(db_session, main_branch, _customer):
    inv = SalesInvoice(
        branch_id=main_branch.id,
        invoice_number='SI-2026-0001',
        invoice_date=date(2026, 6, 14),
        due_date=date(2026, 7, 14),
        customer_id=_customer.id,
        customer_name='Test Customer',
        notes='',
        status='draft',
        amount_paid=Decimal('0.00'),
    )
    db_session.add(inv)
    db_session.commit()
    return inv


class TestSvPrintAccessGate:
    def test_posted_only_hides_print_on_draft(
            self, client, db_session, admin_user, main_branch, _customer, _invoice):
        AppSettings.set_setting('sv_print_access', 'posted_only', 'system')
        login(client)
        resp = client.get(f'/sales-invoices/{_invoice.id}')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'print_invoice' not in html

    def test_draft_and_posted_shows_print_on_draft(
            self, client, db_session, admin_user, main_branch, _customer, _invoice):
        AppSettings.set_setting('sv_print_access', 'draft_and_posted', 'system')
        login(client)
        resp = client.get(f'/sales-invoices/{_invoice.id}')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'print_invoice' in html
```

- [ ] **Step 3.2 — Run test to confirm RED**

```
pytest tests/integration/test_sv_print_access.py::TestSvPrintAccessGate::test_draft_and_posted_shows_print_on_draft -v
```

Expected: FAIL — the template checks `sv_print_access == 'all'` so `'draft_and_posted'` is never matched; Print link is absent.

- [ ] **Step 3.3 — Implement: rename in detail.html**

In `app/sales_invoices/templates/sales_invoices/detail.html`, find line 109 and change:

```html
               or (sv_print_access == 'all' and invoice.status not in ('voided', 'cancelled')) %}
```
to:
```html
               or (sv_print_access == 'draft_and_posted' and invoice.status not in ('voided', 'cancelled')) %}
```

- [ ] **Step 3.4 — Run tests to confirm GREEN**

```
pytest tests/integration/test_sv_print_access.py -v
```

Expected: both tests PASS.

- [ ] **Step 3.5 — Commit**

```
git add "app/sales_invoices/templates/sales_invoices/detail.html"
git add tests/integration/test_sv_print_access.py
git commit -m "fix: rename sv_print_access gate value 'all' -> 'draft_and_posted'; add tests"
```

---

## Task 4: CD gate — read setting in view, gate Print button in template

**Files:**
- Create: `tests/integration/test_cdv_print_access.py`
- Modify: `app/cash_disbursements/views.py`
- Modify: `app/cash_disbursements/templates/cash_disbursements/detail.html`

- [ ] **Step 4.1 — Write failing tests**

Create `tests/integration/test_cdv_print_access.py`:

```python
"""Integration tests for cd_print_access gate on the CDV detail page."""
import pytest
from decimal import Decimal
from datetime import date

from app.settings import AppSettings
from app.vendors.models import Vendor
from app.accounts.models import Account
from app.cash_disbursements.models import CashDisbursementVoucher

pytestmark = [pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


@pytest.fixture
def _vendor(db_session):
    v = Vendor(code='V001', name='Test Vendor',
               check_payee_name='Test Vendor', is_active=True)
    db_session.add(v)
    db_session.commit()
    return v


@pytest.fixture
def _cash_account(db_session):
    a = Account(code='10101', name='Cash on Hand',
                account_type='Asset', normal_balance='debit', is_active=True)
    db_session.add(a)
    db_session.commit()
    return a


@pytest.fixture
def _draft_cdv(db_session, main_branch, _vendor, _cash_account):
    cdv = CashDisbursementVoucher(
        branch_id=main_branch.id,
        cdv_number='CD-2026-06-0001',
        cdv_date=date(2026, 6, 14),
        vendor_id=_vendor.id,
        vendor_name=_vendor.name,
        payment_method='cash',
        cash_account_id=_cash_account.id,
        notes='',
        status='draft',
        total_amount=Decimal('0.00'),
    )
    db_session.add(cdv)
    db_session.commit()
    return cdv


class TestCdvPrintAccessGate:
    def test_posted_only_hides_print_on_draft(
            self, client, db_session, admin_user, main_branch,
            _vendor, _cash_account, _draft_cdv):
        AppSettings.set_setting('cd_print_access', 'posted_only', 'system')
        login(client)
        resp = client.get(f'/cash-disbursements/{_draft_cdv.id}')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'print_cdv' not in html

    def test_draft_and_posted_shows_print_on_draft(
            self, client, db_session, admin_user, main_branch,
            _vendor, _cash_account, _draft_cdv):
        AppSettings.set_setting('cd_print_access', 'draft_and_posted', 'system')
        login(client)
        resp = client.get(f'/cash-disbursements/{_draft_cdv.id}')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'print_cdv' in html

    def test_posted_only_shows_print_on_posted(
            self, client, db_session, admin_user, main_branch,
            _vendor, _cash_account, _draft_cdv):
        _draft_cdv.status = 'posted'
        db_session.commit()
        AppSettings.set_setting('cd_print_access', 'posted_only', 'system')
        login(client)
        resp = client.get(f'/cash-disbursements/{_draft_cdv.id}')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'print_cdv' in html
```

- [ ] **Step 4.2 — Run tests to confirm RED**

```
pytest tests/integration/test_cdv_print_access.py -v
```

Expected: `test_posted_only_hides_print_on_draft` FAILS — Print is always shown. Others may fail due to missing template variable once gate is partially applied.

- [ ] **Step 4.3 — Implement: cash_disbursements/views.py — view()**

In `app/cash_disbursements/views.py`, find the `view()` function and add the setting read:

```python
@cash_disbursements_bp.route('/cash-disbursements/<int:id>')
@login_required
def view(id):
    cdv = _get_cdv_or_404(id)
    je_entries = _build_cdv_je_preview(cdv)
    cd_print_access = AppSettings.get_setting('cd_print_access', 'posted_only')
    return render_template('cash_disbursements/detail.html',
                           cdv=cdv, je_entries=je_entries, now=ph_now(),
                           cd_print_access=cd_print_access)
```

Also add the import at the top of the file (if not already present):

```python
from app.settings import AppSettings
```

- [ ] **Step 4.4 — Implement: cash_disbursements/detail.html — gate Print button**

In `app/cash_disbursements/templates/cash_disbursements/detail.html`, find the Print link (currently ungated at line 76–77):

```html
      <a href="{{ url_for('cash_disbursements.print_cdv', id=cdv.id) }}" target="_blank"
         rel="noopener noreferrer" class="btn btn-secondary">Print</a>
```

Wrap it with the access gate:

```html
      {% if (cd_print_access == 'posted_only' and cdv.status == 'posted')
         or (cd_print_access == 'draft_and_posted' and cdv.status not in ('voided', 'cancelled')) %}
      <a href="{{ url_for('cash_disbursements.print_cdv', id=cdv.id) }}" target="_blank"
         rel="noopener noreferrer" class="btn btn-secondary">Print</a>
      {% endif %}
```

- [ ] **Step 4.5 — Verify AppSettings import exists in cash_disbursements/views.py**

```
grep "from app.settings import AppSettings" app/cash_disbursements/views.py
```

Expected: one match. If not found, add it.

- [ ] **Step 4.6 — Run tests to confirm GREEN**

```
pytest tests/integration/test_cdv_print_access.py -v
```

Expected: all three tests PASS.

- [ ] **Step 4.7 — Commit**

```
git add app/cash_disbursements/views.py
git add "app/cash_disbursements/templates/cash_disbursements/detail.html"
git add tests/integration/test_cdv_print_access.py
git commit -m "feat: add cd_print_access gate to CDV detail page; add tests"
```

---

## Task 5: Full test suite + push

- [ ] **Step 5.1 — Run the full test suite**

```
pytest -x -q
```

Expected: all tests pass, no regressions.

- [ ] **Step 5.2 — Push**

```
git push
```
