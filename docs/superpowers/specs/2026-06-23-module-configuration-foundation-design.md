# Module-Configuration Foundation — Design

_Date: 2026-06-23 · Status: approved design, pre-implementation_

## Problem

CAS is becoming a modular product: a **minimum CAS** core that every client gets, plus a catalog of **optional modules** (BIR Reports, Bank Accounts, Bank Transfers, Bank Reconciliation, Delivery Receipts, …) that each client can include or exclude. Today there is no notion of an instance-level "this module is part of this client's package" — there is only per-*user* access (`can_access_module` / `book_permissions`, staff-only). This foundation adds the missing instance-level layer and proves it by retro-fitting the existing **BIR Reports** section as the first optional module. The actual new modules (Bank Accounts, etc.) are out of scope here; each later ships with its own catalog entry.

See memory `project-configurable-modules`. CAS instances share one codebase and differ only by `.env` + data, so the mechanism is **runtime configuration**, not code branching.

## Decisions (from brainstorming)

1. **Storage/UX:** a DB-backed setting toggled at runtime via an **admin-only "Modules / Package" page** (no redeploy).
2. **Catalog scope:** new modules **plus** retro-fitting the entire **BIR Reports** section (including the working SLSP) as one optional module.
3. **Defaults:** modules that **already ship** default **ON** (so existing RIC/demo instances are unchanged on upgrade — no migration); **new** modules default **OFF**. Encoded per-entry as `default_enabled`.
4. **Dependencies:** **block invalid actions** (no cascade) — can't enable a module whose prerequisite is off; can't disable a module that an enabled module depends on.

## Invariant

Schema and migrations are **always present** in every instance. A toggle gates **behavior and visibility, never data** — disabling a module hides its nav + blocks its routes but **retains its data**; re-enabling restores it. No per-instance schema branching, no migration on toggle, no data loss. This is what makes a client switching a module on/off mid-life safe.

## A. Catalog — extend `MODULE_REGISTRY` (`app/users/module_access.py`)

Add three optional keys to the relevant registry entries: `optional: True`, `depends_on: [<keys>]`, `default_enabled: <bool>`. Entries **without** `optional` are core and always enabled (unchanged behavior).

This foundation adds **one** optional entry — the BIR retro-fit (BIR routes live in the shared `reports` blueprint and are not in the registry today):

```python
{'key': 'bir_reports', 'label': 'BIR Reports', 'section': 'Reports',
 'optional': True, 'depends_on': [], 'default_enabled': True,
 'endpoints': ('reports.bir_index', 'reports.bir_sales', 'reports.bir_sales_export_excel',
               'reports.bir_purchases', 'reports.bir_purchases_export_excel',
               'reports.bir_alphalist', 'reports.bir_alphalist_export_excel')},
```

Future modules (Bank Accounts, Transfers, Recon, DR) each add their own `optional` entry when built — **not in this spec**.

## B. Enablement store + `module_enabled(key)`

Store one value per optional module in `AppSettings` (`app/settings.py`, `get_setting`/`set_setting`): key `module_enabled:<module_key>` → `'1'` / `'0'`. **An absent value falls back to the catalog's `default_enabled`** — so BIR (`default_enabled=True`) is ON everywhere with no migration, and a new module (`default_enabled=False`) is OFF until enabled.

New function in `module_access.py`:

```python
def module_enabled(key):
    """Instance-level: is this optional module part of the package? Core/unknown keys → True."""
    entry = next((m for m in MODULE_REGISTRY if m['key'] == key), None)
    if not entry or not entry.get('optional'):
        return True
    from app.settings import AppSettings
    raw = AppSettings.get_setting(f'module_enabled:{key}')
    return entry.get('default_enabled', False) if raw is None else (raw == '1')
```

Memoize via the existing cache pattern (`app/utils/cache_helpers.py`) — `get_enabled_modules()` map cached for 1h, with `clear_module_config_cache()` called on every toggle. (`module_enabled` reads the cached map.)

## C. Enforcement — fold into the existing chokepoint (the elegant part)

Both the sidebar and the route guard already call `can_access_module`. Make `module_enabled` the **first check** there, so one change covers nav-hiding and route-blocking for **every** role:

```python
def can_access_module(user, key):
    if not module_enabled(key):        # NEW: instance-level package gate (all roles)
        return False
    if user is None or not getattr(user, 'is_authenticated', False):
        return False
    if user.role in ('admin', 'accountant', 'viewer'):
        return True
    return user.get_book_permissions().get(key, False)
```

