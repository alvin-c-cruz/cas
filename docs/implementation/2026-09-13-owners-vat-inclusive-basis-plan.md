# Owners' VAT-Inclusive Reporting Basis — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give RIC's owners a second view of every financial report in which output VAT sits inside the related income account, input VAT inside the related expense account, and VAT remitted to the BIR is an expense by product line — without touching a single posted journal entry.

**Architecture:** One rules module (`app/reports/owners_ledger.py`) re-points the VAT legs of posted journal lines. One seam (`app/reports/ledger.py`) serves account balances and ledger lines to every report generator under a `reporting_basis` argument (`'gaap'` or `'owners'`). The GAAP path is a GROUP BY of the same SQL the reports run today and must produce identical figures. Nothing is persisted; Company Settings holds one switch and a product-category → VAT-expense-account map in the existing `app_settings` table.

**Tech Stack:** Flask 3.1, SQLAlchemy 2.0, SQLite, Jinja2, openpyxl, pytest. Spec: `docs/design/2026-09-13-owners-vat-inclusive-basis-design.md`.

## Global Constraints

- Never edit a posted journal entry. The lens is read-only. Posting code is untouched.
- Never hardcode a GL account code. VAT accounts come from `output_account_ids()`, `input_account_ids()`, and the `vat_payable_account_code` / `input_vat_carryover_account_code` settings (`app/vat_settlement/service.py`).
- Never call `datetime.now()`; use `ph_now()` from `app.utils`.
- The keyword is `reporting_basis` everywhere (`'gaap'` | `'owners'`), default `'gaap'`. It is NOT `basis` — `income_statement_by_product_line.py` already uses `basis` for its allocation rule.
- "Admin-type role" = `current_user.has_full_access` (admin or Chief Accountant), per `app/users/models.py`.
- Copy, verbatim: banner `Owners' basis: VAT included in income and expenses. Not for external reporting.`; General Journal adds `Not a book of record.`; settings switch label `Enable owners' reporting basis`; settings card title `Owners' View`; report control label `Basis:` with options `GAAP` and `Owners`.
- Settings keys, verbatim: `owners_basis_enabled` (`'1'`/`'0'`), `owners_basis_vat_expense_account:<product_category_id>` (account code).
- Untraced reasons, verbatim: `no_source_document`, `manual_entry`, `no_line_account`, `no_vat_on_document_lines`, `uncategorized_sales`, `no_output_vat_in_window`, `unmapped_category:<category name>`.
- Every new test module carries `pytestmark = [pytest.mark.owners_basis, pytest.mark.unit]` or `[pytest.mark.owners_basis, pytest.mark.integration]`; `owners_basis` is registered in `pytest.ini` (Task 1). `--strict-markers` is on.
- Run tests single-threaded (`pytest-xdist` is not installed). Commands below are run from `C:\envs\workspace\cas`.
- Commit after each task with the trailer lines shown in the task's commit step.

---

## File Structure

| File | Responsibility |
|---|---|
| `app/reports/basis.py` (new) | Constants, settings keys, `owners_basis_enabled()`, `vat_expense_account_map()`, `unmapped_categories()`, `can_switch_basis()`, `resolve_basis()` |
| `app/reports/owners_ledger.py` (new) | The rules. `remap(lines) -> (lines, RemapSummary)`, `distribute()`, `RemapSummary`, `Untraced` |
| `app/reports/ledger.py` (new) | The seam. `LedgerLine`, `fetch_lines()`, `period_balances()`, `ledger_lines()`, `owners_summary()`; per-request cache |
| `app/reports/financial.py` (modify) | TB / IS / BS / CF / GL generators gain `reporting_basis`, read only through `ledger.py` |
| `app/reports/two_column.py` (modify) | carry `basis_summary` through the two-column merge |
| `app/reports/general_journal_data.py` (modify) | `build_general_journal(entries, remapped=None)` |
| `app/reports/product_line.py`, `app/reports/income_statement_by_product_line.py` (modify) | `reporting_basis` through the revenue split; VAT-expense accounts attributed straight to their category |
| `app/reports/views.py` (modify) | `_basis()`; blueprint `before_request` + `context_processor`; pass basis + summary through 7 report families |
| `app/reports/templates/reports/_basis.html` (new) | `basis_switch()`, `basis_banner()` macros |
| 7 page templates, 7 print templates, `app/reports/statement_export.py` (modify) | switch, banner, reconciliation box, export note |
| `app/company_settings/views.py`, `app/company_settings/templates/company_settings/owners_view.html` (new), `app/templates/base.html` (modify) | Owners' View settings card + nav link |
| `tools/verify_owners_basis.py` (new) | prints the reconciliation box against a DB copy |
| `tests/unit/test_reports_basis.py`, `tests/unit/test_ledger_seam.py`, `tests/unit/test_owners_ledger.py`, `tests/integration/test_owners_basis_statements.py`, `tests/integration/test_owners_basis_views.py`, `tests/integration/test_owners_view_settings.py` (new) | tests |

---

### Task 1: Basis constants, settings helpers, marker registration

**Files:**
- Create: `app/reports/basis.py`
- Modify: `pytest.ini` (the `markers =` block, after the line `    models: Database model tests`)
- Test: `tests/unit/test_reports_basis.py`

**Interfaces:**
- Produces: `GAAP = 'gaap'`, `OWNERS = 'owners'`, `OWNERS_NOTE`, `NOT_BOOK_OF_RECORD`, `ENABLED_KEY`, `vat_expense_setting_key(category_id) -> str`, `owners_basis_enabled() -> bool`, `vat_expense_account_map() -> {category_id: Account|None}` (active categories only), `unmapped_categories() -> [ProductCategory]`, `can_switch_basis(user) -> bool`, `resolve_basis(user, args) -> str`.

- [ ] **Step 1: Register the marker**

In `pytest.ini`, inside the `markers =` block, add one line directly after `    models: Database model tests`:

```
    owners_basis: Owners' VAT-inclusive reporting basis
```

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/test_reports_basis.py`:

```python
"""resolve_basis() is the only gate to the owners' view: company switch ON, full-access
user, and ?basis=owners. Any one missing -> GAAP, silently (spec section 2)."""
import pytest

from app import db
from app.accounts.models import Account
from app.product_categories.models import ProductCategory
from app.settings import AppSettings
from app.reports import basis as B

pytestmark = [pytest.mark.owners_basis, pytest.mark.unit]


def _cat(code, name, active=True):
    c = ProductCategory(code=code, name=name, is_active=active)
    db.session.add(c); db.session.commit()
    return c


def _acct(code, name, atype='Other Expense', normal='Debit', active=True):
    a = Account(code=code, name=name, account_type=atype, normal_balance=normal, is_active=active)
    db.session.add(a); db.session.commit()
    return a


def test_disabled_by_default(app, db_session):
    assert B.owners_basis_enabled() is False


def test_resolve_is_gaap_when_switch_off(app, db_session, admin_user):
    assert B.resolve_basis(admin_user, {'basis': 'owners'}) == B.GAAP


def test_resolve_is_owners_for_full_access_with_switch_and_param(app, db_session, admin_user):
    AppSettings.set_setting(B.ENABLED_KEY, '1')
    assert B.resolve_basis(admin_user, {'basis': 'owners'}) == B.OWNERS


def test_resolve_is_gaap_without_param(app, db_session, admin_user):
    AppSettings.set_setting(B.ENABLED_KEY, '1')
    assert B.resolve_basis(admin_user, {}) == B.GAAP


def test_resolve_is_gaap_for_staff_even_with_param(app, db_session, staff_user):
    AppSettings.set_setting(B.ENABLED_KEY, '1')
    assert B.resolve_basis(staff_user, {'basis': 'owners'}) == B.GAAP
    assert B.can_switch_basis(staff_user) is False


def test_chief_accountant_may_switch(app, db_session, chief_accountant_user):
    AppSettings.set_setting(B.ENABLED_KEY, '1')
    assert B.can_switch_basis(chief_accountant_user) is True


def test_vat_expense_map_and_unmapped(app, db_session):
    tin = _cat('TIN', 'Tincan'); pla = _cat('PLA', 'Plastic'); _cat('OLD', 'Old', active=False)
    vat_tin = _acct('811001', 'VAT EXPENSE - TINCAN')
    AppSettings.set_setting(B.vat_expense_setting_key(tin.id), vat_tin.code)
    m = B.vat_expense_account_map()
    assert set(m) == {tin.id, pla.id}          # inactive category excluded
    assert m[tin.id].id == vat_tin.id and m[pla.id] is None
    assert [c.id for c in B.unmapped_categories()] == [pla.id]


def test_mapping_to_inactive_account_counts_as_unmapped(app, db_session):
    tin = _cat('TIN', 'Tincan')
    dead = _acct('811009', 'Dead', active=False)
    AppSettings.set_setting(B.vat_expense_setting_key(tin.id), dead.code)
    assert B.vat_expense_account_map()[tin.id] is None
```

- [ ] **Step 3: Run to verify failure**

Run: `python -m pytest tests/unit/test_reports_basis.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.reports.basis'`

- [ ] **Step 4: Implement `app/reports/basis.py`**

```python
"""Which basis a report is rendered on: GAAP (the books) or the owners' VAT-inclusive view.

Spec: docs/design/2026-09-13-owners-vat-inclusive-basis-design.md, section 2.

resolve_basis() is the ONLY gate. Three things must all hold for OWNERS: the company
switch is on, the user has full access (admin / Chief Accountant), and the request asked
for it with ?basis=owners. Anything else is GAAP, with no error: a stakeholder-facing user
who pastes an owners' URL simply gets the books.
"""
from app.settings import AppSettings

GAAP = 'gaap'
OWNERS = 'owners'
BASES = (GAAP, OWNERS)

ENABLED_KEY = 'owners_basis_enabled'
VAT_EXPENSE_KEY_PREFIX = 'owners_basis_vat_expense_account:'

OWNERS_NOTE = "Owners' basis: VAT included in income and expenses. Not for external reporting."
NOT_BOOK_OF_RECORD = 'Not a book of record.'


def owners_basis_enabled():
    return AppSettings.get_setting(ENABLED_KEY) == '1'


def vat_expense_setting_key(category_id):
    return f'{VAT_EXPENSE_KEY_PREFIX}{int(category_id)}'


def _active_categories():
    from app.product_categories.models import ProductCategory
    return ProductCategory.query.filter_by(is_active=True).order_by(ProductCategory.code).all()


def vat_expense_account_map():
    """{ProductCategory.id: Account or None} for every ACTIVE product category.

    A code that no longer resolves to an ACTIVE account is reported as None, so a
    retired account cannot silently swallow VAT expense."""
    from app.accounts.models import Account
    out = {}
    for cat in _active_categories():
        code = AppSettings.get_setting(vat_expense_setting_key(cat.id))
        acct = Account.query.filter_by(code=code, is_active=True).first() if code else None
        out[cat.id] = acct
    return out


def unmapped_categories():
    """Active categories with no usable VAT expense account, in code order."""
    m = vat_expense_account_map()
    return [c for c in _active_categories() if m.get(c.id) is None]


def can_switch_basis(user):
    """Full-access user on a company whose switch is on."""
    return bool(user is not None and getattr(user, 'is_authenticated', False)
                and user.has_full_access and owners_basis_enabled())


def resolve_basis(user, args):
    """GAAP unless the switch is on, the user may switch, AND args['basis'] == 'owners'."""
    if args.get('basis') == OWNERS and can_switch_basis(user):
        return OWNERS
    return GAAP
```

- [ ] **Step 5: Run to verify pass**

Run: `python -m pytest tests/unit/test_reports_basis.py -q`
Expected: `8 passed`

- [ ] **Step 6: Commit**

```bash
git add pytest.ini app/reports/basis.py tests/unit/test_reports_basis.py
git commit -m "feat(reports): owners' basis gate and settings helpers

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ejav4z8uSPiSMknfPtWywA"
```

---

### Task 2: The ledger seam, GAAP path

**Files:**
- Create: `app/reports/ledger.py`
- Test: `tests/unit/test_ledger_seam.py`

**Interfaces:**
- Consumes: `GAAP`, `OWNERS` from Task 1.
- Produces: `LedgerLine` namedtuple with fields `line_id, entry_id, entry_number, display_number, entry_date, entry_type, reference, description, line_number, reversed_entry_id, account_id, debit, credit, moved_from_account_id` (`debit`/`credit` are `Decimal` quantized to centavos); `CLOSING_TYPES`; `ZERO`; `fetch_lines(start, end, branch_id, exclude_closing=False) -> [LedgerLine]`; `period_balances(start, end, branch_id, reporting_basis='gaap', exclude_closing=False) -> {account_id: (Decimal debit, Decimal credit)}`; `ledger_lines(start, end, branch_id, reporting_basis='gaap', account_id=None, exclude_closing=False) -> [LedgerLine]`; `owners_summary(start, end, branch_id, exclude_closing=False)`. The OWNERS path raises `NotImplementedError` until Task 6.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_ledger_seam.py`:

```python
"""period_balances()/ledger_lines() on the GAAP basis must equal the per-account SQL the
reports ran before the seam existed: posted only, optional branch, optional date bounds,
optional closing-entry exclusion."""
from datetime import date
from decimal import Decimal
import pytest

from app import db
from app.accounts.models import Account
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.reports import ledger as L

pytestmark = [pytest.mark.owners_basis, pytest.mark.unit]


def _acct(code, atype, normal):
    a = Account(code=code, name=f'A{code}', account_type=atype, normal_balance=normal, is_active=True)
    db.session.add(a); db.session.commit()
    return a


def _post(branch_id, debit_acct, credit_acct, amount, number, on, entry_type='adjustment', status='posted'):
    amt = Decimal(str(amount))
    je = JournalEntry(entry_number=number, entry_date=on, description='d', reference=number,
                      entry_type=entry_type, branch_id=branch_id, status=status,
                      is_balanced=True, total_debit=amt, total_credit=amt)
    db.session.add(je); db.session.flush()
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=1, account_id=debit_acct.id,
                                    debit_amount=amt, credit_amount=Decimal('0')))
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=2, account_id=credit_acct.id,
                                    debit_amount=Decimal('0'), credit_amount=amt))
    db.session.commit()
    return je


@pytest.fixture
def books(db_session, main_branch, branch_manila):
    cash = _acct('10101', 'Asset', 'Debit')
    sales = _acct('40001', 'Revenue', 'Credit')
    re_ = _acct('30201', 'Equity', 'Credit')
    _post(main_branch.id, cash, sales, 100, 'J1', date(2026, 1, 10))
    _post(main_branch.id, cash, sales, 50, 'J2', date(2026, 2, 5))
    _post(main_branch.id, sales, re_, 150, 'J3', date(2026, 2, 28), entry_type='closing')
    _post(main_branch.id, cash, sales, 999, 'J4', date(2026, 2, 6), status='draft')
    _post(branch_manila.id, cash, sales, 7, 'J5', date(2026, 2, 7))
    return {'cash': cash, 'sales': sales, 're': re_, 'main': main_branch.id, 'manila': branch_manila.id}


def test_balances_posted_only_branch_scoped(books):
    b = L.period_balances(None, date(2026, 12, 31), books['main'])
    assert b[books['cash'].id] == (Decimal('150.00'), Decimal('0.00'))
    assert b[books['sales'].id] == (Decimal('150.00'), Decimal('150.00'))   # closing debit included
    assert books['re'].id in b


def test_balances_exclude_closing_and_bound_by_dates(books):
    b = L.period_balances(date(2026, 2, 1), date(2026, 2, 28), books['main'], exclude_closing=True)
    assert b[books['sales'].id] == (Decimal('0.00'), Decimal('50.00'))
    assert books['re'].id not in b


def test_balances_all_branches_when_branch_none(books):
    b = L.period_balances(None, None, None)
    assert b[books['cash'].id][0] == Decimal('157.00')


def test_ledger_lines_ordered_and_filterable(books):
    lines = L.ledger_lines(date(2026, 1, 1), date(2026, 12, 31), books['main'], account_id=books['sales'].id)
    assert [l.entry_number for l in lines] == ['J1', 'J2', 'J3']
    assert lines[0].credit == Decimal('100.00') and lines[0].debit == Decimal('0.00')
    assert lines[0].moved_from_account_id is None
    assert lines[0].description == 'd'                    # falls back to entry description
    assert lines[0].display_number == 'J1'


def test_owners_not_yet_available_raises(books):
    with pytest.raises(NotImplementedError):
        L.period_balances(None, None, books['main'], reporting_basis=L.OWNERS)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/unit/test_ledger_seam.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.reports.ledger'`

- [ ] **Step 3: Implement `app/reports/ledger.py`**

