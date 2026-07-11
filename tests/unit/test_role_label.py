"""Unit tests for the role_label humanizer (BUG-USERLIST-CA-ROLE-BADGE).

Single source of truth for role display labels, replacing the if/elif blocks
duplicated across the user/branch/staff templates.
"""
import pytest

from app.users.utils import role_label

pytestmark = [pytest.mark.unit, pytest.mark.users]


def test_role_label_known_roles():
    assert role_label('admin') == 'Administrator'
    assert role_label('chief_accountant') == 'Chief Accountant'
    assert role_label('accountant') == 'Accountant'
    assert role_label('staff') == 'Staff'
    assert role_label('viewer') == 'Viewer'


def test_role_label_unknown_falls_back_to_titleized():
    assert role_label('some_new_role') == 'Some New Role'


def test_role_label_empty_is_safe():
    assert role_label('') == ''
    assert role_label(None) == ''
