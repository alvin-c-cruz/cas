# RIC Legacy COA → CAS `ric.db` — Import Design

**Date:** 2026-07-03
**Status:** Design (approved in brainstorming; pending spec review)
**Full-view reference:** the complete proposed tree (28 groups over 340 leaves) is rendered as an Artifact — "RIC Proposed Chart of Accounts".

## Goal

Import Rowell Industrial Corporation's legacy 340-account Chart of Accounts from the legacy
accounting database into the CAS demo-workspace `ric.db`, reshaped from the legacy flat model
into CAS's hierarchical (postable-leaf) model, with account titles converted from the legacy
ALLCAPS to **proper case** (acronyms and codes preserved).

## Source & target

- **Source (read-only):** `C:\envs\ric-workspace\legacy ric\accounting\instance\data.db`
  - `accounts` (340) + `account_type` (16), a **flat** COA (no parent hierarchy).
- **Target:** `C:\envs\erp-workspace\projects\cas\instance\ric.db` (the erp-workspace RIC instance;
  the separate `ric-workspace` copy is explicitly out of scope per the owner).
  - Reached via the CAS app factory with `SQLALCHEMY_DATABASE_URI=sqlite:///ric.db` (an env
    override; `.env` is left untouched pointing at `cas.db`).

## Non-goals (explicitly out of scope)

- Migrating legacy **transactions** (AP/sales/disbursements/receipts/general/petty-cash journals
  and their `_x` archive counterparts). This is COA only.
- **Remapping the posting engine** to the legacy account codes. CAS hardcodes certain codes
  (see "Posting-engine magic codes"); we keep the CAS seed accounts alongside instead.
- **Retiring** the generic 25-account seed. Deferred until posting behaviour for RIC is decided.
- **Reclassifying** the mis-typed legacy Revenue accounts (see "Data-quality caveats").

## Model reshape

The legacy COA is flat (`account_type` + `accounts`, no `parent_id`). CAS uses one
self-referential `accounts` table and **derives postability from hierarchy**:
`is_group = (parent_id is None) or (has children)` → group headers are **non-postable**
(`app/accounts/views.py:161`). A naïve flat import (all `parent_id = NULL`) would make **all
340 accounts non-postable**. Therefore the import synthesises **group-header accounts** and
parents the 340 legacy accounts as **postable leaves**.

Result: **28 group headers (non-postable) + 338 leaves (postable) = 366 accounts** — 2 of the
340 legacy leaves are skipped as seed-name duplicates (see "Seed-duplicate leaves").

## Leaf field mapping (the 340 legacy accounts)

| CAS `Account` field | Source | Notes |
|---|---|---|
| `code` | `accounts.account_number` | verbatim (e.g. `11101`, `11501-P`) |
| `name` | `accounts.account_title`, proper-cased | **Title Case** via the acronym-preserving caser (see Title casing) |
| `account_type` | `account_type.account_type` → TYPE_MAP | valid CAS type (`account_types.py`) |
| `classification` | TYPE_MAP, with per-group overrides | Current / Non-Current / — |
| `normal_balance` | `DEFAULT_NORMAL_BALANCE[type]`, with contra override | debit / credit |
| `parent_id` | the leaf's group header | not NULL — this is the reshape |
| `is_active` | `True` | |
| `description` | NULL | legacy has none |
| dropped | `user_id`, `date_modified`, `id` | not carried |

Each leaf **and** each group header is written with an audit entry (`log_audit`,
`module='accounts'`, `action='import'`, `record_identifier='<code> <name>'`).

### TYPE_MAP (legacy `account_type` → CAS `account_type` + base classification)

