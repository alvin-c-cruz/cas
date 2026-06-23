# Module-Configuration Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an instance-level "is this optional module part of this client's package?" layer to CAS, runtime-toggled by an admin, and prove it by retro-fitting BIR Reports as the first optional module.

**Architecture:** Extend the existing `MODULE_REGISTRY` with `optional`/`depends_on`/`default_enabled`; store per-module enablement in `AppSettings` (`module_enabled:<key>`, absent → `default_enabled`); add `module_enabled(key)` and fold it into `can_access_module` so the existing sidebar and `enforce_module_access` chokepoints gate disabled modules for ALL roles; add an admin "Modules / Package" page.

**Tech Stack:** Flask, SQLAlchemy, Flask-Caching (SimpleCache), pytest. SQLite.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-06-23-module-configuration-foundation-design.md`.
- TDD mandatory: failing test → watch fail → minimal code → watch pass → commit. Work on `main`.
- **Invariant:** the toggle gates behavior/visibility, never data. Schema unchanged — this feature adds **no DB columns/migrations** (enablement lives in the existing `AppSettings` key-value table).
- `module_enabled` is read in `enforce_module_access` on every request → it MUST be cached; clear the cache on every toggle.
- Defaults: retro-fitted modules (`bir_reports`) `default_enabled=True`; new modules `default_enabled=False`. Absent `AppSettings` value falls back to `default_enabled` (so existing instances are unchanged with no migration).
- Core modules (no `optional` flag) must keep behaving exactly as today (`module_enabled` returns True for them).
- Admin "Modules / Package" page is **admin-only**; every toggle writes `log_audit(module='module_config', action='enable'|'disable', record_identifier=<key>)`.
- No JS popups; custom HTML + `{{ csrf_token() }}`; design tokens only.
- Run targeted tests: `python -m pytest <path> -p no:cacheprovider -q -o addopts=""`. Do NOT run the full suite (user-invoked).
- `AppSettings` API: `AppSettings.get_setting(key, default=None)`, `AppSettings.set_setting(key, value, updated_by=None)` (`app/settings.py`).

---

### Task 1: Catalog entry + `module_enabled()` + fold into `can_access_module`

**Files:**
- Modify: `app/users/module_access.py` (add `bir_reports` entry; add `module_enabled`; edit `can_access_module`)
- Modify: `app/utils/cache_helpers.py` (add `get_module_override` + `clear_module_config_cache`)
- Test: `tests/integration/test_module_enablement.py`

**Interfaces:**
- Produces: `module_enabled(key:str) -> bool`; `can_access_module(user, key)` now returns False for a disabled optional module regardless of role; `get_module_override(key) -> str|None` (cached), `clear_module_config_cache()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_module_enablement.py
import pytest

pytestmark = [pytest.mark.integration]


def test_bir_defaults_enabled(db_session):
    from app.users.module_access import module_enabled
    assert module_enabled('bir_reports') is True   # default_enabled=True, no setting


def test_core_module_always_enabled(db_session):
    from app.users.module_access import module_enabled
    assert module_enabled('accounts_payable') is True   # not optional → always on


def test_disabling_bir_hides_it_for_admin(db_session, admin_user):
    from app.settings import AppSettings
    from app.users.module_access import can_access_module, module_enabled
    from app.utils.cache_helpers import clear_module_config_cache

    assert can_access_module(admin_user, 'bir_reports') is True
    AppSettings.set_setting('module_enabled:bir_reports', '0')
    clear_module_config_cache()
    assert module_enabled('bir_reports') is False
    assert can_access_module(admin_user, 'bir_reports') is False   # disabled → off for ALL roles
    assert can_access_module(admin_user, 'accounts_payable') is True   # core unaffected


