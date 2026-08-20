"""The AP employee-payee picker must not offer -- or accept -- an employee from
a branch the user cannot reach.

BUG-AP-EMPLOYEE-PAYEE-PICKER-NOT-BRANCH-FILTERED. Found by the ripple check on
BUG-BRANCH-SCOPED-MASTERS-EDIT-NOT-BRANCH-FILTERED (cas `a13e5e3c`), which
scoped the `employees` module's own routes but not the pickers other modules
build over Employee.

WHY AP AND NOT THE OTHER PICKERS. Measured, not grepped -- two of the four sites
originally suspected were fine:
  * `payroll/views.py` already filters on `_accessible_branch_ids()`.
  * `customers/views.py` is company-wide BY DESIGN -- `Customer` is "shared
    across branches" and has no `branch_id`, so a company-wide salesperson
    picker is coherent there.
AccountsPayable DOES carry `branch_id`, so a payee from another branch is
incoherent for the document it sits on. That difference is the whole scope.

TWO LAYERS, BOTH REQUIRED. Filtering the picker only removes the <option>; it
does not stop a hand-posted `payee=employee:<id>`, which is how the original
cross-branch row was actually reproduced. The backend guard lives in
`_resolve_payee`, the single choke point both create and edit already call, and
returns None so the EXISTING "Selected payee not found." path handles it -- no
new error plumbing, and it does not confirm to the caller that the record
exists.
"""
import json
from datetime import date

import pytest

from app.accounts.models import Account
from app.accounts_payable.models import AccountsPayable
from app.employees.models import Employee
from app.settings import AppSettings
from app.vat_categories.models import VATCategory
from app.vendors.models import Vendor

pytestmark = [pytest.mark.integration, pytest.mark.accounts_payable]

MODULES = ('employees', 'accounts_payable', 'payments')


@pytest.fixture(autouse=True)
def _open_gates(db_session, accountant_user):
    """Both gates, or the whole file is vacuous -- a closed module gate bounces
    every request and each assertion below passes for the wrong reason.
    (memory feedback-outer-gate-masks-inner-guard)"""
    from app.utils.cache_helpers import clear_module_config_cache
    for k in MODULES:
        AppSettings.set_setting('module_enabled:%s' % k, '1')
    clear_module_config_cache()
    perms = accountant_user.get_book_permissions()
    perms.update({k: True for k in MODULES})
    accountant_user.set_book_permissions(perms)
    db_session.commit()
    yield
    clear_module_config_cache()


@pytest.fixture
def books(db_session):
    """Minimum COA + vendor + VAT category an AP POST needs to validate."""
    for code, name, typ, bal in [
        ('20101', 'Accounts Payable - Trade', 'Liability', 'Credit'),
        ('20301', 'Withholding Tax Payable - Expanded', 'Liability', 'Credit'),
        ('10502', 'Input VAT - Domestic Goods', 'Asset', 'Debit'),
        ('69903', 'Test Expense', 'Expense', 'Debit'),
    ]:
        db_session.add(Account(code=code, name=name, account_type=typ,
                               normal_balance=bal, is_active=True))
    db_session.commit()
    db_session.add(VATCategory(
        code='V12DG', name='Input Tax Domestic Goods', rate=12.00, is_active=True,
        input_vat_account_id=Account.query.filter_by(code='10502').first().id))
    v = Vendor(code='PAYV1', name='Payee Test Vendor',
               check_payee_name='Payee Test Vendor', is_active=True)
    db_session.add(v)
    db_session.commit()
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db_session)
    return v, Account.query.filter_by(code='69903').first()


@pytest.fixture
def two_employees(db_session, main_branch, branch_manila):
    own = Employee(employee_no='E-OWN-1', first_name='Own', last_name='Branch',
                   branch_id=main_branch.id, is_active=True)
    other = Employee(employee_no='E-OTHER-1', first_name='Other', last_name='Branch',
                     branch_id=branch_manila.id, is_active=True)
    db_session.add_all([own, other])
    db_session.commit()
    return own, other


def _login_scoped(client, db_session, accountant_user, main_branch):
    accountant_user.set_branches([main_branch])
    db_session.commit()
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    resp = client.post('/login',
                       data={'username': 'accountant', 'password': 'accountant123'},
                       follow_redirects=True)
    assert b'Invalid username or password' not in resp.data


def _ap_payload(vendor, expense, payee, ap_number):
    return {
        'ap_number': ap_number,
        'ap_date': date.today().isoformat(),
        'due_date': date.today().isoformat(),
        'vendor_id': vendor.id,
        'payee': payee,
        'vendor_invoice_number': 'INV-%s' % ap_number,
        'payment_terms': 'Net 30',
        'notes': 'branch scope test',
        'line_items': json.dumps([{
            'description': 'Item', 'amount': 1000.0, 'vat_category': None,
            'account_id': expense.id, 'wt_id': None, 'wt_rate': None,
        }]),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }


# --------------------------------------------------------------------------
# layer 1 -- the picker must not OFFER the other branch's employee
# --------------------------------------------------------------------------

def test_create_form_hides_other_branch_employee(client, db_session, accountant_user,
                                                 main_branch, two_employees):
    own, other = two_employees
    _login_scoped(client, db_session, accountant_user, main_branch)

    resp = client.get('/accounts-payable/create')
    assert resp.status_code == 200
    assert b'E-OWN-1' in resp.data, 'anti-vacuity: the picker did not render at all'
    assert b'E-OTHER-1' not in resp.data


