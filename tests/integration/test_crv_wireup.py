"""Wire-up tests: cash_receipts blueprint registered, legacy receipts blueprint retired,
collections module access gating applied, sidebar link updated.

Covers:
- /cash-receipts reachable (200) for admin with branch selected
- Old 'receipts.*' endpoint no longer registered (GET /receipts 404s)
- Staff WITHOUT 'collections' book permission: blocked (302) from /cash-receipts
- Staff WITH 'collections' book permission: reaches /cash-receipts (200)
- Sidebar shows Cash Receipts link pointing at /cash-receipts for a permitted user
"""
import pytest
from app.users.models import User
from app.branches.models import Branch

pytestmark = [pytest.mark.integration]


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def branch(db_session):
    b = Branch(code='MAIN', name='Main Office', is_active=True)
    db_session.add(b)
    db_session.commit()
    return b


def _make_staff(db_session, branch, books=None, username='staffcrv'):
    u = User(username=username, email=f'{username}@t.com', full_name=username.title(),
             role='staff', is_active=True)
    u.set_password('pw12345')
    if books is not None:
        u.set_book_permissions(books)
    u.set_branches([branch])
    db_session.add(u)
    db_session.commit()
    return u


def _make_admin(db_session, branch, username='adm1'):
    u = User(username=username, email=f'{username}@t.com', full_name='Admin',
             role='admin', is_active=True)
    u.set_password('pw12345')
    u.set_branches([branch])
    db_session.add(u)
    db_session.commit()
    return u


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


# ── Route reachability ────────────────────────────────────────────────────────

def test_cash_receipts_list_reachable_for_admin(client, db_session, branch):
    """Admin with a branch selected gets 200 at /cash-receipts."""
    admin = _make_admin(db_session, branch)
    _login(client, admin, branch)
    resp = client.get('/cash-receipts')
    assert resp.status_code == 200


def test_legacy_receipts_route_returns_404(client, db_session, branch):
    """The old /receipts route is no longer registered — must 404."""
    admin = _make_admin(db_session, branch)
    _login(client, admin, branch)
    resp = client.get('/receipts')
    assert resp.status_code == 404


def test_legacy_receipts_endpoint_not_registered(app):
    """url_for('receipts.list_receipts') must raise BuildError."""
    from flask import url_for
    from werkzeug.routing import BuildError
    with app.test_request_context('/'):
        with pytest.raises(BuildError):
            url_for('receipts.list_receipts')


# ── Staff module gating ───────────────────────────────────────────────────────

def test_staff_without_collections_blocked_from_cash_receipts(client, db_session, branch):
    """Staff without 'collections' book permission is redirected (302) from /cash-receipts."""
    staff = _make_staff(db_session, branch, books={'accounts_payable': True})
    _login(client, staff, branch)
    resp = client.get('/cash-receipts')
    assert resp.status_code == 302


def test_staff_with_collections_reaches_cash_receipts(client, db_session, branch):
    """Staff with 'collections' book permission gets 200 at /cash-receipts."""
    staff = _make_staff(db_session, branch, books={'collections': True})
    _login(client, staff, branch)
    resp = client.get('/cash-receipts')
    assert resp.status_code == 200


# ── Sidebar link ─────────────────────────────────────────────────────────────

def test_sidebar_cash_receipts_link_points_to_new_route(client, db_session, branch):
    """Sidebar contains a link to /cash-receipts for an admin user."""
    admin = _make_admin(db_session, branch)
    _login(client, admin, branch)
    resp = client.get('/cash-receipts')
    assert resp.status_code == 200
    body = resp.data
    # The sidebar must contain the new /cash-receipts href
    assert b'/cash-receipts' in body


def test_sidebar_does_not_link_to_legacy_receipts(client, db_session, branch):
    """Sidebar must NOT link to the legacy /receipts path."""
    admin = _make_admin(db_session, branch)
    _login(client, admin, branch)
    resp = client.get('/cash-receipts')
    body = resp.data
    # Should not contain a link to the old /receipts (only) path
    # '/cash-receipts' is expected; bare '/receipts' should not appear as href
    assert b'href="/receipts"' not in body
    assert b"href='/receipts'" not in body