def test_new_optional_module_defaults_off(db_session, monkeypatch):
    from app.users import module_access
    monkeypatch.setattr(module_access, 'MODULE_REGISTRY', module_access.MODULE_REGISTRY + [
        {'key': 'demo_optional', 'label': 'Demo', 'section': 'Reports',
         'optional': True, 'depends_on': [], 'default_enabled': False, 'endpoints': ()}
    ])
    assert module_access.module_enabled('demo_optional') is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_module_enablement.py -p no:cacheprovider -q -o addopts=""`
Expected: FAIL — `bir_reports` not in registry / `module_enabled` undefined.

- [ ] **Step 3: Add the cache helper**

Append to `app/utils/cache_helpers.py`:

```python
@cache.memoize(timeout=3600)
def get_module_override(key):
    """Stored `module_enabled:<key>` value ('1'/'0') or None if unset (cached 1h)."""
    from app.settings import AppSettings
    return AppSettings.get_setting(f'module_enabled:{key}')


def clear_module_config_cache():
    """Invalidate cached module-enablement after a toggle."""
    cache.delete_memoized(get_module_override)
```

- [ ] **Step 4: Add the BIR entry, `module_enabled`, and fold into `can_access_module`**

In `app/users/module_access.py`, add to `MODULE_REGISTRY` (after the `fiscal_year_close` entry):

```python
    # ── Reports (optional / configurable module) ─────────────────────────────
    {'key': 'bir_reports', 'label': 'BIR Reports', 'section': 'Reports',
     'optional': True, 'depends_on': [], 'default_enabled': True,
     'endpoints': ('reports.bir_index', 'reports.bir_sales', 'reports.bir_sales_export_excel',
                   'reports.bir_purchases', 'reports.bir_purchases_export_excel',
                   'reports.bir_alphalist', 'reports.bir_alphalist_export_excel')},
```

Add the function:

```python
def module_enabled(key):
    """Instance-level package gate: is this optional module included? Core/unknown → True."""
    entry = next((m for m in MODULE_REGISTRY if m['key'] == key), None)
    if not entry or not entry.get('optional'):
        return True
    from app.utils.cache_helpers import get_module_override
    raw = get_module_override(key)
    return entry.get('default_enabled', False) if raw is None else (raw == '1')
```

Edit `can_access_module` to gate on it FIRST:

```python
def can_access_module(user, key):
    """Instance package gate (all roles) then staff-only per-user gate."""
    if not module_enabled(key):
        return False
    if user is None or not getattr(user, 'is_authenticated', False):
        return False
    if user.role in ('admin', 'accountant', 'viewer'):
        return True
    return user.get_book_permissions().get(key, False)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/integration/test_module_enablement.py -p no:cacheprovider -q -o addopts=""`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add app/users/module_access.py app/utils/cache_helpers.py tests/integration/test_module_enablement.py
git commit -m "feat(modules): module_enabled gate + BIR optional entry, folded into can_access_module"
```

---

### Task 2: `can_toggle()` dependency validator

**Files:**
- Modify: `app/users/module_access.py`
- Test: `tests/unit/test_module_dependencies.py`

**Interfaces:**
- Produces: `can_toggle(key:str, enable:bool, enabled_keys:set, registry=MODULE_REGISTRY) -> (bool, str)` — `(ok, reason)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_module_dependencies.py
import pytest

pytestmark = [pytest.mark.unit]

CATALOG = [
    {'key': 'a', 'optional': True, 'depends_on': []},
    {'key': 'b', 'optional': True, 'depends_on': ['a']},
]


def test_enable_blocked_when_prereq_off():
    from app.users.module_access import can_toggle
    ok, reason = can_toggle('b', True, enabled_keys=set(), registry=CATALOG)
    assert ok is False and 'a' in reason


def test_enable_allowed_when_prereq_on():
    from app.users.module_access import can_toggle
    ok, _ = can_toggle('b', True, enabled_keys={'a'}, registry=CATALOG)
    assert ok is True


def test_disable_blocked_when_dependent_enabled():
    from app.users.module_access import can_toggle
    ok, reason = can_toggle('a', False, enabled_keys={'a', 'b'}, registry=CATALOG)
    assert ok is False and 'b' in reason


def test_disable_allowed_when_no_dependent():
    from app.users.module_access import can_toggle
    ok, _ = can_toggle('a', False, enabled_keys={'a'}, registry=CATALOG)
    assert ok is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_module_dependencies.py -p no:cacheprovider -q -o addopts=""`
Expected: FAIL — `can_toggle` undefined.

