# Branch Session Validation — Design Spec

**Date:** 2026-06-14  
**Status:** Approved

---

## Problem

`session['selected_branch_id']` can become stale — pointing to a branch that has been deleted or deactivated — without the app detecting it. Individual views check `session.get('selected_branch_id')` for presence but never verify the branch still exists and is active. This causes confusing "Please select a branch" flashes and broken page renders even when the user is already in an active session.

Root cause observed: deleting the TEST branch while a session held `selected_branch_id = TEST.id` left the session with a dangling foreign key.

---

## Solution

A single `@before_request` hook in `create_app` (`app/__init__.py`) that validates `session['selected_branch_id']` on every request. One central fix — no changes to individual views.

---

## Hook Behaviour

### Exempt routes (skip validation entirely)

```python
BRANCH_EXEMPT_ENDPOINTS = {
    'users.login',
    'users.logout',
    'users.register',
    'users.select_branch',
    'static',
}
```

### Validation logic (pseudocode)

```
if endpoint in BRANCH_EXEMPT_ENDPOINTS:
    return  # skip

if not current_user.is_authenticated:
    return  # Flask-Login handles this

branch_id = session.get('selected_branch_id')
accessible = get_accessible_branches(current_user)  # active branches the user can access

if branch_id is not None:
    valid = any(b.id == branch_id and b.is_active for b in accessible)
    if valid:
        return  # all good
    # stale — clear it and fall through to selection logic
    session.pop('selected_branch_id', None)

# branch_id is None or was stale
if len(accessible) == 1:
    # auto-select, no redirect
    session['selected_branch_id'] = accessible[0].id
    return

# multiple branches — redirect to selection, preserve original destination
return redirect(url_for('users.select_branch', next=request.url))
```

### Auto-select rule

If the user has **exactly one** accessible active branch, set it silently and continue — no flash, no redirect. This matches the existing login-time auto-select behaviour.

### Multiple branches

Redirect to `/select-branch?next=<original_url>` so the user lands back on the page they were trying to reach after picking a branch.

---

## Scope

- **One file changed:** `app/__init__.py` — add one `@before_request` hook after the existing `log_request_info` and `enforce_https` hooks.
- **No view changes** — all 42 existing `session.get('selected_branch_id')` call sites remain unchanged. The hook guarantees a valid value before they run.
- **No model changes, no migrations.**

---

## Helper: `get_accessible_branches(user)`

Extract from the existing `select_branch` view into a small helper (in `app/users/views.py` or `app/utils/`) so both the hook and the view share the same logic:

```python
def get_accessible_branches(user):
    """Return active branches accessible to the given user."""
    from app.branches.models import Branch
    active_branches = Branch.query.filter_by(is_active=True).all()
    if user.role == 'admin':
        return active_branches
    user_branch_ids = {b.id for b in user.branches}
    return [b for b in active_branches if b.id in user_branch_ids]
```

---

## Testing

- Log in, select a branch, delete that branch in another session → refreshing any page should silently auto-select (if one branch left) or redirect to branch selection (if multiple remain).
- Unit test: `test_stale_branch_cleared_on_request` — seed two branches, log in, set `session['selected_branch_id']` to a deleted branch ID, GET `/dashboard`, assert redirect to `/select-branch`.
- Unit test: `test_auto_select_single_branch` — seed one branch, log in with no session branch set, GET `/dashboard`, assert `session['selected_branch_id']` is set and no redirect.
