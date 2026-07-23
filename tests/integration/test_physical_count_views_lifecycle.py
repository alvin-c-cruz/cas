"""Physical Count views (R-03 Physical Count, Task 10): detail, approve, void,
print, plus the resolve-via-Stock-Adjustment `create()` pre-fill.

Note: physical_counts_view and physical_counts_print render templates
(physical_count_view.html, physical_count_print.html) that do NOT exist yet
-- that's Task 11's job. Those two GET routes fail with TemplateNotFound here;
that is the expected end state for this task.

Deviations from the task-10 brief's draft (verified against actual running
behavior, same discipline as Task 9's test_physical_count_views_create.py):
- `module` and `select_branch` are not conftest.py fixtures anywhere in this
  codebase (confirmed by grep) -- defined locally below, following the
  existing _enable_module()/`client.post('/select-branch', ...)` pattern.
- `login_user(client, admin_user)` is not this conftest's signature --
  `login_user` takes (client, username, password); calls below pass
  `<user>.username, '<role>123'` (fixture-defined password) instead.
- `second_accountant_user` is not a conftest.py fixture -- defined locally
  below, following the exact shape of test_physical_count_approval_rule.py's
  own local fixture of the same name.
- `accountant_user` (conftest.py) is assigned to `main_branch` (code MAIN),
  a DIFFERENT Branch row than `branch_main` (code STKMAIN, used by every
  stock-ledger/physical-count fixture here) -- re-scoped to `branch_main` in
  the self-approval test so `_pc_or_404`'s accessible-branches check doesn't
  404 the accountant out of their own physical count.
- The brief's draft asserts `resp.status_code == 200` on the approve/void
  POSTs with `follow_redirects=True`. Verified against actual behavior: both
  routes redirect (302) to `physical_counts_view` on every path (success,
  blocked-self-approval, error), and that view's template
  (physical_count_view.html) does not exist until Task 11 -- so following the
  redirect raises TemplateNotFound here too, same underlying cause as the two
  GET-route failures, not a bug in the approve/void logic itself. Fixed by
  asserting the 302 + Location directly (no follow), reading flashed messages
  via `client.session_transaction()`, and checking DB state -- proving the
  route logic without depending on the not-yet-built template. Re-run this
  file after Task 11 lands the templates to see the full happy-path status
  codes too.
"""
from decimal import Decimal
from datetime import date

import pytest

from app import db
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache
from app.stock_adjustments.models import PhysicalCount, StockBalance
from app.users.models import User

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


@pytest.fixture
def second_accountant_user(db_session):
    """A second active accountant -- needed by the self-approval-blocked test
    so `can_be_approved_by` finds a peer reviewer."""
    user = User(username='accountant2', email='accountant2@test.com',
                full_name='Second Accountant', role='accountant', is_active=True)
    user.set_password('accountant123')
    db.session.add(user)
    db.session.commit()
    return user


def _draft_count(branch, product, counted_qty):
    from app.stock_adjustments.physical_count_service import snapshot_physical_count_lines
    pc = PhysicalCount(pc_number='PC-2026-07-0050', branch_id=branch.id,
                       count_date=date(2026, 7, 23), status='draft')
    snapshot_physical_count_lines(pc, [product])
    pc.lines[0].counted_qty = Decimal(counted_qty)
    db.session.add(pc)
    db.session.commit()
    return pc


class TestPhysicalCountView:
    def test_view_shows_lines_and_variance(
            self, client, admin_user, login_user, branch_main, product_moving_avg, module):
        module('stock_adjustments', True)
        login_user(client, admin_user.username, 'admin123')
        pc = _draft_count(branch_main, product_moving_avg, '7')

        resp = client.get(f'/stock-adjustments/physical-counts/{pc.id}')
        assert resp.status_code == 200
        assert pc.pc_number.encode() in resp.data