- [ ] **Step 3: Implement `can_toggle`**

Add to `app/users/module_access.py`:

```python
def can_toggle(key, enable, enabled_keys, registry=MODULE_REGISTRY):
    """Validate a module toggle against dependencies. Returns (ok, reason)."""
    entry = next((m for m in registry if m['key'] == key), None)
    if entry is None:
        return (False, 'unknown module')
    if enable:
        missing = [d for d in entry.get('depends_on', []) if d not in enabled_keys]
        return (not missing, f"requires {', '.join(missing)}" if missing else '')
    dependents = [m['key'] for m in registry
                  if m.get('optional') and key in m.get('depends_on', []) and m['key'] in enabled_keys]
    return (not dependents, f"in use by {', '.join(dependents)}" if dependents else '')
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_module_dependencies.py -p no:cacheprovider -q -o addopts=""`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add app/users/module_access.py tests/unit/test_module_dependencies.py
git commit -m "feat(modules): can_toggle dependency validator (block, no cascade)"
```

---

### Task 3: Route enforcement — 404 a disabled module for all roles

**Files:**
- Modify: `app/__init__.py` (`enforce_module_access`, ~line 395-408; add `abort` import in the local import line)
- Test: `tests/integration/test_module_route_block.py`

**Interfaces:**
- Consumes: `module_enabled`, `module_key_for_endpoint`, `can_access_module`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_module_route_block.py
import pytest

pytestmark = [pytest.mark.integration]


def _login(client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'},
                follow_redirects=True)


def test_bir_route_200_when_enabled(client, db_session, admin_user, main_branch):
    _login(client)
    resp = client.get('/reports/bir/sales', follow_redirects=False)
    assert resp.status_code == 200


def test_bir_route_404_when_disabled_even_for_admin(client, db_session, admin_user, main_branch):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    _login(client)
    AppSettings.set_setting('module_enabled:bir_reports', '0')
    clear_module_config_cache()
    resp = client.get('/reports/bir/sales', follow_redirects=False)
    assert resp.status_code == 404
```

