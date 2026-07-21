"""Stock Adjustment document views (R-03 slice 2a-i, Task 8).

Draft create -> approve flow, plus the render-assertion that pins the
csrf-only-render-drops-hidden-fields class for this form (the GET must carry
name="row_version" and name="lines" in the rendered body).
"""
import json

import pytest

from app import db
from app.stock_adjustments.models import StockAdjustment
from app.settings import AppSettings
from app.audit.models import AuditLog

pytestmark = pytest.mark.integration


def _enable_module():
    AppSettings.set_setting('module_enabled:inventory', '1', updated_by='test')
    AppSettings.set_setting('module_enabled:stock_adjustments', '1', updated_by='test')
    from app.utils.cache_helpers import clear_module_config_cache
    clear_module_config_cache()


def test_create_draft_then_approve_flow(client, admin_user, login_user, db_session,
                                        product_tracked, branch_main, make_account):
    _enable_module()
    make_account('1401'); AppSettings.set_setting('inventory_account_code', '1401', updated_by='t')
    make_account('7101'); AppSettings.set_setting('inventory_adjustment_account_code', '7101', updated_by='t')
    login_user(client, 'admin', 'admin123')
    client.post('/select-branch', data={'branch_id': branch_main.id})

    lines = json.dumps([{'product_id': product_tracked.id, 'quantity_delta': '5', 'unit_cost': '4.00'}])
    resp = client.post('/stock-adjustments/create', data={
        'adjustment_date': '2026-07-21', 'reason_type': 'correction', 'lines': lines,
    }, follow_redirects=True)
    assert resp.status_code == 200

    adj = StockAdjustment.query.order_by(StockAdjustment.id.desc()).first()
    assert adj is not None
    assert adj.status == 'draft' and len(adj.lines) == 1
    assert adj.lines[0].product_id == product_tracked.id

    # audit row for the create
    assert AuditLog.query.filter_by(module='stock_adjustments', action='create').count() >= 1

    # The list index (module enabled + a real row) must show the created adjustment
    # -- closes Task 7's untested "module enabled + real rows" branch-scoping path.
    list_resp = client.get('/stock-adjustments/', follow_redirects=True)
    assert list_resp.status_code == 200
    assert adj.sa_number.encode() in list_resp.data

    # approve
    client.post(f'/stock-adjustments/{adj.id}/approve', follow_redirects=True)
    db.session.refresh(adj)
    assert adj.status == 'posted'
    assert adj.journal_entry_id is not None

    # audit row for the approve action, via the real HTTP route (not just the
    # service layer) -- CLAUDE.md: "Verify the audit log in CRUD tests".
    approve_log = (AuditLog.query.filter_by(module='stock_adjustments', action='approve',
                                            record_id=adj.id).first())
    assert approve_log is not None
    assert approve_log.record_identifier == adj.sa_number


def test_void_writes_audit_row(client, admin_user, login_user, db_session,
                               product_tracked, branch_main, make_account):
    """Reviewer finding: only create's audit row was asserted through the real
    HTTP route; approve/void were only proven at the service layer. This closes
    the void side (approve's is covered above)."""
    _enable_module()
    make_account('1401'); AppSettings.set_setting('inventory_account_code', '1401', updated_by='t')
    make_account('7101'); AppSettings.set_setting('inventory_adjustment_account_code', '7101', updated_by='t')
    login_user(client, 'admin', 'admin123')
    client.post('/select-branch', data={'branch_id': branch_main.id})

    lines = json.dumps([{'product_id': product_tracked.id, 'quantity_delta': '5', 'unit_cost': '4.00'}])
    resp = client.post('/stock-adjustments/create', data={
        'adjustment_date': '2026-07-21', 'reason_type': 'correction', 'lines': lines,
    }, follow_redirects=True)
    assert resp.status_code == 200
    adj = StockAdjustment.query.order_by(StockAdjustment.id.desc()).first()
    client.post(f'/stock-adjustments/{adj.id}/approve', follow_redirects=True)
    db.session.refresh(adj)
    assert adj.status == 'posted'

    client.post(f'/stock-adjustments/{adj.id}/void', follow_redirects=True)
    db.session.refresh(adj)
    assert adj.status == 'voided'

    void_log = (AuditLog.query.filter_by(module='stock_adjustments', action='void',
                                         record_id=adj.id).first())
    assert void_log is not None
    assert void_log.record_identifier == adj.sa_number


