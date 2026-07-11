# Dashboard "As of Date" defaults to month-end — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Default the Dashboard "As of Date" picker to the end of the current month instead of today, and rename the reset button to "Month End".

**Architecture:** A pure default/render change in one Flask view (`app/dashboard/views.py::home`) and its template (`dashboard/index.html`). The view computes end-of-current-month from PH-now and uses it as the fallback `as_of_date` and as a new `month_end` template kwarg; the template's reset button snaps to that value. No data-helper or route changes.

**Tech Stack:** Flask, Jinja2, pytest (integration, Flask test client). `calendar` (stdlib) for month-end.

**Spec:** `docs/superpowers/specs/2026-07-11-dashboard-asof-eom-default-design.md`
**Bug:** BUG-DASHBOARD-ASOF-DEFAULT-EOM (Low)

## Global Constraints

- Time is always Philippine Standard Time via `app.utils.ph_now` — never naive `datetime.now()`.
- The dev server does NOT hot-reload Python: after editing `views.py`, a running server must be restarted before browser-checking. (pytest is unaffected — it builds a fresh app.)
- This is a default-**render** bug: regress it with render-assertions on the `GET`, not a POST contract (a POST test that supplies `as_of_date` directly cannot catch a wrong default). Same lesson as `csrf-only-render-drops-hidden-fields`.
- Existing "Allow any date — past, present, or future" behavior is intentional; a future-dated EOM default is expected, not a bug.
- Work on a dedicated branch off `main` (keep primary `projects/cas` on `main` for `/ui-test`).

---

### Task 1: Default the dashboard "As of Date" to end-of-current-month + rename reset button

**Files:**
- Modify: `app/dashboard/views.py` (function `home`, currently lines 26–97)
- Modify: `app/dashboard/templates/dashboard/index.html:23,26-30`
- Test: `tests/integration/test_dashboard_asof_default.py` (create)

**Interfaces:**
- Consumes: `app.utils.ph_now` (already imported in `views.py`), the `/dashboard` route, the `admin_user` / `main_branch` / `db_session` / `client` fixtures from `tests/conftest.py`.
- Produces: `GET /dashboard` renders the date input `value` = end of current PH month by default; a `📅 Month End` reset button whose JS target is that same date. No new public function signatures.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_dashboard_asof_default.py`:

```python
import calendar
import pytest
from app.utils import ph_now

pytestmark = [pytest.mark.dashboard, pytest.mark.integration]


def login(client, username, password):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def expected_eom():
    """End of the current PH month, as the view computes it."""
    n = ph_now().date()
    return n.replace(day=calendar.monthrange(n.year, n.month)[1])


@pytest.fixture
def logged_in_admin(client, db_session, admin_user, main_branch):
    admin_user.add_branch(main_branch)
    db_session.commit()
    login(client, 'admin', 'admin123')
    return client


class TestDashboardAsOfDefault:
    def test_default_is_end_of_current_month(self, logged_in_admin):
        resp = logged_in_admin.get('/dashboard')
        assert resp.status_code == 200
        eom = expected_eom().strftime('%Y-%m-%d')
        assert f'value="{eom}"'.encode() in resp.data

    def test_invalid_as_of_date_falls_back_to_eom(self, logged_in_admin):
        resp = logged_in_admin.get('/dashboard?as_of_date=not-a-date')
        assert resp.status_code == 200
        eom = expected_eom().strftime('%Y-%m-%d')
        assert f'value="{eom}"'.encode() in resp.data

    def test_explicit_valid_as_of_date_is_honored(self, logged_in_admin):
        resp = logged_in_admin.get('/dashboard?as_of_date=2026-03-15')
        assert resp.status_code == 200
        assert b'value="2026-03-15"' in resp.data

    def test_reset_button_is_month_end_not_today(self, logged_in_admin):
        resp = logged_in_admin.get('/dashboard')
        assert resp.status_code == 200
        body = resp.data.decode('utf-8')
        # Button label changed
        assert 'Month End' in body
        assert '📅 Today' not in body
        # Button resets to the EOM value
        eom = expected_eom().strftime('%Y-%m-%d')
        assert f".value='{eom}'" in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integration/test_dashboard_asof_default.py -v`
Expected: `test_default_is_end_of_current_month`, `test_invalid_as_of_date_falls_back_to_eom`, and `test_reset_button_is_month_end_not_today` FAIL (page still defaults to today / button still says "Today"). `test_explicit_valid_as_of_date_is_honored` may already PASS (explicit param already honored) — that's fine, it is a regression guard.

Note: if `pytest.mark.dashboard` is unregistered it emits a warning, not a failure. If the run errors on an unknown marker (strict markers), drop `pytest.mark.dashboard` from `pytestmark`, leaving `[pytest.mark.integration]`.

- [ ] **Step 3: Update the view**

In `app/dashboard/views.py`, add `import calendar` at the top (near `import json`). Then change the top of `home()` from:

```python
    """Main dashboard page with real business metrics"""
    # Get "as of" date from query parameter or default to today
    today = ph_now().date()
    as_of_date_str = request.args.get('as_of_date')

    if as_of_date_str:
        try:
            as_of_date = datetime.strptime(as_of_date_str, '%Y-%m-%d').date()
            # Allow any date - past, present, or future
        except ValueError:
            as_of_date = today
    else:
        as_of_date = today
