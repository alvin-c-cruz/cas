"""Per-user module access (book_permissions) enforcement.

Staff are gated by their granted transaction books; admin/accountant/viewer are never gated.
Covers both layers: the `can_access_module` helper (matrix) and the server-side before_request
guard (route redirects).
"""
import pytest

from app.users.models import User
from app.branches.models import Branch
from app.users.module_access import can_access_module, TRANSACTION_KEYS

pytestmark = [pytest.mark.integration, pytest.mark.users]


@pytest.fixture
def branch(db_session):
    b = Branch(code='MAIN', name='Main Office', is_active=True)
    db_session.add(b)
    db_session.commit()
    return b


def _make_user(db_session, branch, role, books=None, username='u1'):
    u = User(username=username, email=f'{username}@t.com', full_name=username.title(),
             role=role, is_active=True)
    u.set_password('pw12345')
    if books is not None:
        u.set_book_permissions(books)
    u.set_branches([branch])
    db_session.add(u)
    db_session.commit()
    return u


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


# ── Helper matrix ────────────────────────────────────────────────────────────

def test_admin_accountant_viewer_never_gated(db_session, branch):
    for role in ('admin', 'accountant', 'viewer'):
        u = _make_user(db_session, branch, role, books={}, username=role)
        for key in TRANSACTION_KEYS:
            assert can_access_module(u, key) is True, f'{role} should access {key}'


def test_staff_gated_by_book_permissions(db_session, branch):
    staff = _make_user(db_session, branch, 'staff',
                       books={'accounts_payable': True}, username='staffap')
    assert can_access_module(staff, 'accounts_payable') is True
    assert can_access_module(staff, 'accounts_receivable') is False
    assert can_access_module(staff, 'payments') is False


def test_staff_phase2_modules_denied_by_default(db_session, branch):
    staff = _make_user(db_session, branch, 'staff',
                       books={'accounts_payable': True}, username='staffp2')
    for key in ('customers', 'vendors', 'chart_of_accounts', 'ap_aging'):
        assert can_access_module(staff, key) is False


# ── Server-side route enforcement ────────────────────────────────────────────

def test_staff_granted_module_is_reachable(client, db_session, branch):
    staff = _make_user(db_session, branch, 'staff',
                       books={'accounts_payable': True}, username='staffap')
    _login(client, staff, branch)
    resp = client.get('/accounts-payable')
    assert resp.status_code == 200


def test_staff_ungranted_module_is_blocked(client, db_session, branch):
    staff = _make_user(db_session, branch, 'staff',
                       books={'accounts_payable': True}, username='staffap')
    _login(client, staff, branch)
    resp = client.get('/sales-invoices')
    assert resp.status_code == 302  # redirected away by the module guard

    # And the flash message is shown after following the redirect.
    resp2 = client.get('/sales-invoices', follow_redirects=True)
    assert b'do not have access to this module' in resp2.data


def test_staff_with_no_books_blocked_from_all_transactions(client, db_session, branch):
    staff = _make_user(db_session, branch, 'staff', books={}, username='staffnone')
    _login(client, staff, branch)
    assert client.get('/accounts-payable').status_code == 302
    assert client.get('/sales-invoices').status_code == 302


def test_staff_blocked_from_ungranted_master_data(client, db_session, branch):
    staff = _make_user(db_session, branch, 'staff',
                       books={'accounts_payable': True}, username='staffap')
    _login(client, staff, branch)
    assert client.get('/vendors').status_code == 302     # Vendors maintenance gated
    assert client.get('/customers').status_code == 302   # Customers maintenance gated


def test_vendor_quick_add_subactions_exempt_for_staff(client, db_session, branch):
    """Staff with AP but NOT Vendors must still reach the inline quick-add autofill — the
    vendor sub-actions used by transaction forms are exempt from the module guard."""
    from app.vendors.models import Vendor
    v = Vendor(code='V001', name='Acme Supplies', is_active=True)
    db_session.add(v)
    db_session.commit()
    staff = _make_user(db_session, branch, 'staff',
                       books={'accounts_payable': True}, username='staffap')
    _login(client, staff, branch)
    resp = client.get(f'/vendors/{v.id}/defaults')
    assert resp.status_code != 302   # NOT redirected away by the module guard


def test_admin_reaches_ungranted_module(client, db_session, branch):
    admin = _make_user(db_session, branch, 'admin', books={}, username='admin1')
    _login(client, admin, branch)
    assert client.get('/sales-invoices').status_code == 200


def test_viewer_not_gated(client, db_session, branch):
    viewer = _make_user(db_session, branch, 'viewer', books={}, username='viewer1')
    _login(client, viewer, branch)
    assert client.get('/sales-invoices').status_code == 200


# ── Sidebar nav hiding ───────────────────────────────────────────────────────

def test_sidebar_hides_ungranted_transactions_for_staff(client, db_session, branch):
    staff = _make_user(db_session, branch, 'staff',
                       books={'accounts_payable': True}, username='staffap')
    _login(client, staff, branch)
    html = client.get('/dashboard').data.decode('utf-8', 'replace')
    # Scope to the Transactions nav section (a dashboard widget may link elsewhere).
    start = html.find('id="section-transactions"')
    end = html.find('id="section-ledger"', start)
    section = html[start:end]
    assert start != -1 and end != -1
    assert 'accounts-payable' in section       # granted -> nav link present
    assert 'sales-invoices' not in section     # ungranted -> nav item hidden
