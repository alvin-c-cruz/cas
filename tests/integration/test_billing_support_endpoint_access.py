"""GET /purchase-orders/billable and /receiving-reports/billable must stay reachable for a
staff user scoped ONLY to accounts_payable -- BUG-AP-BILLING-BLOCKED-BY-SINGLE-MODULE-PERMISSIONS.
These two JSON endpoints exist solely to feed AP's own billing picker."""
import pytest

from app.users.models import User

pytestmark = [pytest.mark.integration, pytest.mark.accounts_payable]


@pytest.fixture(autouse=True)
def _modules_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'receiving_reports'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _make_user(db_session, branch, username, permissions):
    user = User(username=username, email=f'{username}@test.com',
               full_name=username.title(), role='staff', is_active=True)
    user.set_password('testpass123')
    user.set_book_permissions(permissions)
    db_session.add(user)
    db_session.flush()
    user.set_branches([branch])
    db_session.commit()
    return user


def test_staff_scoped_only_to_ap_can_reach_po_billable(client, db_session, main_branch):
    staff_ap = _make_user(db_session, main_branch, 'staff_ap_only', {'accounts_payable': True})
    _login(client, staff_ap, main_branch)
    resp = client.get('/purchase-orders/billable?vendor_id=1')
    assert resp.status_code == 200
    assert resp.is_json
    assert 'pos' in resp.get_json()


def test_staff_scoped_only_to_ap_can_reach_rr_billable(client, db_session, main_branch):
    staff_ap = _make_user(db_session, main_branch, 'staff_ap_only2', {'accounts_payable': True})
    _login(client, staff_ap, main_branch)
    resp = client.get('/receiving-reports/billable?vendor_id=1')
    assert resp.status_code == 200
    assert resp.is_json
    assert 'rrs' in resp.get_json()


def test_staff_with_neither_ap_nor_po_access_still_denied(client, db_session, main_branch):
    staff_none = _make_user(db_session, main_branch, 'staff_no_access', {'vendors': True})
    _login(client, staff_none, main_branch)
    resp = client.get('/purchase-orders/billable?vendor_id=1', follow_redirects=True)
    assert resp.status_code == 200  # landed on dashboard after the redirect chain
    assert b'You do not have access to this module.' in resp.data


def test_staff_with_direct_po_access_still_works(client, db_session, main_branch):
    """Confirms the fix is additive: existing PO/RR-scoped access still passes too."""
    staff_po = _make_user(db_session, main_branch, 'staff_po_direct', {'purchase_orders': True})
    _login(client, staff_po, main_branch)
    resp = client.get('/purchase-orders/billable?vendor_id=1')
    assert resp.status_code == 200
    assert resp.is_json
