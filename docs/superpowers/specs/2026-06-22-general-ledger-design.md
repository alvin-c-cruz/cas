# General Ledger — Design Spec

**Date:** 2026-06-22
**Status:** Approved (brainstorming complete; ready for implementation plan)
**Feature:** Activate the **General Ledger**, currently a nav stub that redirects to
`dashboard.under_development?feature=General+Ledger`.

## Summary

Build the **all-accounts General Ledger book**: the BIR-style bound ledger where every
postable account appears in sequence, each as a section listing its posted journal-entry lines
in date order, with an opening balance, a running balance per line, and a closing subtotal. It
is the missing drill-down layer between the Trial Balance (one balance per account) and the
source documents.

The ledger data already exists — every posted transaction (AP, SI, CDV, CRV, manual Journal
Voucher) replays into `JournalEntry` / `JournalEntryLine`, which is the canonical double-entry
store and is already branch-scoped. This feature is **read-only reporting over existing data**;
it adds no new transactional model.

## Scope

### In scope
- A `generate_general_ledger(...)` generator in `app/reports/financial.py`.
- A `general_ledger` view + template in the existing `reports` blueprint, with Excel, CSV, and
  print outputs.
- A filter form: required date range (default = current month), optional single-account
  search-select, automatic current-branch scope, hide empty accounts.
- Per-line drill-down to the originating source document.
- Wiring: `general_ledger` added to the `book_permissions` module registry; the sidebar nav
  link switched from the under-development stub to the real route.

### Out of scope (deferred)
- **Per-account-title access** (restricting a user to specific accounts). This is its own
  system-wide feature — it needs a `User ↔ Account` grant model + migration and must be enforced
  consistently across GL **and** Trial Balance / Balance Sheet / Income Statement, otherwise the
  same balances leak through the other reports. Not bolted onto this build.
- **Un-stubbing Trial Balance / Income Statement / Balance Sheet / BIR reports.** Their
  generators already exist in `financial.py` but their views are stubbed with an early
  `redirect(... under_development)`. Adjacent, but a separate effort.

## Architecture

Chosen approach: **extend the existing `reports` blueprint + `financial.py`** (Approach A),
mirroring the AR/AP-aging and Trial Balance patterns already in `app/reports/views.py`.
Rejected: a `journal_entries`-blueprint view (splits "reports" across blueprints, breaks the
BIR-book framing) and a standalone `ledger` blueprint (a whole new blueprint to register and
gate for one report).

### 1. Data generator — `app/reports/financial.py`

```
generate_general_ledger(start_date, end_date, branch_id, account_id=None)
```

- Iterate active **postable** accounts in `Account.code` order. Parents/group accounts are
  non-postable and hold no lines, so they fall out naturally; if `account_id` is supplied,
  restrict to that one account.
- For each account:
  - `opening_balance` = Σ(`debit_amount` − `credit_amount`) over **posted** lines whose
    parent `JournalEntry.entry_date < start_date`, branch-scoped.
  - In-range lines: posted `JournalEntry.entry_date` between `start_date` and `end_date`
    inclusive, ordered by `entry_date`, then `entry_number`, then `line_number`. Each line
    carries a **running balance** = previous running balance + (`debit` − `credit`).
  - `closing_balance` = opening + Σ(in-range movements); plus a subtotal row.
  - **Debit-positive convention:** running/opening/closing balances are stored as
    `debit − credit`. The template renders them with a **Dr / Cr** indicator (positive → Dr,
    negative → Cr shown as absolute value) so credit-normal accounts read correctly.
- **Hide-empty:** skip any account whose `opening_balance == 0` **and** which has no in-range
  lines.
- **Posted-only** (`JournalEntry.status == 'posted'`), branch-scoped to the passed `branch_id`.

Return shape (floats for template/export, mirroring the other generators):

```python
{
  'start_date': date, 'end_date': date,
  'accounts': [
    {
      'code': str, 'name': str, 'account_type': str,
      'opening_balance': float,           # debit-positive
      'lines': [
        {
          'entry_id': int, 'entry_number': str, 'entry_date': date,
          'entry_type': str, 'reference': str,
          'description': str,             # line.description or entry.description
          'debit': float, 'credit': float,
          'running_balance': float,       # debit-positive
          'source': {'url': str|None, 'label': str},   # see §2
        }, ...
      ],
      'total_debit': float, 'total_credit': float,
      'closing_balance': float,           # debit-positive
    }, ...
  ],
  'grand_total_debit': float, 'grand_total_credit': float,
}
```

### 2. Source-document drill-down

A helper maps each line's `JournalEntry.entry_type` to its originating document and resolves the
URL by the stored `reference` number:

| `entry_type`                                          | Source doc        | Link target                          |
|-------------------------------------------------------|-------------------|--------------------------------------|
| `sale`                                                | Sales Invoice     | `sales_invoices.view` (by number)    |
| `purchase`                                             | Accounts Payable  | `accounts_payable.view` (by number)  |
| `receipt`                                              | Cash Receipt (CRV)| `cash_receipts.view` (by number)     |
| `disbursement`                                         | Cash Disburse (CDV)| `cash_disbursements.view` (by number)|
| `adjustment` / `opening` / `closing` / `reclassification` / `reversal` | Journal Entry | `journal_entries.view` (by `entry_id`) |