```python
"""The one seam every financial report reads posted journal lines through.

Two bases (app/reports/basis.py): GAAP is the posted lines exactly as booked; OWNERS is the
same lines with VAT legs re-pointed by app/reports/owners_ledger.py. Report generators never
query JournalEntryLine for balances themselves; they call period_balances() or
ledger_lines() here, so a basis is a parameter, not seven copies of VAT logic.

Filters mirror what the generators did before this seam: posted entries only; branch when
given; date bounds when given (None = unbounded); closing/closing-reversal entries excluded
only when the caller says so (P&L-period reports exclude them, balance reports include them).

The owners' path is computed once per (start, end, branch, exclude_closing) per request and
cached on flask.g, which the reports blueprint resets in before_request. Outside a request
nothing is cached.
"""
from collections import defaultdict, namedtuple
from decimal import Decimal

from flask import g, has_request_context
from sqlalchemy import func

from app import db
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.reports.basis import GAAP, OWNERS

CLOSING_TYPES = ('closing', 'closing_reversal')
ZERO = Decimal('0.00')

LedgerLine = namedtuple('LedgerLine', [
    'line_id', 'entry_id', 'entry_number', 'display_number', 'entry_date', 'entry_type',
    'reference', 'description', 'line_number', 'reversed_entry_id',
    'account_id', 'debit', 'credit', 'moved_from_account_id',
])


def _d(x):
    return Decimal(str(x or 0)).quantize(Decimal('0.01'))


def _filters(start, end, branch_id, exclude_closing):
    f = [JournalEntry.status == 'posted']
    if branch_id:
        f.append(JournalEntry.branch_id == branch_id)
    if start is not None:
        f.append(JournalEntry.entry_date >= start)
    if end is not None:
        f.append(JournalEntry.entry_date <= end)
    if exclude_closing:
        f.append(JournalEntry.entry_type.notin_(CLOSING_TYPES))
    return f


def fetch_lines(start, end, branch_id, exclude_closing=False):
    """Raw posted lines as LedgerLine, ordered (date, entry_number, line_number)."""
    rows = db.session.query(JournalEntryLine, JournalEntry).join(JournalEntry).filter(
        *_filters(start, end, branch_id, exclude_closing)
    ).order_by(JournalEntry.entry_date, JournalEntry.entry_number, JournalEntryLine.line_number).all()
    return [LedgerLine(
        line_id=l.id, entry_id=e.id, entry_number=e.entry_number, display_number=e.display_number,
        entry_date=e.entry_date, entry_type=e.entry_type, reference=e.reference,
        description=l.description or e.description, line_number=l.line_number,
        reversed_entry_id=e.reversed_entry_id, account_id=l.account_id,
        debit=_d(l.debit_amount), credit=_d(l.credit_amount), moved_from_account_id=None,
    ) for l, e in rows]


def _gaap_balances(start, end, branch_id, exclude_closing):
    rows = db.session.query(
        JournalEntryLine.account_id,
        func.coalesce(func.sum(JournalEntryLine.debit_amount), 0),
        func.coalesce(func.sum(JournalEntryLine.credit_amount), 0),
    ).join(JournalEntry).filter(*_filters(start, end, branch_id, exclude_closing)
                                ).group_by(JournalEntryLine.account_id).all()
    return {aid: (_d(d), _d(c)) for aid, d, c in rows}


def _owners(start, end, branch_id, exclude_closing):
    """(remapped lines, RemapSummary), cached per request. Task 6 fills this in."""
    raise NotImplementedError('owners basis lands in Task 6')


def period_balances(start, end, branch_id, reporting_basis=GAAP, exclude_closing=False):
    """{account_id: (debit_sum, credit_sum)} over posted lines in scope."""
    if reporting_basis != OWNERS:
        return _gaap_balances(start, end, branch_id, exclude_closing)
    lines, _ = _owners(start, end, branch_id, exclude_closing)
    acc = defaultdict(lambda: [ZERO, ZERO])
    for ln in lines:
        acc[ln.account_id][0] += ln.debit
        acc[ln.account_id][1] += ln.credit
    return {aid: (d, c) for aid, (d, c) in acc.items()}


def ledger_lines(start, end, branch_id, reporting_basis=GAAP, account_id=None, exclude_closing=False):
    """Posted lines in scope, ordered; optionally only one account's."""
    if reporting_basis != OWNERS:
        lines = fetch_lines(start, end, branch_id, exclude_closing)
    else:
        lines, _ = _owners(start, end, branch_id, exclude_closing)
    if account_id is not None:
        lines = [l for l in lines if l.account_id == account_id]
    return lines


def owners_summary(start, end, branch_id, exclude_closing=False):
    """The RemapSummary for the scope (what moved where, what stayed flagged)."""
    return _owners(start, end, branch_id, exclude_closing)[1]
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/unit/test_ledger_seam.py -q`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add app/reports/ledger.py tests/unit/test_ledger_seam.py
git commit -m "feat(reports): ledger seam with GAAP balances and lines

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ejav4z8uSPiSMknfPtWywA"
```

---
### Task 3: The rules module — sales side, purchase side, settlements, untraced

**Files:**
- Create: `app/reports/owners_ledger.py`
- Test: `tests/unit/test_owners_ledger.py`

**Interfaces:**
- Consumes: `LedgerLine`, `ZERO` from Task 2; `vat_expense_account_map` from Task 1; `input_account_ids`, `output_account_ids`, `SETTLEMENT_TYPES`, `quarter_bounds` from `app/vat_settlement/service.py`.
- Produces: `distribute(total, weights) -> {key: Decimal}`; `Untraced` namedtuple `(entry_number, entry_date, account_code, amount, reason)`; class `RemapSummary` with attributes `moved_to_income`, `moved_to_expense`, `moved_to_balance_sheet`, `vat_expense_by_category` (`{category_id: Decimal}`), `settlement_entries_dropped` (int), `untraced` (`[Untraced]`), properties `vat_expense_total`, `untraced_total`, `net_income_effect`, method `as_dict()`; `remap(lines) -> (list[LedgerLine], RemapSummary)`. In this task a debit to VAT Payable outside a settlement is kept with reason `manual_entry`; Task 4 turns it into VAT expense by product line.

Rule reference (spec section 1): output VAT credit on a sales document → the document lines' income accounts pro rata to their `vat_amount`; input VAT debit on a purchase document → the document lines' accounts pro rata; settlement entries dropped; everything else on a VAT account left in place and flagged.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_owners_ledger.py`:

```python
"""remap() re-points VAT legs of posted lines. Every case asserts two invariants on top of
its own expectation: each entry still balances after the lens, and the summary's
net_income_effect equals what moved into P&L accounts."""
from datetime import date
from decimal import Decimal
import pytest

from app import db
from app.accounts.models import Account
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.sales_vat_categories.models import SalesVATCategory
from app.settings import AppSettings
from app.vat_categories.models import VATCategory
from app.reports import ledger as L
from app.reports import owners_ledger as O

pytestmark = [pytest.mark.owners_basis, pytest.mark.unit]

D = Decimal


def _acct(code, name, atype, normal):
    a = Account(code=code, name=name, account_type=atype, normal_balance=normal, is_active=True)
    db.session.add(a); db.session.commit()
    return a


def _je(branch_id, number, on, legs, entry_type='sale', reversed_entry_id=None):
    """legs: [(account, debit, credit), ...] -> posted JournalEntry."""
    total = sum(D(str(d)) for _, d, _ in legs)
    je = JournalEntry(entry_number=number, entry_date=on, description=f'desc {number}',
                      reference=number, entry_type=entry_type, branch_id=branch_id,
                      status='posted', is_balanced=True, total_debit=total, total_credit=total,
                      reversed_entry_id=reversed_entry_id)
    db.session.add(je); db.session.flush()
    for i, (acct, d, c) in enumerate(legs, start=1):
        db.session.add(JournalEntryLine(entry_id=je.id, line_number=i, account_id=acct.id,
                                        debit_amount=D(str(d)), credit_amount=D(str(c))))
    db.session.commit()
    return je


@pytest.fixture
def coa(db_session):
    """Chart: AR, cash, two income accounts, two expense accounts, one asset, VAT accounts."""
    c = {
        'ar': _acct('112001', 'AR TRADE', 'Asset', 'Debit'),
        'cash': _acct('111001', 'CASH', 'Asset', 'Debit'),
        'ap': _acct('211001', 'AP TRADE', 'Liability', 'Credit'),
        'sales_tin': _acct('411001', 'SALES - TINCAN', 'Revenue', 'Credit'),
        'sales_pla': _acct('411005', 'SALES - PLASTIC', 'Revenue', 'Credit'),
        'supplies': _acct('721001', 'SUPPLIES', 'Administrative Expense', 'Debit'),
        'machine': _acct('151001', 'MACHINERY', 'Asset', 'Debit'),
        'output': _acct('213005', 'OUTPUT TAX', 'Liability', 'Credit'),
        'input': _acct('129008', 'INPUT TAX - DOMESTIC', 'Asset', 'Debit'),
        'payable': _acct('213004', 'VAT PAYABLE', 'Liability', 'Credit'),
    }
    db.session.add(SalesVATCategory(code='V12', name='VATABLE', rate=D('12.00'),
                                    transaction_nature='regular', output_vat_account_id=c['output'].id))
    db.session.add(VATCategory(code='V12DG', name='INPUT DG', rate=D('12.00'),
                               transaction_nature='domestic_goods', input_vat_account_id=c['input'].id))
    db.session.commit()
    AppSettings.set_setting('vat_payable_account_code', c['payable'].code)
    return c


def _si(branch_id, customer, je, items, number='SI-1', on=date(2026, 3, 10)):
    inv = SalesInvoice(branch_id=branch_id, invoice_number=number, invoice_date=on,
                       due_date=on, customer_id=customer.id, customer_name=customer.name,
                       customer_tin=customer.tin, status='posted', journal_entry_id=je.id)
    for i, (acct, amount, vat) in enumerate(items, start=1):
        inv.line_items.append(SalesInvoiceItem(
            line_number=i, description='x', amount=D(str(amount)), vat_rate=D('12.00'),
            vat_category='V12', vat_nature='regular', line_total=D(str(amount)),
            vat_amount=D(str(vat)), account_id=acct.id if acct else None))
    db.session.add(inv); db.session.commit()
    return inv


def _ap(branch_id, vendor, je, items, number='AP-1', on=date(2026, 3, 12)):
    ap = AccountsPayable(branch_id=branch_id, ap_number=number, ap_date=on, due_date=on,
                         payee_type='vendor', payee_id=vendor.id, vendor_id=vendor.id,
                         vendor_name=vendor.name, notes='', status='posted', journal_entry_id=je.id)
    for i, (acct, amount, vat) in enumerate(items, start=1):
        ap.line_items.append(AccountsPayableItem(
            line_number=i, description='x', amount=D(str(amount)), vat_rate=D('12.00'),
            line_total=D(str(amount)), vat_amount=D(str(vat)), account_id=acct.id))
    db.session.add(ap); db.session.commit()
    return ap


def _balanced(lines):
    by = {}
    for l in lines:
        d, c = by.get(l.entry_id, (D('0'), D('0')))
        by[l.entry_id] = (d + l.debit, c + l.credit)
    return all(d == c for d, c in by.values())


def _bal(lines, acct):
    return sum((l.debit - l.credit for l in lines if l.account_id == acct.id), D('0'))


def test_distribute_pro_rata_rounding_to_largest():
    out = O.distribute(D('100.00'), {'a': D('1'), 'b': D('1'), 'c': D('1')})
    assert out == {'a': D('33.34'), 'b': D('33.33'), 'c': D('33.33')}
    assert O.distribute(D('10.00'), {}) == {}
    assert O.distribute(D('0.00'), {'a': D('1')}) == {}
    assert O.distribute(D('-9.00'), {'a': D('2'), 'b': D('1')}) == {'a': D('-6.00'), 'b': D('-3.00')}


def test_no_vat_accounts_configured_is_passthrough(db_session, main_branch):
    cash = _acct('111001', 'CASH', 'Asset', 'Debit'); rev = _acct('411001', 'SALES', 'Revenue', 'Credit')
    _je(main_branch.id, 'J1', date(2026, 3, 1), [(cash, 112, 0), (rev, 0, 112)])
    raw = L.fetch_lines(None, None, main_branch.id)
    lines, s = O.remap(raw)
    assert lines == raw and s.untraced == [] and s.net_income_effect == D('0.00')


def test_output_vat_moves_to_income_accounts_pro_rata(coa, main_branch, vl_customer):
    je = _je(main_branch.id, 'J1', date(2026, 3, 10), [
        (coa['ar'], '224.00', 0), (coa['sales_tin'], 0, '100.00'),
        (coa['sales_pla'], 0, '100.00'), (coa['output'], 0, '24.00')])
    _si(main_branch.id, vl_customer, je, [(coa['sales_tin'], '112.00', '12.00'),
                                          (coa['sales_pla'], '112.00', '12.00')])
    lines, s = O.remap(L.fetch_lines(None, None, main_branch.id))
    assert _balanced(lines)
    assert _bal(lines, coa['output']) == D('0.00')
    assert _bal(lines, coa['sales_tin']) == D('-112.00')
    assert _bal(lines, coa['sales_pla']) == D('-112.00')
    moved = [l for l in lines if l.moved_from_account_id == coa['output'].id]
    assert len(moved) == 2 and all(l.credit > 0 and l.debit == 0 for l in moved)
    assert s.moved_to_income == D('24.00') and s.net_income_effect == D('24.00')
    assert s.untraced == []


def test_output_vat_rounding_goes_to_largest_line(coa, main_branch, vl_customer):
    je = _je(main_branch.id, 'J1', date(2026, 3, 10), [
        (coa['ar'], '0.10', 0), (coa['sales_tin'], 0, '0.07'), (coa['output'], 0, '0.03')])
    _si(main_branch.id, vl_customer, je, [(coa['sales_tin'], '0.05', '0.01'),
                                          (coa['sales_pla'], '0.05', '0.01'),
                                          (coa['sales_tin'], '0.05', '0.01')])
    lines, s = O.remap(L.fetch_lines(None, None, main_branch.id))
    assert _balanced(lines) and _bal(lines, coa['output']) == D('0.00')
    assert _bal(lines, coa['sales_tin']) == D('-0.09')      # 0.07 + 0.02 (largest weight takes the cent)
    assert _bal(lines, coa['sales_pla']) == D('-0.01')


def test_input_vat_moves_to_expense_and_asset(coa, main_branch, vl_vendor):
    je = _je(main_branch.id, 'J2', date(2026, 3, 12), [
        (coa['supplies'], '100.00', 0), (coa['machine'], '300.00', 0),
        (coa['input'], '48.00', 0), (coa['ap'], 0, '448.00')], entry_type='purchase')
    _ap(main_branch.id, vl_vendor, je, [(coa['supplies'], '112.00', '12.00'),
                                        (coa['machine'], '336.00', '36.00')])
    lines, s = O.remap(L.fetch_lines(None, None, main_branch.id))
    assert _balanced(lines) and _bal(lines, coa['input']) == D('0.00')
    assert _bal(lines, coa['supplies']) == D('112.00')
    assert _bal(lines, coa['machine']) == D('336.00')
    assert s.moved_to_expense == D('12.00') and s.moved_to_balance_sheet == D('36.00')
    assert s.net_income_effect == D('-12.00')


def test_settlement_entries_are_dropped(coa, main_branch):
    _je(main_branch.id, 'VS-1', date(2026, 4, 5), [
        (coa['output'], '24.00', 0), (coa['input'], 0, '10.00'), (coa['payable'], 0, '14.00')],
        entry_type='vat_settlement')
    lines, s = O.remap(L.fetch_lines(None, None, main_branch.id))
    assert lines == [] and s.settlement_entries_dropped == 1 and s.untraced == []


def test_manual_voucher_on_vat_account_is_kept_and_flagged(coa, main_branch):
    _je(main_branch.id, 'JV-1', date(2026, 3, 20), [
        (coa['output'], '5.00', 0), (coa['cash'], 0, '5.00')], entry_type='adjustment')
    lines, s = O.remap(L.fetch_lines(None, None, main_branch.id))
    assert _balanced(lines) and _bal(lines, coa['output']) == D('5.00')
    assert [(u.entry_number, u.account_code, u.amount, u.reason) for u in s.untraced] == \
        [('JV-1', '213005', D('5.00'), 'no_source_document')]
    assert s.untraced_total == D('5.00') and s.net_income_effect == D('0.00')


def test_document_line_without_account_keeps_its_share_flagged(coa, main_branch, vl_customer):
    je = _je(main_branch.id, 'J1', date(2026, 3, 10), [
        (coa['ar'], '224.00', 0), (coa['sales_tin'], 0, '200.00'), (coa['output'], 0, '24.00')])
    _si(main_branch.id, vl_customer, je, [(coa['sales_tin'], '112.00', '12.00'),
                                          (None, '112.00', '12.00')])
    lines, s = O.remap(L.fetch_lines(None, None, main_branch.id))
    assert _balanced(lines)
    assert _bal(lines, coa['output']) == D('-12.00')
    assert _bal(lines, coa['sales_tin']) == D('-212.00')
    assert s.untraced[0].reason == 'no_line_account' and s.untraced[0].amount == D('12.00')


def test_document_with_no_vat_lines_is_flagged(coa, main_branch, vl_customer):
    je = _je(main_branch.id, 'J1', date(2026, 3, 10), [
        (coa['ar'], '112.00', 0), (coa['sales_tin'], 0, '100.00'), (coa['output'], 0, '12.00')])
    _si(main_branch.id, vl_customer, je, [(coa['sales_tin'], '112.00', '0.00')])
    lines, s = O.remap(L.fetch_lines(None, None, main_branch.id))
    assert _bal(lines, coa['output']) == D('-12.00')
    assert s.untraced[0].reason == 'no_vat_on_document_lines'


def test_payable_debit_is_flagged_until_task_4(coa, main_branch):
    _je(main_branch.id, 'JV-2', date(2026, 4, 25), [
        (coa['payable'], '14.00', 0), (coa['cash'], 0, '14.00')], entry_type='adjustment')
    lines, s = O.remap(L.fetch_lines(None, None, main_branch.id))
    assert _bal(lines, coa['payable']) == D('14.00')
    assert s.untraced[0].reason == 'manual_entry'
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/unit/test_owners_ledger.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.reports.owners_ledger'`

- [ ] **Step 3: Implement `app/reports/owners_ledger.py`**

