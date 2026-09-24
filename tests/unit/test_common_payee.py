"""One payee rule for the APV and the CDV (app/common/payee.py).

Moved out of app/accounts_payable/views.py on 2026-09-24 so the Cash
Disbursement Voucher shares it. Behaviour is the APV's, unchanged:
BUG-AP-EMPLOYEE-PAYEE-PICKER-NOT-BRANCH-FILTERED.
"""
import pytest

from app.common.payee import parse_payee, employee_payee_query, resolve_payee

pytestmark = pytest.mark.unit


@pytest.mark.parametrize('raw, expected', [
    ('vendor:12', ('vendor', 12)),
    ('employee:3', ('employee', 3)),
    ('customer:1', (None, None)),
    ('vendor:', (None, None)),
    ('vendor:abc', (None, None)),
    ('', (None, None)),
    (None, (None, None)),
])
def test_parse_payee(raw, expected):
    assert parse_payee(raw) == expected


def _employee(db_session, branch, no):
    from app.employees.models import Employee
    e = Employee(employee_no=no, first_name='First', last_name=no, branch_id=branch.id,
                 is_active=True)
    db_session.add(e); db_session.commit()
    return e


def _as(client_app, user, branch):
    """Push a request context with `user` logged in and `branch` selected."""
    from flask_login import login_user
    ctx = client_app.test_request_context('/')
    ctx.push()
    login_user(user)
    from flask import session
    session['selected_branch_id'] = branch.id
    return ctx


def test_full_access_user_sees_employees_of_every_branch(app, db_session, admin_user,
                                                         main_branch, branch_manila):
    own = _employee(db_session, main_branch, 'E-OWN')
    other = _employee(db_session, branch_manila, 'E-OTHER')
    ctx = _as(app, admin_user, main_branch)
    try:
        ids = {e.id for e in employee_payee_query().all()}
        assert ids == {own.id, other.id}
        assert resolve_payee('employee', other.id) is other
    finally:
        ctx.pop()


def test_scoped_user_sees_only_reachable_branches(app, db_session, accountant_user,
                                                  main_branch, branch_manila):
    own = _employee(db_session, main_branch, 'E-OWN')
    other = _employee(db_session, branch_manila, 'E-OTHER')
    accountant_user.set_branches([main_branch]); db_session.commit()
    ctx = _as(app, accountant_user, main_branch)
    try:
        assert [e.id for e in employee_payee_query().all()] == [own.id]
        assert resolve_payee('employee', own.id) is own
        assert resolve_payee('employee', other.id) is None, 'unreachable branch must resolve to None'
    finally:
        ctx.pop()


def test_resolve_vendor_and_unknowns(app, db_session, admin_user, main_branch):
    from app.vendors.models import Vendor
    v = Vendor(code='PAYV1', name='Payee Vendor', is_active=True)
    db_session.add(v); db_session.commit()
    ctx = _as(app, admin_user, main_branch)
    try:
        assert resolve_payee('vendor', v.id) is v
        assert resolve_payee('vendor', 999999) is None
        assert resolve_payee('customer', 1) is None
        assert resolve_payee('vendor', None) is None
    finally:
        ctx.pop()


def test_an_inactive_vendor_resolves_to_none(app, db_session, admin_user, main_branch):
    """The picker offers active payees only; a hand-posted inactive one is refused too."""
    from app.vendors.models import Vendor
    v = Vendor(code='PAYV2', name='Retired Vendor', is_active=False)
    db_session.add(v); db_session.commit()
    ctx = _as(app, admin_user, main_branch)
    try:
        assert resolve_payee('vendor', v.id) is None
    finally:
        ctx.pop()


def test_an_inactive_reachable_employee_resolves_to_none(app, db_session, admin_user, main_branch):
    e = _employee(db_session, main_branch, 'E-GONE')
    e.is_active = False; db_session.commit()
    ctx = _as(app, admin_user, main_branch)
    try:
        assert resolve_payee('employee', e.id) is None
    finally:
        ctx.pop()
