# RIC COA Reconciliation — Seed Retirement & Redundancy Cleanup (Plan)

**Date:** 2026-07-03
**Status:** Design — **decisions pending** (nothing executed; `ric.db` untouched at 391 accounts).
**Depends on:** `2026-07-03-ric-coa-import-design.md` (the import that produced the current state).

## Why

The RIC legacy COA was imported **alongside** the 25-account generic seed (kept only so CAS's
posting engine had its hardcoded "magic-code" accounts). That leaves the COA carrying two
accounts for several concepts. This plan retires the redundancy per standard COA hygiene.

## Guiding principles (from accounting research, 2026-07-03)

1. **One account per concept.** A chart of accounts should not carry two accounts for the same
   thing (e.g. seed `Accounts Receivable - Trade` *and* legacy `Accounts Receivable-Trade`).
2. **Consistent naming — `&` and `and` are the same word.** Standardize on **`&`** (legacy and
   RIC's own titles use `&`; only the seed used `and`). No formatting-only duplicates.
3. **Prioritize the legacy (client) account.** RIC's real account wins over the generic seed
   placeholder wherever they duplicate.
4. **Stable numbering the posting engine expects.** CAS hardcodes specific *codes* for automatic
   posting; the reconciliation must preserve those codes, so "prioritize legacy" is achieved by
   **recoding the legacy account onto the magic code**, not by deleting the code.
5. **Nature of accounts preserved.** Real (balance-sheet) vs Nominal (income-statement) typing and
   normal balances (incl. contra) already imported correctly — reconciliation must not disturb them.
6. **Leave numbering gaps** for future accounts; don't renumber beyond what's required.

## Current redundancy (measured in `ric.db`)

Normalized-name duplicate clusters (`&`↔`and`, spacing, case): **5** — plus the broader fact that
all 25 seed accounts duplicate concepts RIC already has. The 25 seed accounts split three ways:

### Category A — generic duplicates, safe to DROP (not hardcoded, not FK-referenced)
`10100` Cash & Cash Equivalents (grp) · `10101` Cash on Hand · `10110` Cash in Bank - Current ·
`10200` Trade & Other Receivables (grp) · `20100` Trade & Other Payables (grp) · `40100` Sales
(grp) · `40101` Sales - Goods · `40102` Sales - Services · `50220` G&A Expenses (grp) · `50226`
Office Supplies Expense. RIC's own accounts cover each; nothing posts to these by hardcoded code.

### Category B — posting-engine magic codes → RECODE legacy onto the code, then drop the seed
CAS hardcodes these codes; the seed VAT accounts are also FK-referenced by VAT categories. For
each, **recode the legacy account to the magic code**, **repoint any FK**, then **delete the seed**:

| Magic code (kept) | Concept | Recode legacy → code | FK to repoint |
|---|---|---|---|
| `10201` | Accounts Receivable – Trade | `11201` Accounts Receivable-Trade | — |
| `20101` | Accounts Payable – Trade | `21101` Accounts Payable-Trade | — |
| `10501` | Input VAT – Capital Goods | `12601` Input Tax - Capital Goods | `vat_categories.V12CG` |
| `10502` | Input VAT – Domestic | `12602` Input Tax - Domestic | `vat_categories.V12DG` |
| `10503` | Input VAT – Services | `12603` Input Tax - Services | `vat_categories.V12SV` |
| `10504` | Input VAT – Importation | `12604` Input Tax - Importation | `vat_categories.V12IM` |
| `20201` | Output VAT – Sales | `22103-1` Output Tax | `sales_vat_categories.V12` |
| `20301` | Withholding Tax Payable – Expanded | `22105` WHT Payable-Suppliers **‹decision›** | — |

### Category C — legacy was SKIPPED at import → seed is currently canonical
`10212` Creditable Withholding Tax (legacy `12501` skipped) · `30200`/`30201` Retained Earnings
(legacy `32101` skipped) · `30301` Current Year Earnings (legacy `33101` "Income & Expenses
Summary" imported separately). Here the seed already holds the magic code and the legacy twin was
dropped, so no recode is strictly needed — **decision:** keep the seed for these, or re-introduce
the legacy account recoded onto the magic code for full legacy-priority consistency.

## Open decisions (confirm before execution)

- **D1 — WHT granularity.** Map magic `20301` (single "Expanded") to legacy `22105` (general
  suppliers WHT), or to the rate-split legacy set (`22105-1..5`)? Posting uses one code.
- **D2 — Output VAT.** Map `20201` to legacy `22103-1` "Output Tax" (recommended) vs `22103`
  "VAT Payable".
- **D3 — Category C.** Keep seed `10212`/`30201`/`30301`, or re-import legacy `12501`/`32101`/`33101`
  recoded onto them and drop the seed (full legacy-priority)?
- **D4 — Group headers.** After recodes/drops, remove the now-empty seed group headers
  (`10500`/`20200`/`20300` etc.) and the two Sales group-title near-dups (`411`/`412` vs their
  leaves) — cosmetic normalization.

## Execution approach (mirrors the import's rigor — data-only, no app-code change)

Phase it as a reversible, dry-run-first tool (extend `scripts/ric_coa/`), TDD against a seeded
test DB:

1. **Back up** `instance/ric.db` first (copy to `ric.db.bak-<date>`).
2. **Recode** each Category-B legacy account's `code` → the magic code (`UPDATE accounts SET code=…`).
3. **Repoint** the 5 VAT-category FKs from the seed account id → the recoded legacy account id.
4. **Delete** the seed duplicates (Category A + the recoded-over Category B seeds), after asserting
   nothing else references them (no journal lines, no FKs).
5. **Normalize** `&` and drop cosmetic near-dups (D4).
6. **Audit** each change; **dry-run** summary → owner confirm → commit; **verify**: TB still
   balances, no orphan FKs, posting-engine codes all resolve to a single (legacy) account,
   `flask db`/reports render.
7. Keep the same safety guards as the importer (target must be `ric.db`; refuse on unexpected state).

## Acceptance

- Zero normalized-name duplicate clusters remain.
- Every posting-engine magic code (`10201`/`20101`/`10501-04`/`20201`/`20301`/`10212`/`30201`/
  `30301`) resolves to exactly **one** account, and where a legacy twin existed it is that account.
- All VAT-category FKs point at live accounts; Trial Balance balances; no orphaned journal lines.
- `&` used consistently; no formatting-only duplicates.

## Non-goals

- No change to the posting engine or any `app/` code (data-only reconciliation).
- No re-typing/re-classification of accounts (nature-of-accounts already correct from the import).
