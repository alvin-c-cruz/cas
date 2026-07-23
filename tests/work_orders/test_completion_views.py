"""Complete / Force Close view routes (R-07 D4)."""
from decimal import Decimal
import pytest
from app import db
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache
from tests.work_orders.test_completion_batch import _ready_wo

pytestmark = [pytest.mark.integration]


def _login(client, user, branch_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch_id


def _enable(db_session):
    AppSettings.set_setting('module_enabled:work_orders', '1')
    AppSettings.set_setting('module_enabled:bill_of_materials', '1')
    db_session.commit(); clear_module_config_cache()


def test_complete_batch_route_posts_and_flashes_success(
        client, db_session, main_branch, accountant_user, wo_control_accounts):
    _enable(db_session)
    wo = _ready_wo(main_branch, accountant_user, qty_to_produce='10')
    _login(client, accountant_user, main_branch.id)
    resp = client.post(f'/work-orders/{wo.id}/complete', data={'batch_qty': '4'}, follow_redirects=True)
    assert resp.status_code == 200
    assert b'Completed' in resp.data
    db.session.refresh(wo)
    assert wo.qty_completed_to_date == Decimal('4')


def test_complete_batch_route_flashes_error_on_invalid_quantity(
        client, db_session, main_branch, accountant_user, wo_control_accounts):
    _enable(db_session)
    wo = _ready_wo(main_branch, accountant_user, qty_to_produce='10')
    _login(client, accountant_user, main_branch.id)
    resp = client.post(f'/work-orders/{wo.id}/complete', data={'batch_qty': 'not-a-number'},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert b'valid batch quantity' in resp.data


def test_force_close_route_posts_and_flashes_warning(
        client, db_session, main_branch, accountant_user, wo_control_accounts):
    from app.work_orders.service import complete_work_order_batch
    _enable(db_session)
    wo = _ready_wo(main_branch, accountant_user, qty_to_produce='10')
    complete_work_order_batch(wo, Decimal('4'), accountant_user)
    db.session.commit()
    _login(client, accountant_user, main_branch.id)
    resp = client.post(f'/work-orders/{wo.id}/force-close',
                       data={'force_close_note': 'Scrapped the remaining units.'},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert b'force-closed' in resp.data
    db.session.refresh(wo)
    assert wo.status == 'completed'
    assert wo.force_close_note == 'Scrapped the remaining units.'
