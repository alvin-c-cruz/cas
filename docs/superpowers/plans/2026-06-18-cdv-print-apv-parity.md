# CDV Print — APV Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the CDV print page to parity with the APV print page (preview-then-print toolbar, APV layout/idiom, peso-sign rule, named signatories) and apply the matching ₱-summary + signature changes to the APV print page.

**Architecture:** Pure presentation change. Two Jinja templates plus one view kwarg edit — no models, no migration, no new routes, no access-control change. Verified with Flask integration tests that GET each print route and assert on rendered HTML.

**Tech Stack:** Flask + Jinja2 templates, pytest integration tests (test client), existing `tests/conftest.py` fixtures.

**Spec:** `docs/superpowers/specs/2026-06-18-cdv-print-apv-parity-design.md`

## Global Constraints

- **Names print `full_name`, never `username`.** Prepared = `created_by.full_name`; Approved = `posted_by.full_name`. Guard every access null-safe (`x.created_by.full_name if x.created_by else ''`).
- **Approved box is blank on drafts** (no `posted_by` yet). Checked box and CDV's Received-by-Payee box are always blank (manual signature).
- **Peso-sign rule (both vouchers):** line-item cells and JE cells = **no ₱**. Summary block = ₱ on the **first row** and on the **first row after each divider** only.
  - APV summary ₱ on: `Gross Amount`, `Net of VAT`, `Net Amount Payable`. Not on the Input-VAT / Withholding rows.
  - CDV summary ₱ on: `AP Applied`, `Net Cash Disbursed`. Not on Direct Expenses / Input VAT / Less-WHT rows.
- **No auto-print.** CDV must print only on the user's Print-button click — the `window.addEventListener('load', () => window.print())` script is removed.
- **No new context vars for APV.** `ap.created_by` / `ap.posted_by` already exist; the APV view is not touched.
- **No JS popups** (project rule) — none used here.
- Commit messages follow repo convention and end with the standard `Co-Authored-By:` / `Claude-Session:` trailers.

---

### Task 1: APV print.html — ₱ summary signs + signatory rework

Template-only change to `app/accounts_payable/templates/accounts_payable/print.html`. Adds ₱ to the three summary headline figures, and replaces the 3 signature boxes (`Prepared / Reviewed / Approved`, all blank) with `Prepared (named) / Checked (blank) / Approved (named)` using a printed-name line above each signature line.

**Files:**
- Modify: `app/accounts_payable/templates/accounts_payable/print.html`
- Test: `tests/integration/test_apv_print_content.py` (create)

**Interfaces:**
- Consumes: existing `print_ap` route at `/accounts-payable/<id>/print`; `ap.created_by`, `ap.posted_by` (User with `.full_name`), `ap.subtotal`, `ap.vat_amount`, `ap.total_amount`.
- Produces: the canonical signature-box markup (`.sig-title` / `.sig-name` / `.sig-line` with caption "Signature over Printed Name & Date") and the `.sig-name` CSS rule that Task 2 reuses verbatim.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_apv_print_content.py`:

```python
"""Integration tests for the APV print page (peso summary + signatories)."""
import pytest
from decimal import Decimal
from app.accounts.models import Account
from app.vendors.models import Vendor
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
from app.utils import ph_now