```python
"""Owners' basis lens: re-point the VAT legs of posted journal lines to their related accounts.

Spec: docs/design/2026-09-13-owners-vat-inclusive-basis-design.md, section 1.

Rules, applied line by line to posted LedgerLines (closing entries are the caller's business):

  1. Output VAT on a sales document (SI / CRV / sales memo)  -> the document lines' income
     accounts, pro rata to each line's vat_amount.
  2. Input VAT on a purchase document (AP / CDV / purchase memo) -> the document lines'
     accounts, pro rata (expense usually; an asset for capital goods).
  3. Any line of a vat_settlement / vat_settlement_reversal entry -> dropped (all legs are VAT).
  4. A debit to VAT Payable outside a settlement (a remittance) -> VAT expense by product
     line (Task 4; until then it is kept and flagged manual_entry).
  5. Anything else on a VAT account -> left where it is and listed in RemapSummary.untraced.

Pure-read. Never raises for data it cannot handle: it keeps the line and records why.
"""
from collections import defaultdict, namedtuple
from decimal import Decimal, ROUND_HALF_UP

from app import db
from app.accounts.models import Account
from app.accounts.account_types import BASE_CATEGORY
from app.settings import AppSettings
from app.reports.ledger import ZERO

CENT = Decimal('0.01')
SALES_KINDS = ('si', 'crv', 'sales_memo')
PURCHASE_KINDS = ('ap', 'cdv', 'purchase_memo')

Untraced = namedtuple('Untraced', ['entry_number', 'entry_date', 'account_code', 'amount', 'reason'])


class RemapSummary:
    """What the lens moved, and what it left in place with a reason.

    Signs: moved_to_income is credit-positive (VAT now inside income); moved_to_expense and
    moved_to_balance_sheet are debit-positive; vat_expense_by_category debit-positive.
    net_income_effect = owners' net income - GAAP net income for the same lines."""

    def __init__(self):
        self.moved_to_income = ZERO
        self.moved_to_expense = ZERO
        self.moved_to_balance_sheet = ZERO
        self.vat_expense_by_category = {}
        self.settlement_entries_dropped = 0
        self.untraced = []

    @property
    def vat_expense_total(self):
        return sum(self.vat_expense_by_category.values(), ZERO)

    @property
    def untraced_total(self):
        return sum((u.amount for u in self.untraced), ZERO)

    @property
    def net_income_effect(self):
        return self.moved_to_income - self.moved_to_expense - self.vat_expense_total

    def as_dict(self):
        return {
            'moved_to_income': float(self.moved_to_income),
            'moved_to_expense': float(self.moved_to_expense),
            'moved_to_balance_sheet': float(self.moved_to_balance_sheet),
            'vat_expense_total': float(self.vat_expense_total),
            'vat_expense_by_category': {k: float(v) for k, v in self.vat_expense_by_category.items()},
            'settlement_entries_dropped': self.settlement_entries_dropped,
            'untraced_total': float(self.untraced_total),
            'untraced': [{'entry_number': u.entry_number, 'entry_date': u.entry_date,
                          'account_code': u.account_code, 'amount': float(u.amount),
                          'reason': u.reason} for u in self.untraced],
            'net_income_effect': float(self.net_income_effect),
        }


def _q(x):
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


def distribute(total, weights):
    """Split `total` across keys pro rata to positive weights; the centavo rounding
    difference lands on the largest weight (first one on ties). {} when nothing to split."""
    total = _q(total)
    positive = {k: Decimal(w) for k, w in weights.items() if w and Decimal(w) > 0}
    if not positive or total == 0:
        return {}
    wsum = sum(positive.values())
    out = {k: _q(total * w / wsum) for k, w in positive.items()}
    diff = total - sum(out.values(), ZERO)
    if diff:
        largest = max(positive, key=lambda k: positive[k])
        out[largest] += diff
    return out


def _account_id_for_setting(key):
    code = AppSettings.get_setting(key)
    if not code:
        return None
    a = Account.query.filter_by(code=code).first()
    return a.id if a else None


def _vat_account_ids():
    from app.vat_settlement.service import input_account_ids, output_account_ids
    return (set(output_account_ids()), set(input_account_ids()),
            _account_id_for_setting('vat_payable_account_code'),
            _account_id_for_setting('input_vat_carryover_account_code'))


def _chunks(seq, n=500):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _source_docs(entry_ids):
    """{journal_entry_id: (kind, [(line_account_id, vat_amount), ...])} for the six
    document types, loaded in bulk. Drafts never carry a journal_entry_id, so no status
    filter is needed."""
    from app.accounts_payable.models import AccountsPayable
    from app.cash_disbursements.models import CashDisbursementVoucher
    from app.cash_receipts.models import CashReceiptVoucher
    from app.purchase_memos.models import PurchaseMemo
    from app.sales_invoices.models import SalesInvoice
    from app.sales_memos.models import SalesMemo
    specs = (('si', SalesInvoice, 'line_items'), ('crv', CashReceiptVoucher, 'revenue_lines'),
             ('sales_memo', SalesMemo, 'line_items'), ('ap', AccountsPayable, 'line_items'),
             ('cdv', CashDisbursementVoucher, 'expense_lines'),
             ('purchase_memo', PurchaseMemo, 'line_items'))
    out = {}
    for ids in _chunks(entry_ids):
        for kind, model, attr in specs:
            for doc in model.query.filter(model.journal_entry_id.in_(ids)).all():
                out[doc.journal_entry_id] = (
                    kind, [(li.account_id, Decimal(str(li.vat_amount or 0))) for li in getattr(doc, attr)])
    return out


class _Lens:
    def __init__(self, lines):
        self.output_ids, self.input_ids, self.payable_id, self.carry_id = _vat_account_ids()
        self.vat_ids = self.output_ids | self.input_ids | {i for i in (self.payable_id, self.carry_id) if i}
        self.summary = RemapSummary()
        self.accounts = {a.id: a for a in Account.query.all()}
        wanted = {l.entry_id for l in lines} | {l.reversed_entry_id for l in lines if l.reversed_entry_id}
        self.docs = _source_docs(wanted) if self.vat_ids else {}
        self.dropped_entries = set()

    # -- helpers -------------------------------------------------------------------------
    def _doc_for(self, ln):
        d = self.docs.get(ln.entry_id)
        if d is None and ln.reversed_entry_id:
            d = self.docs.get(ln.reversed_entry_id)   # a reversal follows its original's document
        return d

    def _keep(self, ln, reason, amount=None):
        """Leave (part of) a line on its VAT account and record why."""
        amt = (ln.debit - ln.credit) if amount is None else amount
        self.summary.untraced.append(Untraced(
            ln.entry_number, ln.entry_date, self.accounts[ln.account_id].code, abs(amt), reason))
        if amount is None:
            return ln
        return ln._replace(debit=max(amt, ZERO), credit=max(-amt, ZERO))

    def _moved(self, ln, target_id, amt):
        return ln._replace(account_id=target_id, debit=max(amt, ZERO), credit=max(-amt, ZERO),
                           moved_from_account_id=ln.account_id)

    def _spread(self, ln, doc_lines):
        """Rules 1 and 2: pro rata over the document lines' vat_amount, keyed by their account."""
        weights = defaultdict(lambda: ZERO)
        for acct_id, vat in doc_lines:
            if vat > 0:
                weights[acct_id] += vat          # acct_id may be None -> that share stays flagged
        shares = distribute(ln.debit - ln.credit, weights)
        if not shares:
            return [self._keep(ln, 'no_vat_on_document_lines')]
        out = []
        for acct_id, amt in shares.items():
            if acct_id is None or acct_id not in self.accounts:
                out.append(self._keep(ln, 'no_line_account', amt))
                continue
            out.append(self._moved(ln, acct_id, amt))
            base = BASE_CATEGORY.get(self.accounts[acct_id].account_type)
            if base == 'Revenue':
                self.summary.moved_to_income += -amt
            elif base == 'Expense':
                self.summary.moved_to_expense += amt
            else:
                self.summary.moved_to_balance_sheet += amt
        return out

    def _remit(self, ln):
        """Rule 4 lands in Task 4."""
        return [self._keep(ln, 'manual_entry')]

    # -- the rule table ------------------------------------------------------------------
    def vat_line(self, ln):
        doc = self._doc_for(ln)
        if ln.account_id in self.output_ids:
            if doc and doc[0] in SALES_KINDS:
                return self._spread(ln, doc[1])
            return [self._keep(ln, 'no_source_document')]
        if ln.account_id in self.input_ids:
            if doc and doc[0] in PURCHASE_KINDS:
                return self._spread(ln, doc[1])
            return [self._keep(ln, 'no_source_document')]
        if ln.account_id == self.payable_id and (ln.debit > ln.credit or ln.reversed_entry_id):
            if doc is None or doc[0] == 'cdv':
                return self._remit(ln)
            return [self._keep(ln, 'no_source_document')]
        return [self._keep(ln, 'manual_entry')]

    def run(self, lines):
        from app.vat_settlement.service import SETTLEMENT_TYPES
        out = []
        for ln in lines:
            if ln.entry_type in SETTLEMENT_TYPES:
                if ln.entry_id not in self.dropped_entries:
                    self.dropped_entries.add(ln.entry_id)
                    self.summary.settlement_entries_dropped += 1
                continue
            if ln.account_id not in self.vat_ids:
                out.append(ln)
                continue
            out.extend(self.vat_line(ln))
        return out


def remap(lines):
    """(remapped LedgerLines in input order, RemapSummary). Lines on non-VAT accounts pass
    through untouched; with no VAT accounts configured everything passes through."""
    lens = _Lens(lines)
    if not lens.vat_ids:
        return list(lines), lens.summary
    return lens.run(lines), lens.summary
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/unit/test_owners_ledger.py -q`
Expected: `10 passed`

- [ ] **Step 5: Commit**

```bash
git add app/reports/owners_ledger.py tests/unit/test_owners_ledger.py
git commit -m "feat(reports): owners' lens moves output/input VAT to related accounts

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ejav4z8uSPiSMknfPtWywA"
```

---

### Task 4: Remittances become VAT expense by product line; reversals follow their original

**Files:**
- Modify: `app/reports/owners_ledger.py` (replace `_Lens._remit`, add `_remittance_shares`)
- Test: `tests/unit/test_owners_ledger.py` (replace `test_payable_debit_is_flagged_until_task_4`, add five tests)

**Interfaces:**
- Consumes: `vat_expense_account_map()` (Task 1), `VatSettlement`, `quarter_bounds`.
- Produces: `RemapSummary.vat_expense_by_category` populated; `_remittance_shares(entry_date) -> {category_id_or_None: Decimal output VAT}`.

Rule 4 (spec): split the payment across product categories in proportion to each category's output VAT in the most recently settled quarter whose `settled_at` is on or before the payment date; if no settlement precedes it, the payment's own calendar quarter. Output VAT per category = sum of posted sales invoice items' `vat_amount` in that window grouped by the item's product category (product-less or category-less items count under `None`).

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_owners_ledger.py`, delete `test_payable_debit_is_flagged_until_task_4` and append:

```python
from datetime import datetime
from app.product_categories.models import ProductCategory
from app.products.models import Product
from app.vat_settlement.models import VatSettlement
from app.reports.basis import vat_expense_setting_key


@pytest.fixture
def lines_of_business(db_session, coa, main_branch, vl_customer, admin_user):
    """TINCAN 24.00 and PLASTIC 12.00 of output VAT invoiced in Q1 2026, one settlement of
    Q1 recorded on 2026-04-20, VAT expense accounts mapped for both categories."""
    tin = ProductCategory(code='TIN', name='Tincan'); pla = ProductCategory(code='PLA', name='Plastic')
    db.session.add_all([tin, pla]); db.session.commit()
    p_tin = Product(name='Can', category_id=tin.id, track_inventory=False)
    p_pla = Product(name='Tub', category_id=pla.id, track_inventory=False)
    db.session.add_all([p_tin, p_pla]); db.session.commit()
    je = _je(main_branch.id, 'J1', date(2026, 3, 10), [
        (coa['ar'], '336.00', 0), (coa['sales_tin'], 0, '200.00'),
        (coa['sales_pla'], 0, '100.00'), (coa['output'], 0, '36.00')])
    inv = _si(main_branch.id, vl_customer, je, [(coa['sales_tin'], '224.00', '24.00'),
                                                (coa['sales_pla'], '112.00', '12.00')])
    inv.line_items[0].product_id = p_tin.id; inv.line_items[1].product_id = p_pla.id
    db.session.add(VatSettlement(fiscal_year=2026, quarter=1, status='settled',
                                 output_vat=D('36.00'), net_payable=D('36.00'),
                                 settled_at=datetime(2026, 4, 20, 9, 0), settled_by_id=admin_user.id))
    db.session.commit()
    vat_tin = _acct('811001', 'VAT EXPENSE - TINCAN', 'Other Expense', 'Debit')
    vat_pla = _acct('811003', 'VAT EXPENSE - PLASTIC', 'Other Expense', 'Debit')
    AppSettings.set_setting(vat_expense_setting_key(tin.id), vat_tin.code)
    AppSettings.set_setting(vat_expense_setting_key(pla.id), vat_pla.code)
    return {'tin': tin, 'pla': pla, 'vat_tin': vat_tin, 'vat_pla': vat_pla, 'je': je}


def test_remittance_splits_by_output_vat_of_settled_quarter(coa, main_branch, lines_of_business):
    _je(main_branch.id, 'JV-2', date(2026, 4, 25), [
        (coa['payable'], '36.00', 0), (coa['cash'], 0, '36.00')], entry_type='adjustment')
    lines, s = O.remap(L.fetch_lines(date(2026, 4, 1), None, main_branch.id))
    assert _balanced(lines) and _bal(lines, coa['payable']) == D('0.00')
    assert _bal(lines, lines_of_business['vat_tin']) == D('24.00')
    assert _bal(lines, lines_of_business['vat_pla']) == D('12.00')
    assert s.vat_expense_by_category == {lines_of_business['tin'].id: D('24.00'),
                                         lines_of_business['pla'].id: D('12.00')}
    assert s.net_income_effect == D('-36.00') and s.untraced == []


def test_remittance_before_any_settlement_uses_its_own_quarter(coa, main_branch, lines_of_business):
    VatSettlement.query.delete(); db.session.commit()
    _je(main_branch.id, 'JV-3', date(2026, 3, 28), [
        (coa['payable'], '9.00', 0), (coa['cash'], 0, '9.00')], entry_type='adjustment')
    lines, s = O.remap(L.fetch_lines(date(2026, 3, 20), None, main_branch.id))
    assert _bal(lines, lines_of_business['vat_tin']) == D('6.00')     # 24:12 of Q1 2026
    assert _bal(lines, lines_of_business['vat_pla']) == D('3.00')


def test_remittance_with_no_output_vat_in_window_is_flagged(coa, main_branch, lines_of_business):
    _je(main_branch.id, 'JV-4', date(2027, 2, 1), [
        (coa['payable'], '5.00', 0), (coa['cash'], 0, '5.00')], entry_type='adjustment')
    VatSettlement.query.delete(); db.session.commit()
    lines, s = O.remap(L.fetch_lines(date(2027, 1, 1), None, main_branch.id))
    assert _bal(lines, coa['payable']) == D('5.00')
    assert s.untraced[0].reason == 'no_output_vat_in_window'


def test_unmapped_category_share_stays_flagged_others_move(coa, main_branch, lines_of_business):
    AppSettings.set_setting(vat_expense_setting_key(lines_of_business['pla'].id), '')
    _je(main_branch.id, 'JV-2', date(2026, 4, 25), [
        (coa['payable'], '36.00', 0), (coa['cash'], 0, '36.00')], entry_type='adjustment')
    lines, s = O.remap(L.fetch_lines(date(2026, 4, 1), None, main_branch.id))
    assert _balanced(lines)
    assert _bal(lines, lines_of_business['vat_tin']) == D('24.00')
    assert _bal(lines, coa['payable']) == D('12.00')
    assert s.untraced[0].reason == 'unmapped_category:Plastic' and s.untraced[0].amount == D('12.00')


def test_reversal_follows_original_document_and_nets_to_zero(coa, main_branch, vl_customer):
    je = _je(main_branch.id, 'J1', date(2026, 3, 10), [
        (coa['ar'], '112.00', 0), (coa['sales_tin'], 0, '100.00'), (coa['output'], 0, '12.00')])
    _si(main_branch.id, vl_customer, je, [(coa['sales_tin'], '112.00', '12.00')])
    _je(main_branch.id, 'JV-R', date(2026, 3, 15), [
        (coa['sales_tin'], '100.00', 0), (coa['output'], '12.00', 0), (coa['ar'], 0, '112.00')],
        entry_type='reversal', reversed_entry_id=je.id)
    lines, s = O.remap(L.fetch_lines(None, None, main_branch.id))
    assert _balanced(lines)
    assert _bal(lines, coa['output']) == D('0.00') and _bal(lines, coa['sales_tin']) == D('0.00')
    assert s.moved_to_income == D('0.00') and s.untraced == []
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/unit/test_owners_ledger.py -q`
Expected: the five new tests FAIL (payable balance stays, reason `manual_entry`); the other nine pass.

- [ ] **Step 3: Implement rule 4**

In `app/reports/owners_ledger.py`, add after `_source_docs`:

```python
def _remittance_shares(entry_date):
    """{category_id_or_None: output VAT} in the window rule 4 prescribes for a payment on
    entry_date: the most recently settled quarter on/before that date, else its own quarter."""
    from datetime import datetime, time, timedelta
    from sqlalchemy import func
    from app.products.models import Product
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
    from app.vat_settlement.models import VatSettlement
    from app.vat_settlement.service import quarter_bounds
    cutoff = datetime.combine(entry_date + timedelta(days=1), time.min)
    settled = (VatSettlement.query.filter(VatSettlement.status == 'settled',
                                          VatSettlement.settled_at < cutoff)
               .order_by(VatSettlement.settled_at.desc()).first())
    if settled:
        year, quarter = settled.fiscal_year, settled.quarter
    else:
        year, quarter = entry_date.year, (entry_date.month - 1) // 3 + 1
    qs, qe = quarter_bounds(year, quarter)
    rows = db.session.query(
        Product.category_id, func.coalesce(func.sum(SalesInvoiceItem.vat_amount), 0),
    ).select_from(SalesInvoiceItem).join(
        SalesInvoice, SalesInvoiceItem.invoice_id == SalesInvoice.id
    ).outerjoin(Product, SalesInvoiceItem.product_id == Product.id).filter(
        SalesInvoice.status.in_(('posted', 'partially_paid', 'paid')),
        SalesInvoice.invoice_date >= qs, SalesInvoice.invoice_date <= qe,
    ).group_by(Product.category_id).all()
    return {cid: Decimal(str(v)) for cid, v in rows if Decimal(str(v)) > 0}
```

In `_Lens.__init__`, after `self.dropped_entries = set()`, add:

```python
        from app.reports.basis import vat_expense_account_map
        from app.product_categories.models import ProductCategory
        self.vat_expense = {cid: (a.id if a else None) for cid, a in vat_expense_account_map().items()}
        self.category_names = {c.id: c.name for c in ProductCategory.query.all()}
        self._shares_cache = {}
```

Replace `_Lens._remit` with:

```python
    def _remit(self, ln):
        """Rule 4: a VAT remittance becomes VAT expense by product line."""
        if ln.entry_date not in self._shares_cache:
            self._shares_cache[ln.entry_date] = _remittance_shares(ln.entry_date)
        parts = distribute(ln.debit - ln.credit, self._shares_cache[ln.entry_date])
        if not parts:
            return [self._keep(ln, 'no_output_vat_in_window')]
        out = []
        for cid, amt in parts.items():
            if cid is None:
                out.append(self._keep(ln, 'uncategorized_sales', amt))
                continue
            target = self.vat_expense.get(cid)
            if not target:
                out.append(self._keep(ln, f'unmapped_category:{self.category_names.get(cid, cid)}', amt))
                continue
            out.append(self._moved(ln, target, amt))
            self.summary.vat_expense_by_category[cid] = self.summary.vat_expense_by_category.get(cid, ZERO) + amt
        return out
```

Update the module docstring's rule 4 line to: `4. A debit to VAT Payable outside a settlement (a remittance) -> VAT expense by product line, split by each category's output VAT in the last settled quarter on/before the payment date (else the payment's own quarter).`

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/unit/test_owners_ledger.py -q`
Expected: `14 passed`

- [ ] **Step 5: Commit**

```bash
git add app/reports/owners_ledger.py tests/unit/test_owners_ledger.py
git commit -m "feat(reports): owners' lens turns VAT remittances into VAT expense by product line

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ejav4z8uSPiSMknfPtWywA"
```

---

### Task 5: Owners' path of the seam, with a per-request cache

**Files:**
- Modify: `app/reports/ledger.py` (replace `_owners`)
- Modify: `app/reports/views.py` (add a `before_request` after `reports_bp = Blueprint(...)` on line 54)
- Test: `tests/unit/test_ledger_seam.py` (replace `test_owners_not_yet_available_raises`, add three tests)

**Interfaces:**
- Consumes: `remap` (Task 3/4).
- Produces: `period_balances(..., reporting_basis='owners')`, `ledger_lines(..., reporting_basis='owners')`, `owners_summary(...)` all working; `g._ledger_cache` reset per reports request.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_ledger_seam.py`, delete `test_owners_not_yet_available_raises` and append:

```python
from app.reports.owners_ledger import RemapSummary
from app.sales_vat_categories.models import SalesVATCategory
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem


