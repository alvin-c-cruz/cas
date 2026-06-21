# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

CAS (Computerized Accounting System) — an accounting-first ERP for Philippine SMEs, BIR-compliant, built with Flask + SQLAlchemy + SQLite. Domain centers on double-entry accounting (Chart of Accounts, journal entries, sales invoices, purchase bills, receipts) with multi-branch support, role-based access, an approval workflow for sensitive changes, and a full audit trail.

## Commands

```powershell
# Run the dev server (port 5000)
python flask_app.py

# Seed the database (admin user, main branch, 173-account COA, VAT categories, WHT codes, settings)
flask seed-db

# Seed minimal data for demos/quick local setup (admin, 1 branch, 6 accounts, 4 VAT categories, 3 WHT codes)
flask seed-minimal

# Migrations (Flask-Migrate / Alembic)
flask db migrate -m "describe change"
flask db upgrade

# Tests (config in pytest.ini; coverage on by default, HTML report -> htmlcov/)
pytest                                   # full suite
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

**Role-based access.** Roles: `admin`, `accountant`, `staff`, `viewer`. Enforcement is inline in views (`if current_user.role not in ['accountant', 'admin']: flash(...); redirect(...)`), plus the `admin_required` decorator in `app/users/views.py`. Templates gate write actions with the same role check; staff/viewer get read-only views with an explanatory flash.

**Time.** Always use Philippine Standard Time helpers from `app.utils` (`ph_now`, `ph_datetime`, `utc_to_pht`, `format_ph_datetime`) — never naive `datetime.now()`.

**Exports.** `app/utils/export.py` provides `export_to_excel` / `export_to_csv` (openpyxl-backed).

**Cache helpers (`app/utils/cache_helpers.py`).** Active accounts, VAT categories, WHT codes, and branches are memoized for 1 hour. After mutating any of these entities, call the matching `clear_*_cache()` function (e.g. `clear_account_cache()`) — otherwise callers see stale data until the TTL expires.

**Branch session validation.** A `before_request` hook in `create_app` validates `session['selected_branch_id']` on every request: if the stored branch is inaccessible, it is cleared and the user is redirected to the branch picker (`users.select_branch`). If the user has exactly one accessible branch it is auto-selected. Exempt endpoints: `users.login`, `users.logout`, `users.register`, `users.select_branch`, `static`. This means any view that assumes a valid branch in session is already guarded — do not duplicate the check.

**Branch access by role.** Admins and accountants can access all active branches. Staff and viewers can access only their explicitly assigned branches (many-to-many `User.branches`). Use `get_accessible_branches(current_user)` from `app/users/utils.py` whenever building branch selectors or scoping queries; never assume all branches are visible.

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
- **Verify the audit log in CRUD tests** — after every write, assert an audit entry exists with the correct action, record reference, and actor.
- **Transaction document submit buttons say "Save" / "Update"; list/launch buttons say "Enter"; master data says "Create".** The in-form submit button on documents that post to the books (purchase bills, sales invoices, receipts, journal entries) reads **"Save"** (create) / **"Update"** (edit) — plain, no document name. The list-page launch buttons that open those forms keep the **"Enter …"** verb (e.g. "+ Enter APV", "+ Enter CDV") and page titles may still read "Enter …". Reference/master records (vendors, customers, accounts, branches, users) keep **"Create"**.

## Testing Notes

- Fixtures live in `tests/conftest.py`: `app` (session-scoped, testing config), `db_session` (function-scoped, creates/drops all tables per test), `client`, plus per-role user fixtures (`admin_user`, `accountant_user`, `staff_user`, `viewer_user`). Additional helpers: `db_with_data` (admin + branch + cash/revenue accounts pre-populated), `branch_manila` (second branch), `login_user()` / `logout_user()` helpers.
- Layout: `tests/unit/`, `tests/integration/`, `tests/performance/`, `tests/test_smoke.py`.
- For browser/Playwright tests, the login password field is `readonly` (anti-autofill) — `click('#password')` to clear it before `fill`/`type`.
- Integration tests that exercise registration need an `ApprovedEmail` row; tests that exercise lockout logic need an account with `failed_login_attempts < 5` and `account_locked_until` unset.

## Deployment

Production target is PythonAnywhere via `wsgi.py` (set `PYTHONANYWHERE_USERNAME` and a real `SECRET_KEY` there; defaults to production config and SQLite at `~/cas.db`).

**Multi-instance (RIC + CAS).** The same codebase is deployed to separate servers, one per client/instance. There is no code branching — each server differs only by its `.env` and its data:
- Each server sets its own `SQLALCHEMY_DATABASE_URI` (RIC → `ric.db`, CAS demo → `cas_demo.db`), keeps its own `instance/uploads` (the logo is a file referenced by the `company_logo` setting, **not** stored in the DB), and sets `company_name` as a DB setting.
- The dev box currently runs the **RIC** instance (`.env` → `sqlite:///ric.db`); the real migration data lives in `instance/ric.db`. Design: `docs/superpowers/specs/2026-06-21-ric-cas-database-separation-design.md`.
- `/reset-database` resolves its target from `.env` and confirms the filename before wiping — it will not blindly delete `cas.db`. Mind which DB `.env` points at before reseeding.

## Gotchas

- Global error handlers are currently **disabled** in `create_app` (bottom of the file) to surface full tracebacks during testing — re-enable before production.
- `app/templates/base.html` has an inline `<style>` block that **duplicates** rules from `app/static/css/style.css` (with hardcoded values, not design tokens) and it loads **after** style.css — so its duplicates win the cascade and can silently override the real rule (this is what hid the dashboard hero gradient, fixed in `e7e1fde`). Before adding or editing a selector in that inline block, grep `style.css` for it and edit there using design tokens.
- Static assets are linked with a **manual `?v=N` query string, not a content hash**. After editing any file under `app/static/`, grep all templates for its filename and **bump the `?v=N` on every `<link>`/`<script>`** that loads it (a shared asset is linked from multiple forms — bump them all). A file linked with no `?v=` caches indefinitely; add one. If a static-asset change "isn't showing" in the browser or Playwright, suspect the stale cache **before** re-editing already-correct code.

## Workflow Preferences

These override default skill behavior:

- **Auto-invoke subagent-driven development.** After `writing-plans` completes, invoke
  `superpowers:subagent-driven-development` immediately — do NOT present a "which approach?"
  choice first.
- **Skip finishing-branch options menu.** After all tasks are committed and pushed and tests
  pass, summarize what was done in 2-3 sentences. Do not invoke `finishing-a-development-branch`
  or present the 4-option menu.
- **Discuss bugs before fixing them.** Any bug found during testing MUST be reported and
  explained to the user, and the user must approve a fix, **before** any fix is made — even in
  a module you are currently touching. Do NOT fix inline. Continue testing (logging further
  findings) while waiting; surface them and let the user decide what gets fixed, when, and how.
  This supersedes the older "fix inline for the current module" tie-breaker.
  - Triage/scoping still applies (note the module, severity, and blast radius), but the fix
    itself always waits for the user's go-ahead.

## Session Start Protocol

At the start of every new conversation, before responding to the first user message:
1. Read `MEMORY.md` (already in context via system-reminder)
2. Output exactly: `Session start — [N] memory rules loaded · CLAUDE.md reviewed · Ready.`
   where N = number of entries listed in MEMORY.md
3. Then proceed with the task
