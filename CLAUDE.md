# CAS app (projects/cas)

This file provides guidance to Claude Code when working with code in this repository.

## What This Is

CAS (Computerized Accounting System) — an accounting-first ERP for Philippine SMEs, BIR-compliant, built with Flask + SQLAlchemy + SQLite. Domain centers on double-entry accounting (Chart of Accounts, journal entries, sales invoices, purchase bills, receipts) with multi-branch support, role-based access, an approval workflow for sensitive changes, and a full audit trail.

This directory (`erp-workspace/projects/cas/`) is CAS's own independent git repo (`origin` → `github.com/alvin-c-cruz/cas.git`, deployed to PythonAnywhere), gitignored by the parent `erp-workspace` repo. It self-guards via its own `.claude/guard.py` + `.claude/regression-map.json` + `.claude/githooks/pre-push` (wired with `git config core.hooksPath .claude/githooks`). The workspace-level tooling that drives this app (`/cas-run`, `/run-tests`, `/guard`, `/audit`, `/retro`) lives one level up, in `erp-workspace/.claude/skills/` — see `erp-workspace/CLAUDE.md` for how the two layers interact.

## Commands

> All commands below run from **`projects/cas/`** (the app root — `cd` here first, or use the project venv path directly as shown).

```powershell
# Run the dev server (port 5050)
python flask_app.py
# or, if python doesn't resolve to the project venv:
C:/envs/erp-workspace/projects/cas/venv/Scripts/python flask_app.py

# Seed the database (admin user, main branch, 173-account COA, VAT categories, WHT codes, settings)
flask seed-db

# Seed minimal data for demos/quick local setup (admin, 1 branch, 6 accounts, 4 VAT categories, 3 WHT codes)
flask seed-minimal

# Migrations (Flask-Migrate / Alembic)
flask db migrate -m "describe change"
flask db upgrade

# Tests (config in pytest.ini; coverage is NOT in addopts -- run --cov explicitly for htmlcov/)
pytest                                   # default run: everything EXCEPT e2e (addopts adds -m "not e2e")
pytest tests/unit/test_user_model.py     # single file
pytest tests/unit/test_user_model.py::TestUserModel::test_password_hashing  # single test
pytest -m unit                           # by marker: unit, integration, auth, models, views, security, smoke, performance, slow
pytest -m "not slow"
```

Requires a `.env` file (see `.env.example`). **`SECRET_KEY` is mandatory** — `config.py` raises at import if it is unset. Tests set their own keys in `tests/conftest.py`.

## Architecture

**App factory + blueprints.** `app/__init__.py::create_app(config_name)` is the single composition root. Every feature is a blueprint package under `app/<feature>/` (typically `models.py`, `forms.py`, `views.py`). Both model imports (for migration autodetect) and blueprint registration are **explicit lists** in `create_app` — when you add a model or blueprint, you must register it there manually. Config is selected by `FLASK_ENV` via `config.py` (`development` / `production` / `testing`); testing uses an in-memory SQLite DB with CSRF disabled.

**Cross-cutting concerns wired in `create_app`:**
- Context processors inject `now` (PH time), `current_branch` (from `session['selected_branch_id']`), and `action_items_count` (pending approval count for the sidebar badge) into all templates.
- `@before_request`/`@after_request` hooks do request logging, response logging for ≥400, HTTPS enforcement (prod), and security headers (CSP, HSTS, X-Frame-Options, etc.).
- Extensions: `db`, `migrate`, `login_manager`, `csrf`, `cache` (Flask-Caching `SimpleCache`) — all module-level singletons in `app/__init__.py`.

**Audit trail (`app/audit/`).** Every create/update/delete must call `log_audit(module, action, record_id, record_identifier, old_values, new_values, notes)` (or the `log_create`/`log_update`/`log_delete` shortcuts) from `app/audit/utils.py`. Use `get_changes(old_obj, new_data, fields)` to diff before logging updates, and `model_to_dict(obj, fields)` to snapshot before deletes. Auth events (login/logout/branch select) are also audited. `log_audit` swallows its own errors and rolls back so it never breaks the main operation.

**Approval workflow.** Sensitive entities (accounts, VAT categories, withholding tax) use a `*ChangeRequest` model (`change_type`, `change_data` as JSON via `get_change_data()`/`set_change_data()`, `status`, `requested_by`, `reviewed_by`, etc.). `can_auto_approve()` returns True only for the sole accountant; admins always go to pending. `can_be_approved_by(username)` blocks self-approval when other reviewers exist. States: `pending → approved | rejected`. **Rejections log `action='reject'`**, not the original change type.

