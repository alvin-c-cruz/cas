# Fix Unexpected CAS Session Logout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop CAS sessions from dying unpredictably during active use, and stop the resulting crash when a stale page is submitted against a dead session.

**Architecture:** Two small, independent changes to `projects/cas`: (1) mark the login session `permanent` and raise its configured lifetime to 12 hours so the existing `PERMANENT_SESSION_LIFETIME` config actually governs session expiry instead of an undefined browser-cookie lifetime; (2) register a `CSRFError` handler so a request against an already-dead session redirects to `/login` with a friendly flash instead of crashing with an unhandled 500.

**Tech Stack:** Flask, Flask-Login, Flask-WTF (`CSRFProtect`/`CSRFError`), pytest.

**Spec:** `docs/superpowers/specs/2026-07-18-session-logout-fix-design.md`

## Global Constraints

- Branch + worktree required — never commit directly to `main` (this repo's standing convention). Cut the worktree from THIS repo: `git -C projects/cas worktree add ../wt-session-logout-fix -b fix/session-logout main` (run from the outer `erp-workspace` directory), or equivalently from inside `projects/cas`: `git worktree add ../wt-session-logout-fix -b fix/session-logout main`.
- `REMEMBER_COOKIE_DURATION` (7 days) is untouched by this work.
- `WTF_CSRF_TIME_LIMIT` stays `None` — unrelated to this fix.
- No model change, no migration.
- This is the shared `projects/cas` codebase — merging to `main` affects all 5 live clients (RIC, alvinccruz, philgen, bccruz, zhiyuan) on their next `/deploy`, not only Zhiyuan.

---

### Task 1: Make login sessions permanent with a 12-hour lifetime

**Files:**
- Modify: `config.py:29` (default value)
- Modify: `.env.example:28` (documented default)
- Modify: `.env` (local dev copy, gitignored — not committed, but keep local behavior consistent with the new default)
- Modify: `app/users/views.py:192` (the `login()` view)
- Test: `tests/integration/test_auth.py` (add to the existing `TestSessionManagement` class)

**Interfaces:**
- Consumes: nothing new — `session` is already imported in `app/users/views.py:5`.
- Produces: nothing consumed by Task 2 — these two tasks are independent.

- [ ] **Step 1: Write the failing test**

Add this test to the `TestSessionManagement` class in `tests/integration/test_auth.py`, right after `test_session_created_on_login` (currently ending at line 168):

```python
    def test_session_permanent_on_login(self, client, admin_user, main_branch, login_user):
        """Session is marked permanent so PERMANENT_SESSION_LIFETIME actually governs
        expiry, instead of the cookie riding on an undefined browser-session lifetime
        (BUG-PA-SESSION-UNEXPECTED-LOGOUT)."""
        login_user(client, 'admin', 'admin123')

        with client.session_transaction() as sess:
            assert sess.permanent is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_auth.py::TestSessionManagement::test_session_permanent_on_login -v`
Expected: FAIL — `assert False is True` (Flask sessions default `permanent` to `False`).

- [ ] **Step 3: Write minimal implementation — mark the session permanent at login**

In `app/users/views.py`, inside `login()`, change:

```python
        login_user(user, remember=form.remember_me.data)
        return _post_login_redirect(user, form)
```

to:

```python
        login_user(user, remember=form.remember_me.data)
        session.permanent = True
        return _post_login_redirect(user, form)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_auth.py::TestSessionManagement::test_session_permanent_on_login -v`
Expected: PASS

- [ ] **Step 5: Write the failing test for the 12-hour lifetime default**

Add this test anywhere in `tests/test_smoke.py` inside the existing class that holds `test_csrf_protection_configured` (around line 110-116) — it belongs next to the other raw-config assertions:

```python
    def test_permanent_session_lifetime_is_twelve_hours(self, app):
        """PERMANENT_SESSION_LIFETIME defaults to a 12-hour workday, not the old
        1-hour value that was previously dead config (BUG-PA-SESSION-UNEXPECTED-LOGOUT)."""
        from datetime import timedelta
        assert app.config['PERMANENT_SESSION_LIFETIME'] == timedelta(hours=12)
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_smoke.py -k test_permanent_session_lifetime_is_twelve_hours -v`
Expected: FAIL — `timedelta(seconds=3600) != timedelta(hours=12)`

- [ ] **Step 7: Write minimal implementation — bump the default lifetime**

In `config.py`, change line 29 from:

```python
    PERMANENT_SESSION_LIFETIME = timedelta(seconds=int(os.environ.get('PERMANENT_SESSION_LIFETIME', '3600')))
```

to:

```python
    PERMANENT_SESSION_LIFETIME = timedelta(seconds=int(os.environ.get('PERMANENT_SESSION_LIFETIME', '43200')))
```

In `.env.example`, change line 28 from:

```
PERMANENT_SESSION_LIFETIME=3600  # 1 hour in seconds
```

to:

```
PERMANENT_SESSION_LIFETIME=43200  # 12 hours in seconds
```

In the local `.env` (gitignored, not part of the commit — edit it directly so local runs reflect the new default instead of the old explicit value), change:

```
PERMANENT_SESSION_LIFETIME=3600
```

to:

```
PERMANENT_SESSION_LIFETIME=43200
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_smoke.py -k test_permanent_session_lifetime_is_twelve_hours -v`
Expected: PASS

- [ ] **Step 9: Run the full auth + smoke suites to confirm no regressions**

Run: `pytest tests/integration/test_auth.py tests/test_smoke.py -v`
Expected: all PASS (no pre-existing failures introduced)

- [ ] **Step 10: Commit**

```bash
git add config.py .env.example app/users/views.py tests/integration/test_auth.py tests/test_smoke.py
git commit -m "fix: mark login session permanent, raise lifetime to 12 hours (BUG-PA-SESSION-UNEXPECTED-LOGOUT)"
```

---

### Task 2: Graceful CSRFError handler

**Files:**
- Modify: `app/__init__.py:12` (import) and `app/__init__.py` after line 653 (new handler, alongside the existing 429 handler)
- Test: `tests/integration/test_csrf_error_handling.py` (new file)

**Interfaces:**
- Consumes: nothing from Task 1 — independent.
- Produces: nothing consumed elsewhere — this is a terminal error handler.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_csrf_error_handling.py`:

```python
"""Integration test for graceful CSRF-error handling (BUG-PA-SESSION-UNEXPECTED-LOGOUT).

CSRF is disabled by default in the testing config so it does not get in the way of
the rest of the suite (see config.py TestingConfig.WTF_CSRF_ENABLED = False and the
identical pattern in tests/integration/test_login_rate_limit.py). This test builds a
FRESH app with CSRF enabled at init time, matching that same pattern, rather than
mutating the shared session app.
"""
import os

import pytest

from app import create_app, db

pytestmark = [pytest.mark.integration, pytest.mark.security]


@pytest.fixture
def csrf_client(monkeypatch):
    """A dedicated app + client with CSRF protection enabled at init time."""
    os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-testing-only')
    import config as config_module  # import here: config.py validates SECRET_KEY at import
    monkeypatch.setattr(config_module.TestingConfig, 'WTF_CSRF_ENABLED', True)
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        try:
            yield app.test_client()
        finally:
            db.session.remove()
            db.drop_all()


def test_stale_session_csrf_error_redirects_to_login_gracefully(csrf_client):
    """Reproduces the production incident: a POST carrying a CSRF token value but
    whose SESSION has no 'csrf_token' key at all (the exact 'CSRF session token is
    missing' case — distinct from a missing/expired/mismatched token) must redirect
    to /login with a friendly flash, not crash with an unhandled 500."""
    response = csrf_client.post('/login', data={
        'username': 'admin',
        'password': 'admin123',
        'csrf_token': 'stale-token-from-a-long-idle-page',
    }, follow_redirects=True)

    assert response.status_code == 200  # followed the redirect, not a 500
    assert b'session has expired' in response.data.lower()
    assert response.request.path == '/login'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_csrf_error_handling.py -v`
Expected: FAIL — either a 500 response, or a `CSRFError`/`InternalServerError` propagating out of the test client (Flask re-raises unhandled exceptions in testing mode when no handler catches them), confirming the crash is real before the fix.

- [ ] **Step 3: Write minimal implementation**

In `app/__init__.py`, change the import on line 12 from:

```python
from flask_wtf.csrf import CSRFProtect
```

to:

```python
from flask_wtf.csrf import CSRFProtect, CSRFError
```

Then, in `app/__init__.py`, add the new handler immediately after the existing `ratelimit_handler` (right after line 653, `return render_template('users/login.html', form=LoginForm()), 429`, and before the `# Generic error handlers` comment on line 655):

```python
    # CSRF error handler — registered in ALL environments (like the 429 handler
    # above), not just production, so a dead/stale session fails gracefully
    # instead of crashing with an unhandled 500 (BUG-PA-SESSION-UNEXPECTED-LOGOUT).
    @app.errorhandler(CSRFError)
    def csrf_error_handler(e):
        from flask import redirect, url_for, flash, session
        session.clear()
        flash('Your session has expired. Please log in again.', 'info')
        return redirect(url_for('users.login'))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_csrf_error_handling.py -v`
Expected: PASS

- [ ] **Step 5: Run the full CSRF/auth/rate-limit test files to confirm no regressions**

Run: `pytest tests/integration/test_auth.py tests/integration/test_login_rate_limit.py tests/integration/test_csrf_error_handling.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add app/__init__.py tests/integration/test_csrf_error_handling.py
git commit -m "fix: handle CSRFError gracefully instead of crashing with a 500 (BUG-PA-SESSION-UNEXPECTED-LOGOUT)"
```

---

### Task 3: Full regression pass and merge

**Files:** none new — verification only.

- [ ] **Step 1: Run the full test suite**

Run: `pytest`
Expected: same pass/fail counts as the pre-existing baseline, plus the 3 new tests from Tasks 1-2 passing. No new failures. (Per this project's own convention, `/run-tests`/`/guard` stay user-invoked — do not auto-run them as a gate; a plain `pytest` here is sufficient for this plan's own verification.)

- [ ] **Step 2: Merge the branch back to `main`**

From the worktree:

```bash
git -C projects/cas checkout main
git -C projects/cas merge --ff-only fix/session-logout
```

If not fast-forwardable, merge normally and resolve, then re-run `pytest` once more on `main` before considering this done.

- [ ] **Step 3: Remove the worktree and delete the branch**

```bash
git -C projects/cas worktree remove ../wt-session-logout-fix
git -C projects/cas branch -d fix/session-logout
```

---

## Deployment note (not a plan task — for whoever runs `/deploy` next)

This change ships to all 5 live clients on their next deploy, not just Zhiyuan. Before running `/deploy` for each client, check that client's live `.env` for an explicit `PERMANENT_SESSION_LIFETIME` value — if one is set (overriding the new `43200` default), decide per-client whether to update it to `43200` so the new 12-hour behavior actually takes effect there too, per the design doc's Rollout section.