@pytest.fixture
def vat_books(db_session, main_branch, vl_customer):
    ar = _acct('112001', 'Asset', 'Debit')
    sales = _acct('411001', 'Revenue', 'Credit')
    output = _acct('213005', 'Liability', 'Credit')
    db.session.add(SalesVATCategory(code='V12', name='V', rate=Decimal('12.00'),
                                    transaction_nature='regular', output_vat_account_id=output.id))
    db.session.commit()
    je = JournalEntry(entry_number='J1', entry_date=date(2026, 3, 10), description='d', reference='J1',
                      entry_type='sale', branch_id=main_branch.id, status='posted', is_balanced=True,
                      total_debit=Decimal('112'), total_credit=Decimal('112'))
    db.session.add(je); db.session.flush()
    db.session.add_all([
        JournalEntryLine(entry_id=je.id, line_number=1, account_id=ar.id, debit_amount=Decimal('112'), credit_amount=0),
        JournalEntryLine(entry_id=je.id, line_number=2, account_id=sales.id, debit_amount=0, credit_amount=Decimal('100')),
        JournalEntryLine(entry_id=je.id, line_number=3, account_id=output.id, debit_amount=0, credit_amount=Decimal('12'))])
    inv = SalesInvoice(branch_id=main_branch.id, invoice_number='SI-1', invoice_date=date(2026, 3, 10),
                       due_date=date(2026, 3, 10), customer_id=vl_customer.id, customer_name=vl_customer.name,
                       customer_tin=vl_customer.tin, status='posted', journal_entry_id=je.id)
    inv.line_items.append(SalesInvoiceItem(line_number=1, description='x', amount=Decimal('112'),
                                           vat_rate=Decimal('12'), vat_category='V12', vat_nature='regular',
                                           line_total=Decimal('112'), vat_amount=Decimal('12'), account_id=sales.id))
    db.session.add(inv); db.session.commit()
    return {'sales': sales, 'output': output, 'main': main_branch.id}


def test_owners_balances_fold_output_vat_into_sales(vat_books):
    b = L.period_balances(None, None, vat_books['main'], reporting_basis=L.OWNERS)
    assert b[vat_books['sales'].id] == (Decimal('0.00'), Decimal('112.00'))
    assert vat_books['output'].id not in b
    s = L.owners_summary(None, None, vat_books['main'])
    assert isinstance(s, RemapSummary) and s.moved_to_income == Decimal('12.00')


def test_owners_lines_annotate_moved_from(vat_books):
    lines = L.ledger_lines(None, None, vat_books['main'], reporting_basis=L.OWNERS, account_id=vat_books['sales'].id)
    assert [(l.credit, l.moved_from_account_id) for l in lines] == \
        [(Decimal('100.00'), None), (Decimal('12.00'), vat_books['output'].id)]


def test_owners_result_is_cached_within_a_request_only(app, vat_books, monkeypatch):
    import app.reports.owners_ledger as O
    calls = {'n': 0}
    real = O.remap
    def counting(lines):
        calls['n'] += 1
        return real(lines)
    monkeypatch.setattr(O, 'remap', counting)
    L.period_balances(None, None, vat_books['main'], reporting_basis=L.OWNERS)
    L.period_balances(None, None, vat_books['main'], reporting_basis=L.OWNERS)
    assert calls['n'] == 2                                  # no request -> no cache
    with app.test_request_context('/reports/income-statement'):
        from flask import g
        g._ledger_cache = {}
        L.period_balances(None, None, vat_books['main'], reporting_basis=L.OWNERS)
        L.ledger_lines(None, None, vat_books['main'], reporting_basis=L.OWNERS)
        L.owners_summary(None, None, vat_books['main'])
    assert calls['n'] == 3                                  # one remap for the three reads
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/unit/test_ledger_seam.py -q`
Expected: three new tests FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement**

In `app/reports/ledger.py`, replace `_owners`:

```python
def _owners(start, end, branch_id, exclude_closing):
    """(remapped lines, RemapSummary). Cached on g._ledger_cache inside a request; the
    reports blueprint resets that dict in before_request so nothing leaks across requests."""
    from app.reports.owners_ledger import remap
    key = (start, end, branch_id, exclude_closing)
    cache = getattr(g, '_ledger_cache', None) if has_request_context() else None
    if cache is not None and key in cache:
        return cache[key]
    result = remap(fetch_lines(start, end, branch_id, exclude_closing))
    if cache is not None:
        cache[key] = result
    return result
```

In `app/reports/views.py`, directly after `reports_bp = Blueprint('reports', __name__, template_folder='templates')`, add:

```python
@reports_bp.before_request
def _reset_ledger_cache():
    """app/reports/ledger.py memoises the owners' remap on g for the life of ONE request."""
    from flask import g
    g._ledger_cache = {}
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/unit/test_ledger_seam.py tests/unit/test_owners_ledger.py -q`
Expected: `21 passed`

- [ ] **Step 5: Commit**

```bash
git add app/reports/ledger.py app/reports/views.py tests/unit/test_ledger_seam.py
git commit -m "feat(reports): owners' basis served through the ledger seam with per-request cache

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ejav4z8uSPiSMknfPtWywA"
```

---
### Task 6: Trial Balance, Income Statement, Balance Sheet through the seam

**Files:**
- Modify: `app/reports/financial.py` (`generate_trial_balance` lines 23-107, `generate_income_statement` lines 125-168, `generate_balance_sheet` lines 171-244; imports at lines 12-20)
- Modify: `app/reports/two_column.py` (`merge_is_two_column`, lines 66-83)
- Test: `tests/integration/test_owners_basis_statements.py`

**Interfaces:**
- Consumes: `period_balances`, `owners_summary`, `ZERO` (Task 2/5); `GAAP`, `OWNERS` (Task 1).
- Produces: `generate_trial_balance(as_of_date=None, branch_id=None, reporting_basis='gaap')`, `generate_income_statement(start_date, end_date, branch_id=None, reporting_basis='gaap')`, `generate_balance_sheet(as_of_date=None, branch_id=None, reporting_basis='gaap')`. Each result dict gains `'reporting_basis'`; under owners the IS and BS gain `'basis_summary'` (the `RemapSummary.as_dict()`), and the BS may gain an equity line named `Prior years' VAT adjustment (owners' basis)`. `merge_is_two_column` output gains `'reporting_basis'` and `'basis_summary': {'mtd': ..., 'ytd': ...}`. `_period_balance` stays as-is (budget variance uses it).

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_owners_basis_statements.py`:

```python
"""Statement generators under both bases. Invariants: GAAP figures equal the hand-computed
books; owners' NI - GAAP NI == basis_summary.net_income_effect; owners' TB and BS balance."""
from datetime import date, datetime
from decimal import Decimal
import pytest

from app import db
from app.accounts.models import Account
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.sales_vat_categories.models import SalesVATCategory
from app.settings import AppSettings
from app.vat_categories.models import VATCategory
from app.year_end.models import FiscalYearClose
from app.reports.basis import GAAP, OWNERS
from app.reports.financial import (generate_trial_balance, generate_income_statement,
                                   generate_balance_sheet)
from app.reports.two_column import merge_is_two_column

pytestmark = [pytest.mark.owners_basis, pytest.mark.integration]
D = Decimal


def _acct(code, name, atype, normal, classification=None):
    a = Account(code=code, name=name, account_type=atype, normal_balance=normal,
                classification=classification, is_active=True)
    db.session.add(a); db.session.commit()
    return a


def _je(branch_id, number, on, legs, entry_type='sale'):
    total = sum(D(str(d)) for _, d, _ in legs)
    je = JournalEntry(entry_number=number, entry_date=on, description=number, reference=number,
                      entry_type=entry_type, branch_id=branch_id, status='posted',
                      is_balanced=True, total_debit=total, total_credit=total)
    db.session.add(je); db.session.flush()
    for i, (acct, d, c) in enumerate(legs, start=1):
        db.session.add(JournalEntryLine(entry_id=je.id, line_number=i, account_id=acct.id,
                                        debit_amount=D(str(d)), credit_amount=D(str(c))))
    db.session.commit()
    return je


@pytest.fixture
def books(db_session, main_branch, vl_customer, vl_vendor):
    """2026-03: one sale 100 + 12 VAT, one purchase 40 + 4.80 VAT. GAAP NI = 60.
    Owners: sales 112, supplies 44.80 -> NI 67.20 (effect +7.20)."""
    c = {
        'cash': _acct('111001', 'CASH', 'Asset', 'Debit', 'Current'),
        'ar': _acct('112001', 'AR', 'Asset', 'Debit', 'Current'),
        'input': _acct('129008', 'INPUT TAX', 'Asset', 'Debit', 'Current'),
        'ap': _acct('211001', 'AP', 'Liability', 'Credit', 'Current'),
        'output': _acct('213005', 'OUTPUT TAX', 'Liability', 'Credit', 'Current'),
        'capital': _acct('301001', 'CAPITAL', 'Equity', 'Credit'),
        're': _acct('302001', 'RETAINED EARNINGS', 'Equity', 'Credit'),
        'sales': _acct('411001', 'SALES', 'Revenue', 'Credit'),
        'supplies': _acct('721001', 'SUPPLIES', 'Administrative Expense', 'Debit'),
    }
    db.session.add(SalesVATCategory(code='V12', name='V', rate=D('12'), transaction_nature='regular',
                                    output_vat_account_id=c['output'].id))
    db.session.add(VATCategory(code='V12DG', name='I', rate=D('12'), transaction_nature='domestic_goods',
                               input_vat_account_id=c['input'].id))
    db.session.commit()
    _je(main_branch.id, 'CAP', date(2026, 1, 1), [(c['cash'], '1000.00', 0), (c['capital'], 0, '1000.00')],
        entry_type='opening_balance')
    sale = _je(main_branch.id, 'S1', date(2026, 3, 10), [
        (c['ar'], '112.00', 0), (c['sales'], 0, '100.00'), (c['output'], 0, '12.00')])
    inv = SalesInvoice(branch_id=main_branch.id, invoice_number='SI-1', invoice_date=date(2026, 3, 10),
                       due_date=date(2026, 3, 10), customer_id=vl_customer.id, customer_name=vl_customer.name,
                       customer_tin=vl_customer.tin, status='posted', journal_entry_id=sale.id)
    inv.line_items.append(SalesInvoiceItem(line_number=1, description='x', amount=D('112'), vat_rate=D('12'),
                                           vat_category='V12', vat_nature='regular', line_total=D('112'),
                                           vat_amount=D('12'), account_id=c['sales'].id))
    buy = _je(main_branch.id, 'P1', date(2026, 3, 12), [
        (c['supplies'], '40.00', 0), (c['input'], '4.80', 0), (c['ap'], 0, '44.80')], entry_type='purchase')
    ap = AccountsPayable(branch_id=main_branch.id, ap_number='AP-1', ap_date=date(2026, 3, 12),
                         due_date=date(2026, 3, 12), payee_type='vendor', payee_id=vl_vendor.id,
                         vendor_id=vl_vendor.id, vendor_name=vl_vendor.name, notes='', status='posted',
                         journal_entry_id=buy.id)
    ap.line_items.append(AccountsPayableItem(line_number=1, description='x', amount=D('44.80'), vat_rate=D('12'),
                                             line_total=D('44.80'), vat_amount=D('4.80'), account_id=c['supplies'].id))
    db.session.add_all([inv, ap]); db.session.commit()
    c['branch'] = main_branch.id
    return c


def test_gaap_income_statement_unchanged(books):
    is_ = generate_income_statement(date(2026, 1, 1), date(2026, 3, 31), branch_id=books['branch'])
    assert is_['net_income'] == 60.0 and is_['reporting_basis'] == GAAP
    assert 'basis_summary' not in is_


def test_owners_income_statement_and_identity(books):
    gaap = generate_income_statement(date(2026, 1, 1), date(2026, 3, 31), branch_id=books['branch'])
    own = generate_income_statement(date(2026, 1, 1), date(2026, 3, 31), branch_id=books['branch'],
                                    reporting_basis=OWNERS)
    assert own['net_income'] == pytest.approx(67.20)
    assert own['net_sales'] == pytest.approx(112.0)
    s = own['basis_summary']
    assert s['moved_to_income'] == 12.0 and s['moved_to_expense'] == 4.8 and s['untraced'] == []
    assert own['net_income'] - gaap['net_income'] == pytest.approx(s['net_income_effect'])


def test_two_column_merge_carries_summary(books):
    mtd = generate_income_statement(date(2026, 3, 1), date(2026, 3, 31), branch_id=books['branch'], reporting_basis=OWNERS)
    ytd = generate_income_statement(date(2026, 1, 1), date(2026, 3, 31), branch_id=books['branch'], reporting_basis=OWNERS)
    merged = merge_is_two_column(mtd, ytd)
    assert merged['reporting_basis'] == OWNERS
    assert merged['basis_summary']['ytd']['net_income_effect'] == pytest.approx(7.2)


def test_owners_trial_balance_balances_without_vat_accounts(books):
    tb = generate_trial_balance(date(2026, 3, 31), branch_id=books['branch'], reporting_basis=OWNERS)
    assert tb['is_balanced']
    codes = {r['code'] for r in tb['accounts']}
    assert '213005' not in codes and '129008' not in codes
    gaap = generate_trial_balance(date(2026, 3, 31), branch_id=books['branch'])
    assert {r['code'] for r in gaap['accounts']} >= {'213005', '129008'}


def test_owners_balance_sheet_balances_and_drops_vat(books):
    gaap = generate_balance_sheet(date(2026, 3, 31), branch_id=books['branch'])
    own = generate_balance_sheet(date(2026, 3, 31), branch_id=books['branch'], reporting_basis=OWNERS)
    assert gaap['is_balanced'] and own['is_balanced']
    assert own['total_assets'] == pytest.approx(gaap['total_assets'] - 4.8)
    assert own['total_liabilities'] == pytest.approx(gaap['total_liabilities'] - 12.0)
    assert own['total_equity'] == pytest.approx(gaap['total_equity'] + 7.2)
    assert own['basis_summary']['net_income_effect'] == pytest.approx(7.2)


def test_owners_balance_sheet_carries_prior_closed_year_adjustment(books, admin_user):
    """A closed year closed GAAP figures into RE; the owners' VAT effect of that year is
    still sitting in the P&L accounts and must appear as its own equity line."""
    c = books
    sale = _je(c['branch'], 'S0', date(2025, 6, 1), [
        (c['ar'], '224.00', 0), (c['sales'], 0, '200.00'), (c['output'], 0, '24.00')])
    inv = SalesInvoice(branch_id=c['branch'], invoice_number='SI-0', invoice_date=date(2025, 6, 1),
                       due_date=date(2025, 6, 1), customer_id=SalesInvoice.query.first().customer_id,
                       customer_name='x', customer_tin='',
                       status='posted', journal_entry_id=sale.id)
    inv.line_items.append(SalesInvoiceItem(line_number=1, description='x', amount=D('224'), vat_rate=D('12'),
                                           vat_category='V12', vat_nature='regular', line_total=D('224'),
                                           vat_amount=D('24'), account_id=c['sales'].id))
    db.session.add(inv)
    _je(c['branch'], 'CLOSE-2025', date(2025, 12, 31), [(c['sales'], '200.00', 0), (c['re'], 0, '200.00')],
        entry_type='closing')
    db.session.add(FiscalYearClose(fiscal_year=2025, branch_id=c['branch'], status='closed',
                                   net_income=D('200'), closed_at=datetime(2026, 1, 5), closed_by_id=admin_user.id))
    db.session.commit()
    own = generate_balance_sheet(date(2026, 3, 31), branch_id=c['branch'], reporting_basis=OWNERS)
    assert own['is_balanced']
    equity = next(s for s in own['sections'] if s['key'] == 'equity')
    names = {ln['name']: ln['total'] for dv in equity['divisions'] for ln in dv['lines']}
    assert names["Prior years' VAT adjustment (owners' basis)"] == pytest.approx(24.0)
    assert names['Net Income (current year)'] == pytest.approx(67.2)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/integration/test_owners_basis_statements.py -q`
Expected: FAIL with `TypeError: generate_income_statement() got an unexpected keyword argument 'reporting_basis'` (and the GAAP test fails on the missing `'reporting_basis'` key).

- [ ] **Step 3: Rewrite the three generators in `app/reports/financial.py`**

Add to the imports (after `from app.accounts.account_types import BASE_CATEGORY, DEFAULT_NORMAL_BALANCE`):

```python
from app.reports.basis import GAAP, OWNERS
from app.reports.ledger import period_balances, ledger_lines, owners_summary, ZERO
```

Replace `generate_trial_balance` (lines 23-107) with:

```python
def generate_trial_balance(as_of_date=None, branch_id=None, reporting_basis=GAAP):
    """Trial Balance as of a date: every active account's debit or credit balance over
    posted lines, read through the ledger seam so the owners' basis is one argument."""
    if as_of_date is None:
        as_of_date = date.today()

    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    balances = period_balances(None, as_of_date, branch_id, reporting_basis)

    account_balances = []
    total_debit = Decimal('0.00')
    total_credit = Decimal('0.00')

    for account in accounts:
        debit_sum, credit_sum = balances.get(account.id, (ZERO, ZERO))
        balance = debit_sum - credit_sum
        if balance == 0:
            continue
        debit_balance = Decimal('0.00')
        credit_balance = Decimal('0.00')
        if balance > 0:
            debit_balance = balance
            total_debit += balance
        else:
            credit_balance = abs(balance)
            total_credit += abs(balance)
        account_balances.append({
            'code': account.code,
            'name': account.name,
            'account_type': account.account_type,
            'debit_balance': float(debit_balance),
            'credit_balance': float(credit_balance)
        })

    return {
        'as_of_date': as_of_date,
        'accounts': account_balances,
        'total_debit': float(total_debit),
        'total_credit': float(total_credit),
        'is_balanced': (total_debit == total_credit),
        'difference': float(abs(total_debit - total_credit)),
        'reporting_basis': reporting_basis,
    }
```

Replace `generate_income_statement` (lines 125-168) with:

```python
def generate_income_statement(start_date, end_date, branch_id=None, reporting_basis=GAAP):
    """Hierarchical, type-driven Income Statement for a period.

    Sections and their subtotal chain come from IS_SECTIONS; each account's
    placement is its account_type. Revenue-natured types are credit-positive,
    everything else debit-positive. Returns floats for template/export use.
    'net_income' key/semantics preserved (Balance Sheet + Year-End depend on it).
    Balances come through app/reports/ledger.py, so reporting_basis='owners' folds VAT
    into income/expense per app/reports/owners_ledger.py without touching this layout.
    """
    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    by_type = {}
    for a in accounts:
        by_type.setdefault(a.account_type, []).append(a)

    balances = period_balances(start_date, end_date, branch_id, reporting_basis, exclude_closing=True)

    def amount(a):
        d, c = balances.get(a.id, (ZERO, ZERO))
        return float((c - d) if DEFAULT_NORMAL_BALANCE.get(a.account_type) == 'credit' else (d - c))

    sections, running, subtotals = [], Decimal('0.00'), {}
    for spec in IS_SECTIONS:
        rows = []
        sec_total = Decimal('0.00')
        for t in spec['types']:
            for a in by_type.get(t, []):
                amt = amount(a)
                if amt != 0:
                    rows.append({'account_id': a.id, 'code': a.code, 'name': a.name, 'amount': amt})
                    sec_total += Decimal(str(amt))
        running += spec['sign'] * sec_total
        section = {'key': spec['key'], 'label': spec['label'], 'sign': spec['sign'],
                   'total': float(sec_total), 'lines': rollup(rows, accounts)}
        if spec['subtotal']:
            section['subtotal_label'] = spec['subtotal']
            section['subtotal'] = float(running)
            subtotals[spec['subtotal']] = float(running)
        sections.append(section)

    out = {
        'period_start': start_date, 'period_end': end_date, 'sections': sections,
        'net_sales': subtotals.get('Net Sales', 0.0),
        'gross_profit': subtotals.get('Gross Profit', 0.0),
        'operating_income': subtotals.get('Operating Income', 0.0),
        'income_before_tax': subtotals.get('Income Before Tax', 0.0),
        'net_income': subtotals.get('Net Income', 0.0),
        'reporting_basis': reporting_basis,
    }
    if reporting_basis == OWNERS:
        out['basis_summary'] = owners_summary(start_date, end_date, branch_id, exclude_closing=True).as_dict()
    return out
```

