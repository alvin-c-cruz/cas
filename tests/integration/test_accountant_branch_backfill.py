"""Integration tests for backfill_accountant_branches() helper (Task 2).

Verifies the idempotent INSERT…SELECT that seeds existing accountants with all
active branches when they have zero branch assignments.
"""
import pytest
from app.users.models import User
from app.users.utils import backfill_accountant_branches

pytestmark = [pytest.mark.integration, pytest.mark.branches]


def test_backfill_assigns_all_active_branches_to_unassigned_accountant(
    db_session, main_branch, branch_manila
):
    """An accountant with 0 branches is backfilled with all active branches."""
    acct = User(username='acct_bf', email='acct_bf@test.com',
                full_name='Backfill Accountant', role='accountant', is_active=True)
    acct.set_password('pass')
    db_session.add(acct)
    db_session.commit()

    assert acct.get_branch_ids() == [], "should start with no branches"

    rows = backfill_accountant_branches()

    assert rows == 2, f"expected 2 inserts (one per active branch), got {rows}"
    branch_ids = acct.get_branch_ids()
    assert main_branch.id in branch_ids
    assert branch_manila.id in branch_ids


def test_backfill_is_idempotent_for_already_assigned_accountant(
    db_session, main_branch, branch_manila
):
    """An accountant already assigned to ≥1 branch is not touched by the backfill."""
    acct = User(username='acct_bf2', email='acct_bf2@test.com',
                full_name='Backfill Accountant 2', role='accountant', is_active=True)
    acct.set_password('pass')
    db_session.add(acct)
    db_session.flush()
    acct.branches.append(main_branch)
    db_session.commit()

    assert main_branch.id in acct.get_branch_ids()

    rows = backfill_accountant_branches()

    assert rows == 0, f"already-assigned accountant should add 0 rows, got {rows}"
    assert main_branch.id in acct.get_branch_ids(), "existing assignment must be preserved"
