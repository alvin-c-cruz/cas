import pytest
from app import db
from app.users.forms import UserForm
from app.users.utils import get_accessible_branches
from app.users.module_access import can_access_module, module_enabled

pytestmark = [pytest.mark.integration]


def test_fixture_is_chief_accountant(chief_accountant_user):
    assert chief_accountant_user.role == 'chief_accountant'
    assert chief_accountant_user.has_full_access is True
    assert chief_accountant_user.is_admin is False


def test_userform_accepts_chief_accountant_without_branch(app):
    # Chief Accountant, like admin, needs no branch assignment.
    with app.test_request_context():
        form = UserForm(meta={'csrf': False})
        form.role.data = 'chief_accountant'
        form.branch_ids.data = []
        form.validate_branch_ids(form.branch_ids)  # must not raise


def test_ca_sees_all_active_branches(db_session, chief_accountant_user, main_branch, branch_manila):
    got = {b.id for b in get_accessible_branches(chief_accountant_user)}
    assert got == {main_branch.id, branch_manila.id}  # incl. unassigned branch


def test_ca_accesses_all_core_modules_without_permissions(db_session, chief_accountant_user, main_branch):
    for key in ['accounts_receivable', 'accounts_payable', 'journal_entries',
                'chart_of_accounts', 'trial_balance', 'fiscal_year_close']:
        assert can_access_module(chief_accountant_user, key) is True
    assert chief_accountant_user.has_book_access('accounts_payable') is True
    assert chief_accountant_user.has_branch_access(main_branch.id) is True


def test_ca_still_subject_to_disabled_optional_module(db_session, chief_accountant_user):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    clear_module_config_cache()  # start clean
    try:
        AppSettings.set_setting('module_enabled:bir_reports', '0', updated_by='t')
        clear_module_config_cache()
        assert module_enabled('bir_reports') is False
        assert can_access_module(chief_accountant_user, 'bir_reports') is False
    finally:
        clear_module_config_cache()  # don't leak stale '0' into later tests


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def test_ca_can_reach_periods_and_audit(client, db_session, chief_accountant_user, main_branch):
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    # Periods management page: not redirected away with the admin-only flash.
    resp = client.get('/periods/', follow_redirects=True)
    assert b'Only Administrators can manage accounting periods' not in resp.data
    # Audit log: reachable (accountant+admin+CA).
    resp = client.get('/audit-log', follow_redirects=True)
    assert b'Only Accountants and Administrators' not in resp.data


def test_ca_counts_change_request_action_items(db_session, chief_accountant_user):
    from app.dashboard.action_items_service import count_action_items
    from app.accounts.approval_models import AccountChangeRequest
    db.session.add(AccountChangeRequest(
        change_type='create', change_data='{}', status='pending', requested_by='someone'))
    db.session.commit()
    # CA sees pending change-request approvals in its badge (branch_id None: approvals only).
    assert count_action_items(chief_accountant_user, None) >= 1


def test_ca_sees_approval_items_list(db_session, chief_accountant_user):
    from app.dashboard.action_items_service import gather_approval_items
    from app.accounts.approval_models import AccountChangeRequest
    db.session.add(AccountChangeRequest(
        change_type='create', change_data='{}', status='pending', requested_by='someone'))
    db.session.commit()
    # CA sees pending approval items in the list, not just the badge count.
    items = gather_approval_items(chief_accountant_user)
    assert len(items) >= 1
    assert any(item['type'] == 'Chart of Accounts' for item in items)


def test_ca_can_approve_coa_change_request(db_session, chief_accountant_user):
    from app.accounts.approval_models import AccountChangeRequest
    cr = AccountChangeRequest(change_type='create', change_data='{}',
                              status='pending', requested_by='accountant')
    db.session.add(cr)
    db.session.commit()
    assert cr.can_be_approved_by(chief_accountant_user.username) is True


def test_ca_cannot_reach_vat_review_is_now_allowed(client, db_session, chief_accountant_user, main_branch):
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/vat-categories/', follow_redirects=True)
    assert b'Only Administrators and Chief Accountants can access VAT Categories' not in resp.data


def test_ca_can_approve_own_coa_change_request(db_session, chief_accountant_user, admin_user):
    """CA self-approval of its own COA change request is permitted (admin-like).
    admin_user in scope means another reviewer exists, so the accountant-count
    fallback would BLOCK self-approval without the has_full_access short-circuit —
    making this test decisive for the new branch."""
    from app.accounts.approval_models import AccountChangeRequest
    cr = AccountChangeRequest(change_type='create', change_data='{}',
                              status='pending', requested_by=chief_accountant_user.username)
    db.session.add(cr)
    db.session.commit()
    assert cr.can_be_approved_by(chief_accountant_user.username) is True


def test_ca_can_save_and_post_opening_balances(client, db_session, chief_accountant_user, main_branch,
                                               cash_account, revenue_account):
    from tests.integration.test_opening_balances import _make_postable, _save_payload
    from app.opening_balances.utils import get_opening_entry
    _make_postable(db_session, cash_account, revenue_account)
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.post('/opening-balances/save', data=_save_payload('2026-01-01', [
        (cash_account.id, '2000.00', '0'), (revenue_account.id, '0', '2000.00'),
    ]), follow_redirects=False)
    assert resp.status_code == 302  # CA passed the accountant_or_admin_required gate
    entry = get_opening_entry(main_branch.id)
    assert entry is not None
    assert entry.status == 'draft'

    resp = client.post('/opening-balances/post', follow_redirects=False)
    assert resp.status_code == 302
    entry = get_opening_entry(main_branch.id)
    assert entry.status == 'posted'


