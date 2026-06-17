# CDV Print — APV Parity (preview sequence + layout + peso sign)

**Date:** 2026-06-18
**Status:** Design — approved approach (Option A), pending spec review
**Scope:** 3 files — `app/cash_disbursements/templates/cash_disbursements/print.html`,
`app/cash_disbursements/views.py` (`print_cdv`), `app/accounts_payable/templates/accounts_payable/print.html`

## Goal

Make the CDV (Cash Disbursement Voucher) print experience match the APV (Accounts
Payable Voucher) print experience in **two** ways:

1. **Sequence** — CDV gains a true *preview-then-print* step. Today CDV auto-fires the
   OS print dialog on load with no toolbar; APV opens a preview with a screen-only
   Print/Close toolbar and prints only on user action. CDV adopts the APV behaviour.
2. **Layout** — CDV's `print.html` is reskinned into APV's visual language and wrapper
   structure (Option A: *reskin, preserve CDV content* — no flattening of CDV-specific
   data).

Plus a small cross-cutting change: **add the ₱ peso sign to the APV summary** so both
vouchers follow one shared currency-sign rule (below).

## Non-goals (explicitly out of scope)

- The **route-level print-access gap** (`print_ap` / `print_cdv` do not enforce
  `*_print_access`; gating is template-cosmetic only). This is identical in both
  vouchers, so "matching APV" does not address it. Left logged in the backlog, not
  touched here.
- Any change to CDV data, JE assembly, or the `_build_cdv_je_preview` ordering.
- Any APV layout/structure change. APV's **only** change is adding ₱ to its summary
  (see Peso rule). Its line-item/JE tables stay sign-free (already are).

## Approach — Option A (reskin, preserve content)

Adopt APV's visual idiom and wrapper blocks (centered company header, bordered
info-row tables, JE-beside-Summary row, 3-box signature row, audit footer, screen-only
Print/Close toolbar) **while keeping every CDV content block** — payment/check fields,
Section A (AP bills paid), Section B (direct expenses), and the CDV summary. CDV carries
accounting meaning APV lacks (two payment sections, check details, a different summary
chain); flattening it into APV's single-particulars skeleton (Option B) was rejected
because it destroys that information.

## CDV print.html — block-by-block target

