"""Physical Count views (R-03 Physical Count, Task 9): list, create, count-entry.

Note: the templates these routes render (physical_count_list.html,
physical_count_create.html, physical_count_entry.html) do NOT exist yet --
that's Task 11's job. GET paths that reach a render_template() call fail with
TemplateNotFound here; that is the expected end state for this task. The
POST/logic paths that don't need a template (permission checks, redirects,
the actual create/save writes) are asserted directly against the DB.

Fixture deviations from the task-9 brief's draft (verified against actual
conftest.py, same pattern as prior tasks in this arc):
- `module` and `select_branch` are not conftest.py fixtures anywhere in this
  codebase (confirmed by grep) -- defined locally below, following the
  existing _enable_module()/`client.post('/select-branch', ...)` pattern
  used by tests/integration/test_stock_adjustment_views.py.
- `login_user(client, admin_user)` is not this conftest's signature --
  `login_user` takes (client, username, password); calls below pass
  `admin_user.username, 'admin123'` (fixture-defined password) instead.
"""
from decimal import Decimal
from datetime import date

import pytest

from app import db
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache
from app.stock_adjustments.models import PhysicalCount, StockBalance

pytestmark = pytest.mark.integration


@pytest.fixture
def module():
    def _enable(name, enabled=True):
        AppSettings.set_setting('module_enabled:inventory', '1', updated_by='test')
        AppSettings.set_setting(f'module_enabled:{name}', '1' if enabled else '0', updated_by='test')
        clear_module_config_cache()
    return _enable


@pytest.fixture
def select_branch():
    def _select(client, branch_id):
        return client.post('/select-branch', data={'branch_id': branch_id}, follow_redirects=True)
    return _select


class TestPhysicalCountList:
    def test_list_requires_module_enabled(self, client, admin_user, login_user, branch_main):
        # branch_main is required even though this test never selects it: with
        # zero branches in the DB, the before_request branch-session guard force
        # -logs-out any authenticated user before the request reaches routing
        # (see app/__init__.py::validate_branch_session -> users.select_branch's
        # "no accessible branches" path) -- unrelated to the module-enabled check
        # this test actually exercises.
        #
        # Deviation from the task-9 brief's draft: the brief asserted the in-view
        # _guard() flash text ("Stock Adjustments module is not enabled"), but
        # verified against the app's actual before_request order, that flash is
        # unreachable for this scenario. app/__init__.py::enforce_module_access
        # runs BEFORE any view and, for a module disabled at the INSTANCE level
        # (module_enabled() False, the state under test here -- no module(...)
        # call has enabled it), aborts 404 for every role including admin, by
        # design ("the route appears to not exist for this deployment package").
        # test_wht_certificates.py::test_register_is_gated_by_bir_reports_module
        # pins the identical pattern for another optional module. _guard()'s own
        # flash only matters for a module key unknown to MODULE_REGISTRY, which
        # doesn't apply here.
        #
        # clear_module_config_cache() first: other physical-count test files in
        # this same run may have already enabled `stock_adjustments` and left
        # the @cache.memoize'd module-config cache warm, which would make this
        # test see the module as enabled and fail depending on run order.
        clear_module_config_cache()
        login_user(client, admin_user.username, 'admin123')
        resp = client.get('/stock-adjustments/physical-counts')
        assert resp.status_code == 404

    def test_list_shows_existing_counts(self, client, admin_user, login_user, branch_main, module):
        # EXPECTED-FAILING until Task 11: physical_count_list.html doesn't exist
        # yet -> TemplateNotFound. Left as the brief specifies; this pins the
        # target behavior for Task 11 to make pass.
        module('stock_adjustments', True)
        login_user(client, admin_user.username, 'admin123')
        pc = PhysicalCount(pc_number='PC-2026-07-0040', branch_id=branch_main.id,
                           count_date=date(2026, 7, 23), status='draft')
        db.session.add(pc)
        db.session.commit()

        resp = client.get('/stock-adjustments/physical-counts')
        assert resp.status_code == 200
        assert b'PC-2026-07-0040' in resp.data


