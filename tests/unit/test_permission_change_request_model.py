import pytest
from app.permission_requests.models import PermissionChangeRequest


pytestmark = pytest.mark.unit


def test_get_requested_permissions_empty_when_unset(db_session):
    req = PermissionChangeRequest(
        target_user_id=1, requested_by_id=2,
        requested_permissions=None, request_reason='need it', status='pending',
    )
    assert req.get_requested_permissions() == {}


def test_set_and_get_requested_permissions_round_trip(db_session):
    req = PermissionChangeRequest(
        target_user_id=1, requested_by_id=2, request_reason='need it', status='pending',
    )
    req.set_requested_permissions({'chart_of_accounts': True, 'accounts_payable': True})
    assert req.get_requested_permissions() == {'chart_of_accounts': True, 'accounts_payable': True}


def test_default_status_is_pending(db_session, accountant_user, chief_accountant_user):
    req = PermissionChangeRequest(
        target_user_id=accountant_user.id,
        requested_by_id=chief_accountant_user.id,
        request_reason='need it',
    )
    req.set_requested_permissions({'payments': True})
    db_session.add(req)
    db_session.commit()
    assert req.status == 'pending'
    assert req.reviewed_by_id is None
    assert req.reviewed_at is None