class TestPhysicalCountApprove:
    def test_approve_posts_adjustment_and_flashes_success(
            self, client, admin_user, login_user, branch_main, product_moving_avg, module,
            control_accounts):
        module('stock_adjustments', True)
        login_user(client, admin_user.username, 'admin123')
        bal = StockBalance(product_id=product_moving_avg.id, branch_id=branch_main.id,
                          quantity_on_hand=Decimal('10'), average_unit_cost=Decimal('5.00'),
                          total_value=Decimal('50.00'))
        db.session.add(bal)
        db.session.commit()
        pc = _draft_count(branch_main, product_moving_avg, '7')

        resp = client.post(f'/stock-adjustments/physical-counts/{pc.id}/approve')
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith(f'/physical-counts/{pc.id}')
        with client.session_transaction() as sess:
            flashed = ' '.join(m for _, m in sess.get('_flashes', [])).lower()
        assert 'approved' in flashed and 'posted stock adjustment' in flashed

        reloaded = db.session.get(PhysicalCount, pc.id)
        assert reloaded.status == 'approved'
        assert reloaded.stock_adjustment_id is not None

    def test_self_approval_blocked_for_non_full_access_user_with_a_peer(
            self, client, accountant_user, second_accountant_user, login_user, branch_main,
            product_moving_avg, module, control_accounts):
        # accountant_user (conftest.py) is assigned to `main_branch` (code
        # MAIN), a DIFFERENT branch row than `branch_main` (code STKMAIN,
        # used by all the stock-ledger fixtures including product_moving_avg
        # and the PhysicalCount created below). Re-scope to branch_main so
        # `_pc_or_404`'s accessible-branches check doesn't 404 the accountant
        # out of their own physical count.
        accountant_user.set_branches([branch_main])
        db.session.commit()
        module('stock_adjustments', True)
        login_user(client, accountant_user.username, 'accountant123')
        pc = _draft_count(branch_main, product_moving_avg, '7')
        pc.created_by_id = accountant_user.id
        db.session.commit()

        resp = client.post(f'/stock-adjustments/physical-counts/{pc.id}/approve')
        assert resp.status_code == 302
        with client.session_transaction() as sess:
            flashed = ' '.join(m for _, m in sess.get('_flashes', [])).lower()
        assert 'cannot approve your own' in flashed

        reloaded = db.session.get(PhysicalCount, pc.id)
        assert reloaded.status == 'draft'


class TestPhysicalCountVoid:
    def test_void_reverses_and_flashes(
            self, client, admin_user, login_user, branch_main, product_moving_avg, module,
            control_accounts):
        module('stock_adjustments', True)
        login_user(client, admin_user.username, 'admin123')
        bal = StockBalance(product_id=product_moving_avg.id, branch_id=branch_main.id,
                          quantity_on_hand=Decimal('10'), average_unit_cost=Decimal('5.00'),
                          total_value=Decimal('50.00'))
        db.session.add(bal)
        db.session.commit()
        pc = _draft_count(branch_main, product_moving_avg, '7')
        client.post(f'/stock-adjustments/physical-counts/{pc.id}/approve')

        resp = client.post(f'/stock-adjustments/physical-counts/{pc.id}/void')
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith(f'/physical-counts/{pc.id}')
        with client.session_transaction() as sess:
            flashed = ' '.join(m for _, m in sess.get('_flashes', [])).lower()
        assert 'voided' in flashed
        reloaded = db.session.get(PhysicalCount, pc.id)
        assert reloaded.status == 'voided'


class TestPhysicalCountPrint:
    def test_print_renders(self, client, admin_user, login_user, branch_main, product_moving_avg,
                           module):
        module('stock_adjustments', True)
        login_user(client, admin_user.username, 'admin123')
        pc = _draft_count(branch_main, product_moving_avg, '7')

        resp = client.get(f'/stock-adjustments/physical-counts/{pc.id}/print')
        assert resp.status_code == 200


class TestResolveViaStockAdjustmentPrefill:
    def test_create_prefills_a_line_from_query_params(
            self, client, admin_user, login_user, branch_main, product_fifo, module,
            select_branch):
        module('stock_adjustments', True)
        login_user(client, admin_user.username, 'admin123')
        select_branch(client, branch_main.id)

        resp = client.get(f'/stock-adjustments/create?product_id={product_fifo.id}&qty=-3')
        assert resp.status_code == 200
        assert str(product_fifo.id).encode() in resp.data
