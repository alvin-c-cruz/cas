"""The Sales Order detail page's action bar -- every control gated on the SAME
rule its own route enforces.

Three filed bugs, one template block (`app/sales_orders/templates/sales_orders/
detail.html`, the `card-header-actions` div):

* BUG-SO-PRINT-BUTTON-NOT-GATED-BY-HIDDEN  -- Print rendered with no condition at
  all, while `print_so()` refuses when `so_print_form == 'hidden'`.
* BUG-SO-AMEND-BUTTON-SHOWN-TO-VIEWER      -- Amend gated on STATUS only, while
  `amend()` calls `_role_gate()` first.
* BUG-SO-DR-BUTTON-IGNORES-PER-USER-MODULE-ACCESS -- "+ Delivery Receipt" gated on
  `module_enabled()` (the INSTANCE package gate), while `enforce_module_access`
  requires `can_access_module()` (instance gate AND the per-user book permission).

None of the three is a bypass -- every route refuses correctly. The defect is that
the page advertises an action the clicker cannot perform. That makes all three
invisible to a POST-based test: the POST is refused either way, green either way.
Every assertion here is therefore made on a **GET render** of the detail page.

Both directions are asserted for each control, and every absence assertion carries
a positive control (`so.so_number in html`) so that a 302, a 404 or an empty body
cannot pass for a correctly hidden button -- the exact way a green absence test
proves nothing (memory `feedback-control-test-must-assert-outcome`).
"""
import json
import pytest
from decimal import Decimal

from app import db
from app.sales_orders.models import SalesOrder

from tests.integration._so_helpers import (
    sales_orders_module_enabled, _login, _select_branch,
    _customer, _product, _enable_products,
)

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


# --- fixtures ---------------------------------------------------------------

@pytest.fixture
def branch(db_session):
    from app.branches.models import Branch
    b = Branch.query.first()
    if b is None:
        b = Branch(code='CORP', name='CORP')
        db_session.add(b)
        db_session.commit()
    return b


@pytest.fixture
def customer(db_session):
    return _customer(db_session)


@pytest.fixture
def product(db_session):
    _enable_products(db_session)
    return _product(db_session)


def _make_user(db_session, branch, username, role, perms):
    """A branch-scoped user with an explicit book_permissions grant.

    set_branches() matters as much as the role: a non-admin with no assigned
    branch is force-logged-out by the branch-session guard before any view runs,
    which would "pass" every absence test below for entirely the wrong reason.
    """
    from app.users.models import User
    u = User(username=username, email=f'{username}@example.com',
             full_name=username.title(), role=role, is_active=True,
             branch_id=branch.id)
    u.set_password('uitest-Pass123!')
    u.set_book_permissions(perms)
    db_session.add(u)
    db_session.flush()
    u.set_branches([branch])
    db_session.commit()
    return u


@pytest.fixture
def staff_user(db_session, branch):
    """Staff WITH delivery_receipts -- the SO author, who may amend and may deliver.

    job_order_slips is its OWN grantable module key (print_job_order's endpoint is
    registered under it, not sales_orders), so the job-order ripple test below
    needs the grant as well as the instance gate _so_helpers already opens.
    """
    return _make_user(db_session, branch, 'china', 'staff',
                      {'sales_orders': True, 'delivery_receipts': True,
                       'job_order_slips': True})


@pytest.fixture
def staff_no_dr_user(db_session, branch):
    """Staff WITHOUT delivery_receipts -- RIC's `China` in the filed evidence.

    THE gate case for the DR button: the instance package gate says yes and the
    per-user gate says no, so a button testing only the former renders a control
    `enforce_module_access` bounces on click.
    """
    return _make_user(db_session, branch, 'china_nodr', 'staff',
                      {'sales_orders': True, 'delivery_receipts': False})


@pytest.fixture
def accountant_user(db_session, branch):
    return _make_user(db_session, branch, 'ana', 'accountant',
                      {'sales_orders': True, 'delivery_receipts': True})


@pytest.fixture
def viewer_user(db_session, branch):
    """A viewer WITH the sales_orders book permission, so the MODULE gate cannot
    mask the ROLE behaviour under test -- this user reaches the page, and the only
    thing that may hide the Amend button is the role condition itself."""
    return _make_user(db_session, branch, 'val', 'viewer',
                      {'sales_orders': True, 'delivery_receipts': True})