```

to:

```python
    """Main dashboard page with real business metrics"""
    # Get "as of" date from query parameter or default to end of the current
    # month (the natural month-end reporting date), consistent with the EOM
    # two-column IS/CF. BUG-DASHBOARD-ASOF-DEFAULT-EOM.
    now = ph_now().date()
    month_end = now.replace(day=calendar.monthrange(now.year, now.month)[1])
    as_of_date_str = request.args.get('as_of_date')

    if as_of_date_str:
        try:
            as_of_date = datetime.strptime(as_of_date_str, '%Y-%m-%d').date()
            # Allow any date - past, present, or future
        except ValueError:
            as_of_date = month_end
    else:
        as_of_date = month_end
```

Then change the `render_template` call's final kwarg from:

```python
                         today=today.strftime('%Y-%m-%d'))
```

to:

```python
                         month_end=month_end.strftime('%Y-%m-%d'))
```

- [ ] **Step 4: Update the template**

In `app/dashboard/templates/dashboard/index.html`, change the reset button block (currently lines 26–30) from:

```html
                        <button type="button"
                                onclick="document.getElementById('asOfDate').value='{{ today }}'; document.getElementById('dateForm').submit();"
                                class="btn btn-sm dashboard-today-btn">
                            📅 Today
                        </button>
```

to:

```html
                        <button type="button"
                                onclick="document.getElementById('asOfDate').value='{{ month_end }}'; document.getElementById('dateForm').submit();"
                                class="btn btn-sm dashboard-today-btn">
                            📅 Month End
                        </button>
```

The input `value="{{ as_of_date }}"` (line 23) is unchanged — it now receives the EOM default from the view.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/integration/test_dashboard_asof_default.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 6: Guard against regressions in the existing dashboard suite**

Run: `pytest tests/integration/test_dashboard_roles.py tests/integration/test_dashboard_aggregate_math.py tests/integration/test_dashboard_branch_scope.py -q`
Expected: PASS (no test asserts the old "Today" button label or the today-default). If any fails on the old label/default, it is a stale assertion pinned to the old behavior — update that assertion to the new "Month End" / EOM expectation (test-only change) and note it in the commit.

- [ ] **Step 7: Commit**

```bash
git add app/dashboard/views.py app/dashboard/templates/dashboard/index.html tests/integration/test_dashboard_asof_default.py
git commit -m "fix(dashboard): default As-of-Date to month-end; rename reset button to Month End (BUG-DASHBOARD-ASOF-DEFAULT-EOM)"
```

---

## Self-Review

**Spec coverage:**
- Default → end of current month → Task 1 Step 3 + `test_default_is_end_of_current_month`. ✓
- Reset button → "Month End" resetting to EOM → Task 1 Step 4 + `test_reset_button_is_month_end_not_today`. ✓
- Explicit valid param honored (unchanged) → `test_explicit_valid_as_of_date_is_honored`. ✓
- Invalid param falls back to EOM, no 500 → `test_invalid_as_of_date_falls_back_to_eom`. ✓
- No data-helper / route changes → view edit touches only the default computation + one kwarg; helpers untouched. ✓
- `current_year`/`current_month` still derive from `as_of_date` → not modified. ✓

**Placeholder scan:** No TBD/TODO/"add error handling" — all steps carry exact code and commands. ✓

**Type consistency:** `month_end` is the single name used in the view local, the `render_template` kwarg, the template `{{ month_end }}`, and asserted in tests. The removed `today` local/kwarg is gone from both view and template. `calendar.monthrange(y, m)[1]` returns the last day-of-month int, fed to `date.replace(day=...)`. ✓