**Role-based access.** Five roles, in ascending privilege (`ROLE_LEVEL`, `app/utils/authz.py`): `viewer` < `staff` < `accountant` < `chief_accountant` < `admin`. `chief_accountant` is "admin minus the Admin panel". Enforcement is inline in views (`if current_user.role not in ['accountant', 'admin']: flash(...); redirect(...)`), plus the canonical decorators `admin_panel_required` (admin only) and `full_access_required` (admin or chief_accountant) in `app/utils/authz.py` — there is no `admin_required` decorator. Templates gate write actions with the same role check; staff/viewer get read-only views with an explanatory flash.

**Time.** Always use Philippine Standard Time helpers from `app.utils` (`ph_now`, `ph_datetime`, `utc_to_pht`, `format_ph_datetime`) — never naive `datetime.now()`.

**Exports.** `app/utils/export.py` provides `export_to_excel` / `export_to_csv` (openpyxl-backed).

**Cache helpers (`app/utils/cache_helpers.py`).** Active accounts, VAT categories, WHT codes, and branches are memoized for 1 hour. After mutating any of these entities, call the matching `clear_*_cache()` function (e.g. `clear_account_cache()`) — otherwise callers see stale data until the TTL expires. **NEVER `@cache.memoize` ORM objects whose `to_dict()` reads a relationship** (lazy load): the cached object outlives its request/session, so a later read on the detached object raises `DetachedInstanceError` → HTTP 500 (P-56's `get_active_products` 500'd every document form once a product existed). The existing helpers are safe only because their `to_dict` reads loaded *columns*. If a cached helper's `to_dict` touches a relationship, **`joinedload` it in the query** (so the value is loaded, not lazy) — or cache plain dicts instead of ORM objects.

**Branch session validation.** A `before_request` hook in `create_app` validates `session['selected_branch_id']` on every request: if the stored branch is inaccessible, it is cleared and the user is redirected to the branch picker (`users.select_branch`). If the user has exactly one accessible branch it is auto-selected. Exempt endpoints: `users.login`, `users.logout`, `users.register`, `users.select_branch`, `static`. This means any view that assumes a valid branch in session is already guarded — do not duplicate the check.

**Branch access by role.** **Full-access users (admin OR chief_accountant, `user.has_full_access`)** access all active branches. Accountants, staff, and viewers access only their explicitly assigned branches (many-to-many `User.branches`) — accountants were branch-scoped on 2026-06-27 (previously they saw all). Use `get_accessible_branches(current_user)` from `app/users/utils.py` whenever building branch selectors or scoping queries; never assume all branches are visible. A non-admin user must have ≥1 assigned branch (enforced in `UserForm`), or the `before_request` gate force-logs-them-out at the branch picker.

**VAT mechanics (Philippine BIR).** Line amounts in Sales Invoices and Accounts Payable are **VAT-inclusive** — VAT is *extracted* from the amount, not added on top. The `vat_amount` is derived from `subtotal` using the line's VAT category percentage. `vat_override` / `wt_override` flags allow manual adjustment when the auto-calc doesn't match a counterparty agreement.

**Accounting periods (`app/periods/`).** The `AccountingPeriod` model tracks open/closed fiscal periods. Posting a journal entry to a closed period must be blocked at the view layer; check period status before accepting a posted date.

**Notifications (`app/notifications/`).** When a change request is approved or rejected, create a `Notification` record for the requestor (`category` = `'success'` or `'error'`, `related_type`/`related_id` pointing to the change request). Notifications are in-app only; no email.

**User registration guard.** `ApprovedEmail` model (in `app/users/`) is a whitelist of email addresses allowed to self-register. New registrants are created with `role='viewer'` and must be promoted by an admin. Tests that create users directly bypass this; integration tests that hit `/register` need an `ApprovedEmail` row first.

**Account lockout.** `User.is_account_locked()` checks `account_locked_until`; `User.increment_failed_attempts()` locks after 5 failures for 15 minutes. Login tests that expect a success response must use unlocked, active accounts.

**Jinja filter.** A `from_json` filter is registered globally — `{{ some_field | from_json }}` parses a JSON string in a template and returns a dict (returns `{}` on parse error).