The four clean transaction types deep-link by their `reference` (= the document number). Manual
vouchers and reversals (whose `reference` may be prefixed, e.g. `CANCEL-…`) link to the Journal
Entry view by `entry_id` — no fragile prefix-parsing. `label` is a human string
(e.g. `"SI AR-2026-06-0001"`). If a mapped type's `reference` can't be matched to an existing
document (rare — the source doc was hard-deleted while its JE survived), the line falls back to
the Journal Entry view link as well (label = JE number), so the Source cell is always a usable
link. (Decided 2026-06-22 over an earlier `url=None` draft: the JE link is strictly more useful
and `entry_id` is always valid. The `source.url` field is therefore always non-null in practice.)

### 3. Routes — `app/reports/views.py`

All gated by `accountant_or_admin_required` **and** registered under the `general_ledger`
book-permission key (see §5):

| Route | Purpose |
|-------|---------|
| `GET /reports/general-ledger` | Filter form + rendered book |
| `GET /reports/general-ledger/export/excel` | `.xlsx` via `export_to_excel` |
| `GET /reports/general-ledger/export/csv` | `.csv` via `export_to_csv` |
| `GET /reports/general-ledger/print` | Print layout, page-break per account section |

Filter inputs (query params): `start_date`, `end_date` (default = 1st of current month → today),
`account_id` (optional). Branch comes from `session['selected_branch_id']` (already validated by
the global `before_request` hook — no duplicate check needed). Invalid/blank dates fall back to
the current-month default, matching the aging-report pattern.

Exports and print honour the same filter params so a "filtered" export never leaks every row
(see the query-param-name-mismatch hazard — every export/print link must carry `start_date`,
`end_date`, `account_id`).

### 4. UI — templates

- `app/reports/templates/reports/general_ledger.html` — filter bar + the book; one card per
  account: header `code — name`, columns **Date · JE# · Source · Description · Debit · Credit ·
  Balance**, an opening-balance row and a closing-subtotal row. JE# links to the JE view; Source
  links per §2.
- `app/reports/templates/reports/general_ledger_print.html` — print-optimized, page-break per
  account section.
- Conventions: design tokens only (no hardcoded styling), responsive (desktop/tablet/mobile),
  the literal `₱` glyph (never `&#8369;`), and the account picker built via `initSearchSelect`
  (Choices.js, code+name, `escHtml`/`allowHTML:false`).
- Add a General Ledger card to `reports/index.html` alongside the AR/AP-aging cards.
- Any new/edited static asset under `app/static/` gets its `?v=N` cache-buster bumped on every
  template that links it.

### 5. Access wiring — `app/users/module_access.py`

Add to `MODULE_REGISTRY` (section `'Ledger'`):

```python
{'key': 'general_ledger', 'label': 'General Ledger', 'section': 'Ledger',
 'endpoints': ('reports.general_ledger', 'reports.general_ledger_export_excel',
               'reports.general_ledger_export_csv', 'reports.general_ledger_print')}
```

Gating is **staff-only** (admin/accountant/viewer always allowed; staff checked against
`book_permissions`), consistent with `ap_aging`/`ar_aging`. The user-edit form's Ledger section
picks up the new checkbox automatically from the registry.

### 6. Nav — `app/templates/base.html`

Replace the `nav-item--soon` "General Ledger → `dashboard.under_development`" link (~line 1141)
with a real link to `reports.general_ledger`, wrapped in
`{% if can_access_module(current_user, 'general_ledger') %}` (matching the surrounding Ledger
items), 📖 icon kept, "Soon" badge removed, `active` state keyed on the new endpoint.

## Ripple effects

- `app/reports/financial.py` — new generator (+ its source-doc helper, or place the helper in
  the view).
- `app/reports/views.py` — 4 new routes.
- `app/reports/templates/reports/` — 2 new templates + `index.html` card.
- `app/users/module_access.py` — registry entry (drives sidebar + user-edit form + global
  `before_request` gate; no other code change needed there).
- `app/templates/base.html` — nav link swap.
- `tests/integration/test_under_development.py` — GL no longer redirects; update/remove the GL
  assertion.
- `tests/integration/test_sidebar_roles.py` — GL sidebar item changes from a "Soon" stub to a
  gated real link; update expectations.
- Seed/`book_permissions`: existing staff users won't have the new key → denied by default,
  which is the intended Phase-2 deny-default behaviour. No seed change required, but note it.

## Testing (TDD)

Unit — `generate_general_ledger`:
- opening balance = sum of prior posted lines only (drafts/other branches excluded);
- running balance accumulates correctly across multiple lines and equals closing balance;
- hide-empty skips zero-opening + no-movement accounts but keeps an account with only an opening
  balance;
- `account_id` filter returns exactly one account;
- branch scoping excludes another branch's lines;
- posted-only (a draft JE in range is ignored).

Integration — views:
- access control: accountant/admin 200; staff without the grant redirected/403; staff **with**
  `general_ledger` granted gets 200; viewer 200;
- date-range + account filters reflected in output and carried into export/print links;
- Excel/CSV/print routes return the right content type and honour filters;
- nav shows the real GL link (no "Soon") and the under-development redirect is gone.

The GL is **read-only** — it performs no writes, so the audit-in-tests rule (assert an audit row
after every write) does not apply here; there is nothing to audit.

## Open implementation notes
- Running-balance rendering (Dr/Cr indicator) is a template concern; the generator stays in the
  debit-positive numeric convention used by the existing Trial Balance generator.
- The all-accounts book over ~360 accounts is bounded by the current-month default and the
  hide-empty rule; if performance is a concern later, the single-account path is the fast lane.