Replace `generate_balance_sheet` (lines 171-244) with:

```python
PRIOR_YEARS_ADJ_LABEL = "Prior years' VAT adjustment (owners' basis)"


def _owners_prior_years_adjustment(upto, branch_id):
    """Closed years were closed at GAAP figures, so under the owners' basis the VAT that the
    lens moved into P&L accounts in those years is still sitting there. Return it
    (credit-positive) so the Balance Sheet can carry it as its own equity line."""
    from app.accounts.account_types import IS_TYPES
    balances = period_balances(None, upto, branch_id, OWNERS)
    is_ids = {a.id for a in Account.query.filter(Account.account_type.in_(IS_TYPES)).all()}
    return sum((c - d for aid, (d, c) in balances.items() if aid in is_ids), Decimal('0.00'))


def generate_balance_sheet(as_of_date=None, branch_id=None, reporting_basis=GAAP):
    """Classified, type-driven Balance Sheet. Assets/Liabilities split into
    Current/Non-Current by classification; Equity carries Retained Earnings +
    current-year Net Income. Verifies Assets = Liabilities + Equity."""
    if as_of_date is None:
        as_of_date = date.today()
    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    by_type = {}
    for a in accounts:
        by_type.setdefault(a.account_type, []).append(a)

    balances = period_balances(None, as_of_date, branch_id, reporting_basis)

    def bal(account_id, credit_positive):
        d, c = balances.get(account_id, (ZERO, ZERO))
        return (c - d) if credit_positive else (d - c)

    sections, totals = [], {}
    for spec in BS_SECTIONS:
        accts = by_type.get(spec['type'], [])
        divisions = []
        section_total = Decimal('0.00')
        groups_for = spec['divisions'] or [None]
        for div in groups_for:
            rows = []
            div_total = Decimal('0.00')
            for a in accts:
                if div is not None and a.classification != div:
                    continue
                amt = bal(a.id, spec['credit_positive'])
                if amt != 0:
                    rows.append({'account_id': a.id, 'code': a.code, 'name': a.name, 'amount': float(amt)})
                    div_total += amt
            label = f'{div} {spec["label"].title()}' if div else spec['label'].title()
            divisions.append({'label': label, 'total': float(div_total), 'lines': rollup(rows, accounts)})
            section_total += div_total
        totals[spec['key']] = section_total
        sections.append({'key': spec['key'], 'label': spec['label'],
                         'total': float(section_total), 'divisions': divisions})

    # Net income for the open span added to Equity (unchanged policy)
    from app.year_end.service import latest_closed_year_end
    last_close = latest_closed_year_end(branch_id)
    open_start = date(last_close.year + 1, 1, 1) if last_close else date(1900, 1, 1)
    ni = Decimal(str(generate_income_statement(open_start, as_of_date, branch_id=branch_id,
                                               reporting_basis=reporting_basis)['net_income']))
    equity = next(s for s in sections if s['key'] == 'equity')

    def _add_equity_line(name, amount):
        eded = equity['divisions'][0] if equity['divisions'] else None
        line = {'code': '', 'name': name, 'account_id': None, 'total': float(amount), 'children': []}
        if eded:
            eded['lines'].append(line); eded['total'] = float(Decimal(str(eded['total'])) + amount)
        else:
            equity['divisions'].append({'label': 'Equity', 'total': float(amount), 'lines': [line]})
        equity['total'] = float(Decimal(str(equity['total'])) + amount)
        totals['equity'] += amount

    if ni != 0:
        _add_equity_line('Net Income (current year)', ni)
    if reporting_basis == OWNERS and last_close:
        prior = _owners_prior_years_adjustment(open_start - timedelta(days=1), branch_id)
        if prior != 0:
            _add_equity_line(PRIOR_YEARS_ADJ_LABEL, prior)

    tle = totals['liabilities'] + totals['equity']
    diff = abs(totals['assets'] - tle)
    out = {'as_of_date': as_of_date, 'sections': sections,
           'total_assets': float(totals['assets']),
           'total_liabilities': float(totals['liabilities']),
           'total_equity': float(totals['equity']),
           'total_liabilities_equity': float(tle),
           'is_balanced': bool(diff < Decimal('0.01')), 'difference': float(diff),
           'reporting_basis': reporting_basis}
    if reporting_basis == OWNERS:
        out['basis_summary'] = owners_summary(None, as_of_date, branch_id).as_dict()
    return out
```

In `app/reports/two_column.py`, in `merge_is_two_column`, replace the two lines

```python
    for k in _IS_SCALARS:
        out[k] = {'mtd': mtd.get(k, 0.0), 'ytd': ytd.get(k, 0.0)}
    return out
```

with

```python
    for k in _IS_SCALARS:
        out[k] = {'mtd': mtd.get(k, 0.0), 'ytd': ytd.get(k, 0.0)}
    out['reporting_basis'] = ytd.get('reporting_basis', 'gaap')
    if 'basis_summary' in mtd or 'basis_summary' in ytd:
        out['basis_summary'] = {'mtd': mtd.get('basis_summary'), 'ytd': ytd.get('basis_summary')}
    return out
```

- [ ] **Step 4: Run to verify pass, then the existing statement suites**

Run: `python -m pytest tests/integration/test_owners_basis_statements.py -q`
Expected: `6 passed`

Run: `python -m pytest tests/integration/test_income_statement_views.py tests/integration/test_balance_sheet_views.py tests/integration/test_balance_sheet_closing.py tests/integration/test_trial_balance_views.py tests/integration/test_opening_balances_acceptance.py tests/unit -q -m "not e2e"`
Expected: all pass (GAAP figures unchanged; the GROUP BY seam returns the same sums as the old per-account queries).

- [ ] **Step 5: Commit**

```bash
git add app/reports/financial.py app/reports/two_column.py tests/integration/test_owners_basis_statements.py
git commit -m "feat(reports): TB, IS and BS read through the ledger seam with reporting_basis

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ejav4z8uSPiSMknfPtWywA"
```

---

### Task 7: Cash Flow through the seam

**Files:**
- Modify: `app/reports/financial.py` (`generate_cash_flow`, lines 293-525)
- Test: `tests/integration/test_owners_basis_statements.py` (append)

**Interfaces:**
- Produces: `generate_cash_flow(start_date, end_date, branch_id=None, method='indirect', reporting_basis='gaap')`; result gains `'reporting_basis'`. The direct method is computed from `ledger_lines()` instead of ad-hoc SQL; semantics identical for GAAP.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_owners_basis_statements.py`:

```python
from app.reports.financial import generate_cash_flow


def test_cash_flow_gaap_unchanged_and_reconciled(books):
    cf = generate_cash_flow(date(2026, 1, 1), date(2026, 3, 31), branch_id=books['branch'])
    assert cf['is_reconciled'] and cf['reporting_basis'] == GAAP
    assert cf['operating']['net_income'] == 60.0
    direct = generate_cash_flow(date(2026, 1, 1), date(2026, 3, 31), branch_id=books['branch'], method='direct')
    assert direct['is_reconciled'] and direct['net_change'] == pytest.approx(1000.0)


def test_cash_flow_owners_reconciles_to_same_cash(books):
    gaap = generate_cash_flow(date(2026, 1, 1), date(2026, 3, 31), branch_id=books['branch'])
    own = generate_cash_flow(date(2026, 1, 1), date(2026, 3, 31), branch_id=books['branch'], reporting_basis=OWNERS)
    assert own['is_reconciled']
    assert own['operating']['net_income'] == pytest.approx(67.2)
    assert own['cash_end'] == gaap['cash_end'] and own['net_change'] == pytest.approx(gaap['net_change'])
    wc = {w['name']: w['amount'] for w in own['operating']['working_capital']}
    assert '(Increase)/decrease in INPUT TAX' not in wc and 'Increase/(decrease) in OUTPUT TAX' not in wc
    assert wc['(Increase)/decrease in AR'] == pytest.approx(-112.0)
    d = generate_cash_flow(date(2026, 1, 1), date(2026, 3, 31), branch_id=books['branch'],
                           method='direct', reporting_basis=OWNERS)
    assert d['is_reconciled']
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/integration/test_owners_basis_statements.py -q -k cash_flow`
Expected: FAIL with `TypeError: ... unexpected keyword argument 'reporting_basis'` and `KeyError: 'reporting_basis'`.

- [ ] **Step 3: Rewrite `generate_cash_flow`**

Replace the whole function (lines 293-525) with:

```python
def generate_cash_flow(start_date, end_date, branch_id=None, method='indirect', reporting_basis=GAAP):
    """Statement of Cash Flows (indirect method) for a period.

    Reorganizes every non-cash account's period movement (Sigma debit - credit)
    into Operating / Investing / Financing activities, adds back depreciation,
    and reconciles to the actual change in cash. Returns floats for
    template/export consumption.

    Because every journal entry balances, the change in cash equals the negative
    sum of all non-cash account movements; bucketing those movements therefore
    sums exactly to the change in cash. Depreciation is the one special case: it
    is added back in Operating and Accumulated Depreciation is excluded from
    Investing (the two are equal and opposite, so the total still ties).

    Balances and lines come through app/reports/ledger.py; under the owners' basis the
    remapped lines still balance per entry, so both methods reconcile to the same cash.

    NOTE (closing-entries caveat): equity movement feeds Financing. If year-end
    closing entries are ever posted to a Retained Earnings equity account, that
    movement would double-count net income here (same caveat as the Balance
    Sheet). Not an issue on books without closing entries.
    """
    if method not in ('indirect', 'direct'):
        raise ValueError("Cash-flow method must be 'indirect' or 'direct'")

    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    period = period_balances(start_date, end_date, branch_id, reporting_basis, exclude_closing=True)

    def movement(account_id):
        """Net period movement in debit-positive terms: Sigma(debit) - Sigma(credit)."""
        d, c = period.get(account_id, (ZERO, ZERO))
        return d - c

    def cash_balance(as_of):
        """Sigma over cash accounts of (debit - credit) posted on/before as_of."""
        upto = period_balances(None, as_of, branch_id, reporting_basis)
        total = Decimal('0.00')
        for a in accounts:
            if _is_cash(a):
                d, c = upto.get(a.id, (ZERO, ZERO))
                total += d - c
        return total

    # Operating
    net_income = Decimal(str(generate_income_statement(
        start_date, end_date, branch_id=branch_id, reporting_basis=reporting_basis)['net_income']))

    depreciation = Decimal('0.00')
    for a in accounts:
        if ((a.base_category == 'Expense' or (a.code or '').startswith('5')) and _is_depreciation_name(a)):
            depreciation += movement(a.id)        # debit-positive expense -> positive add-back

    working_capital = []
    wc_total = Decimal('0.00')
    for a in accounts:
        is_curr_asset = (a.account_type == 'Asset' and a.classification == 'Current'
                         and not _is_cash(a))
        is_curr_liab = (a.account_type == 'Liability' and a.classification == 'Current')
        if not (is_curr_asset or is_curr_liab):
            continue
        effect = -movement(a.id)                  # asset up uses cash; liability up frees cash
        if effect != 0:
            verb = '(Increase)/decrease in ' if is_curr_asset else 'Increase/(decrease) in '
            working_capital.append({'name': verb + a.name, 'amount': float(effect)})
            wc_total += effect

    operating_total = net_income + depreciation + wc_total

    # Investing: non-current assets excluding accumulated depreciation
    investing_lines = []
    investing_total = Decimal('0.00')
    for a in accounts:
        if _activity_bucket(a) != 'investing':
            continue
        effect = -movement(a.id)                  # purchase (debit up) -> outflow (negative)
        if effect != 0:
            investing_lines.append({'name': '(Acquisition)/disposal of ' + a.name,
                                    'amount': float(effect)})
            investing_total += effect

    # Financing: non-current liabilities + equity
    financing_lines = []
    financing_total = Decimal('0.00')
    for a in accounts:
        if _activity_bucket(a) != 'financing':
            continue
        effect = -movement(a.id)                  # contribution / loan proceeds (credit up) -> inflow
        if effect != 0:
            financing_lines.append({'name': a.name, 'amount': float(effect)})
            financing_total += effect

    net_change = operating_total + investing_total + financing_total
    cash_begin = cash_balance(start_date - timedelta(days=1))
    cash_end = cash_balance(end_date)
    diff = abs(net_change - (cash_end - cash_begin))

    indirect = {
        'period_start': start_date,
        'period_end': end_date,
        'method': 'indirect',
        'operating': {
            'net_income': float(net_income),
            'depreciation': float(depreciation),
            'working_capital': working_capital,
            'total': float(operating_total),
        },
        'investing': {'lines': investing_lines, 'total': float(investing_total)},
        'financing': {'lines': financing_lines, 'total': float(financing_total)},
        'net_change': float(net_change),
        'cash_begin': float(cash_begin),
        'cash_end': float(cash_end),
        'is_reconciled': bool(diff < Decimal('0.01')),
        'difference': float(diff),
        'reporting_basis': reporting_basis,
    }
    if method == 'indirect':
        return indirect

    # method == 'direct': decompose the period's ACTUAL cash into the three
    # activities from cash-touching JEs. Non-cash transactions (no cash line) are
    # excluded and listed in `noncash`. Ties to the cash movement by construction.
    acct_by_id = {a.id: a for a in accounts}
    cash_ids = {a.id for a in accounts if _is_cash(a)}
    lines = ledger_lines(start_date, end_date, branch_id, reporting_basis, exclude_closing=True)

    op_buckets = {k: Decimal('0.00') for k in _DIRECT_SUBLINE_ORDER}
    inv_by_acct, fin_by_acct = {}, {}
    cash_je_ids = {l.entry_id for l in lines if l.account_id in cash_ids}
    if cash_ids:
        contra = {}
        for l in lines:
            if l.entry_id in cash_je_ids and l.account_id not in cash_ids:
                contra[l.account_id] = contra.get(l.account_id, Decimal('0.00')) + (l.credit - l.debit)
        for account_id, effect in contra.items():
            a = acct_by_id.get(account_id)
            if a is None:
                continue
            activity = _activity_bucket(a)
            if activity == 'investing':
                inv_by_acct[a.id] = (a, effect)
            elif activity == 'financing':
                fin_by_acct[a.id] = (a, effect)
            else:
                op_buckets[_direct_operating_subline(a)] += effect

    operating_lines = [{'name': k, 'amount': float(op_buckets[k])}
                       for k in _DIRECT_SUBLINE_ORDER if op_buckets[k] != 0]
    operating_dtotal = sum(op_buckets.values(), Decimal('0.00'))

    investing_dlines, investing_dtotal = [], Decimal('0.00')
    for a, eff in sorted(inv_by_acct.values(), key=lambda x: x[0].code or ''):
        if eff != 0:
            investing_dlines.append({'name': '(Acquisition)/disposal of ' + a.name,
                                     'amount': float(eff)})
            investing_dtotal += eff
    financing_dlines, financing_dtotal = [], Decimal('0.00')
    for a, eff in sorted(fin_by_acct.values(), key=lambda x: x[0].code or ''):
        if eff != 0:
            financing_dlines.append({'name': a.name, 'amount': float(eff)})
            financing_dtotal += eff

    # Non-cash investing & financing transactions: posted in-period branch JEs
    # not touching cash that hit a real investing (11x non-accum-depr) or
    # financing (21x/30x) account. (Depreciation entries hit only accumulated
    # depreciation among 11x accounts, so they do not qualify.)
    noncash = []
    invfin_ids = {a.id for a in accounts if _activity_bucket(a) in ('investing', 'financing')}
    if invfin_ids:
        cand, first_seen = {}, {}
        for l in lines:
            if l.account_id in invfin_ids and l.entry_id not in cash_je_ids:
                cand.setdefault(l.entry_id, (l.description, l.reference))
        gross = {}
        for l in lines:
            if l.entry_id in cand:
                gross[l.entry_id] = gross.get(l.entry_id, Decimal('0.00')) + l.debit
        for eid in sorted(cand):
            desc, ref = cand[eid]
            noncash.append({'description': desc or ref or f'JE {eid}', 'amount': float(gross.get(eid, 0))})

    net_change_d = operating_dtotal + investing_dtotal + financing_dtotal
    diff_d = abs(net_change_d - (cash_end - cash_begin))
    return {
        'period_start': start_date,
        'period_end': end_date,
        'method': 'direct',
        'operating': {'lines': operating_lines, 'total': float(operating_dtotal)},
        'investing': {'lines': investing_dlines, 'total': float(investing_dtotal)},
        'financing': {'lines': financing_dlines, 'total': float(financing_dtotal)},
        'noncash': noncash,
        'reconciliation': indirect['operating'],
        'net_change': float(net_change_d),
        'cash_begin': float(cash_begin),
        'cash_end': float(cash_end),
        'is_reconciled': bool(diff_d < Decimal('0.01')),
        'difference': float(diff_d),
        'reporting_basis': reporting_basis,
    }
```

Note for the implementer: the old `noncash` description used `je.description or je.reference`; `LedgerLine.description` already falls back to the entry description, so `desc or ref` preserves that. The `first_seen` name is unused and may be dropped.

- [ ] **Step 4: Run to verify pass, then the existing cash-flow suites**

Run: `python -m pytest tests/integration/test_owners_basis_statements.py tests/integration/test_cash_flow_views.py tests/integration/test_cash_flow_closing.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/reports/financial.py tests/integration/test_owners_basis_statements.py
git commit -m "feat(reports): cash flow reads through the ledger seam with reporting_basis

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ejav4z8uSPiSMknfPtWywA"
```

---

### Task 8: General Ledger through the seam, with "moved from" annotations

**Files:**
- Modify: `app/reports/financial.py` (`generate_general_ledger`, lines 527-612)
- Test: `tests/integration/test_owners_basis_statements.py` (append)

**Interfaces:**
- Produces: `generate_general_ledger(start_date, end_date, branch_id, account_id=None, reporting_basis='gaap')`; each line dict gains `'moved_from': '<code> <name>' or None`; result gains `'reporting_basis'`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_owners_basis_statements.py`:

