"""What a user can actually reach, and why -- the resolver behind the admin viewer.

BUG-NO-ADMIN-PATH-TO-VERIFY-ANOTHER-USERS-ACCESS, owner option 2 (2026-08-28).

THE DESIGN RULE THIS FILE EXISTS TO PIN: the resolver NEVER reimplements the
gate. `can_access_module` decides the verdict; the resolver only explains it.
A second copy of the rule would drift from the first, and a viewer that
confidently explains a rule the app no longer follows is worse than no viewer
at all -- it converts "I cannot verify this" into "I verified it wrongly".

`test_every_row_agrees_with_can_access_module` is that guard, and it has its own
guard: an all-True or all-False fixture would satisfy it vacuously.

ONE THING IS DELIBERATELY *NOT* `can_access_module`: the branch prerequisite. A
non-full-access user with no accessible branch is redirected to the branch
picker by create_app's before_request on EVERY request, before any module gate
is consulted -- so their grants are irrelevant. `can_access_module` knows
nothing about that, which is exactly why reading it alone (or reading
book_permissions in the database) answers the admin's question wrongly.
"""
import pytest

from app.settings import AppSettings
from app.users.effective_access import REASON_VERDICT, effective_access
from app.users.module_access import (MODULE_REGISTRY, can_access_module,
                                     default_all_permissions)
from app.utils.cache_helpers import clear_module_config_cache

pytestmark = [pytest.mark.unit, pytest.mark.auth]


@pytest.fixture(autouse=True)
def _module_cache(app):
    """get_module_override is memoized on an APP-level cache that is NOT reset
    between tests, so a sibling test's toggle leaks in and out of this one.
    Cleared on both sides -- see optional-module-gating-traps, trap 2.

    Pushes its own context rather than relying on the test's: flask_caching
    reaches for `current_app`, and a test that takes no db fixture (the registry
    shape guard below) has none."""
    with app.app_context():
        clear_module_config_cache()
    yield
    with app.app_context():
        clear_module_config_cache()


def _enable(key, on=True):
    AppSettings.set_setting('module_enabled:%s' % key, '1' if on else '0')
    clear_module_config_cache()


def _pick(optional, per_user):
    """A real registry key of the given shape, so the tests follow the registry
    instead of hard-coding a key that may be re-flagged later."""
    for m in MODULE_REGISTRY:
        if bool(m.get('optional')) is optional and bool(m.get('per_user')) is per_user:
            return m['key']
    return None


GRANTABLE_OPTIONAL = _pick(optional=True, per_user=True)     # e.g. purchase_orders
BARE_OPTIONAL = _pick(optional=True, per_user=False)         # e.g. product_categories
CORE = _pick(optional=False, per_user=False)                 # e.g. chart_of_accounts


def test_the_registry_still_has_all_three_shapes():
    """GUARD ON THE FIXTURES. Every test below is parameterised on these three
    shapes; if the registry stopped containing one, its tests would silently
    skip the case rather than fail."""
    assert GRANTABLE_OPTIONAL, 'no optional+per_user module in the registry'
    assert BARE_OPTIONAL, 'no bare-optional module in the registry'
    assert CORE, 'no core module in the registry'


def _staff(db_session, main_branch, grants=None, branches=True):
    from app.users.models import User
    u = User(username='ea_staff', email='ea_staff@test.com', full_name='EA Staff',
             role='staff', is_active=True)
    u.set_password('x')
    u.set_book_permissions(grants if grants is not None else {})
    db_session.add(u)
    db_session.flush()
    if branches:
        u.branches.append(main_branch)
    db_session.commit()
    return u


# -- the anti-drift guard ------------------------------------------------------

class TestTheVerdictIsNeverReimplemented:

    def test_every_row_agrees_with_can_access_module(self, db_session, main_branch):
        """THE GUARD. Change the gate and this fails, rather than the page
        quietly explaining a rule the app stopped following."""
        _enable(GRANTABLE_OPTIONAL, True)
        _enable(BARE_OPTIONAL, True)
        user = _staff(db_session, main_branch,
                      grants={**default_all_permissions(), GRANTABLE_OPTIONAL: True})
        rows = effective_access(user)['rows']
        mismatched = [r.key for r in rows
                      if r.effective != can_access_module(user, r.key)]
        assert not mismatched, (
            'These rows disagree with can_access_module: %s. The resolver must '
            'DELEGATE the verdict and only explain it -- a second copy of the '
            'rule is how the viewer starts lying.' % mismatched)

    def test_that_guard_is_not_vacuous(self, db_session, main_branch):
        """An all-True or all-False fixture would satisfy the test above without
        exercising a single interesting branch."""
        _enable(GRANTABLE_OPTIONAL, True)
        user = _staff(db_session, main_branch,
                      grants={**default_all_permissions(), GRANTABLE_OPTIONAL: True})
        verdicts = {r.effective for r in effective_access(user)['rows']}
        assert verdicts == {True, False}, (
            'The fixture produced only %s verdicts, so the agreement test above '
            'proves nothing.' % verdicts)


