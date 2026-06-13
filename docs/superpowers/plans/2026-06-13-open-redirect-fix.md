# Open Redirect Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent `login()` and `select_branch()` from redirecting users to external hosts via an unvalidated `?next=` parameter.

**Architecture:** Add a `_is_safe_url(target)` helper to `app/users/views.py` that uses `urlparse` + `urljoin` to reject any `next` value whose resolved host differs from the request host. Apply it at the two call sites. Verify with three integration tests added to the existing `tests/integration/test_auth.py`.

**Tech Stack:** Python stdlib `urllib.parse`, Flask `request`, pytest, existing `client` / `accountant_user` / `main_branch` fixtures.

---

### Task 1: Write failing tests

**Files:**
- Modify: `tests/integration/test_auth.py`

- [ ] **Step 1: Append `TestOpenRedirect` class to `tests/integration/test_auth.py`**

Add at the end of the file (after the last existing class):

```python
@pytest.mark.integration
@pytest.mark.auth
class TestOpenRedirect:
    """Ensure ?next= redirects cannot send users to external hosts."""

    def test_absolute_url_blocked(self, client, accountant_user, main_branch):
        """POST /login?next=http://evil.com must redirect to dashboard, not evil.com."""
        resp = client.post(
            '/login?next=http://evil.com',
            data={'username': 'accountant', 'password': 'accountant123'},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert 'evil.com' not in resp.headers['Location']

    def test_protocol_relative_url_blocked(self, client, accountant_user, main_branch):
        """POST /login?next=//evil.com must redirect to dashboard, not evil.com."""
        resp = client.post(
            '/login?next=//evil.com',
            data={'username': 'accountant', 'password': 'accountant123'},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert 'evil.com' not in resp.headers['Location']

    def test_valid_local_next_honored(self, client, accountant_user, main_branch):
        """POST /login?next=/vendors must redirect to /vendors."""
        resp = client.post(
            '/login?next=/vendors',
            data={'username': 'accountant', 'password': 'accountant123'},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/vendors')
```

**Why `accountant_user` + `main_branch`:** The `accountant_user` fixture has `role='accountant'`, so the login view gives it access to all active branches. With exactly one active branch (`main_branch`) in the test DB, login auto-selects it and reaches the `next_page` redirect code path. Without `main_branch`, login finds zero accessible branches, flashes an error, and never hits the redirect — tests would all fail for the wrong reason.

- [ ] **Step 2: Run the new tests to confirm T1 and T2 fail (T3 may pass)**

```
pytest tests/integration/test_auth.py::TestOpenRedirect -v
```

Expected:
```
FAILED test_absolute_url_blocked      - AssertionError: 'evil.com' in Location
FAILED test_protocol_relative_url_blocked - AssertionError: 'evil.com' in Location
PASSED test_valid_local_next_honored  (already works, regression guard)
```

If all three pass, something is wrong — stop and investigate before continuing.

---

### Task 2: Add `_is_safe_url` helper and fix `login()`

**Files:**
- Modify: `app/users/views.py`

- [ ] **Step 1: Add `urlparse`/`urljoin` import at the top of `app/users/views.py`**

Find the existing import block (lines 1–8). Add one line after the `from flask import ...` line:

```python
from flask import Blueprint, render_template, redirect, url_for, flash, request
from urllib.parse import urlparse, urljoin          # ← add this line
from flask_login import login_user, logout_user, login_required, current_user
```

- [ ] **Step 2: Add `_is_safe_url` helper after `admin_required` (around line 22)**

Insert immediately after the closing `return decorated_function` / `return f(*args, **kwargs)` of `admin_required` and before the `@users_bp.route('/login', ...)` decorator:

```python
def _is_safe_url(target):
    ref = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, target))
    return test.scheme in ('http', 'https') and ref.netloc == test.netloc
```

- [ ] **Step 3: Fix the redirect in `login()` — lines ~182–184**

Find this block inside the `if len(accessible_branches) == 1:` block:

```python
            # Redirect to next page or dashboard
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            return redirect(url_for('dashboard.index'))
```

Replace with:

```python
            # Redirect to next page or dashboard (validated to prevent open redirect)
            next_page = request.args.get('next')
            if next_page and _is_safe_url(next_page):
                return redirect(next_page)
            return redirect(url_for('dashboard.index'))
```

- [ ] **Step 4: Run the open redirect tests — expect all three to pass**

```
pytest tests/integration/test_auth.py::TestOpenRedirect -v
```

Expected:
```
PASSED test_absolute_url_blocked
PASSED test_protocol_relative_url_blocked
PASSED test_valid_local_next_honored
```

---

### Task 3: Fix `select_branch()` and commit

**Files:**
- Modify: `app/users/views.py`

- [ ] **Step 1: Fix `select_branch()` — line ~203**

Find this line near the top of `select_branch()`:

```python
    next_url = request.args.get('next') or request.form.get('next') or url_for('dashboard.index')
```

Replace with:

```python
    _raw_next = request.args.get('next') or request.form.get('next')
    next_url = _raw_next if (_raw_next and _is_safe_url(_raw_next)) else url_for('dashboard.index')
```

The two `redirect(next_url)` calls at lines ~221 and ~255 are unchanged — they now always receive a validated value.

- [ ] **Step 2: Run the full test suite**

```
pytest -x -q
```

Expected: all existing tests pass; `TestOpenRedirect` passes (3/3).

If any existing test breaks, investigate before committing — do not skip.

- [ ] **Step 3: Commit**

```
git add app/users/views.py tests/integration/test_auth.py
git commit -m "fix: validate next= URL in login and select_branch to prevent open redirect"
```

- [ ] **Step 4: Push**

```
git push
```
