"""`employees` must not serve or list another branch's records.

BUG-BRANCH-SCOPED-MASTERS-EDIT-NOT-BRANCH-FILTERED, the THIRD and final
sub-shape. `list_employees()` applied no branch filter at all -- unlike every
other masters module -- and `edit`/`toggle_status`/`delete` were each a bare
`db.get_or_404(Employee, id)`.

WHY THIS SUB-SHAPE IS THE REACHABLE ONE. The other two were downgraded on the
grounds that their modules are `optional` WITHOUT `per_user`, so only
admin/chief-accountant could open them and those roles reach every branch
legitimately. `employees` is `optional: True, per_user: True`
(`app/users/module_access.py:217-220`), so a branch-limited accountant or staff
user CAN hold it via `book_permissions` and CAN then type another branch's
employee id into these routes. This is a live cross-branch authz crossing, not a
latent one.

THE GUARD IS SET MEMBERSHIP, deliberately not equality against
`session['selected_branch_id']` -- same call as the `accessible_ids` sub-shape.
A user assigned two branches must still open a record in the branch that is not
currently selected; the single-branch `_get_scoped()` used by
work_centers/bank_accounts/petty_cash would refuse it, turning a security fix
into a regression. `test_second_assigned_branch_is_not_refused` pins that.

THE LIST IS FILTERED TO THE SAME SET (owner decision, 2026-08-20). The
alternative -- guard the by-id routes but leave the list global -- was declined
because it shows rows whose own Edit button then 404s. Filtering both means the
list can never display a record the user cannot act on.

WHY THE USER IS AN ACCOUNTANT AND NEVER admin: `get_accessible_branches` returns
ALL active branches for a full-access user, so an admin crossing a branch
boundary is CORRECT behaviour. A test driven as admin cannot fail here no matter
how broken the guard is.

Every test issues a REAL request. A unit assertion on the query object would
pass against the vulnerable code, because it never exercises the route's own
lookup -- which IS the defect.
"""
import pytest

from app.employees.models import Employee
from app.settings import AppSettings

pytestmark = [pytest.mark.integration, pytest.mark.employees]


@pytest.fixture(autouse=True)
def _enable_employees_module(db_session):
    """Open BOTH gates, instance and per-user, or this whole file is vacuous.

    `employees` is `default_enabled: False`. Without the instance flag the module
    gate 404s every route here and every cross-branch assertion passes for the
    wrong reason -- green against the vulnerable code, proving nothing. That
    exact trap made 13 tests pass on the first sub-shape. The `test_control_*`
    cases are the tripwire: they assert 200 on an OWN-branch record, so a closed
    gate fails loudly instead of letting the denial tests fake success.
    (memory feedback-outer-gate-masks-inner-guard)

    Clearing the cache on the way OUT is required, not tidiness: the
    `module_enabled:` override is memoized for an hour on the SESSION-scoped app
    while `db_session` drops rows per test, so a cached '1' would outlive its
    data and leak into later tests. Same class as
    BUG-TEST-MODULE-CACHE-LEAK-ORDER-MONITORING.
    """
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:employees', '1')
    clear_module_config_cache()
    yield
    clear_module_config_cache()


@pytest.fixture(autouse=True)
def _grant_employees_to_accountant(db_session, accountant_user):
    """The per-user half of the gate. `employees` IS `per_user: True`, so this
    grant is not a fiction invented for the test -- it is the ordinary
    production state that makes the defect reachable."""
    perms = accountant_user.get_book_permissions()
    perms['employees'] = True
    accountant_user.set_book_permissions(perms)
    db_session.commit()


def _login(client):
    resp = client.post('/login',
                       data={'username': 'accountant', 'password': 'accountant123'},
                       follow_redirects=True)
    assert b'Invalid username or password' not in resp.data
    return resp


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def _make_employee(db_session, branch, no, last='Cruz'):
    e = Employee(employee_no=no, first_name='Test', last_name=last,
                 branch_id=branch.id, is_active=True)
    db_session.add(e)
    db_session.commit()
    return e


def _assert_denied(response, what):
    """404 specifically -- not "any non-200", and not a 3xx.

    A redirect is what an unrelated flash-and-bounce produces, so accepting 3xx
    would let a vulnerable route look guarded. That precise mistake made a
    petty-cash test unable to fail on the first sub-shape.
    """
    assert response.status_code == 404, (
        '%s was not refused across the branch boundary (status %s)'
        % (what, response.status_code))


# --------------------------------------------------------------------------
# by-id routes: the cross-branch crossing
# --------------------------------------------------------------------------

def test_edit_refuses_other_branch(client, db_session, accountant_user,
                                   main_branch, branch_manila):
    accountant_user.set_branches([main_branch])
    db_session.commit()
    other = _make_employee(db_session, branch_manila, 'E-MNL-1')
    _login(client)
    _select_branch(client, main_branch.id)

    _assert_denied(client.get('/employees/%d/edit' % other.id), 'edit GET')


def test_edit_post_refuses_other_branch(client, db_session, accountant_user,
                                        main_branch, branch_manila):
    """The GET being guarded does not prove the POST is -- assert the write."""
    accountant_user.set_branches([main_branch])
    db_session.commit()
    other = _make_employee(db_session, branch_manila, 'E-MNL-2', last='Original')
    _login(client)
    _select_branch(client, main_branch.id)

    resp = client.post('/employees/%d/edit' % other.id,
                       data={'employee_no': 'E-MNL-2', 'first_name': 'Hacked',
                             'last_name': 'Hacked', 'branch_id': main_branch.id,
                             'is_active': '1'})
    _assert_denied(resp, 'edit POST')
    db_session.refresh(other)
    assert other.last_name == 'Original', 'the cross-branch POST mutated the record'
    assert other.branch_id == branch_manila.id, 'the record was moved to another branch'