class TestReasonsAndVerdictsAgree:

    def test_every_reason_code_is_declared(self, db_session, main_branch):
        user = _staff(db_session, main_branch, grants=default_all_permissions())
        unknown = {r.reason_code for r in effective_access(user)['rows']
                   } - set(REASON_VERDICT)
        assert not unknown, 'undeclared reason codes: %s' % sorted(unknown)

    def test_the_reason_always_implies_the_verdict(self, db_session, main_branch):
        """A row that says "granted" while denying access, or "not granted"
        while allowing it, is worse than a blank cell."""
        _enable(BARE_OPTIONAL, True)
        user = _staff(db_session, main_branch, grants=default_all_permissions())
        for r in effective_access(user)['rows']:
            assert r.effective is REASON_VERDICT[r.reason_code], (
                '%s: reason %r implies %s but the verdict is %s'
                % (r.key, r.reason_code, REASON_VERDICT[r.reason_code], r.effective))

    def test_every_row_carries_a_human_reason(self, db_session, main_branch):
        user = _staff(db_session, main_branch, grants=default_all_permissions())
        blank = [r.key for r in effective_access(user)['rows'] if not (r.reason or '').strip()]
        assert not blank, 'rows with no explanation: %s' % blank


# -- role ---------------------------------------------------------------------

class TestFullAccessRoles:

    @pytest.mark.parametrize('fixture', ['admin_user', 'chief_accountant_user'])
    def test_reach_every_enabled_module_by_role(self, request, fixture, db_session,
                                                main_branch):
        _enable(GRANTABLE_OPTIONAL, True)
        user = request.getfixturevalue(fixture)
        rows = [r for r in effective_access(user)['rows'] if r.instance_enabled]
        assert rows
        assert all(r.effective for r in rows)
        assert {r.reason_code for r in rows} == {'full_access'}

    def test_a_disabled_module_still_refuses_an_admin(self, admin_user, db_session,
                                                      main_branch):
        """CONTROL. The instance package gate is checked BEFORE the role bypass,
        so 'admin sees everything' must not become 'admin sees everything'."""
        _enable(GRANTABLE_OPTIONAL, False)
        row = _row(effective_access(admin_user), GRANTABLE_OPTIONAL)
        assert row.effective is False
        assert row.reason_code == 'instance_off'


def _row(result, key):
    return next(r for r in result['rows'] if r.key == key)


class TestPerUserGrants:

    def test_granted_and_enabled_is_reachable(self, db_session, main_branch):
        _enable(GRANTABLE_OPTIONAL, True)
        user = _staff(db_session, main_branch, grants={GRANTABLE_OPTIONAL: True})
        row = _row(effective_access(user), GRANTABLE_OPTIONAL)
        assert row.effective is True
        assert row.reason_code == 'granted'

    def test_ungranted_and_enabled_is_not_reachable(self, db_session, main_branch):
        _enable(GRANTABLE_OPTIONAL, True)
        user = _staff(db_session, main_branch, grants={})
        row = _row(effective_access(user), GRANTABLE_OPTIONAL)
        assert row.effective is False
        assert row.reason_code == 'not_granted'


# -- the two cases no existing surface shows -----------------------------------

class TestTheDeadGrant:
    """A grant on a module that is switched off company-wide. The permission
    grid renders it as held; it does nothing. Found live on PhilGen."""

    def test_the_grant_is_overruled_by_the_instance_gate(self, db_session, main_branch):
        _enable(GRANTABLE_OPTIONAL, False)
        user = _staff(db_session, main_branch, grants={GRANTABLE_OPTIONAL: True})
        row = _row(effective_access(user), GRANTABLE_OPTIONAL)
        assert row.granted is True
        assert row.effective is False
        assert row.reason_code == 'instance_off'

    def test_it_is_reported_as_a_notice(self, db_session, main_branch):
        _enable(GRANTABLE_OPTIONAL, False)
        user = _staff(db_session, main_branch, grants={GRANTABLE_OPTIONAL: True})
        dead = [r.key for r in effective_access(user)['notices']['dead_grants']]
        assert GRANTABLE_OPTIONAL in dead

    def test_a_live_grant_is_not_reported_as_dead(self, db_session, main_branch):
        """CONTROL. The notice must mean something -- if every grant landed in
        it, an admin would learn nothing from reading it."""
        _enable(GRANTABLE_OPTIONAL, True)
        user = _staff(db_session, main_branch, grants={GRANTABLE_OPTIONAL: True})
        dead = [r.key for r in effective_access(user)['notices']['dead_grants']]
        assert GRANTABLE_OPTIONAL not in dead


