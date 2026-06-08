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

## Project Conventions (non-negotiable)

These come from `PROJECT_FOUNDATIONS.md` — read it for the full rationale and reusable code patterns (hierarchical leaf-node rule, depth computation, two-pass seeding, COA homepage "Option A").

- **No JavaScript popups.** Never use `confirm()`, `alert()`, or `prompt()`. Build custom HTML modal forms with a `{{ csrf_token() }}` hidden input. The delete-modal pattern is documented in `PROJECT_FOUNDATIONS.md` §3.
- **Model changes require explicit user approval first.** Before editing any `models.py` or running a migration, describe the change (field name, type, nullable, default, migration impact) and get sign-off.
- **Propose before seeding/bulk-writing.** Show proposed data for review before running anything that writes to the DB. Do not seed and ask forgiveness.
- **Hierarchy is derived, not stored.** For tree data (COA), a node is a GROUP if it has children, a LEAF (postable) otherwise — computed from `parent_id`, no `is_header` field. See §3.
- **No hardcoded styling in templates.** Use design tokens / CSS variables.
- **Responsive on all UI** (desktop, tablet, mobile).
- **Verify the audit log in CRUD tests** — after every write, assert an audit entry exists with the correct action, record reference, and actor.

## Testing Notes

- Fixtures live in `tests/conftest.py`: `app` (session-scoped, testing config), `db_session` (function-scoped, creates/drops all tables per test), `client`, plus per-role user fixtures (`admin_user`, `accountant_user`, `staff_user`, `viewer_user`).
- Layout: `tests/unit/`, `tests/integration/`, `tests/performance/`, `tests/test_smoke.py`.
- For browser/Playwright tests, the login password field is `readonly` (anti-autofill) — `click('#password')` to clear it before `fill`/`type`. Test credentials and selector guidance are in `PROJECT_FOUNDATIONS.md` §4.

## Deployment

Production target is PythonAnywhere via `wsgi.py` (set `PYTHONANYWHERE_USERNAME` and a real `SECRET_KEY` there; defaults to production config and SQLite at `~/cas.db`).

## Gotchas

- **Root-level `*.md` files are gitignored** (`.gitignore` has `/*.md` with only `README.md` whitelisted). `CLAUDE.md` and `PROJECT_FOUNDATIONS.md` won't be tracked unless force-added (`git add -f`). Docs are expected under `../../docs/cas/` and scripts under `../../scripts/cas/`.
- Global error handlers are currently **disabled** in `create_app` (bottom of the file) to surface full tracebacks during testing — re-enable before production.
