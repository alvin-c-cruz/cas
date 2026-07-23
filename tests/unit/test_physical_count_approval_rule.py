import pytest
from datetime import date
from app import db
from app.stock_adjustments.models import PhysicalCount
from app.users.models import User


def _make_count(branch_id, created_by_user):
    """Create a saved PhysicalCount authored by created_by_user.

    NOTE: the task brief's draft _make_count(branch_id, created_by) accepted
    a username string but never assigned it to the row (PhysicalCount has no
    stored username column, only created_by_id/created_by relationship -- see
    app/stock_adjustments/models.py), so every count's created_by stayed None
    and the self-approval assertions below would pass for the wrong reason.
    Fixed here to actually persist authorship via created_by_id.
    """
    pc = PhysicalCount(pc_number=f'PC-TEST-{created_by_user.username}', branch_id=branch_id,
                       count_date=date(2026, 7, 23), status='draft',
                       created_by_id=created_by_user.id)
    db.session.add(pc)
    db.session.commit()
    return pc


@pytest.fixture
def second_accountant_user(db_session):
    """A second active accountant -- not a conftest.py fixture (checked; only
    a local `make_second_accountant` helper exists in
    tests/integration/test_sole_accountant_autoapprove.py), added here
    following the exact shape of conftest.py's accountant_user sibling
    fixture, minus branch assignment (not needed by can_be_approved_by,
    which never checks branch access)."""
    user = User(username='accountant2', email='accountant2@test.com',
                full_name='Second Accountant', role='accountant', is_active=True)
    user.set_password('accountant123')
    db.session.add(user)
    db.session.commit()
    return user


class TestCanBeApprovedBy:
    def test_admin_can_approve_own_count(self, db_session, branch_main, admin_user):
        pc = _make_count(branch_main.id, admin_user)
        assert pc.can_be_approved_by(admin_user.username) is True

    def test_chief_accountant_can_approve_own_count(self, db_session, branch_main, chief_accountant_user):
        pc = _make_count(branch_main.id, chief_accountant_user)
        assert pc.can_be_approved_by(chief_accountant_user.username) is True

    def test_accountant_cannot_approve_own_count_when_a_peer_exists(
            self, db_session, branch_main, accountant_user, second_accountant_user):
        pc = _make_count(branch_main.id, accountant_user)
        assert pc.can_be_approved_by(accountant_user.username) is False
        assert pc.can_be_approved_by(second_accountant_user.username) is True

    def test_sole_accountant_can_approve_own_count(self, db_session, branch_main, accountant_user):
        pc = _make_count(branch_main.id, accountant_user)
        assert pc.can_be_approved_by(accountant_user.username) is True
