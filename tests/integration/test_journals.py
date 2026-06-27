import pytest
from app import create_app, db
from app.users.models import User
from app.branches.models import Branch
from app.journal_entries.models import JournalEntry
from app.utils import ph_now
from sqlalchemy import event
from sqlalchemy.engine import Engine
import os
pytestmark = [pytest.mark.journals, pytest.mark.integration]


class _QueryCounter:
    """Count every SQL statement executed inside the `with` block."""

    def __init__(self):
        self.count = 0

    def _on_execute(self, *args, **kwargs):
        self.count += 1

    def __enter__(self):
        event.listen(Engine, 'before_cursor_execute', self._on_execute)
        return self

    def __exit__(self, *exc):
        event.remove(Engine, 'before_cursor_execute', self._on_execute)


def _make_voucher(db_session, branch, n, created_by=None, posted_by=None,
                  status='posted', entry_type='adjustment'):
    """Create a journal-voucher-type JournalEntry for list tests."""
    je = JournalEntry(
        entry_number=f'JE-2026-{n:04d}',
        entry_date=ph_now().date(),
        description=f'Test voucher {n}',
        entry_type=entry_type,
        status=status,
        branch_id=branch.id,
        total_debit=100,
        total_credit=100,
        created_by_id=created_by.id if created_by else None,
        posted_by_id=posted_by.id if posted_by else None,
    )
    db_session.add(je)
    db_session.commit()
    return je




@pytest.fixture(scope='function')
def setup(db_session):
    branch = Branch(name='Main', code='MAIN')
    db_session.add(branch)
    db_session.commit()

    from app.users.module_access import default_all_permissions
    users = {
        'admin': User(username='admin', email='admin@t.com', full_name='Admin',
                      role='admin', is_active=True),
        'accountant': User(username='accountant', email='acc@t.com', full_name='Acc',
                           role='accountant', is_active=True),
        'staff': User(username='staff', email='staff@t.com', full_name='Staff',
                      role='staff', is_active=True),
        'viewer': User(username='viewer', email='viewer@t.com', full_name='Viewer',
                       role='viewer', is_active=True),
    }
    # Accountant and viewer are now gated by book_permissions (Task 3: gate flip).
    # Grant all permissions so these role-access tests remain meaningful — they verify
    # that a properly-permissioned accountant/viewer reaches the journal, while a
    # staff user WITHOUT book_permissions is still redirected.
    all_perms = default_all_permissions()
    for role, u in users.items():
        u.set_password('pass')
        if role in ('accountant', 'viewer'):
            u.set_book_permissions(all_perms)
        u.branches.append(branch)
        db_session.add(u)
    db_session.commit()
    return users, branch


def login(client, username):
    client.post('/login', data={'username': username, 'password': 'pass'},
                follow_redirects=True)


def test_ap_journal_requires_login(client, setup):
    res = client.get('/journals/ap')
    assert res.status_code in (302, 401)


# admin is always ungated; accountant and viewer are gated but the setup fixture
# grants them default_all_permissions(), so they can reach every journal.
# Staff is created WITHOUT book_permissions, so it is redirected on every journal
# route — that is the gating behavior we verify in the per-role assertions below.
# The positive staff-with-permission path is covered in test_module_access.py.
UNGATED_ROLES = ['admin', 'accountant', 'viewer']


def _assert_journal_access(client, branch, path):
    for role in UNGATED_ROLES:
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = branch.id
        login(client, role)
        res = client.get(path)
        assert res.status_code == 200, f"{role} got {res.status_code} on {path}"
        client.get('/logout')
    # staff without the book permission is redirected (per-module access gate)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    login(client, 'staff')
    res = client.get(path)
    assert res.status_code == 302, f"staff should be gated on {path}, got {res.status_code}"
    client.get('/logout')


def test_ap_journal_access_by_role(client, setup):
    users, branch = setup
    _assert_journal_access(client, branch, '/journals/ap')


def test_voucher_access_by_role(client, setup):
    users, branch = setup
    _assert_journal_access(client, branch, '/journals/voucher')


def test_cd_journal_access_by_role(client, setup):
    users, branch = setup
    _assert_journal_access(client, branch, '/journals/cd')


def test_cr_journal_access_by_role(client, setup):
    """CR journal was activated (cash_receipts module) — it no longer redirects to
    under-development; it is a live journal gated like the others."""
    users, branch = setup
    _assert_journal_access(client, branch, '/journals/cr')


def test_journal_entries_redirects_to_voucher(client, setup):
    users, branch = setup
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    login(client, 'accountant')
    res = client.get('/journal-entries')
    assert res.status_code == 302
    assert 'voucher' in res.location


def test_voucher_launch_button_uses_enter_verb(client, setup):
    """List/launch button must use the 'Enter' verb, not 'New' (CLAUDE.md verb rule)."""
    users, branch = setup
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    login(client, 'accountant')
    body = client.get('/journals/voucher').get_data(as_text=True)
    assert 'Enter Journal Voucher' in body
    assert 'New Journal Voucher' not in body