## Project Conventions (non-negotiable)

- **No JavaScript popups.** Never use `confirm()`, `alert()`, or `prompt()`. Build custom HTML modal forms with a `{{ csrf_token() }}` hidden input.
- **Model changes require explicit user approval first.** Before editing any `models.py` or running a migration, describe the change (field name, type, nullable, default, migration impact) and get sign-off.
- **Propose before seeding/bulk-writing.** Show proposed data for review before running anything that writes to the DB. Do not seed and ask forgiveness.
- **Hierarchy is derived, not stored.** For tree data (COA), a node is a PARENT (group header, non-postable) if it is top-level (no `parent_id`) **or** has children; otherwise it is a LEAF (postable). Computed from `parent_id`, no stored `is_header` field. The COA list badges parents as **PARENT** (not the old "GROUP") from creation — so a freshly-created top-level header reads as PARENT before it has any children.
- **No hardcoded styling in templates.** Use design tokens / CSS variables.
- **Peso sign: use the literal `₱` (U+20B1) glyph, never the `&#8369;` HTML entity.** Templates are UTF-8 and `₱` renders everywhere. The entity is fine in *direct* template HTML but becomes literal text (`&#8369;`) the moment a value carrying it passes through an autoescaping Jinja macro (`{{ val }}`) — which is exactly the bug it caused in the CRV summary. The literal glyph survives autoescaping, so standardize on it.
- **Responsive on all UI** (desktop, tablet, mobile).
- **No empty-state "Create your first X" CTA buttons.** Do NOT add the empty-state call-to-action button (e.g. "+ Create First Unit of Measure", "Create your first customer") that some list pages show when the list is empty. Keep the plain "No <things> found." message only — the "+ Enter/Create" launch button at the top of the list already covers creation. Remove this from any shared list-template boilerplate/macro/scaffold so new modules never inherit it. (User preference, 2026-06-28.)
- **Verify the audit log in CRUD tests** — after every write, assert an audit entry exists with the correct action, record reference, and actor.
- **Posted-JE legs must tie to the source-document header, not just balance.** For any document that posts a journal entry (AP/CDV/CRV/SI/JV) or prints/reports a figure derived from one (check printing, BIR 1601-EQ/alphalist, subsidiary ledgers), `Dr == Cr` is **not** proof of correctness — the cash/AR/AP residual leg is a plug that silently absorbs any per-leg error. In tests and reviews, assert each **non-plug** leg against the document HEADER total (WHT-payable == `doc.total_wt`, input/output VAT == `doc.total_vat`, each per-ATC/per-account bucket sum == its header bucket). Any header-level override (`wt_override`, VAT-override diff, manual total) must be reconciled into the per-line buckets that feed the JE, with a guard that **raises** when it can't be allocated — never absorbed into the residual leg. See memory entry `posted-je-leg-vs-source-header-invariant`.
- **Transaction document submit buttons say "Save" / "Update"; list/launch buttons say "Enter"; master data says "Create".** The in-form submit button on documents that post to the books (purchase bills, sales invoices, receipts, journal entries) reads **"Save"** (create) / **"Update"** (edit) — plain, no document name. The list-page launch buttons that open those forms keep the **"Enter …"** verb (e.g. "+ Enter APV", "+ Enter CDV") and page titles may still read "Enter …". Reference/master records (vendors, customers, accounts, branches, users) keep **"Create"**.

## Testing Notes

