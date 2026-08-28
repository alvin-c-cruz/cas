"""The admin-only Effective Access viewer.

BUG-NO-ADMIN-PATH-TO-VERIFY-ANOTHER-USERS-ACCESS, owner option 2 (2026-08-28).

Read-only by construction: GET only, no form, no session switching, and it never
touches the inspected user's credentials -- which is the whole reason this page
exists instead of impersonation.

TWO GATES STAND BETWEEN A NON-ADMIN AND THIS VIEW, and only the inner one is
under test here. `create_app`'s before_request redirects any user with no
selected/accessible branch to the branch picker BEFORE the view runs, so a
non-admin fixture without a branch would be turned away by the OUTER gate and
the test would pass without ever exercising `admin_panel_required`. Every
non-admin user below is therefore given a branch and a selected_branch_id --
see memory feedback-outer-gate-masks-inner-guard.
"""
import pytest

from app.settings import AppSettings
from app.users.models import User
from app.users.module_access import MODULE_REGISTRY, default_all_permissions
from app.utils.cache_helpers import clear_module_config_cache

pytestmark = [pytest.mark.integration, pytest.mark.auth]

URL = '/users/%d/effective-access'


@pytest.fixture(autouse=True)
def _module_cache(app):
    with app.app_context():
        clear_module_config_cache()
    yield
    with app.app_context():
        clear_module_config_cache()


def _login(client, user, branch=None):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        if branch is not None:
            sess['selected_branch_id'] = branch.id


def _user(db_session, username, role, branch=None, grants=None):
    u = User(username=username, email='%s@test.com' % username,
             full_name=username.title(), role=role, is_active=True)
    u.set_password('pw12345')
    u.set_book_permissions(grants if grants is not None else default_all_permissions())
    db_session.add(u)
    db_session.flush()
    if branch is not None:
        u.branches.append(branch)
    db_session.commit()
    return u


def _grantable_optional():
    for m in MODULE_REGISTRY:
        if m.get('optional') and m.get('per_user'):
            return m['key']
    return None


# -- who may open it -----------------------------------------------------------

class TestOnlyAnAdministratorMayOpenIt:
    """The page reports another user's access, so it belongs behind the Admin
    panel gate -- the same one that guards the user list and edit form. The
    Chief Accountant is deliberately excluded by `admin_panel_required`, and
    that exclusion is a decision, so it is pinned rather than assumed."""

    def test_an_admin_gets_the_page(self, client, db_session, admin_user, main_branch):
        target = _user(db_session, 'target', 'staff', branch=main_branch)
        _login(client, admin_user, main_branch)
        resp = client.get(URL % target.id)
        assert resp.status_code == 200
        assert b'Effective Access' in resp.data

    @pytest.mark.parametrize('role', ['chief_accountant', 'accountant', 'staff', 'viewer'])
    def test_every_other_role_is_turned_away(self, client, db_session, main_branch, role):
        """Asserts the OUTCOME, not merely 'not 200'. `admin_panel_required`
        redirects rather than 403s, so a status-only check would pass against a
        redirect to the page itself."""
        target = _user(db_session, 'target', 'staff', branch=main_branch)
        actor = _user(db_session, 'actor_%s' % role, role, branch=main_branch)
        _login(client, actor, main_branch)
        resp = client.get(URL % target.id)
        assert resp.status_code == 302
        assert '/users/%d/effective-access' % target.id not in resp.headers['Location']
        body = client.get(URL % target.id, follow_redirects=True).data
        assert b'Effective Access' not in body

    def test_an_anonymous_visitor_is_sent_to_login(self, client, db_session,
                                                   main_branch):
        target = _user(db_session, 'target', 'staff', branch=main_branch)
        resp = client.get(URL % target.id)
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']

    def test_an_unknown_user_is_a_404(self, client, admin_user, main_branch):
        _login(client, admin_user, main_branch)
        assert client.get(URL % 999999).status_code == 404


# -- what it says --------------------------------------------------------------

