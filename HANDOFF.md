# HANDOFF — Delivery Receipt build (wt-dr) → owning session

**Written:** 2026-07-09 · **Worktree:** `C:/envs/erp-workspace/projects/wt-dr`
**Branch:** `feat/delivery-receipts` @ `55c93ce` · **Base:** `main` @ `e6281af`
**Status:** all 5 plan tasks implemented, TDD, one commit each. **Not merged. Not pushed. `main` untouched.**

The executing session is handing the plan back per your request. Nothing here is blocked —
this is a status + recommendations document, not a bug report.

---

## 1. What exists on the branch

| # | Commit | Task |
|---|--------|------|
| 1 | `66b93bd` | Models, `so_line_open_qty`, `generate_dr_number`, `post_delivery_je` seam, migration |
| 2 | `a841468` | Optional module + blueprint + nav + list |
| 3 | `9329606` | Create/view/edit a draft DR against a confirmed SO |
| 4 | `4000eb7` | approve/deliver/cancel lifecycle + cumulative-delivered ≤ ordered guard |
| 5 | `55c93ce` | Printable DR + Create-DR action on SO detail + regression-map |

20 files changed, +1424 / −4.

**Test result:** `pytest -m delivery_receipts -p no:cov -n0 -q` → **24 passed, 0 failed.**

**Collateral suites re-run green** (the registry/nav/shared-surface blast radius):
- 160 passed — `-m "sidebar_nav or settings or users"`
- 84 passed — permission-grid tests (`test_books_access`, `test_admin_sets_viewer_permissions`, `test_chief_accountant`, `test_ca_authz`)
- 51 passed — `-m sales_orders` (its `detail.html` was edited)

**Migration:** `b3d7f1c04e28`, `down_revision = 'a84189785f23'` (the single head at the time).
Verified by `upgrade` + `downgrade` round-trip on a **scratch copy** of the real `cas.db`:
2 tables + 10 indexes created, `dr_number` unique, downgrade removes both cleanly.
**Per the hard rule, the migration was NOT applied to the shared `../cas/instance/cas.db`.**
It is still un-applied there. Whoever merges must run `flask db upgrade` on the dev DB.

---

## 2. Defects found IN THE PLAN (all fixed on the branch; the plan file still has them)

These are the ones worth folding back into `docs/superpowers/plans/2026-07-09-delivery-receipt.md`
before anyone reuses it as a template.

1. **Marker ordering bug.** `pytest.ini` sets `--strict-markers` and had no `delivery_receipts`
   marker. Every test file in the plan opens with `pytest.mark.delivery_receipts`, but the plan
   only registers the marker in **Task 5 Step 5**. Task 1 Step 2 would therefore have died at
   collection with an unknown-marker error, not the intended `ModuleNotFoundError`.
   → Marker registration belongs in **Task 1**.

2. **Wrong gate expectation.** The plan's `test_dr_list_blocked_when_module_off` asserts
   `status_code in (302, 403)`. The real gate (`app/__init__.py`, `before_request`) calls
   `abort(404)` — a disabled optional module is deliberately made to look *absent*, not
   *forbidden*. The plan's test fails against correct behaviour.
   → Assert **404**.

3. **`qty_fmt` renders blank on every DR line.** `app/utils/format_line_qty` duck-types on
   `getattr(item, 'quantity', None)` and returns `''` when absent. A DR line stores
   `delivered_quantity`. The plan's `{{ item | qty_fmt }}` in `detail.html` / `print.html`
   would have rendered an **empty quantity column**, and the plan's print test
   (`assert dr_number in body and 'Widget' in body`) would have passed anyway.
   → Fixed with read-only `quantity` / `unit_of_measure` / `uom_text` properties on
   `DeliveryReceiptItem` (no column, no migration). Approved by the user before implementing.
   → The print test now asserts the quantity string (`'3.0000'`) actually appears.

