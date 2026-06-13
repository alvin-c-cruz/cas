"""Unit tests for app.users.utils.get_accessible_branches."""
import pytest
from app.users.utils import get_accessible_branches


class TestGetAccessibleBranches:
    def test_admin_gets_all_active_branches(self, db_session, admin_user, main_branch):
        from app.branches.models import Branch
        extra = Branch(name='Extra', code='EXT', is_active=True)
        db_session.add(extra)
        db_session.commit()
        result = get_accessible_branches(admin_user)
        ids = {b.id for b in result}
        assert main_branch.id in ids
        assert extra.id in ids

    def test_accountant_gets_all_active_branches(self, db_session, accountant_user, main_branch):
        result = get_accessible_branches(accountant_user)
        assert any(b.id == main_branch.id for b in result)

    def test_staff_gets_only_assigned_branches(self, db_session, staff_user, main_branch):
        from app.branches.models import Branch
        other = Branch(name='Other', code='OTH', is_active=True)
        db_session.add(other)
        db_session.commit()
        # staff_user is not assigned to any branch yet
        result = get_accessible_branches(staff_user)
        assert all(b.id != other.id for b in result)

    def test_inactive_branches_excluded(self, db_session, admin_user, main_branch):
        from app.branches.models import Branch
        inactive = Branch(name='Old', code='OLD', is_active=False)
        db_session.add(inactive)
        db_session.commit()
        result = get_accessible_branches(admin_user)
        assert all(b.is_active for b in result)