- Fixtures live in `tests/conftest.py`: `app` (session-scoped, testing config), `db_session` (function-scoped, creates/drops all tables per test), `client`, plus per-role user fixtures (`admin_user`, `accountant_user`, `staff_user`, `viewer_user`). Additional helpers: `db_with_data` (admin + branch + cash/revenue accounts pre-populated), `branch_manila` (second branch), `login_user()` / `logout_user()` helpers.
- Layout: `tests/unit/`, `tests/integration/`, `tests/performance/`, `tests/test_smoke.py`.
- For browser/Playwright tests, the login password field is `readonly` (anti-autofill) — `click('#password')` to clear it before `fill`/`type`.
- Integration tests that exercise registration need an `ApprovedEmail` row; tests that exercise lockout logic need an account with `failed_login_attempts < 5` and `account_locked_until` unset.
- **The `/ui-test cas` empty-schema build is a distinct regression surface.** Building the whole app through the UI from a **0-row** DB (first-run admin → COA → VAT/WHT → settings → customers/vendors → UOM/products → enable modules → transact) exercises onboarding paths the **seeded pytest fixtures HIDE** — it is where whole-app "the seeded DB already has X" assumptions surface. Two HIGH bugs were found this way that a green suite structurally cannot see: the posting engines' **hardcoded control-account codes** (`10201/10212/20101/20301` — a self-built COA can't post) and the **first-run admin deadlock**. Treat "can a fresh client build a working install through the UI alone?" as its own question, separate from a green suite. Durable browser specs live in `clients/cas/ui-tests/` (see its `TEST-CASES.md`). Memory `feedback-empty-build-surfaces-seed-hidden-bugs`.
- **Driving enhanced widgets in browser tests:** a **Choices.js** picker *strips* the native `<select>`'s `<option>`s, so `select.options` sees only the placeholder — read/select via the Choices dropdown DOM (open + mousedown/click the item), never conclude "dropdown empty" from `select.options` (this trap nearly produced false "missing data" bug reports). The Active/Inactive **status toggle** is a hidden `<select>`, so Playwright `select_option` throws "not visible" — set `.value` + dispatch `change` in JS. Memory `apv-playwright-quirks`.

## Deployment

Production target is PythonAnywhere via `wsgi.py` (set `PYTHONANYWHERE_USERNAME` and a real `SECRET_KEY` there; defaults to production config and SQLite at `~/cas.db`).