(If `main_branch` is needed for branch-session validation on `/reports/*`, the fixture auto-selects the single branch; confirm `/reports/bir/sales` renders 200 in the enabled case — it lists sales with no data fine.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_module_route_block.py -p no:cacheprovider -q -o addopts=""`
Expected: `test_bir_route_404...` FAILS — the current hook redirects (302) rather than 404 for a disabled module (and `can_access_module` would already 302 it via the existing redirect path, not 404).

- [ ] **Step 3: Add the 404 path to `enforce_module_access`**

In `app/__init__.py`, edit `enforce_module_access` (the import line and the gate):

```python
        from flask import redirect, url_for, request, flash, abort
        from flask_login import current_user
        from app.users.module_access import module_key_for_endpoint, can_access_module, module_enabled

        if request.endpoint is None or not current_user.is_authenticated:
            return
        key = module_key_for_endpoint(request.endpoint)
        if key:
            if not module_enabled(key):
                abort(404)   # module not part of this instance's package
            if not can_access_module(current_user, key):
                flash('You do not have access to this module.', 'error')
                return redirect(url_for('dashboard.index'))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/integration/test_module_route_block.py -p no:cacheprovider -q -o addopts=""`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add app/__init__.py tests/integration/test_module_route_block.py
git commit -m "feat(modules): 404 disabled-module routes for all roles in enforce_module_access"
```

---

### Task 4: Admin "Modules / Package" page

**Files:**
- Modify: `app/company_settings/views.py` (add `modules` GET + `modules_toggle` POST, `@admin_only`)
- Create: `app/company_settings/templates/company_settings/modules.html`
- Modify: `app/company_settings/templates/company_settings/settings.html` (add a link to the Modules page) — confirm the actual settings template filename rendered by `edit_settings`
- Test: `tests/integration/test_modules_admin_page.py`

**Interfaces:**
- Consumes: `MODULE_REGISTRY`, `module_enabled`, `can_toggle`, `AppSettings.set_setting`, `clear_module_config_cache`, `log_audit`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_modules_admin_page.py
import pytest
from app.audit.models import AuditLog

pytestmark = [pytest.mark.integration]


def _login(client, user, pw):
    client.post('/login', data={'username': user, 'password': pw}, follow_redirects=True)


def test_page_admin_only(client, db_session, staff_user, main_branch):
    _login(client, staff_user.username, 'staff123')
    resp = client.get('/settings/modules', follow_redirects=True)
    assert b'Modules' not in resp.data or b'Only administrators' in resp.data


def test_admin_sees_bir_toggle(client, db_session, admin_user, main_branch):
    _login(client, 'admin', 'admin123')
    resp = client.get('/settings/modules')
    assert resp.status_code == 200
    assert b'BIR Reports' in resp.data


def test_disable_persists_and_audits(client, db_session, admin_user, main_branch):
    from app.settings import AppSettings
    _login(client, 'admin', 'admin123')
    client.post('/settings/modules/toggle',
                data={'key': 'bir_reports', 'enable': '0'}, follow_redirects=True)
    assert AppSettings.get_setting('module_enabled:bir_reports') == '0'
    log = AuditLog.query.filter_by(module='module_config', action='disable').first()
    assert log is not None and log.record_identifier == 'bir_reports'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_modules_admin_page.py -p no:cacheprovider -q -o addopts=""`
Expected: FAIL — 404 on `/settings/modules`.

- [ ] **Step 3: Add the routes**

In `app/company_settings/views.py` (uses the existing `admin_only` decorator + `AppSettings`):

```python
@company_settings_bp.route('/modules')
@login_required
@admin_only
def modules():
    from app.users.module_access import MODULE_REGISTRY, module_enabled
    optional = [dict(m, enabled=module_enabled(m['key']))
                for m in MODULE_REGISTRY if m.get('optional')]
    return render_template('company_settings/modules.html', modules=optional)


@company_settings_bp.route('/modules/toggle', methods=['POST'])
@login_required
@admin_only
def modules_toggle():
    from app.users.module_access import MODULE_REGISTRY, module_enabled, can_toggle
    from app.utils.cache_helpers import clear_module_config_cache
    from app.audit.utils import log_audit
    key = request.form.get('key', '')
    enable = request.form.get('enable') == '1'
    enabled_keys = {m['key'] for m in MODULE_REGISTRY
                    if m.get('optional') and module_enabled(m['key'])}
    ok, reason = can_toggle(key, enable, enabled_keys)
    if not ok:
        flash(f'Cannot change "{key}": {reason}.', 'error')
        return redirect(url_for('company_settings.modules'))
    AppSettings.set_setting(f'module_enabled:{key}', '1' if enable else '0',
                            updated_by=current_user.username)
    clear_module_config_cache()
    log_audit(module='module_config', action='enable' if enable else 'disable',
              record_id=None, record_identifier=key,
              new_values={'enabled': enable})
    flash(f'Module "{key}" {"enabled" if enable else "disabled"}.', 'success')
    return redirect(url_for('company_settings.modules'))
```

- [ ] **Step 4: Create the template**

```html
<!-- app/company_settings/templates/company_settings/modules.html -->
{% extends "base.html" %}
{% block title %}Modules / Package - CAS{% endblock %}
{% block page_title %}Modules / Package{% endblock %}
{% block content %}
<div class="content-card"><div class="card-body">
  <p class="text-muted">Enable or disable optional modules for this company. Disabling a module
    hides it for everyone and retains its data; re-enabling restores it.</p>
  <table class="data-table">
    <thead><tr><th>Module</th><th>Section</th><th>Requires</th><th>Status</th><th>Action</th></tr></thead>
    <tbody>
    {% for m in modules %}
      <tr>
        <td>{{ m.label }}</td>
        <td>{{ m.section }}</td>
        <td>{{ m.depends_on | join(', ') if m.depends_on else '—' }}</td>
        <td><span class="badge {{ 'badge-active' if m.enabled else 'badge-inactive' }}">
            {{ 'Enabled' if m.enabled else 'Disabled' }}</span></td>
        <td>
          <form method="post" action="{{ url_for('company_settings.modules_toggle') }}">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
            <input type="hidden" name="key" value="{{ m.key }}"/>
            <input type="hidden" name="enable" value="{{ '0' if m.enabled else '1' }}"/>
            <button type="submit" class="btn {{ 'btn-danger' if m.enabled else 'btn-primary' }}">
              {{ 'Disable' if m.enabled else 'Enable' }}</button>
          </form>
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
</div></div>
{% endblock %}
```

- [ ] **Step 5: Link to it from the settings page**

In the template rendered by `edit_settings` (confirm filename — likely `app/company_settings/templates/company_settings/settings.html`), add near the top:

```html
<a href="{{ url_for('company_settings.modules') }}" class="btn btn-secondary">Modules / Package</a>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/integration/test_modules_admin_page.py -p no:cacheprovider -q -o addopts=""`
Expected: PASS (3 passed).

- [ ] **Step 7: Commit**

```bash
git add app/company_settings/ tests/integration/test_modules_admin_page.py
git commit -m "feat(modules): admin Modules/Package page (toggle, dependency-block, audit)"
```

---

### Task 5: Gate the BIR Reports sidebar section

**Files:**
- Modify: `app/templates/base.html` (wrap the BIR Reports nav section, lines ~1202-1214)
- Test: `tests/integration/test_module_nav_gating.py`

**Interfaces:**
- Consumes: `can_access_module` (already a Jinja global).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_module_nav_gating.py
import pytest

pytestmark = [pytest.mark.integration]


def _login(client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)


def test_bir_nav_present_when_enabled(client, db_session, admin_user, main_branch):
    _login(client)
    resp = client.get('/dashboard')
    assert b'BIR Reports' in resp.data


def test_bir_nav_absent_when_disabled(client, db_session, admin_user, main_branch):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    _login(client)
    AppSettings.set_setting('module_enabled:bir_reports', '0')
    clear_module_config_cache()
    resp = client.get('/dashboard')
    assert b'BIR Reports' not in resp.data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_module_nav_gating.py -p no:cacheprovider -q -o addopts=""`
Expected: `test_bir_nav_absent...` FAILS — the BIR section renders unconditionally today.

- [ ] **Step 3: Wrap the BIR Reports sidebar section**

In `app/templates/base.html`, wrap the entire "BIR Reports Section" block (the `<!-- BIR Reports Section -->` div through its closing tag, ~lines 1202-1214) with:

```html
{% if can_access_module(current_user, 'bir_reports') %}
  <!-- BIR Reports Section -->
  ...existing block unchanged...
{% endif %}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/integration/test_module_nav_gating.py -p no:cacheprovider -q -o addopts=""`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add app/templates/base.html tests/integration/test_module_nav_gating.py
git commit -m "feat(modules): gate BIR Reports sidebar section on module enablement"
```

---

## Self-Review

**Spec coverage:**
- Catalog extension + BIR entry → Task 1. ✓
- Enablement store + `module_enabled` + default fallback → Task 1. ✓
- Fold into `can_access_module` (nav + route gate, all roles) → Task 1 (gate) + Task 3 (404 route) + Task 5 (sidebar). ✓
- `can_toggle` dependency block (no cascade) → Task 2. ✓
- Admin Modules page (admin-only, toggle, dependency-block, cache-clear, audit) → Task 4. ✓
- Caching + clear-on-toggle → Task 1 (`get_module_override`/`clear_module_config_cache`), called in Task 4. ✓
- Retro-fit BIR optional, default ON, no migration → Task 1 entry (`default_enabled=True`). ✓

**Placeholder scan:** No TBD/TODO. Two confirm-on-apply notes: (a) the exact settings template filename for the Modules link (Task 4 Step 5); (b) `/reports/bir/sales` returns 200 with no data in the enabled case (Task 3) — if it requires a posted-period or other precondition, use `/reports/bir/purchases` or seed minimal data.

**Type consistency:** `module_enabled(key)`, `can_toggle(key, enable, enabled_keys, registry)`, `get_module_override(key)`, `clear_module_config_cache()`, `module_key_for_endpoint(endpoint)`, audit `module='module_config'` — used consistently across tasks. The `bir_reports` key and its `endpoints` tuple match between Task 1 (registry) and Task 3 (route gate).