def test_voucher_status_filter_includes_reversed(client, setup):
    """The model has a 'reversed' status; the filter must offer it."""
    users, branch = setup
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    login(client, 'accountant')
    body = client.get('/journals/voucher').get_data(as_text=True)
    assert 'value="reversed"' in body


def test_voucher_uses_global_status_badges(client, setup, db_session):
    """Status badges must reuse the global semantic classes, not local bootstrap-y ones."""
    users, branch = setup
    _make_voucher(db_session, branch, 1, posted_by=users['accountant'], status='posted')
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    login(client, 'accountant')
    body = client.get('/journals/voucher').get_data(as_text=True)
    assert 'badge-posted' in body
    assert 'badge-info' not in body
    assert 'badge-secondary' not in body


def test_voucher_list_is_paginated(client, setup, db_session):
    """A page must cap at per_page rows; the overflow lands on page 2."""
    users, branch = setup
    for n in range(1, 52):  # 51 vouchers, per_page = 50
        _make_voucher(db_session, branch, n, status='posted')
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    login(client, 'accountant')
    page1 = client.get('/journals/voucher').get_data(as_text=True)
    assert page1.count('JE-2026-') == 50
    page2 = client.get('/journals/voucher?page=2').get_data(as_text=True)
    assert page2.count('JE-2026-') == 1


def test_voucher_list_avoids_n_plus_one(client, setup, db_session):
    """Query count must stay flat as rows grow — posted_by is eager-loaded.

    Each row gets a DISTINCT posted_by user so the identity-map cache can't mask
    a per-row lazy load. Comparing 1 row vs 10 rows makes a real N+1 (~+9 queries)
    unmistakable against the small (±1) cross-test SimpleCache jitter, so the
    threshold is a tolerant constant rather than exact equality.
    """
    users, branch = setup
    posters = []
    for i in range(10):
        u = User(username=f'poster{i}', email=f'poster{i}@t.com',
                 full_name=f'P{i}', role='accountant', is_active=True)
        u.set_password('pass')
        u.branches.append(branch)
        db_session.add(u)
        posters.append(u)
    db_session.commit()

    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    login(client, 'accountant')

    _make_voucher(db_session, branch, 1, posted_by=posters[0], status='posted')
    with _QueryCounter() as c1:
        client.get('/journals/voucher')

    for n in range(2, 11):  # 9 more rows, each a distinct posted_by user
        _make_voucher(db_session, branch, n, posted_by=posters[n - 1], status='posted')
    with _QueryCounter() as c10:
        client.get('/journals/voucher')

    assert c10.count - c1.count <= 2, (
        f'N+1: {c1.count} queries for 1 row but {c10.count} for 10 rows')


def test_jv_book_shows_closing_and_closing_reversal_after_reopen(client, db_session):
    """After close_fiscal_year(2025) then reopen_fiscal_year(2025), the JV book
    must show BOTH the closing entries (CLOSE-2025) AND their reversals (REOPEN-2025).
    Covers Fix I-2: 'closing_reversal' must be in VOUCHER_TYPES.
    """
    from tests.integration.test_year_end_close import _world
    from app.year_end import service
    from app import db as _db
    from app.users.models import User
    from app.branches.models import Branch

    # Build a standalone branch and admin user (avoids fixture conflicts with setup)
    branch = Branch(name='JV-Test-Branch', code='JVTB')
    db_session.add(branch)
    db_session.flush()

    admin = User(username='admin_jvtest', email='admin_jvtest@test.com',
                 full_name='Admin JV', role='admin', is_active=True)
    admin.set_password('admin123')
    db_session.add(admin)
    db_session.flush()

    _world(branch.id)
    _db.session.commit()

    service.close_fiscal_year(2025, admin.id)
    _db.session.commit()

    service.reopen_fiscal_year(2025, admin.id)
    _db.session.commit()

    # Log in as the test admin user, then set branch in session
    client.post('/login', data={'username': 'admin_jvtest', 'password': 'admin123'},
                follow_redirects=True)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id

    body = client.get(
        '/journals/voucher?date_from=2025-01-01&date_to=2025-12-31',
    ).get_data(as_text=True)

    # Closing entries show descriptions like "Close revenue to Income Summary — FY2025"
    assert 'FY2025' in body, "JV book must show closing entries (description contains FY2025)"
    # Reversal entries show descriptions like "Reverse Close revenue to Income Summary — FY2025"
    assert 'Reverse Close' in body, (
        "JV book must show closing_reversal entries (description starts with 'Reverse Close'). "
        "If this fails, 'closing_reversal' is missing from VOUCHER_TYPES."
    )


def test_voucher_print_and_export_render(client, setup, db_session):
    """Print/export share the voucher query helper and must still render."""
    users, branch = setup
    _make_voucher(db_session, branch, 1, posted_by=users['accountant'], status='posted')
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    login(client, 'accountant')
    assert client.get('/journals/voucher/print').status_code == 200
    res = client.get('/journals/voucher/export')
    assert res.status_code == 200
    assert 'spreadsheet' in res.headers.get('Content-Type', '')
