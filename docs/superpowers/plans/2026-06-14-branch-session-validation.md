# Branch Session Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `@before_request` hook that validates `session['selected_branch_id']` on every request, auto-selects when only one branch is accessible, and redirects to branch selection when stale or missing.

**Architecture:** One new `@before_request` hook in `app/__init__.py` after the existing `enforce_https` hook. One new helper `get_accessible_branches(user)` extracted into `app/users/utils.py` (new file) so the hook and the `select_branch` view share the same logic. No view changes.

**Tech Stack:** Flask, Flask-Login, SQLAlchemy, pytest

---

### Task 1: Extract `get_accessible_branches` helper

**Files:**
- Create: `app/users/utils.py`
- Modify: `app/users/views.py` — replace inline branch-filtering logic with call to helper

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_branch_utils.py`:

```python
"""Unit tests for app.users.utils.get_accessible_branches."""
import pytest
from app.users.utils import get_accessible_branches


class TestGetAccessibleBranches:
    def test_admin_gets_all_active_branches(self, db_session, admin_user, main_branch):
        from app.branches.models import Branch
        extra = Branch(name='Extra', code='EXT', is_active=True)
        db_session.add(extra)
        db_session.commit()
        result = get_accessible_branches(admin_user)
        ids = {b.id for b in result}
        assert main_branch.id in ids
        assert extra.id in ids

    def test_accountant_gets_all_active_branches(self, db_session, accountant_user, main_branch):
        result = get_accessible_branches(accountant_user)
        assert any(b.id == main_branch.id for b in result)

    def test_staff_gets_only_assigned_branches(self, db_session, staff_user, main_branch):
        from app.branches.models import Branch
        other = Branch(name='Other', code='OTH', is_active=True)
        db_session.add(other)
        db_session.commit()
        # staff_user is not assigned to any branch yet
        result = get_accessible_branches(staff_user)
        assert all(b.id != other.id for b in result)

    def test_inactive_branches_excluded(self, db_session, admin_user, main_branch):
        from app.branches.models import Branch
        inactive = Branch(name='Old', code='OLD', is_active=False)
        db_session.add(inactive)
        db_session.commit()
        result = get_accessible_branches(admin_user)
        assert all(b.is_active for b in result)
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/unit/test_branch_utils.py -v
```

Expected: `ImportError: cannot import name 'get_accessible_branches' from 'app.users.utils'`

- [ ] **Step 3: Create `app/users/utils.py`**

```python
from app.branches.models import Branch


def get_accessible_branches(user):
    """Return active branches accessible to the given user.

    Admins and accountants access all active branches.
    Staff and viewers access only their assigned branches.
    """
    active = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
    if user.role in ('admin', 'accountant'):
        return active
    assigned_ids = {b.id for b in user.branches.all()}
    return [b for b in active if b.id in assigned_ids]
```

- [ ] **Step 4: Run tests to confirm pass**

```
pytest tests/unit/test_branch_utils.py -v
```

Expected: 4 PASS

- [ ] **Step 5: Update `select_branch` view to use the helper**

In `app/users/views.py`, find the `select_branch` view. Replace:

```python
    active_branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()

    if current_user.role in ['admin', 'accountant']:
        accessible_branches = active_branches
    else:
        user_branch_ids = current_user.get_branch_ids()
        accessible_branches = [b for b in active_branches if b.id in user_branch_ids]
```

With:

```python
    from app.users.utils import get_accessible_branches
    accessible_branches = get_accessible_branches(current_user)
```

- [ ] **Step 6: Update `_post_login_redirect` to use the helper**

In `app/users/views.py`, find `_post_login_redirect`. Replace:

```python
    active_branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
    if user.role in ['admin', 'accountant']:
        accessible_branches = active_branches
    else:
        user_branch_ids = {b.id for b in user.branches.all()}
        accessible_branches = [b for b in active_branches if b.id in user_branch_ids]
```

With:

```python
    from app.users.utils import get_accessible_branches
    accessible_branches = get_accessible_branches(user)
