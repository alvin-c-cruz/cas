"""Cancel is blocked once any completion batch has posted (R-07 D4)."""
from decimal import Decimal
import pytest
from app import db
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache
from tests.work_orders.test_completion_batch import _ready_wo

pytestmark = [pytest.mark.integration, pytest.mark.work_orders]


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _enable(db_session):
    AppSettings.set_setting('module_enabled:work_orders', '1')
    AppSettings.set_setting('module_enabled:bill_of_materials', '1')
    db_session.commit(); clear_module_config_cache()


def test_cancel_view_blocked_once_qty_completed_to_date_is_positive(
        client, db_session, main_branch, accountant_user, wo_control_accounts):
    from app.work_orders.service import complete_work_order_batch
    _enable(db_session)
    _login(client, accountant_user, main_branch)
    wo = _ready_wo(main_branch, accountant_user, qty_to_produce='10')
    complete_work_order_batch(wo, Decimal('4'), accountant_user)
    db.session.commit()

    resp = client.post(f'/work-orders/{wo.id}/cancel',
                       data={'cancel_reason': 'Trying to cancel after completion.'},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert b'can no longer be cancelled' in resp.data
    db.session.refresh(wo)
    assert wo.status != 'cancelled'