```python
from app.reports.financial import generate_general_ledger


def test_general_ledger_gaap_unchanged(books):
    gl = generate_general_ledger(date(2026, 3, 1), date(2026, 3, 31), books['branch'])
    sales = next(a for a in gl['accounts'] if a['code'] == '411001')
    assert sales['closing_balance'] == -100.0 and sales['lines'][0]['moved_from'] is None
    assert gl['reporting_basis'] == GAAP


def test_general_ledger_owners_shows_moved_lines(books):
    gl = generate_general_ledger(date(2026, 3, 1), date(2026, 3, 31), books['branch'], reporting_basis=OWNERS)
    codes = {a['code'] for a in gl['accounts']}
    assert '213005' not in codes and '129008' not in codes
    sales = next(a for a in gl['accounts'] if a['code'] == '411001')
    assert sales['closing_balance'] == -112.0
    moved = [l for l in sales['lines'] if l['moved_from']]
    assert moved == [dict(moved[0], moved_from='213005 OUTPUT TAX')] and moved[0]['credit'] == 12.0
    assert gl['grand_total_debit'] == pytest.approx(gl['grand_total_credit'])


def test_general_ledger_owners_opening_balance_is_remapped(books):
    gl = generate_general_ledger(date(2026, 4, 1), date(2026, 4, 30), books['branch'], reporting_basis=OWNERS)
    supplies = next(a for a in gl['accounts'] if a['code'] == '721001')
    assert supplies['opening_balance'] == 44.8 and supplies['lines'] == []
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/integration/test_owners_basis_statements.py -q -k general_ledger`
Expected: FAIL (`TypeError` on `reporting_basis`; `KeyError: 'moved_from'`).

- [ ] **Step 3: Rewrite `generate_general_ledger`**

Replace lines 527-612 with:

```python
def generate_general_ledger(start_date, end_date, branch_id, account_id=None, reporting_basis=GAAP):
    """All-accounts General Ledger book over posted journal entries.

    Per account: opening balance (debit-positive) carried from before start_date,
    each in-range posted line with a running balance, and a closing subtotal.
    Accounts with no opening balance and no in-range activity are omitted.
    Under the owners' basis a line the lens moved carries 'moved_from' naming the VAT
    account it came from; GAAP lines carry None.
    """
    accounts_q = Account.query.filter_by(is_active=True)
    if account_id:
        accounts_q = accounts_q.filter(Account.id == account_id)
    accounts = accounts_q.order_by(Account.code).all()
    all_accounts = {a.id: a for a in Account.query.all()}

    opening_by = period_balances(None, start_date - timedelta(days=1), branch_id, reporting_basis)
    lines_by = {}
    for ln in ledger_lines(start_date, end_date, branch_id, reporting_basis):
        lines_by.setdefault(ln.account_id, []).append(ln)

    result_accounts = []
    grand_debit = Decimal('0.00')
    grand_credit = Decimal('0.00')

    for account in accounts:
        od, oc = opening_by.get(account.id, (ZERO, ZERO))
        opening = od - oc
        rows = lines_by.get(account.id, [])
        if opening == 0 and not rows:
            continue

        running = opening
        total_debit = Decimal('0.00')
        total_credit = Decimal('0.00')
        line_dicts = []
        for line in rows:
            running += (line.debit - line.credit)
            total_debit += line.debit
            total_credit += line.credit
            src = all_accounts.get(line.moved_from_account_id) if line.moved_from_account_id else None
            line_dicts.append({
                'entry_id': line.entry_id,
                'entry_number': line.entry_number,
                'display_number': line.display_number,
                'entry_date': line.entry_date,
                'entry_type': line.entry_type,
                'reference': line.reference,
                'description': line.description,
                'debit': float(line.debit),
                'credit': float(line.credit),
                'running_balance': float(running),
                'moved_from': f'{src.code} {src.name}' if src else None,
            })

        closing = opening + (total_debit - total_credit)
        grand_debit += total_debit
        grand_credit += total_credit
        result_accounts.append({
            'code': account.code,
            'name': account.name,
            'account_type': account.account_type,
            'opening_balance': float(opening),
            'lines': line_dicts,
            'total_debit': float(total_debit),
            'total_credit': float(total_credit),
            'closing_balance': float(closing),
        })

    return {
        'start_date': start_date,
        'end_date': end_date,
        'accounts': result_accounts,
        'grand_total_debit': float(grand_debit),
        'grand_total_credit': float(grand_credit),
        'reporting_basis': reporting_basis,
    }
```

Note: the old code filtered `JournalEntry.branch_id == branch_id` unconditionally, so a `None` branch produced an empty book; `period_balances`/`ledger_lines` skip the branch filter when it is falsy. The GL routes always pass the selected branch (they redirect otherwise), so behaviour is unchanged for real requests.

- [ ] **Step 4: Run to verify pass, then the existing GL suite**

Run: `python -m pytest tests/integration/test_owners_basis_statements.py tests/integration/test_general_ledger_views.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/reports/financial.py tests/integration/test_owners_basis_statements.py
git commit -m "feat(reports): general ledger reads through the ledger seam, annotates moved VAT

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ejav4z8uSPiSMknfPtWywA"
```

---

### Task 9: General Journal listing on the owners' basis

**Files:**
- Modify: `app/reports/general_journal_data.py` (`build_general_journal`, lines 15-33; `_write_gj_rows`, lines 36-49)
- Test: `tests/integration/test_owners_basis_statements.py` (append)

**Interfaces:**
- Produces: `build_general_journal(entries, remapped=None)` where `remapped` is `{entry_id: [LedgerLine]}`; when an entry's id is in `remapped`, its debit/credit rows come from those lines (each row `{'account': Account, 'amount': Decimal, 'moved_from': Account|None}`), otherwise from `entry.lines` with `'moved_from': None`. Drafts/voided entries are never in `remapped` (the seam only serves posted lines) so they list as before.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_owners_basis_statements.py`:

```python
from app.journal_entries.models import JournalEntry as JE
from app.reports.general_journal_data import build_general_journal
from app.reports.ledger import ledger_lines


def test_general_journal_rows_from_remapped_lines(books):
    c = books
    jv = _je(c['branch'], 'JV-2026-03-0001', date(2026, 3, 20), [
        (c['output'], '5.00', 0), (c['cash'], 0, '5.00')], entry_type='adjustment')
    entries = [db.session.get(JE, jv.id)]
    gaap = build_general_journal(entries)
    assert gaap['rows'][0]['debits'][0]['account'].code == '213005'
    assert gaap['rows'][0]['debits'][0]['moved_from'] is None
    remapped = {}
    for ln in ledger_lines(date(2026, 3, 1), date(2026, 3, 31), c['branch'], reporting_basis=OWNERS):
        remapped.setdefault(ln.entry_id, []).append(ln)
    own = build_general_journal(entries, remapped=remapped)
    assert own['rows'][0]['debits'][0]['account'].code == '213005'      # manual voucher: kept, flagged
    assert own['balanced'] and own['total_debit'] == D('5.00')
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/integration/test_owners_basis_statements.py -q -k general_journal`
Expected: FAIL with `KeyError: 'moved_from'`, then `TypeError` on `remapped`.

- [ ] **Step 3: Implement**

Replace `build_general_journal` with:

```python
def build_general_journal(entries, remapped=None):
    """Shape an iterable of JournalEntry into General Journal rows. Only posted
    entries contribute to totals; drafts and voided entries are listed but excluded.

    remapped: optional {entry_id: [LedgerLine]} from app/reports/ledger.py on the owners'
    basis. An entry present there is rendered from those lines (a moved line names the VAT
    account it came from in 'moved_from'); everything else renders from entry.lines."""
    from app.accounts.models import Account
    remapped = remapped or {}
    acct_by_id = {a.id: a for a in Account.query.all()} if remapped else {}

    rows, total_debit, total_credit = [], Decimal('0.00'), Decimal('0.00')
    for e in entries:
        debits, credits = [], []
        if e.id in remapped:
            for ln in remapped[e.id]:
                src = acct_by_id.get(ln.moved_from_account_id) if ln.moved_from_account_id else None
                if ln.debit > 0:
                    debits.append({'account': acct_by_id[ln.account_id], 'amount': ln.debit, 'moved_from': src})
                if ln.credit > 0:
                    credits.append({'account': acct_by_id[ln.account_id], 'amount': ln.credit, 'moved_from': src})
        else:
            for line in e.lines:
                if line.debit_amount and line.debit_amount > 0:
                    debits.append({'account': line.account, 'amount': line.debit_amount, 'moved_from': None})
                if line.credit_amount and line.credit_amount > 0:
                    credits.append({'account': line.account, 'amount': line.credit_amount, 'moved_from': None})
        if e.status == 'posted':
            total_debit += sum((d['amount'] for d in debits), Decimal('0.00'))
            total_credit += sum((c['amount'] for c in credits), Decimal('0.00'))
        rows.append({'entry': e, 'debits': debits, 'credits': credits,
                     'explanation': e.description or '',
                     'is_draft': e.status == 'draft',
                     'is_voided': e.status in ('cancelled', 'reversed')})
    return {'rows': rows, 'total_debit': total_debit, 'total_credit': total_credit,
            'balanced': total_debit == total_credit}
```

In `_write_gj_rows`, change the two account-name lines so a moved line says where it came from:

```python
        for d in row['debits']:
            name = d['account'].name + (f"  (from {d['moved_from'].code})" if d.get('moved_from') else '')
            ws.append(['', name, '', float(d['amount']), None])
        for c in row['credits']:
            name = c['account'].name + (f"  (from {c['moved_from'].code})" if c.get('moved_from') else '')
            ws.append(['', '    ' + name, '', None, float(c['amount'])])
```

- [ ] **Step 4: Run to verify pass, then the existing GJ suites**

Run: `python -m pytest tests/integration/test_owners_basis_statements.py tests/integration/test_general_journal_views.py tests/integration/test_general_journal_voucher_types.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/reports/general_journal_data.py tests/integration/test_owners_basis_statements.py
git commit -m "feat(reports): general journal rows can render from owners'-basis lines

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ejav4z8uSPiSMknfPtWywA"
```

---
### Task 10: Product-line reports on the owners' basis

**Files:**
- Modify: `app/reports/product_line.py` (`_net_by_category` lines 22-40, `generate_sales_by_product_line` lines 42-76, `build_sales_by_product_line` lines 83-116)
- Modify: `app/reports/income_statement_by_product_line.py` (`_revenue_by_category` line 51, `_matrix_for_period` lines 167-236, `generate_income_statement_by_product_line` lines 258-270)
- Test: `tests/integration/test_owners_basis_statements.py` (append)

**Interfaces:**
- Produces: `generate_sales_by_product_line(start_date, end_date, branch_id=None, reporting_basis='gaap')` (owners: per-line net = `line_total`, VAT included); `build_sales_by_product_line(as_of, mtd_start, ytd_start, branch_id=None, reporting_basis='gaap')`; `generate_income_statement_by_product_line(as_of, mtd_start, ytd_start, branch_id=None, reporting_basis='gaap')` (owners: a VAT-expense account mapped to a category is attributed 100% to that category, ignoring allocation rules). Results gain `'reporting_basis'`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_owners_basis_statements.py`:

```python
from app.product_categories.models import ProductCategory
from app.products.models import Product
from app.reports.basis import vat_expense_setting_key
from app.reports.product_line import generate_sales_by_product_line
from app.reports.income_statement_by_product_line import generate_income_statement_by_product_line


@pytest.fixture
def categorized(books):
    tin = ProductCategory(code='TIN', name='Tincan'); db.session.add(tin); db.session.commit()
    p = Product(name='Can', category_id=tin.id, track_inventory=False); db.session.add(p); db.session.commit()
    inv = SalesInvoice.query.filter_by(invoice_number='SI-1').one()
    inv.line_items[0].product_id = p.id
    vat_tin = _acct('811001', 'VAT EXPENSE - TINCAN', 'Other Expense', 'Debit')
    AppSettings.set_setting(vat_expense_setting_key(tin.id), vat_tin.code)
    db.session.commit()
    _je(books['branch'], 'JV-VAT', date(2026, 3, 25), [(vat_tin, '3.00', 0), (books['cash'], 0, '3.00')],
        entry_type='adjustment')
    books['tin'] = tin
    return books


def test_sales_by_product_line_gross_under_owners(categorized):
    gaap = generate_sales_by_product_line(date(2026, 3, 1), date(2026, 3, 31), categorized['branch'])
    own = generate_sales_by_product_line(date(2026, 3, 1), date(2026, 3, 31), categorized['branch'],
                                         reporting_basis=OWNERS)
    assert gaap['rows'][0]['net'] == 100.0 and own['rows'][0]['net'] == 112.0
    assert own['reporting_basis'] == OWNERS


def test_is_by_product_line_ties_under_owners_and_attributes_vat_expense(categorized):
    data = generate_income_statement_by_product_line(date(2026, 3, 31), date(2026, 3, 1), date(2026, 1, 1),
                                                     branch_id=categorized['branch'], reporting_basis=OWNERS)
    assert data['reporting_basis'] == OWNERS
    assert all(chk['ties'] for chk in data['ytd']['reconciliation'].values())
    rows = {r['key']: r for r in data['ytd']['rows']}
    tin = categorized['tin'].id
    assert rows['revenue']['by_column'][tin] == pytest.approx(112.0)
    assert rows['other_expense']['by_column'][tin] == pytest.approx(3.0)        # direct, not "Unallocated"
    assert rows['other_expense']['by_column']['unallocated'] == pytest.approx(0.0)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/integration/test_owners_basis_statements.py -q -k product_line`
Expected: FAIL with `TypeError: ... unexpected keyword argument 'reporting_basis'`.

- [ ] **Step 3: Implement in `app/reports/product_line.py`**

Add after the existing imports: `from app.reports.basis import GAAP, OWNERS`.

Change `_net_by_category` to take a `gross` flag. Replace its signature and the sum expression:

```python
def _net_by_category(item_model, header_model, header_fk, date_col,
                     start_date, end_date, branch_id, extra_filters, gross=False):
    """Return [(category_id_or_None, amount)] grouped by product category.

    amount per line = line_total - vat_amount (GAAP), or line_total when gross=True (the
    owners' basis keeps VAT inside sales). An outer join to Product means a NULL
    product_id yields category_id None; a product with a NULL category also yields None.
    """
    branch = [header_model.branch_id == branch_id] if branch_id else []
    measure = item_model.line_total if gross else (item_model.line_total - item_model.vat_amount)
    return db.session.query(
        Product.category_id,
        func.coalesce(func.sum(measure), 0),
    ).select_from(item_model).join(
        header_model, getattr(item_model, header_fk) == header_model.id
    ).outerjoin(
        Product, item_model.product_id == Product.id
    ).filter(
        date_col >= start_date, date_col <= end_date, *extra_filters, *branch,
    ).group_by(Product.category_id).all()
```

In `generate_sales_by_product_line`, change the signature to `def generate_sales_by_product_line(start_date, end_date, branch_id=None, reporting_basis=GAAP):`, add `gross = reporting_basis == OWNERS` as the first line, pass `gross=gross` as the last argument to all three `_net_by_category(...)` calls, and add `'reporting_basis': reporting_basis` to the returned dict.

In `build_sales_by_product_line`, change the signature to `def build_sales_by_product_line(as_of, mtd_start, ytd_start, branch_id=None, reporting_basis=GAAP):`, pass `reporting_basis=reporting_basis` to both `generate_sales_by_product_line(...)` calls and both `generate_income_statement(...)` calls, and add `'reporting_basis': reporting_basis` to the returned dict.

- [ ] **Step 4: Implement in `app/reports/income_statement_by_product_line.py`**

Add after the existing imports: `from app.reports.basis import GAAP, OWNERS, vat_expense_account_map`.

Replace `_revenue_by_category`:

```python
def _revenue_by_category(start_date, end_date, branch_id, reporting_basis=GAAP):
    data = generate_sales_by_product_line(start_date, end_date, branch_id, reporting_basis=reporting_basis)
    return {r['category_id']: Decimal(str(r['net'])) for r in data['rows']}
```

In `_matrix_for_period`, change the signature to `def _matrix_for_period(start_date, end_date, branch_id, categories, reporting_basis=GAAP):`; change its first line to `stmt = generate_income_statement(start_date, end_date, branch_id=branch_id, reporting_basis=reporting_basis)`; change `revenue_by_cat = _revenue_by_category(start_date, end_date, branch_id)` to `revenue_by_cat = _revenue_by_category(start_date, end_date, branch_id, reporting_basis)`; directly after `rules = {r.account_id: r.basis for r in ExpenseAllocationRule.query.all()}` add:

```python
    # Owners' basis: a VAT expense account mapped to a product category belongs wholly to it.
    direct = ({a.id: cid for cid, a in vat_expense_account_map().items() if a}
              if reporting_basis == OWNERS else {})
```

and in the final `else:` branch replace

```python
            for leaf in leaves:
                basis = rules.get(leaf['account_id'], 'none')
                shares = _allocation_shares(basis, revenue_by_cat, gross_profit_by_cat,
                                            units_by_cat, category_ids)
                distributions.append(_distribute(leaf['amount'], shares))
```

with

```python
            for leaf in leaves:
                if leaf['account_id'] in direct:
                    shares = {direct[leaf['account_id']]: Decimal('1')}
                else:
                    basis = rules.get(leaf['account_id'], 'none')
                    shares = _allocation_shares(basis, revenue_by_cat, gross_profit_by_cat,
                                                units_by_cat, category_ids)
                distributions.append(_distribute(leaf['amount'], shares))
```

Replace `generate_income_statement_by_product_line`:

```python
def generate_income_statement_by_product_line(as_of, mtd_start, ytd_start, branch_id=None,
                                              reporting_basis=GAAP):
    categories = _categories()
    mtd = _matrix_for_period(mtd_start, as_of, branch_id, categories, reporting_basis)
    ytd = _matrix_for_period(ytd_start, as_of, branch_id, categories, reporting_basis)

    columns = ([{'category_id': c.id, 'code': c.code, 'name': c.name}
               for c in sorted(categories.values(), key=lambda c: c.code)]
              + [{'category_id': UNALLOCATED, 'code': None, 'name': 'Unallocated'},
                 {'category_id': TOTAL, 'code': None, 'name': 'Total'}])

    out = {'as_of': as_of, 'columns': columns, 'reporting_basis': reporting_basis,
           'mtd': {'rows': _finalize_rows(mtd), 'reconciliation': _reconcile(mtd)},
           'ytd': {'rows': _finalize_rows(ytd), 'reconciliation': _reconcile(ytd)}}
    if reporting_basis == OWNERS:
        out['basis_summary'] = {'mtd': mtd['stmt'].get('basis_summary'), 'ytd': ytd['stmt'].get('basis_summary')}
    return out
```

- [ ] **Step 5: Run to verify pass, then the existing product-line suites**

Run: `python -m pytest tests/integration/test_owners_basis_statements.py -q`
Expected: all pass.

Run: `python -m pytest tests -q -k "product_line" -m "not e2e"`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/reports/product_line.py app/reports/income_statement_by_product_line.py tests/integration/test_owners_basis_statements.py
git commit -m "feat(reports): product-line reports take reporting_basis

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ejav4z8uSPiSMknfPtWywA"
```