4. **The worktree has no `venv`, no `.env`, no `instance/`** (all gitignored, so
   `git worktree add` didn't bring them). Every command in the plan
   (`venv/Scripts/python.exe …`, `cp instance/cas.db …`, `flask db upgrade`) is unrunnable
   as written. `EXECUTE-ME.md` documents the venv workaround; the plan does not.
   → Ran pytest via `../cas/venv/Scripts/python.exe` from inside the worktree (works; tests
   supply their own `SECRET_KEY`), and verified the migration on a scratchpad copy.

### Three more things the plan didn't anticipate (found while implementing)

5. **`base.html` needs FOUR nav edits, not three.** Besides the route / icon / subtext dicts
   (~1052 / ~1076 / ~1141), the `active_class()` macro (~1022) also switches on the module key.
   Without it the sidebar link never highlights on a DR page.

6. **The staff approve-gate test passes for the wrong reason as written.** `delivery_receipts`
   is `per_user` and deny-by-default, so a staff user is bounced by the *module* gate long
   before reaching the *approve* gate. The test must grant the `delivery_receipts` book
   permission first, then assert approve is refused.

7. **`generate_so_number()` takes no branch argument** and lives in `views.py`, not `models.py`.
   Its monthly sequence is global (matching the globally-unique number column). The plan's
   `generate_dr_number(branch_id)` accepts `branch_id` but cannot use it. Kept the signature
   for call-site symmetry; documented that the sequence is global.

### One guard added beyond the plan

Cancelling an **already-cancelled** DR is now refused rather than silently re-cancelled.

---

## 3. Deviations from the plan / EXECUTE-ME, stated plainly

- **No `Claude-Session:` trailer** on any of the 5 commits. `EXECUTE-ME.md` asks for
  `Claude-Session: <this session's URL>`; the executing session had no access to that value
  and would not fabricate one. `Co-Authored-By:` is present on all five.
  → Trivially fixable with an interactive rebase / `filter-branch` if you want it.
- **Migration verified on a scratchpad copy**, not on a copy inside the worktree as
  `EXECUTE-ME.md` suggests. Strictly safer — it honours the "never `flask db upgrade` the shared
  `cas.db`" rule and leaves no gitignored DB behind.
- **The line grid ships as a new static file** `app/static/js/delivery_receipts.js` (cache-busted
  `?v=1`), which the plan gestured at but did not specify. Rows are built with `textContent`,
  never `innerHTML`; payloads go through `|tojson`.
- **In-form submit reads Save / Update**, not "Create", per the project's Enter-vs-Create verb rule.
- **`EXECUTE-ME.md` did not exist** when the session started — it appeared partway through the
  run (created by another session or by the user). It is left **untracked**.

---

## 4. NOT done — deliberately, and yours to run

1. **`/guard cas` has not been run.** Standing rule: `/guard` and `/run-tests` are user-invoked
   only and must never be used by an agent as a self-declared green gate. The plan's
   post-implementation step calls for `/guard cas` before pushing. **Run it before merging** —
   this change touches `app/__init__.py`, `app/templates/base.html`, `app/users/module_access.py`
   and `app/sales_orders/templates/sales_orders/detail.html`, all high blast radius.
2. **No browser verification.** The plan's post-implementation asks for a manual pass with
   SO + Products + UoM + `delivery_receipts` all enabled: create a partial DR from a confirmed
   SO → approve → SO open qty drops → a second DR cannot over-deliver at approve → cancel
   releases → print renders → nav link gated. **Not performed.**
3. **The migration is not applied to `../cas/instance/cas.db`.** Run `flask db upgrade` there
   when you merge.
4. **Nothing pushed, nothing merged, no branch deleted, `main` never checked out.**

---

## 5. Live risk: `main` moved under us

`main` advanced from `e6281af` → `f9d7a32` ("docs(spec): Quotation (R-01)") **during** this run.
Another session is active in the shared checkout.

Checked, so you don't have to:
- `e6281af` **is** an ancestor of the new `main` — clean fast-forward, merge is trivial.
- The new commit touches **only** `docs/superpowers/specs/2026-07-09-quotation-design.md`.
- It adds **no migration**, so `b3d7f1c04e28` remains the single alembic head. No merge migration needed.

Note the adjacency: that new spec puts a **Quotation** at the front of the O2C chain
(`Quotation → SO → DR → SI`). Worth a look at whether the DR's `copy_salesperson` carry and the
`billed` seam still line up with what that spec assumes.

---

## 6. Recommendations, in the order I'd take them

1. **Review the diff** — `git diff e6281af..55c93ce` in this worktree. Start with
   `app/delivery_receipts/models.py` (`so_line_open_qty` + `COMMITTED_STATUSES` is the whole
   correctness story) and `views.py::approve` (the guard).
2. **Run `/guard cas`.** It will now pick up `delivery_receipts` — the regression-map was updated
   with the module plus **8** blast edges (the plan listed 3): the three new module files,
   `sales_orders/models.py` (DR reads ordered qty and product through it), and the four shared
   surfaces this change touches (`base.html`, `app/__init__.py`, `module_access.py`,
   `utils/__init__.py` — the last because `qty_fmt` lives there).
3. **Browser-verify** the six-step flow in §4.2 before merging. The guard's arithmetic is
   test-covered; the *form grid* (open-qty column, deliver-now inputs, serialization into the
   hidden `lines` field) has **no browser coverage at all** — that JS is the least-proven surface
   on this branch.
4. **Amend the plan file** with defects 1–4 above so the next module built from this template
   doesn't inherit them. Defect 3 in particular is a silent-green class of bug worth a memory
   entry: *a duck-typed shared filter (`qty_fmt`) fails open — it renders `''` rather than
   raising — so a test that only asserts "the row exists" cannot see the blank column.*
5. **Then merge** (`git merge --no-ff feat/delivery-receipts` from a `main` checkout), run
   `flask db upgrade` on the dev DB, and `git worktree remove` this tree.
6. **Follow-ups already scoped by the spec, none started:** the DR→SI billing flow
   (sub-project #2 — the `sales_invoice_id` + `billed` seam is in place and inert), the Approver
   role (the approve gate carries a `# TODO(Approver role)` and is interim-gated to
   accountant/admin/chief_accountant), R-03 COGS (`post_delivery_je(dr)` is a documented no-op),
   the pre-printed DR designer, and an SO "fully-delivered" status for Order Monitoring.

---

## 7. Friction in the ARRANGEMENT (not the code) — read before setting up the next one

The code came out fine. The *setup* cost real time, and the same seams will bite the next
session unless they're fixed at the source:

1. **`EXECUTE-ME.md` did not exist when the executing session was pointed at it.** The first
   three turns were spent proving a negative (not on disk, never committed on any branch of
   either repo, no stashes, not in the scratchpad) before the file appeared mid-run. If a
   session is going to be told "read `X` and follow it", **write `X` before handing over the
   path.**
2. **The plan assumed a working tree it wasn't going to run in.** `git worktree add` does not
   carry gitignored files, so `venv/`, `.env` and `instance/` were absent, and *every* command
   the plan spelled out was unrunnable as written. Either bake the sibling-venv invocation into
   the plan, or have the setup step copy what's needed — don't leave it for the executor to
   discover at Task 1 Step 2.
3. **The plan was never executed even once before being handed off.** All four defects in §2 are
   things a single dry run would have surfaced immediately (an unregistered marker under
   `--strict-markers`, a gate that returns 404 rather than 302/403, a filter that fails open to
   `''`, and missing tooling). A plan written from reading the code, but never run against it,
   ships its assumptions as instructions.
4. **The commit-trailer requirement was unsatisfiable.** `EXECUTE-ME.md` demanded a
   `Claude-Session: <URL>` trailer on every commit; the executing session has no access to that
   value. Don't require a value the executor cannot obtain.
5. **`main` moved during the run** (`e6281af` → `f9d7a32`). The worktree isolated the work
   correctly — this is the arrangement *working* — but it confirms concurrent sessions on one
   checkout. Anything long-running belongs in its own worktree, as this was.

Net: the worktree isolation did its job. The handoff *protocol* around it (a promised file that
didn't exist, a plan never dry-run, a required trailer nobody could supply) is what cost the time.

---

## 8. If you'd rather not keep this work

The branch is self-contained and nothing outside it was modified. To discard entirely:

```bash
git worktree remove C:/envs/erp-workspace/projects/wt-dr --force
git branch -D feat/delivery-receipts
```

Nothing was pushed, so there is no remote state to clean up.
