import pytest
from app.users.models import User

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize('role,is_admin,full', [
    ('admin', True, True),
    ('chief_accountant', False, True),
    ('accountant', False, False),
    ('staff', False, False),
    ('viewer', False, False),
])
def test_role_predicates(role, is_admin, full):
    u = User(username='u', email='u@t.com', full_name='U', role=role, is_active=True)
    assert u.is_admin is is_admin
    assert u.has_full_access is full