@pytest.fixture
def dr_module_enabled(db_session):
    """delivery_receipts is optional -- turn the INSTANCE gate ON for this file, so
    that when the button is absent it is the PER-USER gate that hid it."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:delivery_receipts', '1')
    db_session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


@pytest.fixture
def confirmed_so(client, db_session, staff_user, branch, customer, product):
    """A confirmed SO, built through the routes so its status is written by the
    code under test. Returned logged OUT of nobody -- each test logs in the role
    it is about."""
    _login(client, staff_user)
    _select_branch(client, branch.id)
    lines = json.dumps([{'line_number': 1, 'product_id': product.id,
                         'quantity': '10', 'unit_price': '4.20',
                         'amount': '42.00'}])
    client.post('/sales-orders/create', data={
        'so_number': '2026080077', 'order_date': '2026-08-04',
        'customer_id': str(customer.id), 'payment_terms': 'Net 60',
        'notes': '', 'line_items': lines}, follow_redirects=True)
    so = SalesOrder.query.filter_by(so_number='2026080077').one()
    client.post(f'/sales-orders/{so.id}/confirm', follow_redirects=True)
    db_session.refresh(so)
    assert so.status == 'confirmed'
    return so


def _detail(client, so):
    resp = client.get(f'/sales-orders/{so.id}')
    assert resp.status_code == 200
    html = resp.data.decode()
    # Positive control for every absence assertion in this file: the page really
    # rendered this order, so a missing control is a hidden control.
    assert so.so_number in html
    return html


def _set_print_form(db_session, value):
    from app.settings import AppSettings
    AppSettings.set_setting('so_print_form', value)
    db_session.commit()


def _print_href(so):
    return f'/sales-orders/{so.id}/print'


def _amend_href(so):
    return f'/sales-orders/{so.id}/amend'


_DR_HREF = '/delivery-receipts/create'


# --- BUG-SO-PRINT-BUTTON-NOT-GATED-BY-HIDDEN --------------------------------

class TestPrintButtonFollowsSoPrintForm:
    """`print_so()` reads `so_print_form` and refuses on 'hidden'. The button must
    read the same setting. Modelled on delivery_receipts/detail.html:48 -- the
    right sibling to copy, because SO has no `*_print_access` status tier the way
    SI/APV/CDV do."""

    @pytest.fixture(autouse=True)
    def _as_staff(self, client, staff_user, branch):
        _login(client, staff_user)
        _select_branch(client, branch.id)

    def test_the_print_button_is_shown_when_printing_is_current(
            self, client, db_session, confirmed_so):
        _set_print_form(db_session, 'current')
        assert _print_href(confirmed_so) in _detail(client, confirmed_so)

    def test_the_print_button_is_shown_when_printing_is_preprinted(
            self, client, db_session, confirmed_so):
        # 'hidden' is the ONLY value that disables printing. A guard written as
        # `== 'current'` passes the test above and silently drops the preprinted
        # form, which is the one BIR-registered clients actually use.
        _set_print_form(db_session, 'preprinted')
        assert _print_href(confirmed_so) in _detail(client, confirmed_so)

    def test_the_print_button_is_hidden_when_printing_is_hidden(
            self, client, db_session, confirmed_so):
        _set_print_form(db_session, 'hidden')
        assert _print_href(confirmed_so) not in _detail(client, confirmed_so)

    def test_the_print_button_is_shown_when_the_setting_is_unset(
            self, client, confirmed_so):
        # AppSettings.get_setting's default is 'current'. If the view forgets to
        # pass so_print_form at all, Jinja's Undefined != 'hidden' is True and this
        # test still passes -- which is why the 'hidden' case above is the real
        # gate. This one pins that an out-of-the-box instance keeps its button.
        assert _print_href(confirmed_so) in _detail(client, confirmed_so)


def test_the_job_order_slip_stays_printable_while_so_printing_is_hidden(
        client, db_session, staff_user, branch, confirmed_so):
    """Documented ripple: the Job Order Slip is deliberately NOT covered by
    so_print_form (see print_job_order's docstring). It is linked from
    job_order_list.html, not the detail page, so the fix must not reach it --
    asserted rather than assumed."""
    _login(client, staff_user)
    _select_branch(client, branch.id)
    _set_print_form(db_session, 'hidden')
    resp = client.get('/sales-orders/job-order-slips')
    assert resp.status_code == 200
    html = resp.data.decode()
    assert confirmed_so.so_number in html
    assert f'/sales-orders/{confirmed_so.so_number}/print-job-order' in html


# --- BUG-SO-AMEND-BUTTON-SHOWN-TO-VIEWER ------------------------------------

class TestAmendButtonFollowsTheRoleGate:
    """`amend()` calls `_role_gate()` first: staff/accountant/admin/chief_accountant.
    The button must carry exactly that list -- the same one its sibling Confirm and
    Edit controls already carry three lines away."""

    def test_a_viewer_does_not_see_the_amend_button(
            self, client, viewer_user, branch, confirmed_so):
        # THE gate case. A viewer is refused by _role_gate() on both GET and POST,
        # so the button is a control that always bounces.
        _login(client, viewer_user)
        _select_branch(client, branch.id)
        assert _amend_href(confirmed_so) not in _detail(client, confirmed_so)

    def test_a_staff_user_still_sees_the_amend_button(
            self, client, staff_user, branch, confirmed_so):
        # Staff MUST keep Amend -- deliberate, and covered by
        # test_amend_is_reachable_by_staff. Narrowing this to cancel()'s stricter
        # accountant-or-full-access rule would be a regression, not a fix.
        _login(client, staff_user)
        _select_branch(client, branch.id)
        assert _amend_href(confirmed_so) in _detail(client, confirmed_so)

    def test_an_accountant_sees_the_amend_button(
            self, client, accountant_user, branch, confirmed_so):
        _login(client, accountant_user)
        _select_branch(client, branch.id)
        assert _amend_href(confirmed_so) in _detail(client, confirmed_so)

    def test_a_draft_so_shows_no_amend_button_to_anyone(
            self, client, db_session, staff_user, branch, confirmed_so):
        # The status half of the condition, pinned independently: adding the role
        # list must not drop it. Runs as staff, who passes the role half.
        confirmed_so.status = 'draft'
        db.session.commit()
        _login(client, staff_user)
        _select_branch(client, branch.id)
        assert _amend_href(confirmed_so) not in _detail(client, confirmed_so)


# --- BUG-SO-DR-BUTTON-IGNORES-PER-USER-MODULE-ACCESS ------------------------

class TestDeliveryReceiptButtonFollowsPerUserModuleAccess:
    """`can_access_module()` is `module_enabled()` AND the per-user book permission
    (module_access.py:369-378, and its first statement is the instance gate -- so
    this is a substitution, not a composition). It is what `enforce_module_access`
    requires of the DR route, and what base.html uses to build the sidebar. The
    button must use it too, or the page and the sidebar disagree by construction."""

    def test_staff_without_the_dr_module_do_not_see_the_button(
            self, client, dr_module_enabled, staff_no_dr_user, branch, confirmed_so):
        # THE gate case, and the filed repro: instance gate ON, per-user grant OFF.
        # The sidebar already hides Delivery Receipts for this user.
        _login(client, staff_no_dr_user)
        _select_branch(client, branch.id)
        assert _DR_HREF not in _detail(client, confirmed_so)

    def test_staff_with_the_dr_module_see_the_button(
            self, client, dr_module_enabled, staff_user, branch, confirmed_so):
        _login(client, staff_user)
        _select_branch(client, branch.id)
        assert _DR_HREF in _detail(client, confirmed_so)

    def test_an_admin_sees_the_button(
            self, client, dr_module_enabled, admin_user, branch, confirmed_so):
        # has_full_access short-circuits the book_permissions lookup. An admin has
        # no explicit delivery_receipts grant, so a fix written as a raw
        # book_permissions read instead of can_access_module() would hide the
        # button from the one role that certainly may use it.
        admin_user.set_branches([branch])
        db.session.commit()
        _login(client, admin_user)
        _select_branch(client, branch.id)
        assert _DR_HREF in _detail(client, confirmed_so)

    def test_the_button_is_hidden_when_the_dr_module_is_off_instance_wide(
            self, client, staff_user, branch, confirmed_so):
        # The instance half, pinned independently. can_access_module() subsumes it,
        # but a fix written as `book_permissions only` would lose it -- this user
        # HAS the grant, so only the package gate can hide the button here.
        from app.settings import AppSettings
        from app.utils.cache_helpers import clear_module_config_cache
        AppSettings.set_setting('module_enabled:delivery_receipts', '0')
        db.session.commit()
        clear_module_config_cache()
        _login(client, staff_user)
        _select_branch(client, branch.id)
        assert _DR_HREF not in _detail(client, confirmed_so)

    def test_a_draft_so_shows_no_dr_button(
            self, client, dr_module_enabled, db_session, staff_user, branch,
            confirmed_so):
        # The status half. You deliver against a CONFIRMED order.
        confirmed_so.status = 'draft'
        db.session.commit()
        _login(client, staff_user)
        _select_branch(client, branch.id)
        assert _DR_HREF not in _detail(client, confirmed_so)
