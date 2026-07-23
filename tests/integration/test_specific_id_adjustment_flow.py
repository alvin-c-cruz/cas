"""Real-UI integration flow for the Stock Adjustment form's Lot column
(R-03 slice 2d, Task 6) -- a specific-identification receipt line carrying a
free-text lot_reference, an issue line requiring a picked lot_id, and the
full draft->approve round trip posting at the picked lot's own cost.

Setup mirrors tests/integration/test_stock_adjustment_views.py (module must
be enabled + inventory/adjustment control accounts configured for approve()
to post a balanced JE) -- the brief's own draft test used a bare
session_transaction() login that 404's before the module-enable/account
setup below is applied; corrected here to match the real app's requirements,
the same class of correction every prior sub-slice's implementers have made.
"""
import json
from decimal import Decimal

import pytest

from app import db
from app.settings import AppSettings

D = Decimal

pytestmark = pytest.mark.integration


def _enable_module():
    AppSettings.set_setting('module_enabled:inventory', '1', updated_by='test')
    AppSettings.set_setting('module_enabled:stock_adjustments', '1', updated_by='test')
    from app.utils.cache_helpers import clear_module_config_cache
    clear_module_config_cache()


def _setup(client, branch_main, login_user, make_account):
    _enable_module()
    make_account('1401')
    AppSettings.set_setting('inventory_account_code', '1401', updated_by='test')
    make_account('7101')
    AppSettings.set_setting('inventory_adjustment_account_code', '7101', updated_by='test')
    make_account('3101')
    AppSettings.set_setting('inventory_opening_equity_account_code', '3101', updated_by='test')
    login_user(client, 'admin', 'admin123')
    client.post('/select-branch', data={'branch_id': branch_main.id})


def test_create_receipt_line_with_lot_reference(client, db_session, admin_user, branch_main,
                                                 product_specific_id, login_user, make_account):
    _setup(client, branch_main, login_user, make_account)
    lines = [{'product_id': product_specific_id.id, 'quantity_delta': '10',
             'unit_cost': '5.00', 'lot_reference': 'Job Order #123'}]
    resp = client.post('/stock-adjustments/create', data={
        'adjustment_date': '2026-01-01', 'reason_type': 'opening', 'notes': 'test',
        'lines': json.dumps(lines), 'csrf_token': ''}, follow_redirects=True)
    assert resp.status_code == 200
    from app.stock_adjustments.models import StockAdjustment
    adj = StockAdjustment.query.order_by(StockAdjustment.id.desc()).first()
    assert adj is not None
    assert adj.lines[0].lot_reference == 'Job Order #123'
    assert adj.lines[0].lot_id is None


def test_create_issue_line_requires_a_lot_id(client, db_session, admin_user, branch_main,
                                              product_specific_id, login_user, make_account):
    _setup(client, branch_main, login_user, make_account)
    lines = [{'product_id': product_specific_id.id, 'quantity_delta': '-2'}]   # no lot_id
    resp = client.post('/stock-adjustments/create', data={
        'adjustment_date': '2026-01-01', 'reason_type': 'correction', 'notes': 'test',
        'lines': json.dumps(lines), 'csrf_token': ''}, follow_redirects=True)
    assert resp.status_code == 200
    assert b'requires a lot to be selected' in resp.data
    from app.stock_adjustments.models import StockAdjustment
    assert StockAdjustment.query.count() == 0   # nothing saved


def test_full_approve_flow_posts_at_picked_lots_cost(client, db_session, admin_user, branch_main,
                                                      product_specific_id, login_user, make_account):
    from app.stock_adjustments.models import StockLot
    _setup(client, branch_main, login_user, make_account)
    # first: an opening receipt naming a lot
    lines = [{'product_id': product_specific_id.id, 'quantity_delta': '10',
             'unit_cost': '5.00', 'lot_reference': 'Batch X'}]
    client.post('/stock-adjustments/create', data={
        'adjustment_date': '2026-01-01', 'reason_type': 'opening', 'notes': 'opening',
        'lines': json.dumps(lines), 'csrf_token': ''}, follow_redirects=True)
    from app.stock_adjustments.models import StockAdjustment
    adj1 = StockAdjustment.query.order_by(StockAdjustment.id.desc()).first()
    resp = client.post(f'/stock-adjustments/{adj1.id}/approve', data={}, follow_redirects=True)
    assert b'approved and posted' in resp.data
    lot = StockLot.query.filter_by(lot_reference='Batch X').first()
    assert lot is not None

    # then: an issue against that specific lot
    lines2 = [{'product_id': product_specific_id.id, 'quantity_delta': '-4', 'lot_id': lot.id}]
    client.post('/stock-adjustments/create', data={
        'adjustment_date': '2026-02-01', 'reason_type': 'correction', 'notes': 'issue',
        'lines': json.dumps(lines2), 'csrf_token': ''}, follow_redirects=True)
    adj2 = StockAdjustment.query.order_by(StockAdjustment.id.desc()).first()
    resp = client.post(f'/stock-adjustments/{adj2.id}/approve', data={}, follow_redirects=True)
    assert b'approved and posted' in resp.data
    db.session.refresh(lot)
    assert lot.remaining_qty == D('6.0000')