def test_status_badge_uses_named_modifier_class(client, admin_user, login_user, db_session,
                                                product_tracked, branch_main, make_account):
    """Reviewer finding: status was rendered via a bare <span class="badge">
    (unstyled default) instead of this codebase's named badge-{status} design-
    token modifier -- .badge-draft/.badge-posted/.badge-voided already exist in
    style.css and match this document's exact status values."""
    _enable_module()
    make_account('1401'); AppSettings.set_setting('inventory_account_code', '1401', updated_by='t')
    make_account('7101'); AppSettings.set_setting('inventory_adjustment_account_code', '7101', updated_by='t')
    login_user(client, 'admin', 'admin123')
    client.post('/select-branch', data={'branch_id': branch_main.id})

    lines = json.dumps([{'product_id': product_tracked.id, 'quantity_delta': '5', 'unit_cost': '4.00'}])
    resp = client.post('/stock-adjustments/create', data={
        'adjustment_date': '2026-07-21', 'reason_type': 'correction', 'lines': lines,
    }, follow_redirects=True)
    adj = StockAdjustment.query.order_by(StockAdjustment.id.desc()).first()

    list_resp = client.get('/stock-adjustments/')
    assert b'class="badge badge-draft"' in list_resp.data
    view_resp = client.get(f'/stock-adjustments/{adj.id}')
    assert b'class="badge badge-draft"' in view_resp.data

    client.post(f'/stock-adjustments/{adj.id}/approve', follow_redirects=True)
    view_resp = client.get(f'/stock-adjustments/{adj.id}')
    assert b'class="badge badge-posted"' in view_resp.data

    client.post(f'/stock-adjustments/{adj.id}/void', follow_redirects=True)
    view_resp = client.get(f'/stock-adjustments/{adj.id}')
    assert b'class="badge badge-voided"' in view_resp.data


def test_form_get_renders_row_version_hidden_field(client, admin_user, login_user, branch_main):
    _enable_module()
    login_user(client, 'admin', 'admin123')
    client.post('/select-branch', data={'branch_id': branch_main.id})
    resp = client.get('/stock-adjustments/create')
    assert resp.status_code == 200
    assert b'name="row_version"' in resp.data   # csrf-only-render-drops-hidden-fields guard
    assert b'name="lines"' in resp.data


def test_view_reachable_for_accessible_branch_not_currently_selected(
        client, admin_user, login_user, db_session, product_tracked,
        branch_manila, main_branch, make_account):
    """Reviewer finding: a multi-branch user's record must stay reachable even
    after they switch their SELECTED branch away from it -- accessible-branch
    scoping (matching the list route), not selected-branch scoping."""
    _enable_module()
    make_account('1401'); AppSettings.set_setting('inventory_account_code', '1401', updated_by='t')
    make_account('7101'); AppSettings.set_setting('inventory_adjustment_account_code', '7101', updated_by='t')
    login_user(client, 'admin', 'admin123')

    # Create the adjustment while Manila is the selected branch.
    client.post('/select-branch', data={'branch_id': branch_manila.id})
    lines = json.dumps([{'product_id': product_tracked.id, 'quantity_delta': '3', 'unit_cost': '2.00'}])
    resp = client.post('/stock-adjustments/create', data={
        'adjustment_date': '2026-07-21', 'reason_type': 'correction', 'lines': lines,
    }, follow_redirects=True)
    assert resp.status_code == 200
    adj = (StockAdjustment.query.filter_by(branch_id=branch_manila.id)
           .order_by(StockAdjustment.id.desc()).first())
    assert adj is not None

    # Admin (full-access) switches the SELECTED branch away from Manila. The
    # record's branch remains in the admin's ACCESSIBLE set, so it must not 404.
    client.post('/select-branch', data={'branch_id': main_branch.id})
    view_resp = client.get(f'/stock-adjustments/{adj.id}')
    assert view_resp.status_code == 200
    assert adj.sa_number.encode() in view_resp.data

    # Same for the print route, which shares the _adj_or_404 helper.
    print_resp = client.get(f'/stock-adjustments/{adj.id}/print')
    assert print_resp.status_code == 200


def test_view_blocked_for_branch_outside_users_accessible_set(
        client, admin_user, login_user, logout_user, db_session, product_tracked,
        branch_manila, accountant_user, make_account):
    """Negative case: a branch-scoped user with NO access to the record's
    branch at all must still 404 -- the relaxation only widens "selected" to
    "accessible", it does not remove branch scoping entirely."""
    _enable_module()
    make_account('1401'); AppSettings.set_setting('inventory_account_code', '1401', updated_by='t')
    make_account('7101'); AppSettings.set_setting('inventory_adjustment_account_code', '7101', updated_by='t')
    login_user(client, 'admin', 'admin123')
    client.post('/select-branch', data={'branch_id': branch_manila.id})
    lines = json.dumps([{'product_id': product_tracked.id, 'quantity_delta': '2', 'unit_cost': '1.00'}])
    resp = client.post('/stock-adjustments/create', data={
        'adjustment_date': '2026-07-21', 'reason_type': 'correction', 'lines': lines,
    }, follow_redirects=True)
    assert resp.status_code == 200
    adj = (StockAdjustment.query.filter_by(branch_id=branch_manila.id)
           .order_by(StockAdjustment.id.desc()).first())
    assert adj is not None
    logout_user(client)

    # accountant_user (conftest) is assigned only to main_branch -- not Manila.
    # Grant the stock_adjustments book permission explicitly so this test isolates
    # the branch-scoping check (app/__init__.py's enforce_module_access before_request
    # hook gates per-module access separately, and would otherwise also 404/redirect
    # for an unrelated reason -- accountant_user's default fixture permissions don't
    # include this module).
    perms = accountant_user.get_book_permissions()
    perms['stock_adjustments'] = True
    accountant_user.set_book_permissions(perms)
    db.session.commit()

    login_user(client, 'accountant', 'accountant123')
    view_resp = client.get(f'/stock-adjustments/{adj.id}')
    assert view_resp.status_code == 404