class TestWhatThePageReports:

    def test_it_names_the_user_being_inspected(self, client, db_session, admin_user,
                                               main_branch):
        """The page reports on somebody OTHER than the reader -- if it silently
        rendered the admin's own access it would answer confidently and wrongly.

        The name alone does NOT prove that: the heading renders from `target`
        while every row renders from the resolved result, so swapping only the
        result leaves the right name above the wrong data. Mutation V2 did
        exactly that and this assertion did not move. Hence the second one --
        the reader has full access, so "Full access by role" appearing while
        inspecting a STAFF user means the rows describe the reader.
        """
        target = _user(db_session, 'angilyn', 'staff', branch=main_branch)
        _login(client, admin_user, main_branch)
        resp = client.get(URL % target.id)
        assert b'angilyn' in resp.data
        assert b'Full access by role' not in resp.data, (
            'the rows describe the reader, not the inspected user')

    def test_it_lists_modules_with_a_reason(self, client, db_session, admin_user,
                                            main_branch):
        target = _user(db_session, 'target', 'staff', branch=main_branch,
                       grants=default_all_permissions())
        _login(client, admin_user, main_branch)
        resp = client.get(URL % target.id)
        assert b'Chart of Accounts' in resp.data
        assert b'Granted to this user' in resp.data

    def test_a_dead_grant_is_called_out(self, client, db_session, admin_user,
                                        main_branch):
        """The case no other surface shows: a grant the instance gate overrules.
        The permission grid renders it as held.

        Asserts the NOTICE and the row SEPARATELY. Both say "no effect", so a
        single assertion on that phrase is satisfied by the row alone -- the
        whole notices block could be deleted and this test would not move. It
        was, in mutation V5, and it did not.
        """
        key = _grantable_optional()
        assert key, 'no optional+per_user module in the registry'
        AppSettings.set_setting('module_enabled:%s' % key, '0')
        clear_module_config_cache()
        target = _user(db_session, 'target', 'staff', branch=main_branch,
                       grants={key: True})
        _login(client, admin_user, main_branch)
        resp = client.get(URL % target.id)
        assert b'Dead grant' in resp.data, 'the notices block did not report it'
        assert b'no effect' in resp.data, 'the module row did not explain it'

    def test_no_dead_grant_notice_when_there_is_none(self, client, db_session,
                                                     admin_user, main_branch):
        """CONTROL, paired with a positive assertion so it cannot pass by the
        page failing to render at all."""
        key = _grantable_optional()
        AppSettings.set_setting('module_enabled:%s' % key, '1')
        clear_module_config_cache()
        target = _user(db_session, 'target', 'staff', branch=main_branch,
                       grants={key: True})
        _login(client, admin_user, main_branch)
        resp = client.get(URL % target.id)
        assert resp.status_code == 200
        assert b'Granted to this user' in resp.data      # the page DID render
        assert b'Dead grant' not in resp.data
        assert b'no effect' not in resp.data


class TestTheBranchBanner:

    def test_a_branchless_user_gets_the_banner(self, client, db_session, admin_user,
                                               main_branch):
        target = _user(db_session, 'newhire', 'staff', branch=None)
        _login(client, admin_user, main_branch)
        resp = client.get(URL % target.id)
        assert b'cannot reach any page' in resp.data

    def test_a_branched_user_does_not(self, client, db_session, admin_user,
                                      main_branch):
        """CONTROL with a positive assertion -- an absence test alone would pass
        against a 500."""
        target = _user(db_session, 'target', 'staff', branch=main_branch)
        _login(client, admin_user, main_branch)
        resp = client.get(URL % target.id)
        assert resp.status_code == 200
        assert b'Effective Access' in resp.data
        assert b'cannot reach any page' not in resp.data


class TestItIsReachableFromTheEditForm:
    """A page nobody can find is not a fix. Owner approved the entry point on
    the user's own edit form, beside the permission grid it explains.

    A RENDER assertion on the GET, deliberately: a route test proves the page
    WORKS, never that it is REACHABLE -- which is exactly how
    delete_approved_email shipped backend-complete with no UI path."""

    def test_the_edit_form_links_to_it(self, client, db_session, admin_user,
                                       main_branch):
        target = _user(db_session, 'target', 'staff', branch=main_branch)
        _login(client, admin_user, main_branch)
        resp = client.get('/users/%d/edit' % target.id)
        assert resp.status_code == 200
        assert (b'/users/%d/effective-access' % target.id) in resp.data

    def test_the_user_list_links_to_it(self, client, db_session, admin_user,
                                       main_branch):
        target = _user(db_session, 'target', 'staff', branch=main_branch)
        _login(client, admin_user, main_branch)
        resp = client.get('/users')
        assert (b'/users/%d/effective-access' % target.id) in resp.data


class TestItIsReadOnly:

    def test_it_refuses_a_post(self, client, db_session, admin_user, main_branch):
        """The page must never grow a write path by accident: the whole reason
        it was chosen over impersonation is that it changes nothing."""
        target = _user(db_session, 'target', 'staff', branch=main_branch)
        _login(client, admin_user, main_branch)
        assert client.post(URL % target.id).status_code == 405