| Legacy type | CAS `account_type` | classification |
|---|---|---|
| Cash and Cash Equivalents | Asset | Current |
| Trade Receivable | Asset | Current |
| Other Current Assets | Asset | Current |
| Fixed Assets | Asset | Non-Current |
| Other Assets | Asset | Non-Current* |
| Accounts Payable | Liability | Current |
| Other Current Liabilities | Liability | Current |
| Other Liabilities | Liability | Non-Current |
| Stockholder's Equity | Equity | — |
| Revenues | Revenue | — |
| Other Income | Other Income | — |
| Direct Materials / Direct Labor / Factory Overhead | Cost of Goods Sold | — |
| Selling Expenses | Selling Expense | — |
| Administrative Expenses | Administrative Expense | — |

\* Overridden per group — see classification overrides.

### Title casing

Legacy titles are ALLCAPS (`CASH ON HAND/CASH SALES`); they are stored **Title Case** for
readability via a deterministic, reusable `proper_case()` helper:

- Each maximal **letter-run** is title-cased; **digits, `%`, `$`, `/`, parentheses, hyphens** and
  other separators are left exactly as-is (so codes/serials/percentages survive:
  `BPI-00008-85`, `... - 1/2%`).
- **True initialisms stay uppercase** via an allow-list — `BPI, SSS, HDMF, NHMFC, VAT, CWT, WHT,
  PDC, RCC, RLMC, RIC, TIN, FO, SE, AE, HMO, ATM, QC` (dot/paren-insensitive, so `(RCC)` and
  `Q.C.` are preserved). Special-cased: `PHILHEALTH → PhilHealth`, `X'MAS → X'mas`.
- **Minor words** (`of, to, the, on, in, for, and, …`) lowercase mid-title; **ordinals**
  lowercase (`13TH → 13th`). Abbreviations that aren't initialisms title-case normally
  (`DEP'N → Dep'n`, `EQPT → Eqpt`, `FCTY → Fcty`).
- **Guarantee:** the transform is **case-only** — `proper_case(t).upper() == t.upper()` holds for
  all 340 titles (verified), so no characters are added, dropped, or reordered.

The acronym allow-list is data-tuned; new client data may need additions. `proper_case()` is
authored once and shared by the importer and any preview tooling.

## Grouping design

Groups are derived from the legacy `account_type` and the account-number prefix. Balance-sheet
buckets sub-group cleanly on the 3-digit prefix (the numbering is semantic there); expense
buckets are numbered sequentially, so they stay **flat** under one header. Two owner decisions:
**Factory Overhead** splits into Indirect Labor vs Manufacturing Overhead; **Fixed Assets**
splits into PPE-at-Cost vs Accumulated Depreciation (a separate parent).

### The 28 groups

| Code | Group header (title) | CAS type | classification | leaves |
|---|---|---|---|---:|
| 111 | Cash & Cash Equivalents | Asset | Current | 12 |
| 112 | Trade Receivables | Asset | Current | 4 |
| 112N | Advances & Non-Trade Receivables | Asset | Current | 6 |
| 113 | Inventory — Tincan | Asset | Current | 4 |
| 114 | Inventory — Plastic | Asset | Current | 4 |
| 115 | Factory & Maintenance Supplies | Asset | Current | 5 |
| 116 | Prepaid Expenses & Interest | Asset | Current | 2 |
| 117 | Assets in Transit | Asset | Current | 8 |
| 125 | Creditable Withholding Tax & Overpayments | Asset | **Current** | 1 * |
| 126 | Input VAT & Tax Credits | Asset | **Current** | 6 |
| 122 | Property, Plant & Equipment — at Cost | Asset | Non-Current | 14 |
| 123 | Accumulated Depreciation (contra) | Asset | Non-Current | 12 |
| 124 | Investments | Asset | Non-Current | 4 |
| 211 | Accounts Payable | Liability | Current | 2 |
| 219 | Other Current Liabilities | Liability | Current | 10 |
| 221 | Tax & Withholding Payables | Liability | Non-Current | 11 |
| 222 | Statutory & Loan Payables | Liability | Non-Current | 9 |
| 311 | Stockholders' Equity | Equity | — | 3 * |
| 411 | Sales — Tincan | Revenue | — | 7 |
| 412 | Sales — Plastic | Revenue | — | 7 |
| 421 | Scrap Sales | Revenue | — | 2 |
| 511 | Other Income & Gains | Other Income | — | 5 |
| 611 | Direct Materials | Cost of Goods Sold | — | 7 |
| 621 | Direct Labor | Cost of Goods Sold | — | 4 |
| 641 | Indirect Labor & Personnel Cost | Cost of Goods Sold | — | 14 |
| 651 | Manufacturing Overhead | Cost of Goods Sold | — | 80 |
| 661 | Selling Expenses | Selling Expense | — | 43 |
| 671 | Administrative Expenses | Administrative Expense | — | 52 |