Result:
- **Sidebar** (`can_access_module` in templates) hides a disabled module for all roles — free.
- **Route guard** `enforce_module_access` (`app/__init__.py:395`) already does `if key and not can_access_module(current_user, key): redirect(...)` → now also blocks a disabled module for **admin/accountant/viewer**, not just staff — free.

Refine the route guard to give a clearer signal for the *disabled* case (vs the per-user *denied* case): when `module_key_for_endpoint(endpoint)` returns a key that is **disabled at the instance level**, `abort(404)` (the module is genuinely not part of this package); keep the existing redirect-with-flash for a per-user denial:

```python
key = module_key_for_endpoint(request.endpoint)
if key:
    if not module_enabled(key):
        abort(404)                 # not in this instance's package
    if not can_access_module(current_user, key):
        flash('You do not have access to this module.', 'error')
        return redirect(url_for('dashboard.index'))
```

Core modules return `module_enabled → True`, so behavior for everything in minimum CAS is unchanged. The Modules admin page (Section D) is a **core** endpoint (no optional registry entry maps to it), so it is never self-blocked — an admin can always reach it to re-enable.

## D. Admin "Modules / Package" page

A new **admin-only** page in the existing settings area (`app/company_settings/`, url_prefix `/settings`), endpoint `company_settings.modules`:
- **GET** `/settings/modules`: list every `optional` registry entry grouped by `section`, each with its current enabled state and `depends_on`, rendered with a status toggle (custom HTML, no JS popups; design tokens; admin-only via the existing `admin_required` decorator).
- **POST** `/settings/modules/toggle` (CSRF): flip one module. Enforce dependency rules with a pure, testable helper:

```python
def can_toggle(key, enable, enabled_keys, registry=MODULE_REGISTRY):
    """Return (ok, reason). enabled_keys = set of currently-enabled optional keys."""
    entry = next((m for m in registry if m['key'] == key), None)
    if enable:
        missing = [d for d in entry.get('depends_on', []) if d not in enabled_keys]
        return (not missing, f"requires {', '.join(missing)}" if missing else '')
    dependents = [m['key'] for m in registry
                  if m.get('optional') and key in m.get('depends_on', []) and m['key'] in enabled_keys]
    return (not dependents, f"in use by {', '.join(dependents)}" if dependents else '')
```

On a valid toggle: `AppSettings.set_setting('module_enabled:<key>', '1'|'0', updated_by=current_user)`, `clear_module_config_cache()`, and `log_audit(module='module_config', action='enable'|'disable', record_identifier=key, ...)`. On an invalid toggle: flash the `reason` and make no change.

## Out of scope

- The actual optional modules (Bank Accounts, Bank Transfers, Bank Reconciliation, Delivery Receipts) — separate specs; each adds its own `optional` registry entry and reads `module_enabled`/`can_access_module`.
- Per-branch module enablement (modules are per-instance, not per-branch).
- A self-service/customer-facing package picker (admin-only here).

## Testing (TDD)

- `module_enabled('bir_reports')` → `True` with no setting (default_enabled); a fixture optional entry with `default_enabled=False` → `False`.
- Setting `module_enabled:bir_reports='0'` → `module_enabled` False; **`can_access_module(admin, 'bir_reports')` False**; `GET /reports/bir` (and a BIR export endpoint) returns **404 even for admin**; the BIR sidebar link is absent. Re-enable → accessible again, link present.
- Core unchanged: `can_access_module(admin, 'accounts_payable')` still True; an AP route is reachable (no regression for minimum CAS).
- `can_toggle` (pure): with a fixture catalog `A` and `B(depends_on=[A])` — can't enable `B` while `A` off; can't disable `A` while `B` enabled; both allowed otherwise. (The first real dependency pair ships with Bank Accounts/Transfers.)
- Admin page: non-admin (staff/accountant/viewer) is denied `GET /settings/modules`; a toggle writes the `AppSettings` value, clears the cache, and creates a `module_config` audit row.

## Risks / notes

- `module_enabled` must be **cached** — it runs in `enforce_module_access` on every request; an uncached `AppSettings` read per request is a hot path. Clear the cache on every toggle (and the toggle path is rare).
- The retro-fit means a BIR route a client previously reached can become a 404 once an admin disables BIR — intended, but flag in the admin-page copy ("disabling hides BIR for everyone in this company").
- `section: 'Reports'` for the BIR entry: if the sidebar has no "Reports"/BIR section wired to the registry yet, the nav link for BIR must be added/gated the same way the other report links are (`can_access_module(current_user, 'bir_reports')`).