**Multi-instance deployment.** The same codebase is deployed to separate servers, one per client/instance. There is no code branching — each server differs only by its `.env` and its data:
- Each server sets its own `SQLALCHEMY_DATABASE_URI`, keeps its own `instance/uploads` (the logo is a file referenced by the `company_logo` setting, **not** stored in the DB), and sets `company_name` as a DB setting.
- This project (`erp-workspace/projects/cas`) is the **CAS demo** instance — `.env` → `sqlite:///cas.db` (the demo data; formerly named `cas_demo.db`, renamed 2026-07-03). The RIC client instance lives in its own workspace at `C:\envs\ric-workspace\`.
- `/reset-database` resolves its target from `.env` and confirms the filename before wiping. Mind which DB `.env` points at before reseeding.

## Gotchas

- Global error handlers (404/403/500/`Exception`) are registered in `create_app` behind `if not app.debug:` — active in production, suppressed under dev/testing (DEBUG on) so tracebacks still surface; the 429 handler registers in all environments. `log_error_to_db` masks any form field whose name contains "password". The production handlers are exercised under `TestingErrorsConfig` (`tests/integration/test_error_handlers.py`); the plain `testing` config never reaches them.
- `app/templates/base.html` has an inline `<style>` block that **duplicates** rules from `app/static/css/style.css` (with hardcoded values, not design tokens) and it loads **after** style.css — so its duplicates win the cascade and can silently override the real rule (this is what hid the dashboard hero gradient, fixed in `e7e1fde`). Before adding or editing a selector in that inline block, grep `style.css` for it and edit there using design tokens.
- Static assets are linked with a **manual `?v=N` query string, not a content hash**. After editing any file under `app/static/`, grep all templates for its filename and **bump the `?v=N` on every `<link>`/`<script>`** that loads it (a shared asset is linked from multiple forms — bump them all). A file linked with no `?v=` caches indefinitely; add one. If a static-asset change "isn't showing" in the browser or Playwright, suspect the stale cache **before** re-editing already-correct code.
- **SQLAlchemy 2.0 spellings (the suite is at 0 warnings — keep it there).** Use `db.session.get(Model, id)` (return-or-None) and `db.get_or_404(Model, id)` (return-or-abort-404). NEVER `Model.query.get(id)` / `Model.query.get_or_404(id)` — both emit `LegacyAPIWarning` and were fully swept out on 2026-06-27 (1719 → 0 warnings). Reintroducing either resurfaces the warning floor. When chasing any deprecation warning, grep **all** `.query.<legacy>(` sibling wrappers, not just the one named in the warning text (the internal `flask_sqlalchemy/query.py` frame hides the real caller).
- **Migrations are HAND-WRITTEN with batch ops; verify constraint changes on a real-DB copy.** `Migrate()` is configured **without** `render_as_batch`, so `flask db migrate` autogen emits plain `ALTER` ops SQLite can't run — hand-write migrations using `op.batch_alter_table(...)` (see `307cc71c8779`). Batch mode reflects the existing DB schema and silently **preserves old/unnamed indexes/constraints unless you explicitly drop them**, so a constraint/index/column-type change is **not** proven by a conftest `create_all()`-from-model unit test (that builds today's model, not the migration history) — such a test goes green while the real migrated DB still enforces the old rule. Verify by running `flask db upgrade` on a **copy** of the real `cas.db` and probing the constraint (e.g. insert the newly-allowed row). See memory entry `migration-verify-on-real-db-copy`.
- **The harness dev server does NOT hot-reload Python.** Launched as a background task it runs single-process (`use_reloader=False`; the Werkzeug reloader's re-exec exits 255 under the harness), so **edits to any `.py` under `app/` do not take effect until you restart the server** — only Jinja templates reload live. If a freshly-added view/global/setting throws `NameError`/`AttributeError` in the browser but grep shows it IS defined, the running process is stale: **restart the server before re-editing already-correct code** (bit `/dashboard` `visible_modules` + `/settings` `accountant_email_self_approval`, 2026-06-27). Related: Playwright drives the user's shared Chrome — the logged-in user can change mid-session, so re-check `current_user` (role/name) on the page before diagnosing role/sidebar rendering.
- **Use Jinja `{# #}` comments, not `<!-- -->`, near role-gated markup.** HTML comments are emitted into the response body, so a comment that names a gated feature defeats `assert b'X' not in resp.data` even when the gate works correctly (a `<!-- … Audit Log … -->` comment false-failed 4 absence-tests, fixed `2938b11`). Jinja comments are stripped server-side. Pair any absence-test with a positive per-role assertion.
- **Batch `add_column` cannot carry an inline `sa.ForeignKey` — "Constraint must have a name".** When hand-writing a migration that adds a column with `op.batch_alter_table(...).add_column(sa.Column('x_id', sa.Integer, sa.ForeignKey('other.id')))`, SQLite batch mode raises `ValueError: Constraint must have a name` (it can't emit an unnamed FK inside the table rebuild). Add the column as a **plain `sa.Integer`** (no `ForeignKey`) — SQLite FK enforcement is off app-wide anyway, so nothing is lost — or give the constraint an explicit name via `sa.ForeignKeyConstraint([...], [...], name='fk_...')`. The model side may still declare `db.ForeignKey(...)` for ORM joins; it's only the *migration* column that must be a bare Integer (see `SalesOrder.quotation_id`, migration `29500ade76f8`).
- **A WTForms `HiddenField` is rendered by BOTH `form.hidden_tag()` and an explicit `{{ form.field(...) }}` — a duplicate `name=` the browser posts twice.** `form.hidden_tag()` emits CSRF **plus every HiddenField**. If the template also renders that same field explicitly (e.g. to attach an `id` for JS), the POST carries the field name twice and `request.form.get(name)` returns the FIRST (usually empty) copy — silently dropping the JS-populated value. This is invisible to pytest (the test client posts a single key) and only bites a real browser submit. Render the hidden field **once**: either give the `hidden_tag()`-emitted field its `id` by targeting it in JS by name, or render CSRF alone (`{{ form.csrf_token }}`) and each hidden field explicitly. (Found via e2e smoke on the Delivery Receipt form — see `tests/e2e/test_dr_smoke.py::test_dr_round_trip_submit`.) **Corollary (the opposite failure): rendering `{{ form.csrf_token }}` alone WITHOUT then rendering the form's other needed hidden fields explicitly drops them from the POST.** The DR form does exactly this and thereby omits `RowVersionFormMixin.row_version`, so `submitted_version()` reads 0 and every draft-DR edit false-conflicts (`BUG-DR-EDIT-FALSE-CONFLICT`). If you switch a form to csrf-only to dodge the duplicate above, you must explicitly render each remaining `HiddenField` it relies on (`row_version`, `lines`, …). **Regress this class with a render-assertion on the GET** (assert the rendered form contains `name="row_version"`), never a POST-contract test that supplies the token directly — the latter structurally cannot catch a dropped-render bug (it is exactly why `BUG-DR-EDIT-FALSE-CONFLICT` shipped green). `tests/integration/test_csrf_only_forms_render_hidden_tokens.py` pins the whole `RowVersionFormMixin` family. Memory `csrf-only-render-drops-hidden-fields`.