def test_ca_can_reopen_opening_balances(client, db_session, chief_accountant_user, main_branch,
                                        cash_account, revenue_account):
    from tests.integration.test_opening_balances import _make_postable, _save_payload
    from app.opening_balances.utils import get_opening_entry
    _make_postable(db_session, cash_account, revenue_account)
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    client.post('/opening-balances/save', data=_save_payload('2026-01-01', [
        (cash_account.id, '3000.00', '0'), (revenue_account.id, '0', '3000.00'),
    ]))
    client.post('/opening-balances/post')
    entry = get_opening_entry(main_branch.id)
    assert entry.status == 'posted'

    resp = client.post('/opening-balances/reopen', follow_redirects=False)
    assert resp.status_code == 302
    entry = get_opening_entry(main_branch.id)
    assert entry.status == 'draft'


def test_ca_can_finalize_opening_balances(client, db_session, admin_user, chief_accountant_user, main_branch,
                                          cash_account, revenue_account):
    from tests.integration.test_opening_balances import _make_postable, _save_payload
    from app.opening_balances.utils import get_opening_entry, LOCK_KEY
    from app.settings import AppSettings
    _make_postable(db_session, cash_account, revenue_account)
    # Admin sets up and posts the entry
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    client.post('/opening-balances/save', data=_save_payload('2026-01-01', [
        (cash_account.id, '1000.00', '0'), (revenue_account.id, '0', '1000.00')]))
    client.post('/opening-balances/post')
    # CA finalizes it
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.post('/opening-balances/finalize', follow_redirects=True)
    assert AppSettings.get_setting(LOCK_KEY(main_branch.id)) == '1'
    assert b'administrator' not in resp.data  # not refused


# ---------------------------------------------------------------------------
# Task 6: Sysadmin areas stay admin-only; CA is blocked
# ---------------------------------------------------------------------------
# Markers chosen: each is a unique heading that ONLY appears when you actually
# land on the management page, not in any flash message or redirect target.
# Deny flash messages for branches/users CONTAIN the page title (e.g. "Branch
# Management"), so we do NOT follow redirects for the CA check — a 302 redirect
# is the definitive signal that the deny gate fired and CA never reached the
# management view. With `follow_redirects=False`, flash-message content is
# irrelevant; only the status code matters.
#
# NOTE: The two tests below use SEPARATE test functions (not one combined test)
# because Flask's test-client `session_transaction()` reads from the last
# response cookie. If CA gets a 302 (denial), the following `_select_branch`
# call in the same function would restore CA's `_user_id` from that 302 cookie,
# causing admin's request to fire as CA. Separate functions avoid this entirely
# — each function has a single user, a fresh session state, and no prior
# response to contaminate it.

_SYSADMIN_PATHS = pytest.mark.parametrize('path,page_marker', [
    ('/users', b'User Management'),
    ('/branches', b'Branch Management'),
    ('/settings', b'Company Settings'),
    ('/settings/modules', b'Modules / Package'),
    ('/admin/errors', b'Error Logs'),
])


@_SYSADMIN_PATHS
def test_ca_blocked_from_sysadmin(client, db_session, chief_accountant_user,
                                   main_branch, path, page_marker):
    """CA is refused (302) from every sysadmin area — deny gate works.

    Single-user test: only CA is logged in, no prior request.
    A 302 redirect (not the management page) proves the gate fired.
    """
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.get(path)  # no follow_redirects — 302 proves denial
    assert resp.status_code == 302, (
        f'CA should be redirected away from {path} (got {resp.status_code})'
    )


@_SYSADMIN_PATHS
def test_admin_reaches_sysadmin(client, db_session, admin_user,
                                 main_branch, path, page_marker):
    """Admin reaches every sysadmin area — deny gate does not over-block.

    Positive (non-vacuous) pair for test_ca_blocked_from_sysadmin.
    Single-user test: only admin is logged in.

    Primary signal: a direct 200 with follow_redirects=False. This is the
    robust guard — an over-blocked admin gets a 302 to the dashboard, so a
    direct 200 proves the admin actually landed on the management view
    without needing a page-unique marker. Three of the five page_marker
    strings ("User Management", "Branch Management", "Company Settings")
    ALSO appear in the always-rendered Admin sidebar nav on every admin
    page (including the dashboard), so a marker-only assertion would still
    pass even if the admin were wrongly redirected — a vacuous positive.
    Only "Modules / Package" and "Error Logs" are genuinely page-unique
    today; the marker is asserted there as an additional, non-primary check.
    """
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get(path, follow_redirects=False)
    assert resp.status_code == 200, (
        f'admin should reach {path}, got {resp.status_code}'
    )
    if path in ('/settings/modules', '/admin/errors'):
        assert page_marker in resp.data, (
            f'Admin response for {path} should contain {page_marker!r}'
        )
