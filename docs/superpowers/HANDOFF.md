# Session Handoff / Coordination Notes

> Cross-session coordination for concurrent Claude sessions sharing this working
> tree. Newest entry on top. Keep entries short; link to the real spec/plan.

## 2026-07-08 — Employee master + combined payee dropdown (READY, model change APPROVED)

**From:** salary-APV session. **Status:** design + plan done, **not started** in code.

- **Spec:** `docs/superpowers/specs/2026-07-08-employee-master-design.md`
- **Plan:** `docs/superpowers/plans/2026-07-08-employee-master-combined-payee.md` (12 tasks, 4 phases, TDD)
- **Owner approval:** model changes **APPROVED** by owner (covers the two `models.py` edits below).

**Heads-up for anyone editing these files — blast radius:**
- **NEW** `app/employees/` blueprint (Employee master, branch-scoped, opt-in `Payroll` module).
- **`app/accounts_payable/models.py`** will gain polymorphic payee: `payee_type` +
  `payee_id`, and **`vendor_id` becomes NULLABLE** (backfilled `payee_type='vendor'`,
  `payee_id=vendor_id`). If you touch AP, expect a hand-written batch migration here.
- **`app/users/module_access.py`** gains an `employees` opt-in entry + `employees.create`
  in `EXEMPT_ENDPOINTS`.
- **AP form / list / detail / print** templates change (vendor select -> combined payee
  select `type:id`).
- **Reports** (AP aging, BIR purchases, supplier Alphalist) get a
  `payee_type == 'vendor'` segregation filter.

**Phase 1 (Employee master, module off by default) is independently shippable** — safe to
land before the AP surgery in Phases 2-4. Coordinate before editing `accounts_payable/`
or `reports/` so we don't collide on the AP changes.

Deferred (separate future initiative): unified Party/Contact model (one person as
vendor + customer + employee).
