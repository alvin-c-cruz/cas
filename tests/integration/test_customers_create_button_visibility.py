"""The Customers list must offer + Create Customer to every role the create
route admits, and to no one else.

BUG-CUSTOMERS-CREATE-BUTTON-HIDDEN-FROM-STAFF: customers.create is
@staff_or_above_required, but list.html gated the anchor on
`has_full_access or role == 'accountant'`, so a staff user could POST the
route while having no UI path to it. The tests below are RENDER assertions on
GET /customers -- a POST-contract test cannot see this class of defect (the
route was always fine).
"""
import pytest

pytestmark = [pytest.mark.customers]

CREATE_HREF = b'href="/customers/create"'


def _login(client, username, password, branch):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    resp = client.post('/login', data={'username': username, 'password': password},
                       follow_redirects=True)
    assert b'Invalid username or password' not in resp.data
    return resp


def test_staff_sees_create_button(client, db_session, staff_user, main_branch):
    """Staff may POST customers.create, so the list must show them the way in."""
    staff_user.add_branch(main_branch)
    db_session.commit()
    _login(client, 'staff', 'staff123', main_branch)

    resp = client.get('/customers')
    assert resp.status_code == 200
    assert b'Customer Maintenance' in resp.data      # the list really rendered
    assert CREATE_HREF in resp.data


def test_staff_reaching_create_is_not_a_redirect(client, db_session, staff_user, main_branch):
    """Control: the route the button points at genuinely admits staff, so the
    button is not offering a dead end."""
    staff_user.add_branch(main_branch)
    db_session.commit()
    _login(client, 'staff', 'staff123', main_branch)

    resp = client.get('/customers/create')
    assert resp.status_code == 200
    assert b'You do not have permission' not in resp.data


def test_accountant_sees_create_button(client, db_session, accountant_user, main_branch):
    """CONTROL: the roles that could already see the button still can."""
    _login(client, accountant_user.username, 'accountant123', main_branch)

    resp = client.get('/customers')
    assert resp.status_code == 200
    assert CREATE_HREF in resp.data


def test_admin_sees_create_button(client, db_session, admin_user, main_branch):
    """CONTROL: admin (has_full_access) is unaffected by the gate change."""
    _login(client, admin_user.username, 'admin123', main_branch)

    resp = client.get('/customers')
    assert resp.status_code == 200
    assert CREATE_HREF in resp.data


def test_viewer_does_not_see_create_button(client, db_session, viewer_user, main_branch):
    """The gate must still EXCLUDE viewer -- the route rejects them, so showing
    the button would be the mirror-image defect."""
    viewer_user.add_branch(main_branch)
    db_session.commit()
    _login(client, 'viewer', 'viewer123', main_branch)

    resp = client.get('/customers')
    assert resp.status_code == 200
    assert b'Customer Maintenance' in resp.data      # anti-vacuity: page rendered
    assert CREATE_HREF not in resp.data


def test_viewer_is_refused_by_the_create_route(client, db_session, viewer_user, main_branch):
    """Control for the test above: viewer is hidden BECAUSE the backend says no."""
    viewer_user.add_branch(main_branch)
    db_session.commit()
    _login(client, 'viewer', 'viewer123', main_branch)

    resp = client.get('/customers/create', follow_redirects=False)
    assert resp.status_code in (302, 403)


def test_staff_row_actions_stay_accountant_only(client, db_session, staff_user, main_branch):
    """SCOPE GUARD: only the CREATE control moves. customers.edit/delete are
    @accountant_or_admin_required and their row gate at list.html:90 is correct;
    this test fails if the fix widens to the row actions."""
    from app.customers.models import Customer
    staff_user.add_branch(main_branch)
    db_session.add(Customer(code='C900', name='Scope Guard Corp', is_active=True))
    db_session.commit()
    _login(client, 'staff', 'staff123', main_branch)

    resp = client.get('/customers')
    assert resp.status_code == 200
    assert b'Scope Guard Corp' in resp.data          # anti-vacuity: the row rendered
    assert b'/customers/edit' not in resp.data
    assert b'delete-modal-' not in resp.data
