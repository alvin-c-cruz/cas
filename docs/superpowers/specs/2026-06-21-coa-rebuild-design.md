# Chart of Accounts Rebuild — Design / Runbook

**Date:** 2026-06-21
**Status:** Approved (pending spec review)
**Author:** rebuild session

## Goal

Rebuild the Chart of Accounts from scratch, one account at a time through the
UI, so the hierarchy and naming are clean. The current 356-account legacy import
displays as a scrambled flat list and the names are all-caps. After the rebuild
the COA must render as a proper hierarchical tree with proper-cased names, and
the dependent VAT/WHT master data must be re-entered against the new accounts.

## Constraints (non-negotiable)

- **Child (leaf) account codes stay exactly as they are.** Group/parent codes
  may be renumbered.
- **The user presses every Save.** This session pre-fills forms; it never
  submits a create/update for an account.
- **Nothing destructive runs without an explicit, separate go-ahead** (the
  wipe in step 2).

## Decisions (confirmed with user)

| Topic | Decision |
|---|---|
| Parent grouping | **Decide each leaf's parent live** during entry. Keep the existing 16 group headers. |
| List ordering | **Hierarchical (DFS)** — group header, then its children indented. |
| Name casing | **Title Case + keep acronyms** (see keep-list). User fine-tunes per account. |
| Rebuild user | `alvin` / `ac1123581321`, role **accountant**, active, branch-assigned. |
| Wipe scope | accounts (356) + vat_categories (7) + sales_vat_categories (3) + withholding_tax (4). Keep branches, users, settings. |
| VAT/WHT | Re-entered fresh after COA (no id re-map needed). |

## Key facts established from the live DB

- **Zero transactions** reference accounts (all SI/AP/CR/CD/journal line tables
  empty) — a wipe breaks no posted entries.
- Only account-id references that exist today are the VAT/WHT mappings, which
  are themselves being wiped and re-entered.
- **Approval workflow:** an admin's Save goes to *pending*; only a **sole active
  accountant** auto-approves on Save. Creating `alvin` as the single accountant
  makes every Save take effect immediately.
- **Leaf inheritance:** on the create form, selecting a parent auto-fetches and
  locks the parent's `account_type` and `normal_balance` (and inherits
  `classification`). So a leaf needs only **code + name + parent**.

## The 16 group headers (created first, codes kept)

| Code | Name | Type | Normal balance | Leaves |
|---|---|---|---|---|
| 11 | Cash and Cash Equivalents | Asset | debit | 12 |
| 12 | Trade Receivable | Asset | debit | 4 |
| 13 | Other Current Assets | Asset | debit | 29 |
| 14 | Fixed Assets | Asset | debit | 26 |
| 15 | Other Assets | Asset | debit | 12 |
| 21 | Accounts Payable | Liability | credit | 2 |
| 22 | Other Current Liabilities | Liability | credit | 10 |
| 23 | Other Liabilities | Liability | credit | 20 |
| 31 | Stockholder's Equity | Equity | credit | 4 |
| 41 | Revenues | Revenue | credit | 16 |
| 51 | Other Income (Group) | Revenue | credit | 5 |
| 61 | Direct Materials | Expense | debit | 7 |
| 62 | Direct Labor | Expense | debit | 4 |
| 63 | Factory Overhead | Expense | debit | 94 |
| 64 | Selling Expenses | Expense | debit | 43 |
| 65 | Administrative Expenses | Expense | debit | 52 |

Group classification is currently None for all; the user may set Current /
Non-Current on the asset/liability headers during entry.

## Casing rule (Title Case + acronym keep-list)

Capitalize the first letter of each word; lowercase the rest; **except** tokens
on the keep-list, which stay uppercase. Existing abbreviations are cased, not
expanded (`DEP'N` → `Dep'n`, `EQPT` → `Eqpt`, `MACH` → `Mach`, `TRANSP` →
`Transp`, `FCTY` → `Fcty`, `MO.` → `Mo.`). Common joining words (`of`, `to`,
`and`, `for`, `in`) are lowercased unless first.

**Keep-uppercase list:** VAT, SSS, HDMF, NHMFC, BPI, RCC, RLMC, RIC, PDC, FO,
SE, AE, AR, AP. **Special-case mapping:** `PHILHEALTH` → `PhilHealth`,
`X'MAS` → `X'mas`, `13TH` → `13th`.

The user has final say on every name before pressing Save.

## Procedure

### 1. Pre-flight (non-destructive — runs after spec review)
1a. Export the current 356 accounts to `docs/legacy-import/coa-worklist.md`
    (code, proper-cased name, type, normal balance, current group) — the
    source-of-truth and progress checklist; allows pause/resume across sessions.
1b. Create user `alvin` (role accountant, active, assigned to a branch) so it is
    the sole active accountant. Log in as `alvin` for the rebuild.

### 2. Wipe (destructive — separate explicit go-ahead required)
Delete all rows from `accounts`, `vat_categories`, `sales_vat_categories`,
`withholding_tax`, and their (empty) change-request / link tables. Branches,
users, and settings are untouched.

### 3. Create group headers (16, user Saves each)
For each group: pre-fill code + proper-cased name + type + normal balance
(+ classification if the user wants); user presses **Create Account**.
Auto-approved instantly.

### 4. Enter leaves (340, user Saves each)
In ascending current-code order, per leaf: drive the browser to
`/accounts/create`, pre-fill **code (exact) + proper-cased name**, and state its
*old* group as a hint; the user picks the parent and presses **Create Account**.
Type/balance/classification inherit from the parent automatically. Tick the
worklist; work in batches.

### 5. Re-enter VAT / WHT (user Saves each)
After the COA exists, re-create the input VAT categories, output VAT categories,
and WHT codes via their own UIs, pointed at the new accounts.

### 6. List ordering fix (code change, TDD)
Change `app/accounts/views.py::list_accounts` to build `account_rows` by
pre-order DFS (each root group, then its children sorted by code, recursively)
instead of a flat code sort. Test: assert every child row appears after its
parent and contiguous within its subtree. View-only; no model change, no
migration.

## Verification

- Account count back to expected total; 16 group headers, 340 leaves.
- No orphan leaves (every leaf's parent exists).
- COA list renders as an indented tree with proper-cased names.
- VAT input/output and WHT codes resolve to live accounts.
- Audit log shows create entries for the rebuild (actor `alvin`).

## Out of scope

- Reducing/merging the legacy account set (we keep all 340 leaves).
- Re-importing vendors/customers/transactions (separate legacy-import track).
