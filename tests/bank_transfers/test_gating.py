"""Module gating (R-04 slice 2)."""
import pytest
from app.utils.cache_helpers import clear_module_config_cache

pytestmark = [pytest.mark.integration]


def test_routes_404_when_module_off(client, admin_user, db_session, main_branch):
    # get_module_override() is memoized for 1h and only invalidated by an explicit
    # clear -- if another test in this process already enabled bank_transfers and
    # left the cache warm, this assertion would false-pass depending on file/run
    # order. Clear it here so this test proves the OFF state regardless of order.
    clear_module_config_cache()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = main_branch.id
    resp = client.get('/bank-transfers/')
    assert resp.status_code == 404
