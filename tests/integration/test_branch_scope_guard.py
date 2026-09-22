"""A document in another branch says so, instead of a bare 404.

Owner report 2026-09-22: "I don't like that 404 on switch of branch."

Every document route refuses a record belonging to a branch other than the one
selected. It did that with `abort(404)` -- correct about ACCESS, useless about
CAUSE. The record is right there; the user simply has another branch selected.

The path they hit is the ordinary one. The sidebar branch switcher posts
`request.full_path` as its return address, so switching branch while viewing a
document sends you back to that document, which now belongs to the other branch.
Switch branch, get a 404, with nothing saying why. There is deliberately NO second
mechanism in the switcher: its redirect lands on the document route, and the guard
below is what that route runs.

THE SPLIT THAT MATTERS
----------------------
Wrong branch + the user CAN reach that branch -> name it, redirect to the module's
own list. Wrong branch + the user CANNOT -> the bare 404 stays. A message naming
the branch confirms the record exists, so it is shown only to people who can
already see that branch exists. The tests below pin BOTH halves; dropping the
second is a disclosure bug, not a simplification.
"""
from datetime import date
from decimal import Decimal

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


@pytest.fixture(autouse=True)
def modules_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('sales_orders', 'products', 'purchase_orders', 'purchase_requests'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


@pytest.fixture
def other_branch(db_session):
    from app.branches.models import Branch
    b = Branch.query.filter_by(code='OTHR').first()
    if b is None:
        b = Branch(code='OTHR', name='OTHER BRANCH', is_active=True)
        db_session.add(b); db_session.commit()
    return b


@pytest.fixture
def customer(db_session):
    from app.customers.models import Customer
    c = Customer.query.filter_by(code='BSC-1').first()
    if c is None:
        c = Customer(code='BSC-1', name='Branch Scope Customer')
        db_session.add(c); db_session.commit()
    return c


def _so_in(db_session, branch, customer, number):
    from app.sales_orders.models import SalesOrder, SalesOrderItem
    so = SalesOrder(branch_id=branch.id, so_number=number,
                    order_date=date(2026, 9, 22), status='draft',
                    customer_id=customer.id, customer_name=customer.name,
                    payment_terms='Net 30', notes='')
    so.line_items.append(SalesOrderItem(line_number=1, quantity=Decimal('1'),
                                        unit_price=Decimal('1.00'),
                                        amount=Decimal('1.00')))
    db_session.add(so); db_session.commit()
    return so


def _login_at(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id
    import flask
    flask.g.pop('_login_user', None)


class TestABranchTheUserCanReach:
    """admin_user has full access, so every branch is reachable."""

    def test_it_redirects_instead_of_404ing(
            self, client, db_session, admin_user, main_branch, other_branch, customer):
        so = _so_in(db_session, other_branch, customer, 'BSC-REDIR')
        _login_at(client, admin_user, main_branch)

        resp = client.get(f'/sales-orders/{so.id}')

        assert resp.status_code == 302, 'a reachable other branch must not 404'

    def test_it_lands_on_the_modules_own_list(
            self, client, db_session, admin_user, main_branch, other_branch, customer):
        """Not the dashboard: the user stays in the module they were working in."""
        so = _so_in(db_session, other_branch, customer, 'BSC-LIST')
        _login_at(client, admin_user, main_branch)

        resp = client.get(f'/sales-orders/{so.id}')

        assert resp.headers['Location'].endswith('/sales-orders')

    def test_it_names_the_branch_to_switch_to(
            self, client, db_session, admin_user, main_branch, other_branch, customer):
        """The whole point -- a 404 said nothing. Naming the branch is what turns
        a dead end into an instruction."""
        so = _so_in(db_session, other_branch, customer, 'BSC-NAME')
        _login_at(client, admin_user, main_branch)

        body = client.get(f'/sales-orders/{so.id}', follow_redirects=True).data.decode()

        assert 'OTHER BRANCH' in body
        assert 'Switch to' in body

    def test_the_same_holds_for_an_action_route_not_just_the_detail_page(
            self, client, db_session, admin_user, main_branch, other_branch, customer):
        so = _so_in(db_session, other_branch, customer, 'BSC-POST')
        _login_at(client, admin_user, main_branch)

        resp = client.post(f'/sales-orders/{so.id}/confirm')

        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/sales-orders')


class TestABranchTheUserCannotReach:
    """The disclosure half. A message naming the branch confirms the record
    exists, so a user with no access to that branch must still see not-found."""

    @pytest.fixture
    def scoped_user(self, db_session, main_branch):
        from app.users.models import User
        u = User.query.filter_by(username='branchscoped').first()
        if u is None:
            u = User(username='branchscoped', email='branchscoped@example.test',
                     full_name='Branch Scoped', role='staff', is_active=True)
            u.set_password('scoped123')
            db_session.add(u); db_session.commit()
        u.branches = [main_branch]          # main only -- NOT other_branch
        # Sales Orders is an optional, per-user module. Without this grant the
        # module gate redirects first and the branch guard never runs -- the test
        # would then pass on a 302 that has nothing to do with branches.
        u.set_book_permissions({'sales_orders': True, 'products': True})
        db_session.commit()
        return u

    def test_it_still_404s(self, client, db_session, scoped_user, main_branch,
                           other_branch, customer):
        so = _so_in(db_session, other_branch, customer, 'BSC-HIDDEN')
        _login_at(client, scoped_user, main_branch)

        resp = client.get(f'/sales-orders/{so.id}')

        assert resp.status_code == 404, \
            'a user who cannot reach that branch must not learn the record exists'

    def test_the_branch_name_never_reaches_them(
            self, client, db_session, scoped_user, main_branch, other_branch, customer):
        so = _so_in(db_session, other_branch, customer, 'BSC-HIDDEN2')
        _login_at(client, scoped_user, main_branch)

        body = client.get(f'/sales-orders/{so.id}', follow_redirects=True).data

        assert b'OTHER BRANCH' not in body


class TestTheSameBranchIsUntouched:
    """Control. The guard must not have become a redirect for everyone."""

    def test_a_document_in_the_selected_branch_still_opens(
            self, client, db_session, admin_user, main_branch, customer):
        so = _so_in(db_session, main_branch, customer, 'BSC-OK')
        _login_at(client, admin_user, main_branch)

        assert client.get(f'/sales-orders/{so.id}').status_code == 200

    def test_a_record_that_does_not_exist_at_all_still_404s(
            self, client, admin_user, main_branch):
        _login_at(client, admin_user, main_branch)
        assert client.get('/sales-orders/999999').status_code == 404


class TestAJsonCallerKeepsThe404:
    """An XHR expecting data cannot do anything with a 302 to an HTML list -- it
    would parse the list page as its payload."""

    def test_an_xhr_gets_404_not_a_redirect(
            self, client, db_session, admin_user, main_branch, other_branch, customer):
        so = _so_in(db_session, other_branch, customer, 'BSC-XHR')
        _login_at(client, admin_user, main_branch)

        resp = client.get(f'/sales-orders/{so.id}',
                          headers={'X-Requested-With': 'XMLHttpRequest'})

        assert resp.status_code == 404

    def test_an_accept_json_caller_gets_404(
            self, client, db_session, admin_user, main_branch, other_branch, customer):
        so = _so_in(db_session, other_branch, customer, 'BSC-ACC')
        _login_at(client, admin_user, main_branch)

        resp = client.get(f'/sales-orders/{so.id}',
                          headers={'Accept': 'application/json'})

        assert resp.status_code == 404
