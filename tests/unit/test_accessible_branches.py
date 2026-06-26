"""Unit tests for accountant branch-scoping in get_accessible_branches.

Task 1: verify accountants are scoped to their assigned branches (not all branches).
"""
import pytest
from app.users.utils import get_accessible_branches

pytestmark = [pytest.mark.unit, pytest.mark.branches]


def test_accountant_limited_to_assigned(db_session, accountant_user, main_branch, branch_manila):
    """Accountant with one assigned branch sees only that branch, not branch_manila."""
    accountant_user.set_branches([main_branch])
    db_session.commit()

    result = get_accessible_branches(accountant_user)
    ids = {b.id for b in result}

    assert main_branch.id in ids, "assigned branch must be accessible"
    assert branch_manila.id not in ids, "unassigned branch must NOT be accessible"


def test_accountant_with_no_branches_gets_none(db_session, accountant_user, main_branch):
    """Accountant with no assigned branches gets an empty list."""
    # Ensure no branches assigned (default fixture has none)
    accountant_user.set_branches([])
    db_session.commit()

    result = get_accessible_branches(accountant_user)
    assert result == [], "unassigned accountant should get empty list"


def test_admin_still_all(db_session, admin_user, main_branch, branch_manila):
    """Admin still gets all active branches regardless of assignments."""
    result = get_accessible_branches(admin_user)
    ids = {b.id for b in result}

    assert main_branch.id in ids
    assert branch_manila.id in ids


def test_staff_unchanged(db_session, staff_user, main_branch, branch_manila):
    """Staff with one assigned branch sees only that branch — unchanged by this feature."""
    staff_user.set_branches([branch_manila])
    db_session.commit()

    result = get_accessible_branches(staff_user)
    ids = {b.id for b in result}

    assert branch_manila.id in ids
    assert main_branch.id not in ids