| # | APV block | CDV target |
|---|---|---|
| 1 | `.print-bar.screen-only` (Print + Close) | **Add.** Blue **Print** button `onclick="window.print()"`; grey **Close** link → `url_for('cash_disbursements.view', id=cdv.id)`. **Remove** the existing `<script>window.addEventListener('load', () => window.print());</script>` auto-print line. |
| 2 | Centered company header (`company` dict) + doc title | **Add.** Render `company.name` (upper), `company.address` · `TIN: company.tin` sub-line, doc title **"CASH DISBURSEMENT VOUCHER"**. Replaces the broken `{% if multi_branch %}` branch-name path (that var was never passed by the view → branch name never rendered). **Drop the header status badge** (APV has none; status moves to the footer). |
| 3 | `.info-row`: 2 bordered tables (doc info \| vendor) | Left table = **CDV details**: CD No., Date, Payment method; when `payment_method == 'check'` also Check #, Check Date, Bank; then Cash/Bank Acct (`code — name`). Right table = **Vendor**: name, TIN. Same `.info-row` / `.vendor-header` styling. |
| 4 | `.particulars` table | **Two** APV-`.particulars`-styled tables, each rendered only when non-empty (as today): **"Section A — AP Bills Paid"** (AP Number, Bill Date, Original Balance, Amount Applied) and **"Section B — Direct Expenses"** (#, Description, Account, VAT, WHT, Amount, VAT Amt, WHT Amt). Section headings use APV's `.section-label` / table-header idiom. **No ₱ in any cell** (remove the ₱ currently on Section A's Original Balance / Amount Applied). |
| 5 | `.je-summary-row` (JE left + Summary right) | Same two-column row. **JE table (left):** restyle the existing `je_entries` loop into APV's `.je-table` (Code / Account Title / Debit / Credit + TOTAL row). Keep dict access — `e.code`, `e.name`, `e.debit`, `e.credit` (the preview helper returns dicts, **not** ORM line objects like APV's `je_lines`) — and keep `_build_cdv_je_preview`'s existing ordering (do **not** impose APV's debit/VAT/credit sort). Keep the indent on credit rows. No ₱ in JE cells. **Summary block (right):** APV `.summary-block` styling, CDV figures — see next section. |
| 6 | `.notes-box` (if notes) | CDV particulars/notes → APV `.notes-box` styling, rendered only when `cdv.notes`. |
| 7 | `.sig-row` (3 boxes) | Keep CDV's labels — **Prepared by / Approved by / Received by (Payee)** — in APV's `.sig-box` styling. ("Reviewed" does not fit a disbursement.) |
| 8 | `.audit-footer` | **Always rendered** for CDV (unlike APV's posted-only), because CDV may legitimately print as a draft. APV `.audit-footer` styling. Content: `Printed by {username} · {printed_at}`, plus Created-by / Posted-by when present, plus the CDV **status** (which the dropped header badge previously carried). |

### CDV summary block (right column, APV styling)

Order, with the peso rule applied:

1. **AP Applied** — *first row* → ₱
2. Direct Expenses
3. Input VAT (append ` ⚙` when `cdv.vat_override`)
4. Less WHT — red, `-` prefix (append ` ⚙` when `cdv.wt_override`)
5. `summary-divider-double`
6. **Net Cash Disbursed** — `.summary-net` / `.netval` → ₱

## Peso-sign rule (shared by both vouchers)

- **Line items** (APV particulars + JE; CDV Section A, Section B, JE) → **no ₱**. The
  column header implies currency. (CDV change: strip the ₱ from Section A cells.)
- **Summary block** → ₱ on the **first row**, and on the first row **after every
  underline/divider**. Intermediate rows get no ₱.
  - **APV summary** ₱ on: `Gross Amount` (first), `Net of VAT` (after single divider),
    `Net Amount Payable` (after double divider). The `Less: Input VAT`, `Add: Input VAT`,
    and `Less: Withholding Tax` rows get **no** ₱.
  - **CDV summary** ₱ on: `AP Applied` (first), `Net Cash Disbursed` (after divider).

## `print_cdv` view change

`app/cash_disbursements/views.py::print_cdv` currently:

```python
cdv = _get_cdv_or_404(id)
je_entries = _build_cdv_je_preview(cdv)
return render_template('cash_disbursements/print.html',
                       cdv=cdv, je_entries=je_entries, now=ph_now)
```

Target — build the same `company` dict APV uses and pass a `printed_at` value (matching
APV's `printed_at=ph_now()` convention; drop the `now=ph_now` callable):

```python
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

The template's footer uses `printed_at.strftime(...)` (as APV does), so the `now()`
callable and the dead `multi_branch` reference are both removed from the template.

## Ripple-effect check

- **Views/routes:** only `print_cdv` signature of `render_template` kwargs changes
  (adds `company`, `printed_at`; removes `now`). No URL, no new route, no access-control
  change. `AppSettings` and `ph_now` are already imported in the module.
- **Detail pages:** unchanged. The Print buttons (both `target="_blank"`) and the
  `*_print_access` gating already exist and are untouched.
- **APV:** only `print.html` summary spans gain ₱. `print_ap` view unchanged.
- **JE helper:** `_build_cdv_je_preview` unchanged (dict shape `{code,name,debit,credit}`
  preserved; template already reads those keys).
- **Audit log:** none of these are write operations — no audit entries involved.
- **Exports:** `_cdv_export_data` / Excel/CSV paths are unrelated and untouched.
- **Tests:** `tests/integration/test_cdv_print_access.py` and `test_apv...` exercise
  access gating and route reachability, not exact markup; the reskin must not change
  status codes, the route, or the access semantics. New assertions should target the
  *new* behaviour: (a) CDV print response no longer contains the auto-print
  `addEventListener('load'...` script; (b) CDV print contains a Close link to
  `cash_disbursements.view`; (c) CDV print renders the company name; (d) ₱ appears on the
  APV `Net Amount Payable` line. Confirm no existing test asserts on the removed
  auto-print script or the old CDV markup before editing.

## Testing notes

- This is a template/presentation change with no model or DB impact, so no migration and
  no model-approval gate.
- Manual visual check via the running dev server (Playwright/browser) on one CDV with
  **both** Section A and Section B populated, one check-payment CDV (to verify the check
  fields appear), one draft CDV (to verify footer status + print-access gating), and one
  APV (to verify the three ₱ summary figures). Compare side-by-side with APV for visual
  parity.
- Per project rule: any bug found while testing is reported and fix-approved before
  fixing — not patched inline.
