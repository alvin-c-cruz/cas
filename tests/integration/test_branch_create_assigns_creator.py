"""Branch creation must assign the creating user to the new branch's user_branches
(BUG-BRANCH-CREATE-NO-CREATOR-ASSIGNMENT)."""
import pytest
from app.branches.models import Branch

pytestmark = [pytest.mark.branches, pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


class TestBranchCreateAssignsCreator:
    def test_create_assigns_creator_to_new_branch(self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.post('/branches/create', data={
            'code': 'CREATOR1', 'name': 'Creator Assignment Branch', 'is_active': 'y',
        }, follow_redirects=True)
        assert resp.status_code == 200

        branch = Branch.query.filter_by(code='CREATOR1').first()
        assert branch is not None
        assert admin_user in branch.users.all()

    def test_create_only_assigns_the_new_branch_not_others(self, client, db_session, admin_user, main_branch):
        # admin_user has no pre-existing assignment to main_branch (conftest doesn't
        # set one); creating a NEW branch must not retroactively touch main_branch's
        # own membership.
        login(client)
        client.post('/branches/create', data={
            'code': 'CREATOR2', 'name': 'Creator Assignment Branch Two', 'is_active': 'y',
        }, follow_redirects=True)

        assert branch_member_count(main_branch, admin_user) == 0


def branch_member_count(branch, user):
    return branch.users.filter_by(id=user.id).count()