---

### Task 11: Company Settings card "Owners' View"

**Files:**
- Modify: `app/company_settings/views.py` (add two routes after `save_control_accounts`, line 259)
- Create: `app/company_settings/templates/company_settings/owners_view.html`
- Modify: `app/templates/base.html` (add a nav item after BOTH Control Accounts nav items, at lines 1348-1351 and 1419-1422)
- Test: `tests/integration/test_owners_view_settings.py`

**Interfaces:**
- Consumes: `ENABLED_KEY`, `vat_expense_setting_key`, `vat_expense_account_map`, `unmapped_categories` (Task 1).
- Produces: routes `company_settings.owners_view` (GET `/settings/owners-view`) and `company_settings.save_owners_view` (POST). Form fields: `owners_basis_enabled` (checkbox `'1'`), and one `<select name="{{ vat_expense_setting_key(cat.id) }}">` per active category. Audit: `log_audit(module='company_settings', action='update', record_identifier='owners_view', old_values=..., new_values=...)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_owners_view_settings.py`:

```python
"""Company Settings -> Owners' View: full-access only; cannot enable with an unmapped
category; saves keys verbatim; writes a real before/after audit diff."""
from datetime import date
import pytest

from app import db
from app.accounts.models import Account
from app.audit.models import AuditLog
from app.product_categories.models import ProductCategory
from app.settings import AppSettings
from app.reports.basis import ENABLED_KEY, vat_expense_setting_key, owners_basis_enabled

pytestmark = [pytest.mark.owners_basis, pytest.mark.integration]


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True


@pytest.fixture
def setup(db_session):
    tin = ProductCategory(code='TIN', name='Tincan'); pla = ProductCategory(code='PLA', name='Plastic')
    parent = Account(code='811000', name='VAT EXPENSE', account_type='Other Expense', normal_balance='Debit')
    db.session.add_all([tin, pla, parent]); db.session.commit()
    a1 = Account(code='811001', name='VAT EXPENSE - TINCAN', account_type='Other Expense',
                 normal_balance='Debit', parent_id=parent.id)
    a2 = Account(code='811003', name='VAT EXPENSE - PLASTIC', account_type='Other Expense',
                 normal_balance='Debit', parent_id=parent.id)
    asset = Account(code='111001', name='CASH', account_type='Asset', normal_balance='Debit', parent_id=parent.id)
    db.session.add_all([a1, a2, asset]); db.session.commit()
    return {'tin': tin, 'pla': pla, 'a1': a1, 'a2': a2, 'asset': asset}


def test_page_requires_full_access(client, db_session, staff_user, setup):
    _login(client, staff_user)
    resp = client.get('/settings/owners-view', follow_redirects=False)
    assert resp.status_code == 302


def test_page_renders_switch_and_one_select_per_category(client, db_session, admin_user, setup):
    _login(client, admin_user)
    resp = client.get('/settings/owners-view')
    html = resp.data.decode()
    assert resp.status_code == 200 and "Owners' View" in html
    assert 'name="owners_basis_enabled"' in html
    assert f'name="{vat_expense_setting_key(setup["tin"].id)}"' in html
    assert f'name="{vat_expense_setting_key(setup["pla"].id)}"' in html
    assert "Enable owners' reporting basis" in html


def test_cannot_enable_with_unmapped_category(client, db_session, admin_user, setup):
    _login(client, admin_user)
    resp = client.post('/settings/owners-view', data={
        'owners_basis_enabled': '1',
        vat_expense_setting_key(setup['tin'].id): '811001',
        vat_expense_setting_key(setup['pla'].id): '',
    }, follow_redirects=True)
    assert b'Plastic' in resp.data
    assert owners_basis_enabled() is False
    assert AppSettings.get_setting(vat_expense_setting_key(setup['tin'].id)) is None  # nothing saved


def test_rejects_non_expense_account(client, db_session, admin_user, setup):
    _login(client, admin_user)
    client.post('/settings/owners-view', data={
        vat_expense_setting_key(setup['tin'].id): '111001',
        vat_expense_setting_key(setup['pla'].id): '811003',
    }, follow_redirects=True)
    assert AppSettings.get_setting(vat_expense_setting_key(setup['tin'].id)) is None


def test_saves_mapping_then_enable_and_audits(client, db_session, admin_user, setup):
    _login(client, admin_user)
    client.post('/settings/owners-view', data={
        vat_expense_setting_key(setup['tin'].id): '811001',
        vat_expense_setting_key(setup['pla'].id): '811003',
    }, follow_redirects=True)
    assert owners_basis_enabled() is False
    resp = client.post('/settings/owners-view', data={
        'owners_basis_enabled': '1',
        vat_expense_setting_key(setup['tin'].id): '811001',
        vat_expense_setting_key(setup['pla'].id): '811003',
    }, follow_redirects=True)
    assert resp.status_code == 200 and owners_basis_enabled() is True
    log = AuditLog.query.filter_by(module='company_settings', record_identifier='owners_view').order_by(AuditLog.id.desc()).first()
    assert log is not None
    assert '"owners_basis_enabled": "0"' in (log.old_values or '') or "'owners_basis_enabled': '0'" in (log.old_values or '')
    assert 'owners_basis_enabled' in (log.new_values or '')
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/integration/test_owners_view_settings.py -q`
Expected: FAIL with 404s (route missing).

- [ ] **Step 3: Add the routes**

In `app/company_settings/views.py`, after `save_control_accounts` (after line 259 `return redirect(url_for('company_settings.control_accounts'))`), add:

```python
# ---------------------------------------------------------------------------
# Owners' View -- the VAT-inclusive reporting basis (spec 2026-09-13)
# ---------------------------------------------------------------------------
def _owners_view_context():
    from app.posting.control_accounts import get_postable_accounts
    from app.accounts.account_types import BASE_CATEGORY
    from app.reports.basis import (ENABLED_KEY, vat_expense_setting_key,
                                   vat_expense_account_map, _active_categories)
    expense_accounts = [a for a in get_postable_accounts() if BASE_CATEGORY.get(a.account_type) == 'Expense']
    current = vat_expense_account_map()
    rows = [{'category': c, 'field': vat_expense_setting_key(c.id),
             'code': current[c.id].code if current.get(c.id) else ''} for c in _active_categories()]
    return {'enabled': AppSettings.get_setting(ENABLED_KEY) == '1',
            'rows': rows, 'expense_accounts': expense_accounts}


@company_settings_bp.route('/owners-view')
@login_required
def owners_view():
    if not current_user.has_full_access:
        flash("Only Administrators and Chief Accountants can configure the Owners' View.", 'error')
        return redirect(url_for('dashboard.index'))
    return render_template('company_settings/owners_view.html', **_owners_view_context())


@company_settings_bp.route('/owners-view', methods=['POST'])
@login_required
def save_owners_view():
    """All-or-nothing: validate every field, then write. The switch cannot go on while
    any active category lacks a usable expense account."""
    if not current_user.has_full_access:
        flash('Only Administrators and Chief Accountants can perform this action.', 'error')
        return redirect(url_for('dashboard.index'))
    from app.audit.utils import get_changes
    from app.reports.basis import ENABLED_KEY
    ctx = _owners_view_context()
    valid = {a.code: a for a in ctx['expense_accounts']}
    want_enabled = request.form.get('owners_basis_enabled') == '1'
    new_values, missing = {}, []
    for row in ctx['rows']:
        code = (request.form.get(row['field']) or '').strip()
        if code and code not in valid:
            flash(f"Account {code} for {row['category'].name} is not an active, postable expense account.", 'error')
            return redirect(url_for('company_settings.owners_view'))
        if not code:
            missing.append(row['category'].name)
        new_values[row['field']] = code
    if want_enabled and missing:
        flash("Cannot enable the owners' basis: no VAT expense account for " + ', '.join(missing) + '.', 'error')
        return redirect(url_for('company_settings.owners_view'))
    new_values[ENABLED_KEY] = '1' if want_enabled else '0'
    old_values = {k: (AppSettings.get_setting(k) or ('0' if k == ENABLED_KEY else ''))
                  for k in new_values}
    for key, value in new_values.items():
        AppSettings.set_setting(key, value, updated_by=current_user.username)
    log_audit(module='company_settings', action='update', record_id=None,
              record_identifier='owners_view', old_values=old_values, new_values=new_values,
              user_id=current_user.id)
    flash("Owners' View settings saved.", 'success')
    return redirect(url_for('company_settings.owners_view'))
```

Note: `get_changes` is imported for parity with the repo convention; `old_values`/`new_values` here are full before/after dicts of the same keys, which is the real diff `log_audit` needs. Remove the unused import if the linter complains.

- [ ] **Step 4: Create the template**

`app/company_settings/templates/company_settings/owners_view.html`:

```html
{# app/company_settings/templates/company_settings/owners_view.html #}
{% extends "base.html" %}
{% block title %}Owners' View - {{ company_name }}{% endblock %}
{% block page_title %}Owners' View{% endblock %}

{% block content %}
<link rel="stylesheet" href="{{ url_for('static', filename='choices.min.css') }}">

<div class="card">
  <div class="card-header">
    <div class="card-title">Owners' View</div>
    <div class="card-sub">A second reporting basis for the owners: output VAT folded into income, input VAT into expenses, VAT remitted to the BIR shown as VAT expense by product line. The books of record are never changed. Only Administrators and Chief Accountants see the switch on reports.</div>
  </div>
  <div class="card-body">
    <form method="post" action="{{ url_for('company_settings.save_owners_view') }}">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
      <div class="form-group">
        <label class="form-label" style="display:flex;align-items:center;gap:8px;">
          <input type="checkbox" name="owners_basis_enabled" value="1" {{ 'checked' if enabled else '' }}>
          Enable owners' reporting basis
        </label>
        <div class="form-hint">Every active product category must have a VAT expense account before this can be turned on.</div>
      </div>
      <h4 style="margin:18px 0 8px;">VAT expense account per product line</h4>
      {% if rows %}
      <div class="form-row-2">
        {% for r in rows %}
        <div class="form-group">
          <label class="form-label" for="ov_{{ r.category.id }}">{{ r.category.code }} &mdash; {{ r.category.name }}</label>
          <select name="{{ r.field }}" id="ov_{{ r.category.id }}" class="form-control">
            <option value="">&mdash; not assigned &mdash;</option>
            {% for a in expense_accounts %}
            <option value="{{ a.code }}" {{ 'selected' if r.code == a.code else '' }}>{{ a.code }}: {{ a.name }}</option>
            {% endfor %}
          </select>
        </div>
        {% endfor %}
      </div>
      {% else %}
      <p class="text-muted">No active product categories. Create them under Product Categories first.</p>
      {% endif %}
      <div class="form-actions">
        <button type="submit" class="btn btn-primary">Save</button>
      </div>
    </form>
  </div>
</div>

<script src="{{ url_for('static', filename='choices.min.js') }}"></script>
<script src="{{ url_for('static', filename='search-select.js') }}?v=3"></script>
<script>
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('select[id^="ov_"]').forEach(function (sel) {
    if (typeof initSearchSelect === 'function' && !sel.closest('.choices')) {
      initSearchSelect(sel);
    }
  });
});
</script>
{% endblock %}
```

- [ ] **Step 5: Add the nav item**

In `app/templates/base.html`, directly after EACH of the two Control Accounts `<a ...>...</a>` blocks (the one ending at line 1351 and the one ending at line 1422), add:

```html
                    {% if current_user.has_full_access %}
                    <a href="{{ url_for('company_settings.owners_view') }}" class="nav-item {% if request.endpoint in ('company_settings.owners_view', 'company_settings.save_owners_view') %}active{% endif %}">
                        <span class="nav-icon">👓</span>
                        <span class="nav-text">Owners' View</span>
                    </a>
                    {% endif %}
```

- [ ] **Step 6: Run to verify pass**

Run: `python -m pytest tests/integration/test_owners_view_settings.py tests/integration/test_company_settings*.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add app/company_settings/views.py app/company_settings/templates/company_settings/owners_view.html app/templates/base.html tests/integration/test_owners_view_settings.py
git commit -m "feat(settings): Owners' View card with switch and VAT expense mapping

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ejav4z8uSPiSMknfPtWywA"
```

---

### Task 12: Report views, switch, banner, reconciliation box, print and Excel

**Files:**
- Modify: `app/reports/views.py` (helpers near line 54; the 7 report families: TB 1160-1197, IS 1235-1275, IS-by-PL 1327-1365, BS 1504-1537, CF 1540-1575, GL 689-741, GJ 1975-2015)
- Create: `app/reports/templates/reports/_basis.html`
- Modify: the 7 page templates and 7 print templates listed below; `app/reports/statement_export.py` (three builders); `app/reports/general_journal_data.py` (`build_general_journal_xlsx`)
- Test: `tests/integration/test_owners_basis_views.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `_basis()` in views; blueprint context processor injecting `reporting_basis`, `can_switch_basis`, `OWNERS_NOTE`, `NOT_BOOK_OF_RECORD`; macros `basis_switch()` and `basis_banner(summary, book=False)`; Excel builders accept `basis_note=None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_owners_basis_views.py`:

```python
"""Route-level behaviour of the Basis switch across the seven report families."""
from datetime import date
from decimal import Decimal
from io import BytesIO
import pytest
import openpyxl

from app import db
from app.settings import AppSettings
from app.reports.basis import ENABLED_KEY, OWNERS_NOTE, NOT_BOOK_OF_RECORD
from tests.integration.test_owners_basis_statements import books, _acct, _je   # noqa: F401 (fixture reuse)

pytestmark = [pytest.mark.owners_basis, pytest.mark.integration]

SWITCH = 'name="basis"'
PAGES = ['/reports/income-statement?as_of=2026-03-31',
         '/reports/income-statement-by-product-line?as_of=2026-03-31',
         '/reports/balance-sheet?as_of=2026-03-31',
         '/reports/cash-flow?as_of=2026-03-31',
         '/reports/trial-balance?as_of=2026-03-31',
         '/reports/general-ledger?start_date=2026-03-01&end_date=2026-03-31',
         '/reports/general-journal?date_from=2026-03-01&date_to=2026-03-31&mode=custom']


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True


def _branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


@pytest.mark.parametrize('url', PAGES)
def test_switch_absent_when_feature_off(client, books, admin_user, url):
    _login(client, admin_user); _branch(client, books['branch'])
    html = client.get(url).data.decode()
    assert SWITCH not in html and OWNERS_NOTE not in html


@pytest.mark.parametrize('url', PAGES)
def test_switch_present_for_full_access_when_on(client, books, admin_user, url):
    AppSettings.set_setting(ENABLED_KEY, '1')
    _login(client, admin_user); _branch(client, books['branch'])
    html = client.get(url).data.decode()
    assert SWITCH in html and 'Basis:' in html and OWNERS_NOTE not in html     # GAAP by default


@pytest.mark.parametrize('url', PAGES)
def test_staff_pasting_owners_url_gets_gaap(client, books, staff_user, url):
    AppSettings.set_setting(ENABLED_KEY, '1')
    _login(client, staff_user); _branch(client, books['branch'])
    html = client.get(url + '&basis=owners').data.decode()
    assert SWITCH not in html and OWNERS_NOTE not in html


@pytest.mark.parametrize('url', PAGES)
def test_owners_page_shows_banner(client, books, admin_user, url):
    AppSettings.set_setting(ENABLED_KEY, '1')
    _login(client, admin_user); _branch(client, books['branch'])
    html = client.get(url + '&basis=owners').data.decode()
    assert OWNERS_NOTE in html
    if 'general-journal' in url:
        assert NOT_BOOK_OF_RECORD in html


def test_owners_income_statement_reconciliation_box(client, books, admin_user):
    AppSettings.set_setting(ENABLED_KEY, '1')
    _login(client, admin_user); _branch(client, books['branch'])
    html = client.get('/reports/income-statement?as_of=2026-03-31&basis=owners').data.decode()
    assert 'GAAP net income' in html and 'Output VAT moved to income' in html
    assert '67.20' in html and '12.00' in html and '4.80' in html


def test_owners_general_ledger_marks_moved_lines(client, books, admin_user):
    AppSettings.set_setting(ENABLED_KEY, '1')
    _login(client, admin_user); _branch(client, books['branch'])
    html = client.get('/reports/general-ledger?start_date=2026-03-01&end_date=2026-03-31&basis=owners').data.decode()
    assert 'from 213005 OUTPUT TAX' in html


@pytest.mark.parametrize('url', [
    '/reports/income-statement/print?as_of=2026-03-31&basis=owners',
    '/reports/balance-sheet/print?as_of=2026-03-31&basis=owners',
    '/reports/cash-flow/print?as_of=2026-03-31&basis=owners',
    '/reports/trial-balance/print?as_of=2026-03-31&basis=owners',
    '/reports/general-ledger/print?start_date=2026-03-01&end_date=2026-03-31&basis=owners',
    '/reports/income-statement-by-product-line/print?as_of=2026-03-31&basis=owners',
    '/reports/general-journal/print?date_from=2026-03-01&date_to=2026-03-31&mode=custom&basis=owners'])
def test_print_views_carry_banner(client, books, admin_user, url):
    AppSettings.set_setting(ENABLED_KEY, '1')
    _login(client, admin_user); _branch(client, books['branch'])
    assert OWNERS_NOTE in client.get(url).data.decode()


@pytest.mark.parametrize('url', [
    '/reports/income-statement/export/excel?as_of=2026-03-31&basis=owners',
    '/reports/balance-sheet/export/excel?as_of=2026-03-31&basis=owners',
    '/reports/cash-flow/export/excel?as_of=2026-03-31&basis=owners',
    '/reports/trial-balance/export/excel?as_of=2026-03-31&basis=owners',
    '/reports/general-ledger/export/excel?start_date=2026-03-01&end_date=2026-03-31&basis=owners',
    '/reports/income-statement-by-product-line/export/excel?as_of=2026-03-31&basis=owners',
    '/reports/general-journal/export?date_from=2026-03-01&date_to=2026-03-31&mode=custom&basis=owners'])
def test_excel_exports_carry_note(client, books, admin_user, url):
    AppSettings.set_setting(ENABLED_KEY, '1')
    _login(client, admin_user); _branch(client, books['branch'])
    resp = client.get(url)
    assert resp.status_code == 200
    wb = openpyxl.load_workbook(BytesIO(resp.data))
    text = ' '.join(str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.value)
    assert OWNERS_NOTE in text


def test_gaap_export_has_no_note(client, books, admin_user):
    AppSettings.set_setting(ENABLED_KEY, '1')
    _login(client, admin_user); _branch(client, books['branch'])
    resp = client.get('/reports/income-statement/export/excel?as_of=2026-03-31')
    wb = openpyxl.load_workbook(BytesIO(resp.data))
    text = ' '.join(str(c.value) for row in wb.active.iter_rows() for c in row if c.value)
    assert OWNERS_NOTE not in text
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/integration/test_owners_basis_views.py -q`
Expected: the "switch present" / "banner" / "note" tests FAIL; the "absent" tests pass.

- [ ] **Step 3: Views helpers and context processor**

In `app/reports/views.py`, add to the imports: `from app.reports.basis import resolve_basis, can_switch_basis, OWNERS, OWNERS_NOTE, NOT_BOOK_OF_RECORD`. After the `_reset_ledger_cache` hook (Task 5), add:

```python
def _basis():
    """Effective reporting basis for this request: GAAP unless the Owners' View is enabled,
    the user has full access, and ?basis=owners."""
    return resolve_basis(current_user, request.args)


