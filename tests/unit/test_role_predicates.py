import pytest
from app.users.models import User

pytestmark = [pytest.mark.unit]


#: ONE table for every role predicate on User, so a new predicate is answered
#: for EVERY role in the same place rather than growing a parallel table that
#: quietly covers a different set of roles.
#:
#: can_edit_print_layout (2026-08-26, owner decision): who may reposition fields
#: on the pre-printed overlay. Widened from has_full_access to each module's
#: EDIT-level role set -- adding `staff` but not `accountant` would have left
#: accountants unable to do something staff can, which is backwards everywhere
#: else in the app.
@pytest.mark.parametrize('role,is_admin,full,layout', [
    ('admin',            True,  True,  True),
    ('chief_accountant',  False, True,  True),
    ('accountant',        False, False, True),
    ('staff',             False, False, True),
    ('viewer',            False, False, False),
])
def test_role_predicates(role, is_admin, full, layout):
    u = User(username='u', email='u@t.com', full_name='U', role=role, is_active=True)
    assert u.is_admin is is_admin
    assert u.has_full_access is full
    assert u.can_edit_print_layout is layout


def test_an_unknown_role_cannot_edit_the_layout():
    """FAIL CLOSED. The predicate is a whitelist, not `role != 'viewer'`.

    A future role -- or a corrupted/blank value -- must not inherit the ability
    to change what prints on a client's real, BIR-registered stationery just by
    not being the one role that was named as excluded.
    """
    u = User(username='u', email='u@t.com', full_name='U', role='auditor_intern',
             is_active=True)
    assert u.can_edit_print_layout is False


def test_a_roleless_user_cannot_edit_the_layout():
    u = User(username='u', email='u@t.com', full_name='U', is_active=True)
    u.role = None
    assert u.can_edit_print_layout is False


def test_layout_editing_is_strictly_wider_than_full_access():
    """The change only ever ADDS. Nobody who could edit a layout before loses it.

    Pins the direction of the widening: if someone later narrows the predicate,
    or redefines it as something that is not a superset of has_full_access, this
    fails rather than silently revoking access from admins or chief accountants.
    """
    for role in ('admin', 'chief_accountant', 'accountant', 'staff', 'viewer'):
        u = User(username='u', email='u@t.com', full_name='U', role=role,
                 is_active=True)
        if u.has_full_access:
            assert u.can_edit_print_layout is True, role
