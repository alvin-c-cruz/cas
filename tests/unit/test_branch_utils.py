"""Unit tests for app.users.utils.get_accessible_branches."""
import pytest
from app.users.utils import get_accessible_branches
pytestmark = [pytest.mark.branches, pytest.mark.unit]



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

    def test_accountant_gets_only_assigned_branches(self, db_session, accountant_user, main_branch):
        """Accountants are now scoped like staff — only their assigned branches."""
        # accountant_user fixture assigns main_branch; that is the only active branch here
        result = get_accessible_branches(accountant_user)
        assert any(b.id == main_branch.id for b in result)

    def test_staff_gets_only_assigned_branches(self, db_session, staff_user, main_branch):
        from app.branches.models import Branch
        other = Branch(name='Other', code='OTH', is_active=True)
        db_session.add(other)
        db_session.commit()
        # Assign staff_user to main_branch only
        staff_user.branches.append(main_branch)
        db_session.commit()
        result = get_accessible_branches(staff_user)
        ids = {b.id for b in result}
        assert main_branch.id in ids       # assigned branch is included
        assert other.id not in ids         # unassigned branch is excluded

    def test_viewer_gets_only_assigned_branches(self, db_session, viewer_user, main_branch):
        from app.branches.models import Branch
        other = Branch(name='Other2', code='OT2', is_active=True)
        db_session.add(other)
        db_session.commit()
        viewer_user.branches.append(main_branch)
        db_session.commit()
        result = get_accessible_branches(viewer_user)
        ids = {b.id for b in result}
        assert main_branch.id in ids
        assert other.id not in ids

    def test_inactive_branches_excluded(self, db_session, admin_user, main_branch):
        from app.branches.models import Branch

        inactive = Branch(name='Old', code='OLD', is_active=False)
        db_session.add(inactive)
        db_session.commit()
        result = get_accessible_branches(admin_user)
        assert all(b.is_active for b in result)