@reports_bp.context_processor
def _inject_basis():
    return {'reporting_basis': _basis(), 'can_switch_basis': can_switch_basis(current_user),
            'OWNERS_NOTE': OWNERS_NOTE, 'NOT_BOOK_OF_RECORD': NOT_BOOK_OF_RECORD}


def _export_note(reporting_basis):
    return OWNERS_NOTE if reporting_basis == OWNERS else None
```

Then thread the basis through every route of the seven families. Exact edits:

Trial Balance (3 routes): after `as_of_date, branch_id = _tb_params()` add `rb = _basis()`; call `generate_trial_balance(as_of_date, branch_id=branch_id, reporting_basis=rb)`. In `trial_balance_export_excel` change the title line to `title = f'Trial Balance - As of {as_of_date.strftime("%B %d, %Y")}' + (f' - {OWNERS_NOTE}' if rb == OWNERS else '')`. In `trial_balance_print` pass `basis_summary=None` (TB has no box).

Income Statement (3 routes): `rb = _basis()`; both `generate_income_statement(..., reporting_basis=rb)` calls; export: `build_income_statement_xlsx(stmt, as_of_label, company, branch_name, filename, basis_note=_export_note(rb))`; page and print: pass `basis_summary=data.get('basis_summary')` (page) / `basis_summary=stmt.get('basis_summary')` (print).

Income Statement by Product Line (3 routes): `rb = _basis()`; `generate_income_statement_by_product_line(..., reporting_basis=rb)`; page/print pass `basis_summary=data.get('basis_summary')`; export: `title='Income Statement by Product Line' + (f' - {OWNERS_NOTE}' if rb == OWNERS else '')` on the `export_to_excel(...)` call.

Balance Sheet (3 routes): `rb = _basis()`; `generate_balance_sheet(as_of_date, branch_id=branch_id, reporting_basis=rb)`; page/print pass `basis_summary=bs.get('basis_summary')` (name the variable `bs` in the page route too); export: `build_balance_sheet_xlsx(bs, as_of_label, company, branch_name, filename, basis_note=_export_note(rb))`.

Cash Flow (3 routes): `rb = _basis()`; both `generate_cash_flow(..., reporting_basis=rb)` calls; export: `build_cash_flow_xlsx(cf, as_of_label, company, branch_name, filename, basis_note=_export_note(rb))`; page/print pass `basis_summary=None`.

General Ledger (4 routes): `rb = _basis()`; `generate_general_ledger(start_date, end_date, branch_id, account_id=account_id, reporting_basis=rb)`; excel/csv: append `+ (f' - {OWNERS_NOTE}' if rb == OWNERS else '')` to `title=` (excel only; csv has no title). In `_flatten_ledger`, change `'particulars': line['description']` to `'particulars': line['description'] + (f"  (from {line['moved_from']})" if line.get('moved_from') else '')`.

General Journal (3 routes): after `period = resolve_period(...)` add:

```python
    rb = _basis()
    remapped = None
    if rb == OWNERS:
        from app.reports.ledger import ledger_lines
        remapped = {}
        for ln in ledger_lines(period['date_from'], period['date_to'], branch_id, reporting_basis=rb):
            remapped.setdefault(ln.entry_id, []).append(ln)
    gj = build_general_journal(_general_journal_entries(branch_id, period), remapped=remapped)
```

replacing the existing `gj = build_general_journal(...)` line in each of the three routes. In `general_journal_export`, change the period label argument to `period['label'] + (f' - {OWNERS_NOTE} {NOT_BOOK_OF_RECORD}' if rb == OWNERS else '')`.

- [ ] **Step 4: Macros**

Create `app/reports/templates/reports/_basis.html`:

```html
{# Basis switch + owners' banner. Context comes from reports_bp's context processor:
   reporting_basis, can_switch_basis, OWNERS_NOTE, NOT_BOOK_OF_RECORD. #}
{% macro basis_switch() %}
{% if can_switch_basis %}
<form method="get" class="basis-switch" style="display:inline-flex;align-items:center;gap:6px;margin:0;">
  {% for k, v in request.args.items() if k != 'basis' %}<input type="hidden" name="{{ k }}" value="{{ v }}">{% endfor %}
  <label for="basis" style="font-weight:600;">Basis:</label>
  <select name="basis" id="basis" class="form-control" style="width:auto;" onchange="this.form.submit()">
    <option value="gaap" {{ 'selected' if reporting_basis == 'gaap' else '' }}>GAAP</option>
    <option value="owners" {{ 'selected' if reporting_basis == 'owners' else '' }}>Owners</option>
  </select>
</form>
{% endif %}
{% endmacro %}

{% macro basis_banner(summary=None, book=False, gaap_net_income=None) %}
{# summary: RemapSummary.as_dict(), or {'mtd': dict, 'ytd': dict} for two-column statements.
   gaap_net_income: number, or {'mtd': n, 'ytd': n} matching summary. None -> no GAAP line. #}
{% if reporting_basis == 'owners' %}
<div class="basis-banner" style="border:2px solid #b45309;background:#fffbeb;color:#78350f;padding:10px 14px;margin:0 0 14px 0;border-radius:6px;">
  <strong>{{ OWNERS_NOTE }}</strong>{% if book %} <strong>{{ NOT_BOOK_OF_RECORD }}</strong>{% endif %}
  {% if summary %}
  {% set two_col = summary.mtd is defined or summary.ytd is defined %}
  {% set blocks = [('Current month', summary.mtd, gaap_net_income.mtd if gaap_net_income else none), ('Year to date', summary.ytd, gaap_net_income.ytd if gaap_net_income else none)] if two_col else [('Reconciliation', summary, gaap_net_income)] %}
  <table class="basis-recon" style="margin-top:8px;border-collapse:collapse;">
    {% for title, s, gaap in blocks if s %}
    <tr><td colspan="2" style="font-weight:600;padding:2px 8px;">{{ title }}</td></tr>
    {% if gaap is not none %}<tr><td style="padding:2px 8px;">GAAP net income</td><td style="text-align:right;padding:2px 8px;">{{ '{:,.2f}'.format(gaap) }}</td></tr>{% endif %}
    <tr><td style="padding:2px 8px;">+ Output VAT moved to income</td><td style="text-align:right;padding:2px 8px;">{{ '{:,.2f}'.format(s.moved_to_income) }}</td></tr>
    <tr><td style="padding:2px 8px;">&minus; Input VAT moved to expense</td><td style="text-align:right;padding:2px 8px;">{{ '{:,.2f}'.format(s.moved_to_expense) }}</td></tr>
    <tr><td style="padding:2px 8px;">&nbsp;&nbsp;Input VAT moved to asset accounts (no P&amp;L effect)</td><td style="text-align:right;padding:2px 8px;">{{ '{:,.2f}'.format(s.moved_to_balance_sheet) }}</td></tr>
    <tr><td style="padding:2px 8px;">&minus; VAT expense recognised</td><td style="text-align:right;padding:2px 8px;">{{ '{:,.2f}'.format(s.vat_expense_total) }}</td></tr>
    <tr><td style="padding:2px 8px;">Untraced VAT (flagged, left on VAT accounts)</td><td style="text-align:right;padding:2px 8px;">{{ '{:,.2f}'.format(s.untraced_total) }}</td></tr>
    {% if gaap is not none %}<tr><td style="padding:2px 8px;font-weight:600;">= Owners' net income</td><td style="text-align:right;padding:2px 8px;font-weight:600;">{{ '{:,.2f}'.format(gaap + s.net_income_effect) }}</td></tr>{% endif %}
    {% for u in s.untraced %}
    <tr><td colspan="2" style="padding:1px 8px 1px 24px;font-size:0.9em;">{{ u.entry_number }} &middot; {{ u.account_code }} &middot; {{ '{:,.2f}'.format(u.amount) }} &middot; {{ u.reason }}</td></tr>
    {% endfor %}
    {% endfor %}
  </table>
  {% endif %}
</div>
{% endif %}
{% endmacro %}
```


- [ ] **Step 5: Templates**

For each page template, add at the top of `{% block content %}`: `{% from 'reports/_basis.html' import basis_switch, basis_banner with context %}` (the `with context` is required: an imported macro cannot otherwise see the blueprint's context variables `reporting_basis`, `can_switch_basis`, `request`).

`income_statement.html`: inside `.card-header-actions` (line 13) add `{{ basis_switch() }}` as the first child; add `basis=reporting_basis` to both `url_for(...)` calls for Excel and Print; at the top of `.card-body` (line 22, before the `<table>`) add:

```html
        {% if basis_summary %}
        {% set gaap_ni = {'mtd': income_statement.net_income.mtd - (basis_summary.mtd.net_income_effect if basis_summary.mtd else 0),
                          'ytd': income_statement.net_income.ytd - (basis_summary.ytd.net_income_effect if basis_summary.ytd else 0)} %}
        {{ basis_banner(basis_summary, gaap_net_income=gaap_ni) }}
        {% endif %}
```

`balance_sheet.html`: same pattern; switch in `.card-header-actions`; `basis=reporting_basis` on Excel/Print links; before the table: `{{ basis_banner(basis_summary) }}` (no GAAP line; the moved amounts are what the reader needs next to the equity lines).

`cash_flow.html`, `trial_balance.html`: switch in `.card-header-actions`; `basis=reporting_basis` on Excel/Print links; `{{ basis_banner() }}` before the table.

`income_statement_by_product_line.html`: add `{{ basis_switch() }}` inside `<div class="page-actions">` first; add `basis=reporting_basis` to the Print and Export links; after `</div>` closing `.content-header` add `{{ basis_banner(basis_summary) }}`.

`general_ledger.html`: line 10 `q` string: append `~ '&basis=' ~ reporting_basis`; add `{{ basis_switch() }}` first inside `.card-header-actions`; after the filter `</form>` (line 51) add `{{ basis_banner() }}`; in the line rows, after the description cell (line 83) change it to `<td>{{ line.description }}{% if line.moved_from %} <span class="badge" style="background:#fde68a;color:#78350f;">from {{ line.moved_from }}</span>{% endif %}</td>`.

`general_journal.html`: `q` string append `~ '&basis=' ~ reporting_basis`; `{{ basis_switch() }}` first inside `.card-header-actions`; after the filter `</form>` (line 52) add `{{ basis_banner(book=True) }}`; in the debit/credit rows (lines 71 and 80) append `{% if d.moved_from %} <small>(from {{ d.moved_from.code }})</small>{% endif %}` / `{% if c.moved_from %} <small>(from {{ c.moved_from.code }})</small>{% endif %}`.

Print templates (`income_statement_print.html`, `balance_sheet_print.html`, `cash_flow_print.html`, `trial_balance_print.html`, `income_statement_by_product_line_print.html`, `general_ledger_print.html`, `general_journal_print.html`): directly after the `<h1>` (or after the `bir_book_header(...)` call for GL/GJ) add:

```html
    {% if reporting_basis == 'owners' %}<div class="meta" style="border:1px solid #000;padding:4px 8px;font-weight:bold;">{{ OWNERS_NOTE }}{% if BOOK %} {{ NOT_BOOK_OF_RECORD }}{% endif %}</div>{% endif %}
```

with `{% set BOOK = true %}` placed above it only in `general_journal_print.html` (elsewhere omit the `{% if BOOK %}` clause entirely). For `income_statement_print.html` also add, after that banner, the reconciliation rows using the same macro: `{% from 'reports/_basis.html' import basis_banner %}{% set gaap_net_income = {'mtd': 0, 'ytd': 0} %}{{ basis_banner(basis_summary) }}` is NOT used in print (keeps print compact); instead print the summary lines plainly:

```html
    {% if basis_summary and basis_summary.ytd %}
    <div class="meta">Owners' basis effect YTD: +{{ '{:,.2f}'.format(basis_summary.ytd.moved_to_income) }} output VAT in income, &minus;{{ '{:,.2f}'.format(basis_summary.ytd.moved_to_expense) }} input VAT in expense, &minus;{{ '{:,.2f}'.format(basis_summary.ytd.vat_expense_total) }} VAT expense, {{ '{:,.2f}'.format(basis_summary.ytd.untraced_total) }} untraced.</div>
    {% endif %}
```

- [ ] **Step 6: Excel builders**

In `app/reports/statement_export.py`, change the three signatures to `build_income_statement_xlsx(stmt, as_of_label, company, branch_name, filename, basis_note=None)`, `build_balance_sheet_xlsx(bs, as_of_label, company, branch_name, filename, basis_note=None)`, `build_cash_flow_xlsx(cf, as_of_label, company, branch_name, filename, basis_note=None)`. In each, directly after the `put(as_of_label)` line of the header, add:

```python
    if basis_note:
        r = put(basis_note); ws.cell(r, 1).font = Font(bold=True, color='B45309')
```

(`build_balance_sheet_xlsx` uses `ws.append([label, amount])` via its own `put`; use the same call shape it already uses for header lines.)

- [ ] **Step 7: Run to verify pass, then every report suite**

Run: `python -m pytest tests/integration/test_owners_basis_views.py -q`
Expected: all pass.

Run: `python -m pytest tests/integration -q -k "report or ledger or journal or statement or balance or trial or cash_flow or product_line" -m "not e2e"`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add app/reports app/company_settings tests/integration/test_owners_basis_views.py
git commit -m "feat(reports): Basis switch, owners' banner and reconciliation across all statements

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ejav4z8uSPiSMknfPtWywA"
```

---

### Task 13: Verification script against a copy of ric.db, and the full suite

**Files:**
- Create: `tools/verify_owners_basis.py`

**Interfaces:**
- Consumes: `generate_income_statement`, `generate_balance_sheet`, `owners_summary`.

- [ ] **Step 1: Write the script**

`tools/verify_owners_basis.py`:

```python
"""Print the owners'-basis reconciliation for a database COPY, so the owners can confirm the
numbers before the switch goes on in production.

    cp instance/ric.db /tmp/ric-verify.db
    SQLALCHEMY_DATABASE_URI=sqlite:////tmp/ric-verify.db python tools/verify_owners_basis.py 2025 2026

Read-only against the copy; never point it at the live file while the server runs.
"""
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / '.env')

from app import create_app                                      # noqa: E402
from app.reports.basis import GAAP, OWNERS, owners_basis_enabled, unmapped_categories  # noqa: E402
from app.reports.financial import generate_income_statement, generate_balance_sheet  # noqa: E402
from app.utils import ph_now                                    # noqa: E402


def main(years):
    app = create_app(os.environ.get('FLASK_ENV', 'development'))
    with app.app_context():
        print(f"Owners' basis enabled: {owners_basis_enabled()}")
        print('Unmapped categories:', ', '.join(c.name for c in unmapped_categories()) or 'none')
        today = ph_now().date()
        for y in years:
            end = date(y, 12, 31) if y < today.year else today
            gaap = generate_income_statement(date(y, 1, 1), end, reporting_basis=GAAP)
            own = generate_income_statement(date(y, 1, 1), end, reporting_basis=OWNERS)
            s = own['basis_summary']
            print(f"\n=== FY{y} to {end} ===")
            print(f"GAAP net income                 {gaap['net_income']:>18,.2f}")
            print(f"+ Output VAT moved to income    {s['moved_to_income']:>18,.2f}")
            print(f"- Input VAT moved to expense    {s['moved_to_expense']:>18,.2f}")
            print(f"  Input VAT moved to assets     {s['moved_to_balance_sheet']:>18,.2f}")
            print(f"- VAT expense recognised        {s['vat_expense_total']:>18,.2f}")
            print(f"Untraced VAT (flagged)          {s['untraced_total']:>18,.2f}")
            print(f"= Owners' net income            {own['net_income']:>18,.2f}")
            diff = own['net_income'] - gaap['net_income'] - s['net_income_effect']
            print(f"identity check (should be 0)    {diff:>18,.2f}")
            bs = generate_balance_sheet(end, reporting_basis=OWNERS)
            print(f"Owners' balance sheet balanced: {bs['is_balanced']} (diff {bs['difference']:,.2f})")
            for u in s['untraced'][:20]:
                print(f"  untraced {u['entry_number']} {u['account_code']} {u['amount']:,.2f} {u['reason']}")
            if len(s['untraced']) > 20:
                print(f"  ... {len(s['untraced']) - 20} more")


if __name__ == '__main__':
    main([int(a) for a in sys.argv[1:]] or [ph_now().year])
```

- [ ] **Step 2: Run it against a copy of RIC's database**

From `C:\envs\workspace\cas` in Git Bash:

```bash
cp instance/ric.db "$TMP/ric-verify.db"
SQLALCHEMY_DATABASE_URI="sqlite:///$TMP/ric-verify.db" python tools/verify_owners_basis.py 2025 2026
```

Expected: the two reconciliation boxes print, `identity check` is `0.00` for both years, the owners' balance sheet reports balanced, and the untraced list is empty (RIC's output tax ties to invoices exactly as of 2026-09-13). Paste the output into the PR description.

- [ ] **Step 3: Full suite**

Run: `python -m pytest -q -m "not e2e"`
Expected: all pass (about 6,650 tests, roughly 25 minutes).

- [ ] **Step 4: Commit**

```bash
git add tools/verify_owners_basis.py
git commit -m "chore(reports): owners' basis verification script

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ejav4z8uSPiSMknfPtWywA"
```

---

## Self-review against the spec

- **Section 1 rules:** rules 1-2 (Task 3), rule 3 (Task 3), rule 4 with the settled-quarter window (Task 4), rule 5 with verbatim reasons (Tasks 3-4), rounding to the largest line (`distribute`, Task 3), reversal follows original (Task 3 `_doc_for`, tested in Task 4), balance-sheet consequence incl. closed years (Task 6).
- **Section 2 settings/access:** keys and switch (Task 1), card + validation + audit (Task 11), gate (Task 1), page furniture and reconciliation box on page/print/export (Task 12), GJ "Not a book of record" (Task 12).
- **Section 3 architecture:** `owners_ledger.py` (Tasks 3-4), `ledger.py` + cache (Tasks 2, 5), generators (Tasks 6-10), `basis.py` (Task 1), macros (Task 12). Year-end, dashboard, BIR untouched.
- **Section 4/5 testing:** invariants (Tasks 3, 6), unit cases (Tasks 3-4), route tests (Tasks 11-12), verification script (Task 13), marker registered (Task 1).
- **Naming check:** `reporting_basis` everywhere; `remap`, `distribute`, `RemapSummary.as_dict`, `period_balances`, `ledger_lines`, `owners_summary`, `LedgerLine.moved_from_account_id`, `build_general_journal(entries, remapped=None)`, `basis_note=` on the three xlsx builders, `_basis()` in views: consistent across tasks.