def test_toggle_status_refuses_other_branch(client, db_session, accountant_user,
                                            main_branch, branch_manila):
    accountant_user.set_branches([main_branch])
    db_session.commit()
    other = _make_employee(db_session, branch_manila, 'E-MNL-3')
    assert other.is_active is True
    _login(client)
    _select_branch(client, main_branch.id)

    _assert_denied(client.post('/employees/%d/toggle-status' % other.id), 'toggle-status')
    db_session.refresh(other)
    assert other.is_active is True, 'the cross-branch toggle still flipped the record'


def test_delete_refuses_other_branch(client, db_session, accountant_user,
                                     main_branch, branch_manila):
    accountant_user.set_branches([main_branch])
    db_session.commit()
    other = _make_employee(db_session, branch_manila, 'E-MNL-4')
    other_id = other.id
    _login(client)
    _select_branch(client, main_branch.id)

    _assert_denied(client.post('/employees/%d/delete' % other_id), 'delete')
    assert db_session.get(Employee, other_id) is not None, \
        'the cross-branch DELETE removed the record'


# --------------------------------------------------------------------------
# the list route
# --------------------------------------------------------------------------

def test_list_hides_other_branch(client, db_session, accountant_user,
                                 main_branch, branch_manila):
    accountant_user.set_branches([main_branch])
    db_session.commit()
    _make_employee(db_session, main_branch, 'E-OWN-1', last='Ownbranch')
    _make_employee(db_session, branch_manila, 'E-MNL-5', last='Otherbranch')
    _login(client)
    _select_branch(client, main_branch.id)

    resp = client.get('/employees')
    assert resp.status_code == 200
    assert b'E-OWN-1' in resp.data, 'anti-vacuity: the own-branch row did not render'
    assert b'E-MNL-5' not in resp.data


def test_list_search_hides_other_branch(client, db_session, accountant_user,
                                        main_branch, branch_manila):
    """The search path builds its own query -- guarding the unfiltered branch
    only would leave `?q=` as a way to read across branches."""
    accountant_user.set_branches([main_branch])
    db_session.commit()
    _make_employee(db_session, main_branch, 'E-OWN-2', last='Searchme')
    _make_employee(db_session, branch_manila, 'E-MNL-6', last='Searchme')
    _login(client)
    _select_branch(client, main_branch.id)

    resp = client.get('/employees?q=Searchme')
    assert resp.status_code == 200
    assert b'E-OWN-2' in resp.data, 'anti-vacuity: the own-branch match did not render'
    assert b'E-MNL-6' not in resp.data


# --------------------------------------------------------------------------
# CONTROLS -- the guard must not over-refuse
# --------------------------------------------------------------------------

def test_control_own_branch_edit_still_opens(client, db_session, accountant_user,
                                             main_branch, branch_manila):
    """Tripwire for a closed module gate: if this 404s, every denial test above
    is passing for the wrong reason."""
    accountant_user.set_branches([main_branch])
    db_session.commit()
    mine = _make_employee(db_session, main_branch, 'E-OWN-3')
    _login(client)
    _select_branch(client, main_branch.id)

    resp = client.get('/employees/%d/edit' % mine.id)
    assert resp.status_code == 200


def test_second_assigned_branch_is_not_refused(client, db_session, accountant_user,
                                               main_branch, branch_manila):
    """THE distinction this sub-shape turns on: set membership, not selected-branch
    equality. The user is assigned BOTH branches with MAIN selected; a Manila
    record must still open. Copying the single-branch `_get_scoped()` from the
    first sub-shape would fail here -- a regression wearing a security fix's
    clothes."""
    accountant_user.set_branches([main_branch, branch_manila])
    db_session.commit()
    other = _make_employee(db_session, branch_manila, 'E-MNL-7')
    _login(client)
    _select_branch(client, main_branch.id)

    resp = client.get('/employees/%d/edit' % other.id)
    assert resp.status_code == 200


def test_second_assigned_branch_is_listed(client, db_session, accountant_user,
                                          main_branch, branch_manila):
    """Same distinction, on the list: both assigned branches' employees show
    while only one is selected."""
    accountant_user.set_branches([main_branch, branch_manila])
    db_session.commit()
    _make_employee(db_session, main_branch, 'E-OWN-4')
    _make_employee(db_session, branch_manila, 'E-MNL-8')
    _login(client)
    _select_branch(client, main_branch.id)

    resp = client.get('/employees')
    assert resp.status_code == 200
    assert b'E-OWN-4' in resp.data
    assert b'E-MNL-8' in resp.data


def test_control_admin_reaches_every_branch(client, db_session, admin_user,
                                            main_branch, branch_manila):
    """Admin is full-access, so `get_accessible_branches` returns every active
    branch and admin crossing a boundary is CORRECT. This pins that the fix did
    not accidentally restrict admin -- and is why no denial test above is driven
    as admin."""
    other = _make_employee(db_session, branch_manila, 'E-MNL-9')
    _select_branch(client, main_branch.id)
    client.post('/login', data={'username': admin_user.username, 'password': 'admin123'},
                follow_redirects=True)

    resp = client.get('/employees/%d/edit' % other.id)
    assert resp.status_code == 200
    listing = client.get('/employees')
    assert b'E-MNL-9' in listing.data