class TestTheUngrantableModule:
    """An `optional` module NOT flagged `per_user` is excluded from
    all_permission_keys(), so it never reaches the grant grid and resolves False
    forever for anyone below full access -- silently, even with the instance
    flag ON. It looks like a misconfiguration and is not one."""

    def test_a_staff_user_can_never_reach_it(self, db_session, main_branch):
        _enable(BARE_OPTIONAL, True)
        user = _staff(db_session, main_branch, grants=default_all_permissions())
        row = _row(effective_access(user), BARE_OPTIONAL)
        assert row.grantable is False
        assert row.effective is False
        assert row.reason_code == 'not_grantable'

    def test_it_is_reported_only_while_the_module_is_on(self, db_session, main_branch):
        """OFF, the honest explanation is the instance gate -- reporting
        'not grantable' would send an admin to fix the wrong control."""
        _enable(BARE_OPTIONAL, True)
        user = _staff(db_session, main_branch, grants=default_all_permissions())
        on = [r.key for r in effective_access(user)['notices']['ungrantable_but_enabled']]
        assert BARE_OPTIONAL in on

        _enable(BARE_OPTIONAL, False)
        off = [r.key for r in effective_access(user)['notices']['ungrantable_but_enabled']]
        assert BARE_OPTIONAL not in off
        assert _row(effective_access(user), BARE_OPTIONAL).reason_code == 'instance_off'

    def test_full_access_is_unaffected(self, admin_user, db_session, main_branch):
        """CONTROL. Ungrantable means "not grantable PER USER", not "unreachable"."""
        _enable(BARE_OPTIONAL, True)
        row = _row(effective_access(admin_user), BARE_OPTIONAL)
        assert row.effective is True


# -- the prerequisite the database never shows ---------------------------------

class TestTheBranchPrerequisite:

    def test_no_branch_blocks_every_module(self, db_session, main_branch):
        _enable(GRANTABLE_OPTIONAL, True)
        user = _staff(db_session, main_branch,
                      grants={**default_all_permissions(), GRANTABLE_OPTIONAL: True},
                      branches=False)
        result = effective_access(user)
        assert result['notices']['no_branch'] is True
        assert not any(r.effective for r in result['rows'])
        assert {r.reason_code for r in result['rows']} == {'no_branch'}

    def test_the_grant_is_still_reported_as_held(self, db_session, main_branch):
        """The row must not pretend the grant is missing -- the grant IS there,
        it is simply unreachable. An admin who reads 'not granted' here would
        go and re-grant a permission the user already has."""
        _enable(GRANTABLE_OPTIONAL, True)
        user = _staff(db_session, main_branch, grants={GRANTABLE_OPTIONAL: True},
                      branches=False)
        row = _row(effective_access(user), GRANTABLE_OPTIONAL)
        assert row.granted is True
        assert row.effective is False

    def test_a_branchless_full_access_user_is_not_blocked(self, admin_user, db_session,
                                                          main_branch):
        """CONTROL. get_accessible_branches gives full-access users every active
        branch, so admin holds no assignment by design and must not be flagged."""
        assert admin_user.branches.count() == 0
        result = effective_access(admin_user)
        assert result['notices']['no_branch'] is False

    def test_a_branched_staff_user_is_not_blocked(self, db_session, main_branch):
        """CONTROL. The banner must not fire for the ordinary case."""
        user = _staff(db_session, main_branch, grants=default_all_permissions())
        assert effective_access(user)['notices']['no_branch'] is False


class TestTheSummary:

    def test_it_counts_only_reachable_modules(self, db_session, main_branch):
        _enable(GRANTABLE_OPTIONAL, True)
        user = _staff(db_session, main_branch, grants={GRANTABLE_OPTIONAL: True})
        result = effective_access(user)
        assert result['summary']['reachable'] == sum(
            1 for r in result['rows'] if r.effective)
        assert result['summary']['total'] == len(MODULE_REGISTRY)

    def test_it_names_the_branches_the_user_can_actually_reach(self, db_session,
                                                               main_branch):
        user = _staff(db_session, main_branch, grants={})
        assert effective_access(user)['summary']['branches'] == [main_branch.name]
