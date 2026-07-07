# CAS Implementation Plans — Index

| Date | Plan | Status |
|---|---|---|
| 2026-07-07 | [Clean copy — firm+software COA + seed-firm](2026-07-07-firm-software-coa-clean-copy.md) | **DONE + DEPLOYED** — `flask seed-firm` + `FIRM_COA` (116 accts), 17 tests; pushed; LIVE at alvinccruz.pythonanywhere.com on fresh cas.db (SavorPack demo archived) |
| 2026-07-03 | [RIC legacy COA import](2026-07-03-ric-coa-import.md) | Done — imported to `ric.db` (391 accts); final review YES; on main, not pushed |
| 2026-07-03 | [RIC COA reconciliation (seed retirement)](2026-07-03-ric-coa-reconciliation.md) | Done — executed on `ric.db` (391→368); D1–D4 resolved; scripts/ric_coa/reconcile.py |
| 2026-07-03 | [WHT per-rate posting routing](2026-07-03-wht-per-rate-posting.md) | Done — final review YES; AP+CDV bucket WHT payable by ATC (20301 fallback); on main, not pushed |
| 2026-07-03 | [Opening Balances — SI line-item parity](2026-07-03-opening-balances-si-parity.md) | Done (on main, not pushed) |
| 2026-07-03 | [Transaction-form line-item component standard](2026-07-03-transaction-line-item-standard.md) | Scoped — not started |
| 2026-07-03 | [Food Toll Packing demo dataset](2026-07-03-food-toll-packing-demo.md) | Done (on main, not pushed) |
| 2026-07-04 | [CDV check printing + per-account layout](2026-07-04-cdv-check-printing.md) | Scoped, boardroom-reviewed (rev.2) — not started; Increment 1 (Default check) then Increment 2 (per-account) |
| 2026-07-05 | [SI pre-printed layout designer](2026-07-05-si-preprinted-layout-designer.md) | **Done (on main, not pushed)** — shipped + extended well beyond the plan: drag/resize/duplicate fields, independent column positioning, show/hide fields+columns, per-element + band font/bold, grouped dot-matrix fonts, paper toggle (continuous/Letter), date-format picker, BIR summary fields, editable Preparer/Checker/Approver texts, value-only output, margin guides, `@page` margin:0. Layout JSON in `app_settings`; ~50 tests (unit+integration+Playwright e2e) |
