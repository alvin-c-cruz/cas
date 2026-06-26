"""Unit tests for ApprovedEmail status lifecycle.

Covers the status field (pending/approved/rejected), the registration gate
(is_email_approved must only return True for status='approved'), and the
approve/reject helper methods.
"""
import pytest

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ae(db_session, email, status='approved', approved_by_id=None, requested_by_id=None, notes=None):
    """Insert an ApprovedEmail row directly, bypassing the form."""
    from app.users.approved_emails import ApprovedEmail
    ae = ApprovedEmail(
        email=email,
        status=status,
        approved_by_user_id=approved_by_id,
        requested_by_user_id=requested_by_id,
        notes=notes,
    )
    db_session.add(ae)
    db_session.commit()
    return ae


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_default_status_approved(db_session, admin_user):
    """A row created by an admin (approved_by set, no status kwarg) defaults to 'approved'."""
    from app.users.approved_emails import ApprovedEmail

    ae = ApprovedEmail(
        email='a@x.ph',
        approved_by_user_id=admin_user.id,
    )
    db_session.add(ae)
    db_session.commit()

    assert ae.status == 'approved'


def test_pending_is_not_registerable(db_session, admin_user):
    """A pending row is NOT registerable via is_email_approved, but get_approved_email still finds it."""
    _make_ae(db_session, 'pending@x.ph', status='pending', requested_by_id=admin_user.id)

    from app.users.approved_emails import ApprovedEmail
    assert ApprovedEmail.is_email_approved('pending@x.ph') is False
    # get_approved_email is status-agnostic (used for lookup, not for gating)
    assert ApprovedEmail.get_approved_email('pending@x.ph') is not None


def test_rejected_is_not_registerable(db_session, admin_user):
    """A rejected row cannot register."""
    _make_ae(db_session, 'rejected@x.ph', status='rejected', approved_by_id=admin_user.id)

    from app.users.approved_emails import ApprovedEmail
    assert ApprovedEmail.is_email_approved('rejected@x.ph') is False


def test_approved_unused_is_registerable(db_session, admin_user):
    """An approved, unused row allows registration."""
    _make_ae(db_session, 'ok@x.ph', status='approved', approved_by_id=admin_user.id)

    from app.users.approved_emails import ApprovedEmail
    assert ApprovedEmail.is_email_approved('ok@x.ph') is True


def test_approve_sets_fields(db_session, admin_user, accountant_user):
    """approve(reviewer_id) sets status='approved', approved_by_user_id, and reviewed_at."""
    ae = _make_ae(db_session, 'toapprove@x.ph', status='pending', requested_by_id=accountant_user.id)

    ae.approve(admin_user.id)

    assert ae.status == 'approved'
    assert ae.approved_by_user_id == admin_user.id
    assert ae.reviewed_at is not None


def test_reject_appends_reason(db_session, admin_user, accountant_user):
    """reject(reviewer_id, reason) sets status='rejected' and appends reason to notes."""
    ae = _make_ae(db_session, 'toreject@x.ph', status='pending', requested_by_id=accountant_user.id)

    ae.reject(admin_user.id, 'dupe')

    assert ae.status == 'rejected'
    assert ae.approved_by_user_id == admin_user.id
    assert ae.reviewed_at is not None
    assert 'dupe' in (ae.notes or '')
