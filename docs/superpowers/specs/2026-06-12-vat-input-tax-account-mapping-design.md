# VAT Category → Input Tax Account Mapping (resolves B-014)

**Date:** 2026-06-12
**Status:** Approved by owner (this document reflects the approved design)
**Origin:** Test run 1 bug B-014 — purchase journal entries hardcode input VAT
to account `10501`, which after the 2026-06-12 COA restructure is
"Input VAT - Capital Goods". All purchase input VAT (goods, services,
importation) was booking there regardless of purchase type.

## Decision summary (owner choices)

1. The input-tax account used in journal entries is a property of the
   **VAT category**, selected on the VAT category form.
2. Four new 12% categories classify purchases: `V12CG`, `V12DG`, `V12SV`,
   `V12IM` (Input Tax Capital Goods / Domestic Goods / Services /
   Importation → accounts 10501 / 10502 / 10503 / 10504).
3. Existing generic `V12` "VAT 12%" stays active and maps to
   **10502 Input VAT - Domestic Goods** (the ordinary-purchases default).
4. Zero-rate categories (`V0`, `VEX`, `INV`) produce no input tax and need
   no account.
5. A VAT-bearing line whose category lacks an account is an **error**, never
   a silent fallback.

## 1. Data model

### New column

```python
# app/vat_categories/models.py — VATCategory
input_vat_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'),
                                 nullable=True)
input_vat_account = db.relationship('Account')
```

- Nullable: NULL is the correct value for zero-rate categories.
- No default. One Alembic migration adds the column; no data backfill in the
  migration (data flows through the app's approval workflow, below).
- `to_dict()` includes `input_vat_account_id` plus the account's `code` and
  `name` (needed by the APV form's JE preview).

### Form rules (`VATCategoryForm`)

- New select field, choices = active accounts rendered `code : name`,
  group accounts disabled (derived: an account is a group if any account has
  it as parent — same rule as the APV picker), Choices.js search-select.
- Validation: **required when rate > 0**; ignored/cleared when rate = 0.
  Client-side: the picker is hidden when the rate field is 0.
  Server-side: form validator enforces the same rule.

### Approval workflow

The field is part of `proposed_data` for create/update change requests:

- Create/edit forms capture it; the duplicate-pending guard is unaffected.
- The review page and the change-requests list show the proposed account
  (`code : name`).
- On approval, the account id is applied to the `VATCategory` row.
- Audit `new_values`/`old_values` include `input_vat_account_id`.

### List page

`/vat-categories/` gains an "Input Tax Account" column showing
`code : name` or "—" for unmapped (zero-rate) categories.

## 2. Journal entry behavior (purchase bills)

### Per-category buckets

`_post_bill_je()` replaces the single aggregate input-VAT line with one debit
line **per distinct input-tax account** across the bill's lines:

1. For each line: compute its VAT amount (existing math). Zero → skip.
2. Resolve the line's VAT category → `input_vat_account`. Missing account on
   a VAT-bearing line → raise `ValueError` naming the category:
   `"VAT category 'X' has no Input Tax account configured. Set it in VAT
   Categories."` The create/update/post routes surface this as the standard
   error flash; nothing is saved.
3. Sum VAT per account; emit one JE debit line per account, ordered by
   account code.

`_get_gl_accounts()` no longer supplies the input-VAT account (the `10501`
hardcode is removed). `20101` Accounts Payable and `20301` Withholding Tax
Payable remain hardcoded — out of scope here.

### VAT override

The existing whole-bill override still works: the difference
(override − computed total) is applied to the **largest VAT bucket**.
Overrides exist for centavo discrepancies against the vendor's invoice, so
adjusting the dominant line matches practice. With a single bucket the
behavior is identical to today.

### Reversal (cancel) and void

- `_create_reversal_je()` currently REBUILDS the reversal from bill totals
  with its own hardcoded `10501`. It is rewritten to **mirror the bill's
  stored JE lines** (same accounts/amounts, debits and credits swapped).
  This reverses exactly what was booked — per-category buckets, overrides
  and all — and removes the second `10501` hardcode. Cancel requires a
  posted bill, which always has a stored JE; if the JE is missing the
  function raises (same error pattern as today).
- Void deletes the draft JE — unaffected.

### JE preview (APV form)

The `vatCategories` JSON payload passed to the form gains each category's
account `{id, code, name}`. `renderJEPreview()` groups line VAT by that
account, mirroring the server logic, including override-to-largest-bucket.

## 3. Data changes (after code ships)

Performed through the app's change-request workflow (one accountant submits,
the other approves) so the audit trail captures them:

| Action | Category | Rate | Input tax account |
|--------|----------|------|-------------------|
| update | V12 — VAT 12% | 12% | 10502 Input VAT - Domestic Goods |
| create | V12CG — Input Tax Capital Goods | 12% | 10501 Input VAT - Capital Goods |
| create | V12DG — Input Tax Domestic Goods | 12% | 10502 Input VAT - Domestic Goods |
| create | V12SV — Input Tax Services | 12% | 10503 Input VAT - Services |
| create | V12IM — Input Tax Importation | 12% | 10504 Input VAT - Importation |

`V0`, `VEX`, `INV` are untouched (rate 0, no account).

Note: under the B-011 rule, with two active accountants (msantos, jreyes)
these requests go pending and are cross-approved.

## 4. Out of scope

- Output VAT (sales-side) account mapping — future analog field.
- Per-line input-tax account overrides on the APV form.
- Remapping `20101`/`20301` hardcodes (tracked under B-014's original note).
- `flask seed-db`: the seeded 173-account COA and VAT categories are checked
  for consistency — if the seed creates 12% categories, the seeder must set
  their input-tax account to the seed COA's input VAT account; otherwise
  seeding stays untouched.

## 5. Testing

- Form validation: rate > 0 without account → rejected; rate 0 without
  account → accepted.
- Approval flow: create + update requests carry the field; approval applies
  it; review page shows it.
- JE split: bill with V12DG and V12SV lines → two input-VAT debit lines
  (10502, 10503), balanced.
- Override: difference lands on the largest bucket only.
- Unmapped guard: VAT-bearing line with an unmapped category → clear error,
  bill not saved.
- Existing purchase-bill suites (numbering, void, cancel, JE lifecycle) stay
  green.

## 6. Affected files (expected)

- `app/vat_categories/models.py` (+ migration)
- `app/vat_categories/forms.py`, `views.py`, templates (form, list,
  review, change_requests)
- `app/purchase_bills/views.py` (`_post_bill_je`, `_create_reversal_je`,
  `_build_je_preview`, `_get_gl_accounts`, create/update/post error handling)
- `app/purchase_bills/templates/purchase_bills/form.html`
  (`renderJEPreview`, `vatCategories` payload)
- `tests/integration/` (new + updated suites)
