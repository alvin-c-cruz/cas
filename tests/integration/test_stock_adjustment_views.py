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


def test_form_get_renders_row_version_hidden_field(client, admin_user, login_user, branch_main):
    _enable_module()
    login_user(client, 'admin', 'admin123')
    client.post('/select-branch', data={'branch_id': branch_main.id})
    resp = client.get('/stock-adjustments/create')
    assert resp.status_code == 200
    assert b'name="row_version"' in resp.data   # csrf-only-render-drops-hidden-fields guard
    assert b'name="lines"' in resp.data
