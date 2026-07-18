"""Module gating (R-04 slice 3)."""
import pytest
from app.utils.cache_helpers import clear_module_config_cache

pytestmark = [pytest.mark.integration]


def test_routes_404_when_module_off(client, admin_user, db_session, main_branch):
    # get_module_override() is memoized for 1h -- clear it so this test proves the
    # OFF state regardless of what an earlier test in this run already enabled
    # (mirrors bank_transfers/petty_cash's identical guard).
    clear_module_config_cache()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = main_branch.id
    resp = client.get('/bank-reconciliation/1/register')
    assert resp.status_code == 404
