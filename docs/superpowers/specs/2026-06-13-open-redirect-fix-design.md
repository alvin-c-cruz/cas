# Open Redirect Fix — Design

**Date:** 2026-06-13
**Status:** Approved — ready for implementation

---

## Problem

`app/users/views.py` passes `request.args.get('next')` directly to `redirect()` in two routes without validating that the URL is local. An attacker can craft `/login?next=http://evil.com` and redirect a freshly-authenticated user to a phishing site.

Affected locations:
- `login()` — `views.py:182–184`
- `select_branch()` — `views.py:203, 221, 255`

---

## Fix

### 1. New helper — `_is_safe_url(target)`

Add near `admin_required` at the top of `app/users/views.py`.

```python
from urllib.parse import urlparse, urljoin

def _is_safe_url(target):
    ref = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, target))
    return test.scheme in ('http', 'https') and ref.netloc == test.netloc
```

The `urljoin` roundtrip resolves protocol-relative (`//evil.com`) and scheme-manipulation
(`javascript:…`) attacks before the netloc comparison. Uses stdlib only.

---

### 2. `login()` — lines 182–184

```python
# Before
next_page = request.args.get('next')
if next_page:
    return redirect(next_page)

# After
next_page = request.args.get('next')
if next_page and _is_safe_url(next_page):
    return redirect(next_page)
```

Unsafe `next` values fall through to `redirect(url_for('dashboard.index'))` unchanged.

---

### 3. `select_branch()` — line 203

```python
# Before
next_url = request.args.get('next') or request.form.get('next') or url_for('dashboard.index')

# After
_raw_next = request.args.get('next') or request.form.get('next')
next_url = _raw_next if (_raw_next and _is_safe_url(_raw_next)) else url_for('dashboard.index')
```

`redirect(next_url)` calls at lines 221 and 255 are unchanged — they always receive a
validated value after this change.

---

## Tests

New file: `tests/integration/test_auth_views.py`

Uses existing fixtures: `client`, `accountant_user` (single-branch user so login
auto-selects branch and hits the `next_page` redirect path).

| Test | Input | Expected outcome |
|------|-------|-----------------|
| `test_login_open_redirect_absolute` | `POST /login?next=http://evil.com` | Response redirects to `/` (dashboard), not `evil.com` |
| `test_login_open_redirect_protocol_relative` | `POST /login?next=//evil.com` | Response redirects to `/` |
| `test_login_valid_next_honored` | `POST /login?next=/vendors` | Response redirects to `/vendors` |

All three tests assert `response.location` does not contain `evil.com` / assert the
final redirect target. No new fixtures required.

---

## Scope

- **Files changed:** `app/users/views.py` (helper + two call sites), `tests/integration/test_auth_views.py` (new)
- **No model changes.** No migration required.
- **No template changes.**