class TestPhysicalCountCreate:
    def test_create_snapshots_every_tracked_product_in_the_session_branch(
            self, client, admin_user, login_user, branch_main, product_moving_avg, module,
            select_branch):
        # EXPECTED-FAILING until Task 11: the POST succeeds and creates the
        # PhysicalCount (verified separately, no-follow, during implementation --
        # see task-9-report.md), but follow_redirects=True chases the redirect
        # into physical_counts_entry's GET render, which needs
        # physical_count_entry.html (Task 11) -> TemplateNotFound. Left as the
        # brief specifies; this pins the target behavior for Task 11.
        module('stock_adjustments', True)
        login_user(client, admin_user.username, 'admin123')
        select_branch(client, branch_main.id)

        resp = client.post('/stock-adjustments/physical-counts/create',
                          data={'count_date': '2026-07-23', 'notes': 'Q3 count'},
                          follow_redirects=True)
        assert resp.status_code == 200

        pc = PhysicalCount.query.order_by(PhysicalCount.id.desc()).first()
        assert pc.branch_id == branch_main.id
        assert pc.status == 'draft'
        assert len(pc.lines) == 1
        assert pc.lines[0].product_id == product_moving_avg.id

    def test_create_requires_manage_permission(self, client, staff_user, login_user, module,
                                               branch_main):
        # Two deviations from the brief's draft, both verified against actual
        # app behavior (same class of fix as test_list_requires_module_enabled
        # above):
        # 1. staff_user carries no branch assignment by default; without one the
        #    before_request branch-session guard force-logs them out before the
        #    permission check under test is ever reached -- assign + select
        #    branch_main first, matching the existing
        #    staff_user.branches.append(main_branch) pattern used across the
        #    suite (e.g. test_balance_sheet_views.py).
        # 2. stock_adjustments is a `per_user: True` optional module (see
        #    MODULE_REGISTRY in app/users/module_access.py) -- module('stock_
        #    adjustments', True) only flips the INSTANCE-level switch.
        #    app/__init__.py::enforce_module_access ALSO gates per-user via
        #    book_permissions, and staff_user's conftest.py fixture does not
        #    grant 'stock_adjustments'; without granting it here, that
        #    upstream before_request gate intercepts first (redirect to
        #    dashboard with a DIFFERENT flash: "You do not have access to
        #    this module") and the in-view _can_manage() check this test
        #    means to exercise is never reached. Grant the book permission so
        #    only the role-based _can_manage() gate is under test.
        staff_user.branches.append(branch_main)
        staff_user.set_book_permissions({**staff_user.get_book_permissions(),
                                         'stock_adjustments': True})
        db.session.commit()
        module('stock_adjustments', True)
        login_user(client, staff_user.username, 'staff123')
        client.post('/select-branch', data={'branch_id': branch_main.id}, follow_redirects=True)
        # Not following the redirect: its target (physical_counts_list) itself
        # render_template()s a Task-11 template that doesn't exist yet
        # (TemplateNotFound), which is unrelated to the permission check this
        # test exercises. Assert the redirect itself -- the flash + redirect to
        # physical_counts_list only happens on the not-_can_manage() branch.
        resp = client.get('/stock-adjustments/physical-counts/create', follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/stock-adjustments/physical-counts')
        with client.session_transaction() as sess:
            flashes = dict(sess.get('_flashes', []))
        assert any('do not have permission' in msg for msg in flashes.values())


class TestPhysicalCountEntry:
    def test_entry_saves_counted_quantities(
            self, client, admin_user, login_user, branch_main, product_moving_avg, module,
            select_branch):
        # EXPECTED-FAILING until Task 11: the POST saves counted_qty correctly
        # (verified separately, no-follow, during implementation -- see
        # task-9-report.md), but follow_redirects=True chases the redirect back
        # into the same GET render, which needs physical_count_entry.html (Task
        # 11) -> TemplateNotFound. Left as the brief specifies.
        module('stock_adjustments', True)
        login_user(client, admin_user.username, 'admin123')
        select_branch(client, branch_main.id)
        from app.stock_adjustments.physical_count_service import snapshot_physical_count_lines
        pc = PhysicalCount(pc_number='PC-2026-07-0041', branch_id=branch_main.id,
                           count_date=date(2026, 7, 23), status='draft')
        snapshot_physical_count_lines(pc, [product_moving_avg])
        db.session.add(pc)
        db.session.commit()
        line_id = pc.lines[0].id

        resp = client.post(f'/stock-adjustments/physical-counts/{pc.id}/entry',
                          data={'row_version': str(pc.row_version),
                                f'counted_qty_{line_id}': '7'},
                          follow_redirects=True)
        assert resp.status_code == 200

        reloaded = db.session.get(PhysicalCount, pc.id)
        assert reloaded.lines[0].counted_qty == Decimal('7')

    def test_entry_blocked_once_approved(
            self, client, admin_user, login_user, branch_main, product_moving_avg, module,
            select_branch, control_accounts):
        # EXPECTED-FAILING until Task 10: `stock_adjustments.physical_counts_view`
        # (the detail page) is Task 10's route, not yet defined on this branch.
        # The status != 'draft' redirect target needs it -> BuildError, a
        # forward-reference gap of the exact same shape as the TemplateNotFound
        # gap Task 11 resolves (see views.py::physical_counts_entry's comment on
        # the same line). The 'Only a draft' flash logic itself is otherwise
        # correct and matches app/stock_adjustments/views.py::void's identical
        # status-guard pattern. Left as the brief specifies; this pins the
        # target behavior for Task 10 to make pass.
        module('stock_adjustments', True)
        login_user(client, admin_user.username, 'admin123')
        select_branch(client, branch_main.id)
        from app.stock_adjustments.physical_count_service import (
            snapshot_physical_count_lines, approve_physical_count)
        pc = PhysicalCount(pc_number='PC-2026-07-0042', branch_id=branch_main.id,
                           count_date=date(2026, 7, 23), status='draft')
        snapshot_physical_count_lines(pc, [product_moving_avg])
        pc.lines[0].counted_qty = Decimal('0')
        db.session.add(pc)
        db.session.commit()
        approve_physical_count(pc, admin_user)
        db.session.commit()

        resp = client.get(f'/stock-adjustments/physical-counts/{pc.id}/entry', follow_redirects=True)
        assert b'Only a draft' in resp.data