pytestmark = [pytest.mark.accounts_payable, pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


@pytest.fixture
def _vendor(db_session):
    v = Vendor(code='V001', name='Acme Supplies',
               check_payee_name='Acme Supplies', is_active=True)
    db_session.add(v); db_session.commit()
    return v


@pytest.fixture
def _expense_account(db_session):
    a = Account(code='60101', name='Office Supplies', account_type='Expense',
                normal_balance='debit', is_active=True)
    db_session.add(a); db_session.commit()
    return a


@pytest.fixture
def _posted_ap(db_session, main_branch, admin_user, accountant_user,
               _vendor, _expense_account):
    today = ph_now().date()
    bill = AccountsPayable(
        ap_number='APV-PRINT-1', vendor_id=_vendor.id, vendor_name=_vendor.name,
        vendor_tin='123-456-789', branch_id=main_branch.id,
        ap_date=today, due_date=today, payment_terms='Net 30',
        status='posted', created_by_id=admin_user.id, posted_by_id=accountant_user.id,
        posted_at=ph_now(),
        subtotal=Decimal('11200.00'), vat_amount=Decimal('1200.00'),
        total_before_wt=Decimal('11200.00'),
        withholding_tax_rate=Decimal('0.00'), withholding_tax_amount=Decimal('0.00'),
        total_amount=Decimal('11200.00'), amount_paid=Decimal('0.00'),
        balance=Decimal('11200.00'),
    )
    db_session.add(bill); db_session.flush()
    item = AccountsPayableItem(
        ap_id=bill.id, line_number=1, description='Test Service',
        amount=Decimal('11200.00'), vat_category='VATABLE', vat_rate=Decimal('12.00'),
        line_total=Decimal('11200.00'), vat_amount=Decimal('1200.00'),
        account_id=_expense_account.id,
    )
    db_session.add(item); db_session.commit()
    return bill


class TestApvPrintContent:
    def test_peso_on_summary_headline_figures(self, client, db_session, admin_user, _posted_ap):
        login(client)
        html = client.get(f'/accounts-payable/{_posted_ap.id}/print').data.decode()
        assert '₱11,200.00' in html      # Gross Amount + Net Amount Payable
        assert '₱10,000.00' in html      # Net of VAT (11200 - 1200)

    def test_no_peso_on_vat_rows(self, client, db_session, admin_user, _posted_ap):
        login(client)
        html = client.get(f'/accounts-payable/{_posted_ap.id}/print').data.decode()
        assert '₱1,200.00' not in html   # Less/Add Input VAT rows stay unsigned

    def test_signatory_labels(self, client, db_session, admin_user, _posted_ap):
        login(client)
        html = client.get(f'/accounts-payable/{_posted_ap.id}/print').data.decode()
        assert 'CHECKED BY' in html
        assert 'REVIEWED BY' not in html
        assert 'Signature over Printed Name' in html

    def test_signatory_names(self, client, db_session, admin_user, _posted_ap):
        login(client)
        html = client.get(f'/accounts-payable/{_posted_ap.id}/print').data.decode()
        assert 'Admin User' in html        # created_by.full_name -> Prepared
        assert 'Accountant User' in html   # posted_by.full_name  -> Approved

    def test_draft_approved_box_blank(self, client, db_session, admin_user, _posted_ap):
        _posted_ap.status = 'draft'
        _posted_ap.posted_by_id = None
        db_session.commit()
        login(client)
        html = client.get(f'/accounts-payable/{_posted_ap.id}/print').data.decode()
        assert 'Admin User' in html            # Prepared still shows
        assert 'Accountant User' not in html   # Approved blank on a draft
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/integration/test_apv_print_content.py -v`
Expected: FAIL — `test_signatory_labels` (no "CHECKED BY"), `test_peso_*` (no ₱), `test_signatory_names` (names not rendered).

- [ ] **Step 3: Add the `.sig-name` CSS and adjust the signature CSS**

In the `<style>` block, replace these two rules:

```css
  .sig-box .sig-title { font-size: 9px; font-weight: 700; color: #555; margin-bottom: 24px; }
  .sig-box .sig-line { border-top: 1px solid #666; padding-top: 2px; font-size: 9px; color: #555; }
```

with:

```css
  .sig-box .sig-title { font-size: 9px; font-weight: 700; color: #555; margin-bottom: 4px; }
  .sig-box .sig-name { margin-top: 22px; text-align: center; font-size: 11px; min-height: 14px; }
  .sig-box .sig-line { border-top: 1px solid #666; padding-top: 2px; font-size: 9px; color: #555; text-align: center; }
```

- [ ] **Step 4: Add ₱ to the three summary headline figures**

Edit 1 — Gross Amount:

```html
          <span class="sval">{{ '{:,.2f}'.format(ap.subtotal) }}</span>
```
→
```html
          <span class="sval">₱{{ '{:,.2f}'.format(ap.subtotal) }}</span>
```

Edit 2 — Net of VAT:

```html
          <span class="sval">{{ '{:,.2f}'.format(ap.subtotal - ap.vat_amount) }}</span>
```
→
```html
          <span class="sval">₱{{ '{:,.2f}'.format(ap.subtotal - ap.vat_amount) }}</span>
```

Edit 3 — Net Amount Payable:

```html
          <span class="netval">{{ '{:,.2f}'.format(ap.total_amount) }}</span>
```
→
```html
          <span class="netval">₱{{ '{:,.2f}'.format(ap.total_amount) }}</span>
```

Leave the `Less: Input VAT`, `Add: Input VAT`, and `Less: Withholding Tax` `.sval` spans unchanged (no ₱).

- [ ] **Step 5: Replace the signature row**

Replace the whole `.sig-row` block:

```html
  <div class="sig-row">
    <div class="sig-box">
      <div class="sig-title">PREPARED BY</div>
      <div class="sig-line">Name &amp; Date</div>
    </div>
    <div class="sig-box">
      <div class="sig-title">REVIEWED BY</div>
      <div class="sig-line">Name &amp; Date</div>
    </div>
    <div class="sig-box">
      <div class="sig-title">APPROVED BY</div>
      <div class="sig-line">Name &amp; Date</div>
    </div>
  </div>
```

with:

```html
  <div class="sig-row">
    <div class="sig-box">
      <div class="sig-title">PREPARED BY</div>
      <div class="sig-name">{{ ap.created_by.full_name if ap.created_by else '' }}</div>
      <div class="sig-line">Signature over Printed Name &amp; Date</div>
    </div>
    <div class="sig-box">
      <div class="sig-title">CHECKED BY</div>
      <div class="sig-name"></div>
      <div class="sig-line">Signature over Printed Name &amp; Date</div>
    </div>
    <div class="sig-box">
      <div class="sig-title">APPROVED BY</div>
      <div class="sig-name">{{ ap.posted_by.full_name if ap.posted_by else '' }}</div>
      <div class="sig-line">Signature over Printed Name &amp; Date</div>
    </div>
  </div>
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/integration/test_apv_print_content.py -v`
Expected: PASS (5 passed).

- [ ] **Step 7: Commit**

```bash
git add tests/integration/test_apv_print_content.py app/accounts_payable/templates/accounts_payable/print.html
git commit -m "feat(apv-print): peso summary signs + named Prepared/Checked/Approved signatories"
```

---

### Task 2: CDV print.html reskin to APV layout + `print_cdv` view

Rewrite `app/cash_disbursements/templates/cash_disbursements/print.html` into APV's idiom (Option A — preserve all CDV content) and update `print_cdv` to pass a `company` dict + `printed_at` value (dropping the `now=ph_now` callable). Adds the screen-only Print/Close toolbar and removes the auto-print script. Reuses the signature markup/CSS from Task 1, with a 4th `Received by (Payee)` box.

**Files:**
- Modify: `app/cash_disbursements/views.py` (`print_cdv`, ~lines 944-950)
- Rewrite: `app/cash_disbursements/templates/cash_disbursements/print.html`
- Test: `tests/integration/test_cdv_print_content.py` (create)

**Interfaces:**
- Consumes: `_build_cdv_je_preview(cdv)` → list of dicts `{code, name, debit, credit}` (unchanged); `AppSettings.get_setting`; `ph_now`; `cdv.created_by`/`cdv.posted_by` (`.full_name`); the `.sig-name` CSS from Task 1.
- Produces: template that reads `company` (dict: name/address/tin), `printed_at` (datetime), `cdv`, `je_entries`. No longer references `now` or `multi_branch`.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_cdv_print_content.py`:

```python
"""Integration tests for the CDV print page (APV-parity reskin)."""
import pytest
from decimal import Decimal
from datetime import date
from app.settings import AppSettings
from app.vendors.models import Vendor
from app.accounts.models import Account
from app.cash_disbursements.models import CashDisbursementVoucher, CDVExpenseLine

pytestmark = [pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


@pytest.fixture
def _vendor(db_session):
    v = Vendor(code='V001', name='Acme Supplies',
               check_payee_name='Acme Supplies', is_active=True)
    db_session.add(v); db_session.commit()
    return v


@pytest.fixture
def _expense_account(db_session):
    a = Account(code='60101', name='Office Supplies', account_type='Expense',
                normal_balance='debit', is_active=True)
    db_session.add(a); db_session.commit()
    return a


@pytest.fixture
def _cash_account(db_session):
    a = Account(code='10101', name='Cash on Hand', account_type='Asset',
                normal_balance='debit', is_active=True)
    db_session.add(a); db_session.commit()
    return a


@pytest.fixture
def _posted_cdv(db_session, main_branch, admin_user, accountant_user,
                _vendor, _expense_account, _cash_account):
    cdv = CashDisbursementVoucher(
        branch_id=main_branch.id, cdv_number='CD-2026-06-0007',
        cdv_date=date(2026, 6, 14), vendor_id=_vendor.id, vendor_name=_vendor.name,
        vendor_tin='001-002-003', payment_method='cash',
        cash_account_id=_cash_account.id, notes='Test disbursement', status='posted',
        created_by_id=admin_user.id, posted_by_id=accountant_user.id,
        total_ap_applied=Decimal('0.00'), total_expense=Decimal('5600.00'),
        total_vat=Decimal('600.00'), total_wt=Decimal('560.00'),
        total_amount=Decimal('5040.00'),
    )
    db_session.add(cdv); db_session.flush()
    line = CDVExpenseLine(
        cdv_id=cdv.id, line_number=1, description='Bond paper',
        amount=Decimal('5600.00'), vat_category='VATABLE', vat_rate=Decimal('12.00'),
        line_total=Decimal('5600.00'), vat_amount=Decimal('600.00'),
        account_id=_expense_account.id, wt_rate=Decimal('10.00'),
        wt_amount=Decimal('560.00'),
    )
    db_session.add(line); db_session.commit()
    return cdv


class TestCdvPrintContent:
    def test_no_auto_print_script(self, client, db_session, admin_user, _posted_cdv):
        login(client)
        html = client.get(f'/cash-disbursements/{_posted_cdv.id}/print').data.decode()
        assert "addEventListener('load'" not in html

    def test_print_and_close_toolbar(self, client, db_session, admin_user, _posted_cdv):
        login(client)
        html = client.get(f'/cash-disbursements/{_posted_cdv.id}/print').data.decode()
        assert 'onclick="window.print()"' in html
        assert f'href="/cash-disbursements/{_posted_cdv.id}"' in html   # Close -> view
        assert '>Close</a>' in html

    def test_renders_company_name(self, client, db_session, admin_user, _posted_cdv):
        AppSettings.set_setting('company_name', 'Mabuhay Trading Inc.', 'system')
        login(client)
        html = client.get(f'/cash-disbursements/{_posted_cdv.id}/print').data.decode()
        assert 'MABUHAY TRADING INC.' in html   # upper-cased header

    def test_peso_sign_rule(self, client, db_session, admin_user, _posted_cdv):
        login(client)
        html = client.get(f'/cash-disbursements/{_posted_cdv.id}/print').data.decode()
        assert '₱0.00' in html         # AP Applied (first summary row)
        assert '₱5,040.00' in html     # Net Cash Disbursed (after divider)
        assert '₱5,600.00' not in html  # Direct Expenses + Section B line stay unsigned
        assert '₱600.00' not in html    # Input VAT + Section B VAT stay unsigned

    def test_four_signatory_boxes(self, client, db_session, admin_user, _posted_cdv):
        login(client)
        html = client.get(f'/cash-disbursements/{_posted_cdv.id}/print').data.decode()
        for label in ('PREPARED BY', 'CHECKED BY', 'APPROVED BY', 'RECEIVED BY (PAYEE)'):
            assert label in html
        assert 'Admin User' in html        # created_by.full_name -> Prepared
        assert 'Accountant User' in html   # posted_by.full_name  -> Approved

    def test_draft_approved_box_blank(self, client, db_session, admin_user, _posted_cdv):
        _posted_cdv.status = 'draft'
        _posted_cdv.posted_by_id = None
        db_session.commit()
        login(client)
        html = client.get(f'/cash-disbursements/{_posted_cdv.id}/print').data.decode()
        assert 'Admin User' in html            # Prepared still shows
        assert 'Accountant User' not in html   # Approved blank on a draft
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/integration/test_cdv_print_content.py -v`
Expected: FAIL — current template auto-prints (`addEventListener('load'` present), has no Close link, no company header, no ₱ rule, 3 boxes without names.

- [ ] **Step 3: Update the `print_cdv` view**

In `app/cash_disbursements/views.py`, replace the body of `print_cdv` (~lines 944-950):

```python
@cash_disbursements_bp.route('/cash-disbursements/<int:id>/print')
@login_required
def print_cdv(id):
    cdv = _get_cdv_or_404(id)
    je_entries = _build_cdv_je_preview(cdv)
    return render_template('cash_disbursements/print.html',
                           cdv=cdv, je_entries=je_entries, now=ph_now)
```

with:

```python
@cash_disbursements_bp.route('/cash-disbursements/<int:id>/print')
@login_required
def print_cdv(id):
    cdv = _get_cdv_or_404(id)
    je_entries = _build_cdv_je_preview(cdv)
    company = {
        'name': AppSettings.get_setting('company_name', ''),
        'address': AppSettings.get_setting('company_address', ''),
        'tin': AppSettings.get_setting('company_tin', ''),
    }
    return render_template('cash_disbursements/print.html',
                           cdv=cdv, je_entries=je_entries,
                           company=company, printed_at=ph_now())
```

Verify `AppSettings` and `ph_now` are already imported at the top of the module (they are — used by `view()` and elsewhere). If a quick grep shows otherwise, add the import.

- [ ] **Step 4: Rewrite the CDV print template**

Replace the entire contents of `app/cash_disbursements/templates/cash_disbursements/print.html` with:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>CDV {{ cdv.cdv_number }}</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: Arial, sans-serif; font-size: 11px; color: #111; background: #fff; }

  .screen-only { }
  @media print {
    .screen-only { display: none !important; }
    @page { size: A4 portrait; margin: 15mm; }
  }

  .page-wrap { max-width: 740px; margin: 0 auto; padding: 24px; }

  .doc-header { text-align: center; border-bottom: 2px solid #111; padding-bottom: 10px; margin-bottom: 12px; }
  .doc-header .company-name { font-size: 16px; font-weight: 700; letter-spacing: .5px; }
  .doc-header .company-sub { font-size: 10px; color: #444; margin-top: 2px; }
  .doc-header .doc-title { font-size: 14px; font-weight: 700; letter-spacing: 2px; margin-top: 8px; }

  .info-row { display: flex; gap: 16px; margin-bottom: 10px; }
  .info-row table { border-collapse: collapse; flex: 1; font-size: 10px; }
  .info-row td { border: 1px solid #aaa; padding: 3px 7px; }
  .info-row td.label { background: #f0f0f0; font-weight: 600; width: 42%; }
  .vendor-header { background: #222; color: #fff; font-weight: 700; }

  .section-head { font-weight: 700; font-size: 10px; margin: 10px 0 0; padding: 3px 0; }
  .particulars { width: 100%; border-collapse: collapse; font-size: 10px; margin-bottom: 10px; }
  .particulars th { background: #222; color: #fff; padding: 4px 7px; text-align: left; border: 1px solid #555; }
  .particulars td { border: 1px solid #aaa; padding: 3px 7px; }
  .particulars td.amount { text-align: right; font-family: monospace; }

  .je-summary-row { display: flex; gap: 12px; margin-bottom: 10px; }
  .je-block { flex: 1; }
  .summary-block { flex: 0 0 230px; }
  .section-label { font-weight: 700; font-size: 10px; border: 1px solid #aaa; border-bottom: none; padding: 3px 7px; background: #f0f0f0; }
  .je-table { width: 100%; border-collapse: collapse; font-size: 10px; }
  .je-table th { background: #ddd; border: 1px solid #aaa; padding: 3px 7px; text-align: left; }
  .je-table th.num { text-align: right; }
  .je-table td { border: 1px solid #aaa; padding: 3px 7px; }
  .je-table td.num { text-align: right; font-family: monospace; }
  .je-table tr.totals { font-weight: 700; background: #f0f0f0; }
  .summary-inner { border: 1px solid #aaa; padding: 10px 12px; font-size: 10px; }
  .summary-row { display: flex; justify-content: space-between; margin-bottom: 7px; }
  .summary-row .slabel { color: #555; }
  .summary-row .sval { font-family: monospace; font-weight: 600; }
  .summary-row .sval.red { color: #c00; }
  .summary-divider-double { height: 2px; background: #888; margin: 8px 0; }
  .summary-net { display: flex; justify-content: space-between; }
  .summary-net .netlabel { font-weight: 700; font-size: 11px; }
  .summary-net .netval { font-family: monospace; font-weight: 700; font-size: 13px; color: #1565c0; }

  .notes-box { border: 1px solid #aaa; padding: 5px 8px; margin-bottom: 10px; background: #fffde7; font-size: 10px; }
  .notes-box .notes-label { font-weight: 700; font-size: 9px; color: #555; text-transform: uppercase; margin-right: 8px; }

  .sig-row { display: flex; margin-top: 8px; }
  .sig-box { flex: 1; border: 1px solid #aaa; border-right: none; padding: 5px 7px; min-height: 56px; }
  .sig-box:last-child { border-right: 1px solid #aaa; }
  .sig-box .sig-title { font-size: 9px; font-weight: 700; color: #555; margin-bottom: 4px; }
  .sig-box .sig-name { margin-top: 22px; text-align: center; font-size: 11px; min-height: 14px; }
  .sig-box .sig-line { border-top: 1px solid #666; padding-top: 2px; font-size: 9px; color: #555; text-align: center; }

  .audit-footer { margin-top: 6px; font-size: 9px; color: #888; text-align: center; border-top: 1px solid #ddd; padding-top: 4px; }

  .print-bar { margin-bottom: 20px; display: flex; gap: 8px; }
  .btn-print { padding: 8px 20px; background: #1565c0; color: #fff; border: none; border-radius: 4px; font-size: 13px; cursor: pointer; }
  .btn-close { padding: 8px 20px; background: #666; color: #fff; border: none; border-radius: 4px; font-size: 13px; cursor: pointer; text-decoration: none; display: inline-block; }
</style>
</head>
<body>
<div class="page-wrap">

  <div class="print-bar screen-only">
    <button class="btn-print" onclick="window.print()">Print</button>
    <a class="btn-close" href="{{ url_for('cash_disbursements.view', id=cdv.id) }}">Close</a>
  </div>

  <div class="doc-header">
    <div class="company-name">{{ company.name | upper }}</div>
    <div class="company-sub">
      {{ company.address }}{% if company.address and company.tin %} &nbsp;·&nbsp; {% endif %}{% if company.tin %}TIN: {{ company.tin }}{% endif %}
    </div>
    <div class="doc-title">CASH DISBURSEMENT VOUCHER</div>
  </div>

  <div class="info-row">
    <table>
      <tr><td class="label">CDV No.</td><td><strong>{{ cdv.cdv_number }}</strong></td></tr>
      <tr><td class="label">Date</td><td>{{ cdv.cdv_date.strftime('%d %B %Y') }}</td></tr>
      <tr><td class="label">Payment</td><td>{{ cdv.payment_method|replace('_',' ')|title }}</td></tr>
      {% if cdv.payment_method == 'check' %}
      <tr><td class="label">Check No.</td><td>{{ cdv.check_number or '—' }}</td></tr>
      <tr><td class="label">Check Date</td><td>{{ cdv.check_date.strftime('%d %B %Y') if cdv.check_date else '—' }}</td></tr>
      <tr><td class="label">Bank</td><td>{{ cdv.check_bank or '—' }}</td></tr>
      {% endif %}
      <tr><td class="label">Cash/Bank Acct</td><td>{{ (cdv.cash_account.code ~ ' : ' ~ cdv.cash_account.name) if cdv.cash_account else '—' }}</td></tr>
    </table>
    <table>
      <tr><td colspan="2" class="label vendor-header">PAY TO</td></tr>
      <tr><td colspan="2"><strong>{{ cdv.vendor_name }}</strong></td></tr>
      <tr><td class="label">TIN</td><td>{{ cdv.vendor_tin or '—' }}</td></tr>
    </table>
  </div>

  {% if cdv.ap_lines %}
  <div class="section-head">SECTION A — AP BILLS PAID</div>
  <table class="particulars">
    <thead>
      <tr>
        <th>AP Number</th>
        <th>Bill Date</th>
        <th style="text-align:right">Original Balance</th>
        <th style="text-align:right">Amount Applied</th>
      </tr>
    </thead>
    <tbody>
      {% for ap_line in cdv.ap_lines %}
      <tr>
        <td>{{ ap_line.ap_number }}</td>
        <td>{{ ap_line.accounts_payable.ap_date.strftime('%d %b %Y') if ap_line.accounts_payable else '—' }}</td>
        <td class="amount">{{ '{:,.2f}'.format(ap_line.original_balance) }}</td>
        <td class="amount">{{ '{:,.2f}'.format(ap_line.amount_applied) }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% endif %}

  {% if cdv.expense_lines %}
  <div class="section-head">SECTION B — DIRECT EXPENSES</div>
  <table class="particulars">
    <thead>
      <tr>
        <th style="width:4%">#</th>
        <th>Description</th>
        <th>Account Title</th>
        <th>VAT</th>
        <th>WHT</th>
        <th style="text-align:right">Amount</th>
        <th style="text-align:right">VAT Amt</th>
        <th style="text-align:right">WHT Amt</th>
      </tr>
    </thead>
    <tbody>
      {% for exp in cdv.expense_lines %}
      <tr>
        <td>{{ exp.line_number }}</td>
        <td>{{ exp.description or '—' }}</td>
        <td>{{ (exp.account.code ~ ' : ' ~ exp.account.name) if exp.account else '—' }}</td>
        <td>{{ exp.vat_category or 'None' }} ({{ '{:.2f}'.format(exp.vat_rate) }}%)</td>
        <td>{% if exp.withholding_tax %}{{ exp.withholding_tax.code }} ({{ '{:.2f}'.format(exp.wt_rate) }}%){% else %}—{% endif %}</td>
        <td class="amount">{{ '{:,.2f}'.format(exp.line_total) }}</td>
        <td class="amount">{{ '{:,.2f}'.format(exp.vat_amount) }}</td>
        <td class="amount">{{ '{:,.2f}'.format(exp.wt_amount) }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% endif %}

  <div class="je-summary-row">
    <div class="je-block">
      <div class="section-label">JOURNAL ENTRY</div>
      <table class="je-table">
        <thead>
          <tr>
            <th style="width:14%">Code</th>
            <th>Account Title</th>
            <th class="num" style="width:22%">Debit</th>
            <th class="num" style="width:22%">Credit</th>
          </tr>
        </thead>
        <tbody>
          {% set ns = namespace(td=0, tc=0) %}
          {% for e in je_entries %}
          {% set dr = e.debit or 0 %}
          {% set cr = e.credit or 0 %}
          {% set ns.td = ns.td + dr %}
          {% set ns.tc = ns.tc + cr %}
          <tr>
            <td>{{ e.code }}</td>
            <td {{ 'style="padding-left:18px;"' | safe if cr > 0 }}>{{ e.name }}</td>
            <td class="num">{% if dr %}{{ '{:,.2f}'.format(dr) }}{% endif %}</td>
            <td class="num">{% if cr %}{{ '{:,.2f}'.format(cr) }}{% endif %}</td>
          </tr>
          {% endfor %}
        </tbody>
        <tfoot>
          <tr class="totals">
            <td colspan="2">TOTAL</td>
            <td class="num">{{ '{:,.2f}'.format(ns.td) }}</td>
            <td class="num">{{ '{:,.2f}'.format(ns.tc) }}</td>
          </tr>
        </tfoot>
      </table>
    </div>

    <div class="summary-block">
      <div class="section-label">SUMMARY</div>
      <div class="summary-inner">
        <div class="summary-row">
          <span class="slabel">AP Applied:</span>
          <span class="sval">₱{{ '{:,.2f}'.format(cdv.total_ap_applied) }}</span>
        </div>
        <div class="summary-row">
          <span class="slabel">Direct Expenses:</span>
          <span class="sval">{{ '{:,.2f}'.format(cdv.total_expense) }}</span>
        </div>
        <div class="summary-row">
          <span class="slabel">Input VAT{{ ' ⚙' if cdv.vat_override }}:</span>
          <span class="sval">{{ '{:,.2f}'.format(cdv.total_vat) }}</span>
        </div>
        <div class="summary-row">
          <span class="slabel">Less: Withholding Tax{{ ' ⚙' if cdv.wt_override }}:</span>
          <span class="sval red">-{{ '{:,.2f}'.format(cdv.total_wt) }}</span>
        </div>
        <div class="summary-divider-double"></div>
        <div class="summary-net">
          <span class="netlabel">Net Cash Disbursed:</span>
          <span class="netval">₱{{ '{:,.2f}'.format(cdv.total_amount) }}</span>
        </div>
      </div>
    </div>
  </div>

  {% if cdv.notes %}
  <div class="notes-box">
    <span class="notes-label">Notes:</span>{{ cdv.notes }}
  </div>
  {% endif %}

  <div class="sig-row">
    <div class="sig-box">
      <div class="sig-title">PREPARED BY</div>
      <div class="sig-name">{{ cdv.created_by.full_name if cdv.created_by else '' }}</div>
      <div class="sig-line">Signature over Printed Name &amp; Date</div>
    </div>
    <div class="sig-box">
      <div class="sig-title">CHECKED BY</div>
      <div class="sig-name"></div>
      <div class="sig-line">Signature over Printed Name &amp; Date</div>
    </div>
    <div class="sig-box">
      <div class="sig-title">APPROVED BY</div>
      <div class="sig-name">{{ cdv.posted_by.full_name if cdv.posted_by else '' }}</div>
      <div class="sig-line">Signature over Printed Name &amp; Date</div>
    </div>
    <div class="sig-box">
      <div class="sig-title">RECEIVED BY (PAYEE)</div>
      <div class="sig-name"></div>
      <div class="sig-line">Signature over Printed Name &amp; Date</div>
    </div>
  </div>

  <div class="audit-footer">
    Status: {{ cdv.status|upper }}
    {% if cdv.created_by %}&nbsp;·&nbsp; Created by {{ cdv.created_by.username }}{% if cdv.created_at %} on {{ cdv.created_at.strftime('%d %b %Y') }}{% endif %}{% endif %}
    {% if cdv.posted_by %}&nbsp;·&nbsp; Posted by {{ cdv.posted_by.username }}{% if cdv.posted_at %} on {{ cdv.posted_at.strftime('%d %b %Y') }}{% endif %}{% endif %}
    &nbsp;|&nbsp; Printed by {{ current_user.username }} · {{ printed_at.strftime('%d %b %Y %I:%M %p') }}
  </div>

</div>
</body>
</html>
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/integration/test_cdv_print_content.py -v`
Expected: PASS (6 passed).

- [ ] **Step 6: Run the existing CDV print-access tests (no regression)**

Run: `pytest tests/integration/test_cdv_print_access.py -v`
Expected: PASS (3 passed) — the route, status codes, and gating are unchanged.

- [ ] **Step 7: Commit**

```bash
git add tests/integration/test_cdv_print_content.py app/cash_disbursements/views.py app/cash_disbursements/templates/cash_disbursements/print.html
git commit -m "feat(cdv-print): reskin to APV layout, preview-then-print, peso rule, signatories"
```

---

## Self-Review

**Spec coverage:**
- Preview sequence (toolbar, no auto-print) → Task 2 Steps 4 (template) + tests `test_no_auto_print_script`, `test_print_and_close_toolbar`. ✓
- CDV layout reskin (header, info-row, Section A/B, JE+Summary, notes, footer) → Task 2 Step 4. ✓
- `print_cdv` company dict + printed_at → Task 2 Step 3. ✓
- Peso rule, both vouchers → APV Task 1 Step 4 + tests; CDV Task 2 Step 4 + `test_peso_sign_rule`. ✓
- Signatories (named Prepared/Approved, blank Checked; APV 3-box, CDV 4-box incl. Payee; full_name; draft blank) → Task 1 Step 5 + Task 2 Step 4 + tests `test_signatory_*`, `test_four_signatory_boxes`, `test_draft_approved_box_blank`. ✓
- Non-goals (route-level print-access gap untouched; JE order/helper unchanged) → respected; `test_cdv_print_access` regression check in Task 2 Step 6. ✓

**Placeholder scan:** none — all code blocks are complete; no TBD/TODO.

**Type consistency:** `company` dict keys (name/address/tin) and `printed_at` produced by Task 2 Step 3 match the template in Step 4. JE loop reads dict keys `e.code/e.name/e.debit/e.credit` matching `_build_cdv_je_preview`'s output. `.sig-name` CSS rule defined in Task 1 Step 3 is reused (copied) in Task 2's style block. Signature labels (`CHECKED BY`, `RECEIVED BY (PAYEE)`) match test assertions exactly.

**Note for implementer:** `₱` and `⚙`/`·`/`—` are literal UTF-8 characters in the templates — save files as UTF-8 (the repo's existing CDV template already uses them, so the editor default is fine).
