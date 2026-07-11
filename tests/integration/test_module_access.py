"""Per-user module access (book_permissions) enforcement.

Admin is never gated; accountant/staff/viewer are gated by their granted transaction books.
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

def test_admin_ungated_accountant_viewer_now_gated(db_session, branch):
    # Admin is never gated
    admin = _make_user(db_session, branch, 'admin', books={}, username='admin')
    for key in TRANSACTION_KEYS:
        assert can_access_module(admin, key) is True, f'admin should access {key}'

    # Accountant and viewer are now gated by book_permissions
    for role in ('accountant', 'viewer'):
        u = _make_user(db_session, branch, role, books={}, username=role)
        for key in TRANSACTION_KEYS:
            assert can_access_module(u, key) is False, f'{role} with no perms should not access {key}'

        # But with the permission granted, they can access
        u.set_book_permissions({key: True})
        assert can_access_module(u, key) is True, f'{role} with perm should access {key}'


def test_staff_gated_by_book_permissions(db_session, branch):
    staff = _make_user(db_session, branch, 'staff',
                       books={'accounts_payable': True}, username='staffap')
    assert can_access_module(staff, 'accounts_payable') is True
    assert can_access_module(staff, 'accounts_receivable') is False
    assert can_access_module(staff, 'payments') is False


def test_staff_phase2_modules_denied_by_default(db_session, branch):
    staff = _make_user(db_session, branch, 'staff',
                       books={'accounts_payable': True}, username='staffp2')
    for key in ('customers', 'vendors', 'chart_of_accounts', 'ap_aging', 'ar_aging'):
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


def test_customer_quick_add_subactions_exempt_for_staff(client, db_session, branch):
    """Staff with a sales-document book (e.g. accounts_receivable/quotations) but NOT the
    Customers module must still reach the customer defaults autofill AND the inline quick-add
    form used by the Quotation/SI/SO customer card — these customer sub-actions are exempt from
    the module guard, mirroring the vendor exemption. Without the exemption the guard redirects
    the XHR to the dashboard (HTTP 200 HTML, not JSON) and the line-items grid never unlocks."""
    from app.customers.models import Customer
    c = Customer(code='C001', name='Acme Corp', is_active=True)
    db_session.add(c)
    db_session.commit()
    staff = _make_user(db_session, branch, 'staff',
                       books={'accounts_receivable': True}, username='staffar1')
    _login(client, staff, branch)
    assert client.get(f'/customers/{c.id}/defaults').status_code == 200   # autofill reachable
    assert client.get('/customers/create').status_code == 200             # inline quick-add reachable


def test_product_quick_add_exempt_and_allows_staff(client, db_session, branch):
    """Owner directive 2026-07-11 (full parity with the customer quick-add): a quotation-delegated
    staff WITHOUT the Products module must still inline-add a product from the quote line grid.
    Two barriers must fall together — the module guard must EXEMPT products.create, and its role
    guard (previously accountant/full-access only, stricter than customers.create) must admit a
    staff delegate. Currently the role guard flash-redirects staff (302), so this is RED."""
    from app.products.models import Product
    staff = _make_user(db_session, branch, 'staff',
                       books={'quotations': True}, username='staffq1')
    _login(client, staff, branch)
    assert client.get('/products/create').status_code == 200             # reachable (exempt + role admits staff)
    resp = client.post('/products/create',
                       data={'code': 'P001', 'name': 'Widget', 'is_active': '1'},
                       headers={'X-Requested-With': 'XMLHttpRequest'})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    assert body['product']['label'] == 'P001 — Widget'
    assert Product.query.filter_by(code='P001').first() is not None


def test_admin_reaches_ungranted_module(client, db_session, branch):
    admin = _make_user(db_session, branch, 'admin', books={}, username='admin1')
    _login(client, admin, branch)
    assert client.get('/sales-invoices').status_code == 200


def test_viewer_gated_then_granted(client, db_session, branch):
    # Viewer with no permissions is blocked
    viewer = _make_user(db_session, branch, 'viewer', books={}, username='viewer1')
    _login(client, viewer, branch)
    assert client.get('/sales-invoices').status_code == 302

    # But when granted accounts_receivable permission, viewer can access
    viewer.set_book_permissions({'accounts_receivable': True})
    db_session.commit()
    assert client.get('/sales-invoices').status_code == 200


# ── Sidebar nav hiding ───────────────────────────────────────────────────────

def test_sidebar_hides_ungranted_transactions_for_staff(client, db_session, branch):
    staff = _make_user(db_session, branch, 'staff',
                       books={'accounts_payable': True, 'chart_of_accounts': True}, username='staffap')
    _login(client, staff, branch)
    html = client.get('/dashboard').data.decode('utf-8', 'replace')
    # Area-based sidebar: AP is in Purchases area, CoA in Accounting area.
    # Scope to the Purchases area to confirm AP link is present.
    start = html.find('id="section-area-purchases"')
    end = html.find('id="section-area-accounting"', start)
    assert start != -1 and end != -1
    section = html[start:end]
    assert 'accounts-payable' in section       # granted -> AP link in Purchases area
    assert 'sales-invoices' not in section     # ungranted -> Sales area absent, no SI link


def test_staff_without_ar_aging_blocked_from_report(client, db_session, branch):
    """A staff user not granted ar_aging is redirected away from /reports/ar-aging."""
    staff = _make_user(db_session, branch, 'staff',
                       books={'accounts_payable': True}, username='staffnoar')
    _login(client, staff, branch)
    assert client.get('/reports/ar-aging').status_code == 302


def test_staff_with_ar_aging_reaches_report(client, db_session, branch):
    """A staff user granted ar_aging can open /reports/ar-aging."""
    staff = _make_user(db_session, branch, 'staff',
                       books={'ar_aging': True}, username='staffar')
    _login(client, staff, branch)
    assert client.get('/reports/ar-aging').status_code == 200


# ── FIX 6: explicit export endpoint gating ───────────────────────────────────

def test_module_registry_lists_ar_aging_export_endpoints():
    """MODULE_REGISTRY ar_aging entry must explicitly name the export endpoints (FIX 6)."""
    from app.users.module_access import MODULE_REGISTRY
    ar_entry = next(m for m in MODULE_REGISTRY if m['key'] == 'ar_aging')
    assert 'reports.ar_aging_export_excel' in ar_entry['endpoints'], (
        'ar_aging registry must explicitly include reports.ar_aging_export_excel')
    assert 'reports.ar_aging_export_csv' in ar_entry['endpoints'], (
        'ar_aging registry must explicitly include reports.ar_aging_export_csv')


def test_module_registry_lists_ap_aging_export_endpoints():
    """MODULE_REGISTRY ap_aging entry must explicitly name the export endpoints (FIX 6)."""
    from app.users.module_access import MODULE_REGISTRY
    ap_entry = next(m for m in MODULE_REGISTRY if m['key'] == 'ap_aging')
    assert 'reports.ap_aging_export_excel' in ap_entry['endpoints'], (
        'ap_aging registry must explicitly include reports.ap_aging_export_excel')
    assert 'reports.ap_aging_export_csv' in ap_entry['endpoints'], (
        'ap_aging registry must explicitly include reports.ap_aging_export_csv')


def test_staff_without_ar_aging_blocked_from_export_excel(client, db_session, branch):
    """Staff user without ar_aging is blocked from the Excel export route."""
    staff = _make_user(db_session, branch, 'staff',
                       books={'accounts_payable': True}, username='staffnoarx')
    _login(client, staff, branch)
    assert client.get('/reports/ar-aging/export/excel').status_code == 302


def test_staff_with_ar_aging_reaches_export_excel(client, db_session, branch):
    """Staff user with ar_aging granted can reach the Excel export route."""
    staff = _make_user(db_session, branch, 'staff',
                       books={'ar_aging': True}, username='staffarx')
    _login(client, staff, branch)
    assert client.get('/reports/ar-aging/export/excel').status_code == 200
