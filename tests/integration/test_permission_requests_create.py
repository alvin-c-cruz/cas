import pytest
from app import db
from app.users.models import User
from app.permission_requests.models import PermissionChangeRequest

pytestmark = pytest.mark.integration


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


@pytest.fixture
def limited_accountant(db_session, main_branch):
    """A second accountant with a deliberately empty book_permissions grid, so
    a permission request against them has something meaningful to add."""
    user = User(
        username='limited_accountant', email='limited@test.com',
        full_name='Limited Accountant', role='accountant', is_active=True,
    )
    user.set_password('limited123')
    user.set_book_permissions({})
    db_session.add(user)
    db_session.flush()
    user.set_branches([main_branch])
    db_session.commit()
    return user


def test_ca_can_submit_valid_request(client, db_session, chief_accountant_user, limited_accountant, main_branch):
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.post('/permission-requests/new', data={
        'target_user_id': str(limited_accountant.id),
        'requested_keys': ['chart_of_accounts', 'accounts_payable'],
        'request_reason': 'Needs to bill vendors for the new Purchases area.',
    }, follow_redirects=False)
    assert resp.status_code == 302
    req = PermissionChangeRequest.query.filter_by(target_user_id=limited_accountant.id).first()
    assert req is not None
    assert req.status == 'pending'
    assert req.requested_by_id == chief_accountant_user.id
    assert req.get_requested_permissions() == {'chart_of_accounts': True, 'accounts_payable': True}


def test_staff_cannot_submit_request(client, db_session, staff_user, limited_accountant, main_branch):
    _login(client, staff_user)
    _select_branch(client, main_branch.id)
    resp = client.post('/permission-requests/new', data={
        'target_user_id': str(limited_accountant.id),
        'requested_keys': ['chart_of_accounts'],
        'request_reason': 'trying anyway',
    }, follow_redirects=False)
    assert resp.status_code == 302
    assert PermissionChangeRequest.query.filter_by(target_user_id=limited_accountant.id).first() is None


def test_duplicate_pending_request_blocked(client, db_session, chief_accountant_user, limited_accountant, main_branch):
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    data = {
        'target_user_id': str(limited_accountant.id),
        'requested_keys': ['chart_of_accounts'],
        'request_reason': 'first attempt',
    }
    client.post('/permission-requests/new', data=data, follow_redirects=False)
    resp2 = client.post('/permission-requests/new', data=data, follow_redirects=True)
    assert resp2.status_code == 200
    assert PermissionChangeRequest.query.filter_by(target_user_id=limited_accountant.id).count() == 1


def test_audit_log_entry_created_on_submit(client, db_session, chief_accountant_user, limited_accountant, main_branch):
    from app.audit.models import AuditLog
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    client.post('/permission-requests/new', data={
        'target_user_id': str(limited_accountant.id),
        'requested_keys': ['payments'],
        'request_reason': 'needs CDV access',
    }, follow_redirects=False)
    entry = AuditLog.query.filter_by(module='permission_change_request', action='create').first()
    assert entry is not None
    assert 'limited_accountant' in entry.record_identifier