```

- [ ] **Step 7: Run existing branch tests to confirm no regression**

```
pytest tests/integration/test_branch_assignment.py -v
```

Expected: all PASS

- [ ] **Step 8: Commit**

```
git add app/users/utils.py app/users/views.py tests/unit/test_branch_utils.py
git commit -m "refactor: extract get_accessible_branches helper to app/users/utils.py"
```

---

### Task 2: Add `validate_branch_session` before_request hook

**Files:**
- Modify: `app/__init__.py` — add hook after `enforce_https`

- [ ] **Step 1: Write the failing integration tests**

Create `tests/integration/test_branch_session_validation.py`:

```python
"""Integration tests for branch session validation before_request hook."""
import pytest
from flask import session


def login(client, password='ac1123581321'):
    with client.session_transaction() as sess:
        pass
    resp = client.post('/login', data={'username': 'admin', 'password': password},
                       follow_redirects=True)
    return resp


class TestBranchSessionValidation:
    def test_stale_branch_id_redirects_to_select_branch(self, client, db_session,
                                                         admin_user, main_branch):
        login(client)
        # Inject a non-existent branch ID into the session
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = 99999
        resp = client.get('/dashboard', follow_redirects=False)
        assert resp.status_code == 302
        assert '/select-branch' in resp.headers['Location']

    def test_missing_branch_id_auto_selects_single_branch(self, client, db_session,
                                                           admin_user, main_branch):
        login(client)
        with client.session_transaction() as sess:
            sess.pop('selected_branch_id', None)
        resp = client.get('/dashboard', follow_redirects=True)
        assert resp.status_code == 200
        with client.session_transaction() as sess:
            assert sess.get('selected_branch_id') == main_branch.id

    def test_valid_branch_id_passes_through(self, client, db_session,
                                             admin_user, main_branch):
        login(client)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        resp = client.get('/dashboard', follow_redirects=False)
        assert resp.status_code == 200

    def test_exempt_routes_skip_validation(self, client, db_session, admin_user):
        # /login should not be redirected even with no branch in session
        resp = client.get('/login', follow_redirects=False)
        assert resp.status_code == 200

    def test_deactivated_branch_redirects_to_select_branch(self, client, db_session,
                                                             admin_user, main_branch):
        from app.branches.models import Branch
        extra = Branch(name='Extra', code='EXT', is_active=True)
        db_session.add(extra)
        db_session.commit()
        login(client)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = extra.id
        # Now deactivate that branch
        extra.is_active = False
        db_session.commit()
        resp = client.get('/dashboard', follow_redirects=False)
        assert resp.status_code == 302
        assert '/select-branch' in resp.headers['Location']
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/integration/test_branch_session_validation.py -v
```

Expected: most tests FAIL (hook doesn't exist yet)

- [ ] **Step 3: Add the hook to `app/__init__.py`**

After the `enforce_https` hook (around line 302), add:

```python
    BRANCH_EXEMPT_ENDPOINTS = {
        'users.login',
        'users.logout',
        'users.register',
        'users.select_branch',
        'static',
    }

    @app.before_request
    def validate_branch_session():
        """Ensure session branch_id is valid on every request; auto-select or redirect if not."""
        from flask import session, redirect, url_for, request
        from flask_login import current_user
        from app.users.utils import get_accessible_branches

        if request.endpoint in BRANCH_EXEMPT_ENDPOINTS:
            return
        if not current_user.is_authenticated:
            return

        branch_id = session.get('selected_branch_id')
        accessible = get_accessible_branches(current_user)

        if branch_id is not None:
            if any(b.id == branch_id for b in accessible):
                return  # valid — continue

            # stale — clear it
            session.pop('selected_branch_id', None)

        # branch_id missing or was stale
        if len(accessible) == 1:
            session['selected_branch_id'] = accessible[0].id
            return

        return redirect(url_for('users.select_branch', next=request.url))
```

- [ ] **Step 4: Run tests to confirm pass**

```
pytest tests/integration/test_branch_session_validation.py -v
```

Expected: 5 PASS

- [ ] **Step 5: Run full suite to confirm no regression**

```
pytest -m "not slow" -q
```

Expected: all PASS

- [ ] **Step 6: Commit**

```
git add app/__init__.py tests/integration/test_branch_session_validation.py
git commit -m "feat: validate branch session on every request via before_request hook"
```
