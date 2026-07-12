# Fixtures

Snapshots of `/ui-test cas` (empty-schema) master data, captured after building it through the
UI, for **reuse as a build recipe** in a later session -- not a seed script. This project's
no-seeding discipline (memory `feedback-ui-mcp-testing-rules`) means these values must be replayed
through the real UI forms, not imported into the DB directly.

## `master_data.json` (2026-07-12)

**Scope: CAS's own generic self-test setup only.** A minimal "Sample Trading Corporation" company:
Company Settings, 3 users (admin + 1 accountant + 1 staff, with their test passwords), a 19-account
COA following the RIC-style convention (specific functional-category top-level parents, no generic
"Assets"/"Liabilities" umbrella -- see memory `ric-coa-parent-account-convention`), 1 purchase-side
VAT category, 1 sales-side VAT category, 1 withholding tax code, and the 4 Control Accounts
assignments. A separate fixture set scoped to the broader ERP context (multi-app workspace setup)
is planned for later -- don't extend this file for that; start a new one alongside it.

**Replay order** (later steps depend on the COA existing):
1. Company Settings -- Company Profile + Accounting tabs
2. Chart of Accounts -- create the 5 top-level categories first (`parent_code: null`), then the
   leaves (`parent_code` refers to another entry's `code` in this same file)
3. VAT Categories (`/vat-categories/create`) + Sales VAT Categories (`/sales-vat-categories/create`)
   -- each needs an Input/Output Tax account from the COA
4. Withholding Tax codes (`/withholding-tax/create`) -- needs the COA (payable/receivable accounts)
5. Settings > Control Accounts -- needs the COA

Note: `accountant_email_self_approval` was left ON in this snapshot from a prior test pass on the
account it was captured from -- verify it matches what you want before replaying.
