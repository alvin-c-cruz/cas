import pytest
from app.users.models import User
from app.users.module_access import can_access_module

pytestmark = [pytest.mark.unit]


def _user(role, perms=None):
    u = User(username=f'{role}_g', email=f'{role}_g@t.com', full_name='G', role=role, is_active=True)
    u.set_password('x')
    if perms is not None:
        u.set_book_permissions(perms)
    return u


def test_admin_ungated(db_session):
    assert can_access_module(_user('admin'), 'accounts_payable') is True


def test_accountant_now_gated(db_session):
    assert can_access_module(_user('accountant', {}), 'accounts_payable') is False
    assert can_access_module(_user('accountant', {'accounts_payable': True}), 'accounts_payable') is True


def test_viewer_now_gated(db_session):
    assert can_access_module(_user('viewer', {}), 'general_ledger') is False
    assert can_access_module(_user('viewer', {'general_ledger': True}), 'general_ledger') is True


def test_staff_still_gated(db_session):
    assert can_access_module(_user('staff', {}), 'payments') is False
    assert can_access_module(_user('staff', {'payments': True}), 'payments') is True