Leaves total **340** in the legacy source; **338 imported** (2 skipped as seed-name
duplicates); groups total **28**. \* Groups `125` and `311` each show their **imported** leaf
count (1 and 3) after skipping `12501` and `32101`.

### Group codes

Group headers are new accounts with synthetic codes. Rule: **the 3-digit legacy prefix of the
group's leaves**; where a prefix is shared across two groups it is disambiguated. The only
collision is `112` (Trade Receivables vs Advances & Non-Trade Receivables, whose leaves
interleave in the `112xx` range) → Advances takes **`112N`**. Flat multi-prefix groups take a
representative unused 3-digit code (`219` for Other Current Liabilities). Group codes are
guaranteed unique and cannot collide with the 5-digit leaf codes or the 5-digit seed codes.
Group titles are new/descriptive — this is *adding* headers, separate from the (proper-cased)
leaf accounts.

### Group header fields

Group headers are real `Account` rows and must satisfy the `NOT NULL` columns. Each group gets:
`code` = its group code (above); `name` = its title (above); `account_type` = the group's CAS
type (from the table); `classification` = the group's classification; `normal_balance` =
`DEFAULT_NORMAL_BALANCE[account_type]` (cosmetic — groups carry no postings, balance 0, and are
skipped by the statement generators' non-zero filter); `parent_id` = NULL (top-level → non-postable);
`description` = NULL; `is_active` = True. The contra override does **not** apply to the group
header `123` itself — only to its leaf accounts.

### Classification overrides

`classification` is taken from TYPE_MAP by legacy type, then overridden per group where the
legacy type is coarser than reality:

- **`125` Creditable Withholding Tax & Overpayments → Current** (recoverable within the year)
- **`126` Input VAT & Tax Credits → Current** (recoverable within the year)
- `124` Investments stays **Non-Current** (the rest of the legacy "Other Assets" type).

### Contra-account normal-balance override

`normal_balance` derives from the CAS type (`DEFAULT_NORMAL_BALANCE`), except **13 contra
accounts** that are debit-typed but credit-natured are forced to **`credit`**:

- All **12 Accumulated Depreciation** accounts (`12301`–`12312`, group `123`)
- **`11202` Allowance for Bad Debts** (group `112N`)

### Seed-duplicate leaves (skipped) & name uniqueness

`Account.name` is **UNIQUE**. After proper-casing, two legacy leaves collide by name with kept
seed accounts, and two group titles collided with their own leaves. Resolution (owner decision
2026-07-03):

- **Skip** the two legacy leaves whose proper-cased name duplicates a seed account —
  `12501 Creditable Withholding Tax` (seed `10212`) and `32101 Retained Earnings` (seed `30200`).
  The seed accounts are canonical; the legacy codes are dropped. `mapping.SKIP_CODES = {'12501',
  '32101'}`. This makes the import **338 leaves** (groups `125` and `311` keep their other leaves).
- **Rename** two group headers so they no longer equal their own leaf: `116` → *Prepaid Expenses
  & Interest*, `511` → *Other Income & Gains*.
- **Guard:** the importer runs `assert_no_name_clash(specs, session)` before writing — it refuses
  on any duplicate name among the specs or against an existing account, so a future collision
  fails fast with a clear message instead of a mid-write `IntegrityError`.

(The full-view Artifact "RIC Proposed Chart of Accounts" predates this change and still shows the
2 skipped leaves and the old group titles.)

## Posting-engine magic codes (why the seed is kept)

CAS hardcodes specific account **codes** for automatic posting: AR `10201`, CWT `10212`, input
VAT `10501`–`10504`, AP `20101`, output VAT `20201`, WHT payable `20301`, year-end `30201`/`30301`.
The legacy COA has these concepts under *different* numbers (AR `11201`, AP `21101`, input VAT
`12601`–`12606`, output VAT `22103-1`, WHT `22104`/`22105*`, retained earnings `32101`, income
summary `33101`). Rather than remap the engine now, the **existing 25-account CAS seed is kept
alongside** the imported COA so AP/AR/VAT/WHT/year-end posting continues to work. There are **no
code collisions** between the seed codes and the legacy leaf codes, so both coexist. Reconciling
(pointing the engine at the legacy accounts and retiring the seed duplicates) is future work.

## Import procedure

1. **Safety asserts:** target URI ends in `ric.db`; legacy source path exists.
2. **Dry-run (default):** read + map + report (counts, per-type distribution, unmapped types,
   code collisions) — **no writes**. Reviewed before commit.
3. **Commit (`--commit`):** within one app-context transaction —
   a. Create the 28 group headers (non-postable parents).
   b. Create the 338 leaves (2 skipped), each parented to its group; apply classification + contra overrides.
   c. `log_audit(action='import')` per account.
   d. Single `db.session.commit()`.
   - The 25-account seed is **not** cleared.
4. **Server handling:** stop the dev server (which holds `ric.db`) before commit to avoid write
   contention; restart it (pointed at `ric.db`) afterward so the app's account cache reflects the
   new COA.

The importer is idempotent-guarded: it refuses to `--commit` if the imported COA already exists
(re-run = rebuild only if the operator clears it first).

## Acceptance criteria

- The import **adds 366 accounts** = 28 non-postable groups + 338 postable leaves (2 legacy
  leaves skipped as seed-name duplicates). The 25 pre-existing seed accounts are untouched, so
  the target `ric.db` holds **391 accounts total**.
- Every leaf `name` equals `proper_case(legacy account_title)`; the transform is **case-only**
  (`proper_case(t).upper() == t.upper()` for all 340 — no characters added/dropped/reordered).
- Every leaf is **postable** (`is_group == False`): has a `parent_id` and no children.
- All 13 contra accounts have `normal_balance == 'credit'`; groups `125`/`126` are `Current`.
- Trial Balance / Balance Sheet / Income Statement render without error for `ric.db` (the seed
  magic accounts still resolve for any posting).
- An audit entry (`action='import'`) exists per imported account.

## Data-quality caveats (noted, not fixed)

- The legacy **Revenues** type contains non-revenue accounts: Sales Returns & Allowances and
  Sales Discount (contra-revenue), plus Bad Debts, VAT Expense, and Income Tax (expense-natured).
  A faithful import keeps them as `Revenue` per the legacy type. Reclassification is deferred.
- Legacy account numbers carry product-line suffixes (`-TINCAN`/`-PLASTIC`, `-P`/`-T`, `-2`/`-3`)
  and duplicate concepts across the two product lines; preserved (only letter case changes).

## Future work

1. Reconcile the posting-engine magic accounts with the legacy equivalents; retire the seed
   duplicates once RIC's posting is defined.
2. Reclassify the mis-typed legacy Revenue accounts (contra-revenue / expense).
3. If/when legacy transactions are migrated, resolve what the `_x` archive tables represent
   (prior-period vs second books) — see the legacy-model diagram.