def test_edit_form_hides_other_branch_employee(client, db_session, accountant_user,
                                               main_branch, books, two_employees):
    """The edit route builds the SAME picker from its own copy of the query --
    guarding create alone would leave this one open."""
    vendor, expense = books
    own, other = two_employees
    _login_scoped(client, db_session, accountant_user, main_branch)
    client.post('/accounts-payable/create',
                data=_ap_payload(vendor, expense, 'vendor:%d' % vendor.id, 'AP-EDIT-0001'))
    ap = AccountsPayable.query.filter_by(ap_number='AP-EDIT-0001').first()
    assert ap is not None, 'setup failed: the AP was not created'

    resp = client.get('/accounts-payable/%d/edit' % ap.id)
    assert resp.status_code == 200
    assert b'E-OWN-1' in resp.data, 'anti-vacuity: the picker did not render at all'
    assert b'E-OTHER-1' not in resp.data


# --------------------------------------------------------------------------
# layer 2 -- the backend must not ACCEPT it either
# --------------------------------------------------------------------------

def test_create_refuses_hand_posted_other_branch_payee(client, db_session, accountant_user,
                                                       main_branch, books, two_employees):
    """The render filter only removes the <option>. This is how the original
    cross-branch row was actually written, so it is the assertion that matters."""
    vendor, expense = books
    own, other = two_employees
    _login_scoped(client, db_session, accountant_user, main_branch)

    client.post('/accounts-payable/create',
                data=_ap_payload(vendor, expense, 'employee:%d' % other.id, 'AP-XB-0001'))

    ap = AccountsPayable.query.filter_by(ap_number='AP-XB-0001').first()
    assert ap is None, 'an AP was created with a payee from an inaccessible branch'


def test_edit_refuses_hand_posted_other_branch_payee(client, db_session, accountant_user,
                                                     main_branch, books, two_employees):
    vendor, expense = books
    own, other = two_employees
    _login_scoped(client, db_session, accountant_user, main_branch)
    client.post('/accounts-payable/create',
                data=_ap_payload(vendor, expense, 'vendor:%d' % vendor.id, 'AP-XB-0002'))
    ap = AccountsPayable.query.filter_by(ap_number='AP-XB-0002').first()
    assert ap is not None, 'setup failed: the AP was not created'
    ap_id = ap.id

    payload = _ap_payload(vendor, expense, 'employee:%d' % other.id, 'AP-XB-0002')
    payload['row_version'] = ap.row_version
    client.post('/accounts-payable/%d/edit' % ap_id, data=payload)

    db_session.expire_all()
    ap = db_session.get(AccountsPayable, ap_id)
    assert ap.payee_type != 'employee' or ap.payee_id != other.id, \
        'the edit moved the payee to an employee in an inaccessible branch'


# --------------------------------------------------------------------------
# CONTROLS -- the guard must not over-refuse
# --------------------------------------------------------------------------

def test_control_own_branch_employee_payee_is_accepted(client, db_session, accountant_user,
                                                       main_branch, books, two_employees):
    """Tripwire: if this fails, the denial tests above prove nothing -- the
    employee payee feature would simply be broken for everyone."""
    vendor, expense = books
    own, other = two_employees
    _login_scoped(client, db_session, accountant_user, main_branch)

    client.post('/accounts-payable/create',
                data=_ap_payload(vendor, expense, 'employee:%d' % own.id, 'AP-OK-0001'))

    ap = AccountsPayable.query.filter_by(ap_number='AP-OK-0001').first()
    assert ap is not None, 'an own-branch employee payee was refused'
    assert ap.payee_type == 'employee'
    assert ap.payee_id == own.id


def test_control_vendor_payee_is_unaffected(client, db_session, accountant_user,
                                            main_branch, books, two_employees):
    """Vendors carry no branch_id -- they are company-wide -- so the guard must
    not touch them."""
    vendor, expense = books
    _login_scoped(client, db_session, accountant_user, main_branch)

    client.post('/accounts-payable/create',
                data=_ap_payload(vendor, expense, 'vendor:%d' % vendor.id, 'AP-VEN-0001'))

    ap = AccountsPayable.query.filter_by(ap_number='AP-VEN-0001').first()
    assert ap is not None, 'a vendor payee was refused'
    assert ap.payee_type == 'vendor'


def test_control_second_assigned_branch_employee_is_offered_and_accepted(
        client, db_session, accountant_user, main_branch, branch_manila, books, two_employees):
    """Set MEMBERSHIP, not selected-branch equality: a user assigned BOTH
    branches must still get the other branch's employee while MAIN is selected.
    Narrowing the guard to session['selected_branch_id'] fails here."""
    vendor, expense = books
    own, other = two_employees
    accountant_user.set_branches([main_branch, branch_manila])
    db_session.commit()
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/login', data={'username': 'accountant', 'password': 'accountant123'},
                follow_redirects=True)

    resp = client.get('/accounts-payable/create')
    assert resp.status_code == 200
    assert b'E-OTHER-1' in resp.data, 'a second assigned branch was hidden from the picker'

    client.post('/accounts-payable/create',
                data=_ap_payload(vendor, expense, 'employee:%d' % other.id, 'AP-2B-0001'))
    ap = AccountsPayable.query.filter_by(ap_number='AP-2B-0001').first()
    assert ap is not None, 'a second assigned branch employee payee was refused'
    assert ap.payee_id == other.id


def test_control_admin_sees_every_branch(client, db_session, admin_user,
                                         main_branch, two_employees):
    """Admin is full-access, so every active branch is accessible and nothing
    should be filtered away."""
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/login', data={'username': admin_user.username, 'password': 'admin123'},
                follow_redirects=True)

    resp = client.get('/accounts-payable/create')
    assert resp.status_code == 200
    assert b'E-OWN-1' in resp.data
    assert b'E-OTHER-1' in resp.data
