"""Unit tests for Feature B — ApprovedEmail role + branch delegation (model layer)."""
import pytest
from app.users.approved_emails import ApprovedEmail

pytestmark = [pytest.mark.unit]


def test_approved_email_has_role_column(db_session):
    """ApprovedEmail accepts a role and round-trips it."""
    ae = ApprovedEmail(email='delegate@example.ph', status='approved', role='staff')
    db_session.add(ae)
    db_session.commit()

    fetched = ApprovedEmail.query.filter_by(email='delegate@example.ph').first()
    assert fetched.role == 'staff'


def test_role_defaults_to_none_for_legacy_rows(db_session):
    """A row created without a role reads as None (legacy → old register behavior)."""
    ae = ApprovedEmail(email='legacy@example.ph', status='approved')
    db_session.add(ae)
    db_session.commit()

    fetched = ApprovedEmail.query.filter_by(email='legacy@example.ph').first()
    assert fetched.role is None


def test_branches_relationship_assign_and_read(db_session, main_branch, branch_manila):
    """branches m2m assigns and reads back the assigned branches."""
    ae = ApprovedEmail(email='branched@example.ph', status='approved', role='viewer')
    ae.branches = [main_branch, branch_manila]
    db_session.add(ae)
    db_session.commit()

    fetched = ApprovedEmail.query.filter_by(email='branched@example.ph').first()
    ids = sorted(b.id for b in fetched.branches)
    assert ids == sorted([main_branch.id, branch_manila.id])


def test_branch_ids_helper(db_session, main_branch):
    """get_branch_ids() returns the list of assigned branch ids."""
    ae = ApprovedEmail(email='helper@example.ph', status='approved', role='staff')
    ae.branches = [main_branch]
    db_session.add(ae)
    db_session.commit()

    assert ae.get_branch_ids() == [main_branch.id]
