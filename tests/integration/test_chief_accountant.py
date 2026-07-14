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
    ('/admin/errors', b'Error Logs'),
])
# NOTE: '/settings/modules' dropped from this list (2026-07-12) — commit
# d701344 retired it to an unconditional redirect (folded into the /settings
# "Packages" tab), so it no longer renders a 200 for ANYONE, admin included.
# Its own redirect-for-every-role behavior is covered by
# tests/integration/test_modules_admin_page.py, and CA's inability to see the
# embedded Packages tab is covered via the '/settings' case above.


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
    without needing a page-unique marker. Three of the four page_marker
    strings ("User Management", "Branch Management", "Company Settings")
    ALSO appear in the always-rendered Admin sidebar nav on every admin
    page (including the dashboard), so a marker-only assertion would still
    pass even if the admin were wrongly redirected — a vacuous positive.
    Only "Error Logs" is genuinely page-unique today; the marker is
    asserted there as an additional, non-primary check.
    """
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get(path, follow_redirects=False)
    assert resp.status_code == 200, (
        f'admin should reach {path}, got {resp.status_code}'
    )
    if path == '/admin/errors':
        assert page_marker in resp.data, (
            f'Admin response for {path} should contain {page_marker!r}'
        )


# ---------------------------------------------------------------------------
# Task 7: Sidebar nav — CA sees accounting/audit, sysadmin stays hidden
# ---------------------------------------------------------------------------

def test_ca_sidebar_shows_accounting_hides_sysadmin(client, db_session, chief_accountant_user,
                                                    main_branch):
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/dashboard', follow_redirects=True)
    body = resp.data
    # Accounting oversight visible:
    assert b'VAT Categories' in body
    assert b'Withholding Tax' in body
    assert b'Audit Log' in body
    # The oversight section is labelled 'Tax & Oversight' (was 'Accounting', which
    # collided with the transactional Accounting area from build_sidebar — one
    # heading each now, no duplicate "Accounting").
    assert b'Tax &amp; Oversight' in body
    # Sysadmin hidden (Jinja {# #} comments in the template near these so the
    # names don't leak into the HTML — see CLAUDE.md gotcha):
    assert b'User Management' not in body
    assert b'Branch Management' not in body
    assert b'Company Settings' not in body


def test_admin_sidebar_shows_sysadmin(client, db_session, admin_user, main_branch):
    """Positive pair for test_ca_sidebar_shows_accounting_hides_sysadmin — guards
    against a vacuous absence test (e.g. if the nav section were removed entirely)."""
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/dashboard', follow_redirects=True)
    assert b'User Management' in resp.data


# ---------------------------------------------------------------------------
# Task 8: End-to-end acceptance — CA full read-write in an unassigned branch;
# CA blocked from the core system-administration areas.
# ---------------------------------------------------------------------------

def test_ca_full_readwrite_in_unassigned_branch(client, db_session, chief_accountant_user,
                                                branch_manila):
    """CA (no branch assignment) can transact in ANY active branch.

    Uses follow_redirects=False and asserts a direct 200 with the form's own
    page title in the body. This is deliberately NOT `follow_redirects=True`
    + bare `status_code == 200`: if the branch/module gates pass but the
    view's OWN role check then denies (flash + redirect to dashboard), a
    followed redirect still lands on the dashboard with status 200 — a
    vacuous pass that would hide exactly the kind of gap this acceptance
    test exists to catch. `resp.data` containing 'New Journal Entry' (the
    form.html page title) is the non-vacuous signal that CA actually reached
    the write form, not the dashboard.
    """
    _login(client, chief_accountant_user)
    _select_branch(client, branch_manila.id)   # a branch CA was never assigned to
    resp = client.get('/journal-entries/create', follow_redirects=False)
    assert resp.status_code == 200, (
        f'CA should reach the JE create form directly in an unassigned branch, '
        f'got {resp.status_code} (Location={resp.headers.get("Location")})'
    )
    assert b'New Journal Entry' in resp.data


# NOTE: kept as two separate single-purpose test functions (not one loop with a
# re-login in the middle) — see the Task 6 comment above: session_transaction()
# reads the last response's cookie, so a 302 denial followed by a same-function
# re-login can silently keep the denied user's session. Each function here logs
# in exactly one user and issues no prior request.

# NOTE (2026-07-12): dropped '/settings/modules' from the loop below — commit
# d701344 retired it to an unconditional redirect (folded into the /settings
# "Packages" tab), so it's no longer a distinct sysadmin area to probe here;
# '/settings' already covers it. Was "all_four"; now three core areas.

def test_ca_blocked_from_core_sysadmin_areas(client, db_session, chief_accountant_user,
                                             main_branch):
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    for path in ['/users', '/branches', '/settings']:
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 302, (
            f'CA should be refused (302) at {path}, got {resp.status_code}'
        )


def test_admin_reaches_core_sysadmin_areas(client, db_session, admin_user, main_branch):
    """Positive pair for test_ca_blocked_from_core_sysadmin_areas — guards
    against a vacuous absence test."""
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    for path in ['/users', '/branches', '/settings']:
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 200, (
            f'admin should reach {path}, got {resp.status_code}'
        )


# ---------------------------------------------------------------------------
# Task 8: per-module acceptance — CA reaches every CORE transaction/master-data
# create form directly (200, not a role-deny 302). These are the write gates
# swept from `role not in ['accountant', 'admin']` to `has_full_access` so the
# Chief Accountant is no longer excluded. Core modules only (SI/AP/CR/CD/
# customers/vendors are always enabled; products/UOM are OPTIONAL and can be
# disabled by default, so they're deliberately not in this set).
#
# follow_redirects=False + a direct 200 is the non-vacuous signal: a role-deny
# would 302 to the dashboard (which also returns 200 under follow_redirects=True),
# so only an un-followed 200 proves CA actually reached the write form.
# ---------------------------------------------------------------------------

_CORE_CREATE_ROUTES = pytest.mark.parametrize('path', [
    '/sales-invoices/create',
    '/accounts-payable/create',
    '/cash-receipts/create',
    '/cash-disbursements/create',
    '/customers/create',
    '/vendors/create',
])


@_CORE_CREATE_ROUTES
def test_admin_reaches_core_create_forms(client, db_session, admin_user,
                                         main_branch, path):
    """Positive control: admin reaches the same forms (guards against a route
    that 302s for a NON-role reason, which would make the CA test vacuous)."""
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get(path, follow_redirects=False)
    assert resp.status_code == 200, (
        f'admin should reach {path} directly, got {resp.status_code} '
        f'(Location={resp.headers.get("Location")})'
    )


@_CORE_CREATE_ROUTES
def test_ca_can_reach_core_create_forms(client, db_session, chief_accountant_user,
                                        main_branch, path):
    """Per-module guard for the write-gate sweep: CA reaches every core
    transaction + master create form directly (200), not a role-denial redirect."""
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.get(path, follow_redirects=False)
    assert resp.status_code == 200, (
        f'CA should reach {path} directly, got {resp.status_code} '
        f'(Location={resp.headers.get("Location")})'
    )


# ---------------------------------------------------------------------------
# Final review — TEMPLATE write-button visibility (not just view-layer 200s).
# The view-layer gates above prove CA reaches the write ROUTE; these prove the
# write BUTTON is actually rendered on the page CA is looking at — the gap the
# final review flagged (templates still gated on the literal pre-CA role list,
# so CA landed on a page with no way to trigger the write action it's allowed
# to reach). One LIST-tier pair (create/launch button) + one DETAIL-tier pair
# (Post/Edit buttons on a real draft APV) — two tiers, each with a CA-sees /
# viewer-does-not-see pair so neither assertion is vacuous.
# ---------------------------------------------------------------------------

def test_ca_sees_apv_list_create_button(client, db_session, chief_accountant_user, main_branch):
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/accounts-payable', follow_redirects=True)
    assert b'Enter APV' in resp.data


def test_viewer_does_not_see_apv_list_create_button(client, db_session, viewer_user, main_branch):
    """Positive/negative pair for test_ca_sees_apv_list_create_button — a
    plain viewer (no write access anywhere) must not see the launch button."""
    viewer_user.set_branches([main_branch])
    db.session.commit()
    _login(client, viewer_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/accounts-payable', follow_redirects=True)
    assert b'Enter APV' not in resp.data


def _make_draft_apv(db_session, main_branch):
    """Build a minimal draft APV so the detail page's status-gated Post/Edit
    buttons (draft-only) have something to render against."""
    from decimal import Decimal
    from app.accounts.models import Account
    from app.vendors.models import Vendor
    from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
    from app.utils import ph_now

    def get_or_create_account(code, name, acct_type, normal_balance):
        a = Account.query.filter_by(code=code).first()
        if not a:
            a = Account(code=code, name=name, account_type=acct_type,
                        normal_balance=normal_balance, is_active=True)
            db.session.add(a)
            db.session.commit()
        return a

    vendor = Vendor.query.filter_by(code='CATV001').first()
    if not vendor:
        vendor = Vendor(code='CATV001', name='CA Test Vendor',
                         check_payee_name='CA Test Vendor', is_active=True)
        db.session.add(vendor)
        db.session.commit()

    expense = get_or_create_account('CA6000', 'CA Test Expense', 'Expense', 'Debit')
    get_or_create_account('CA2010', 'CA Test AP - Trade', 'Liability', 'Credit')

    today = ph_now().date()
    bill = AccountsPayable(
        ap_number='CA-DET-001', vendor_id=vendor.id, vendor_name=vendor.name,
        vendor_tin='123-456-789', vendor_address='Test Address, Manila',
        branch_id=main_branch.id, ap_date=today, due_date=today,
        payment_terms='Net 30', status='draft',
        subtotal=Decimal('1120.00'), vat_amount=Decimal('120.00'),
        total_before_wt=Decimal('1120.00'), withholding_tax_rate=Decimal('0.00'),
        withholding_tax_amount=Decimal('0.00'), total_amount=Decimal('1120.00'),
        amount_paid=Decimal('0.00'), balance=Decimal('1120.00'),
    )
    db.session.add(bill)
    db.session.flush()
    db.session.add(AccountsPayableItem(
        ap_id=bill.id, line_number=1, description='CA Test Service',
        amount=Decimal('1120.00'), vat_category='VATABLE', vat_rate=Decimal('12.00'),
        line_total=Decimal('1120.00'), vat_amount=Decimal('120.00'),
        account_id=expense.id,
    ))
    db.session.commit()
    return bill


# The "Post APV" trigger button text also appears (unconditionally, whenever
# ap.status == 'draft') inside the hidden confirmation modal's own submit
# button — that modal isn't role-gated, only the visible trigger is. So the
# assertion targets the trigger's distinguishing onclick handler, not the bare
# label text, to avoid a false positive/negative against the modal markup.
_POST_TRIGGER = b"postModal').style.display='flex'\">Post APV"


def test_ca_sees_apv_detail_post_and_edit_buttons(client, db_session, chief_accountant_user, main_branch):
    bill = _make_draft_apv(db_session, main_branch)
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.get(f'/accounts-payable/{bill.id}', follow_redirects=True)
    assert _POST_TRIGGER in resp.data
    assert b'>Edit<' in resp.data


def test_viewer_does_not_see_apv_detail_post_and_edit_buttons(client, db_session, viewer_user, main_branch):
    """Positive/negative pair for test_ca_sees_apv_detail_post_and_edit_buttons —
    a plain viewer reaches the (read-only) detail page but must not see the
    Post/Edit write buttons."""
    bill = _make_draft_apv(db_session, main_branch)
    viewer_user.set_branches([main_branch])
    db.session.commit()
    _login(client, viewer_user)
    _select_branch(client, main_branch.id)
    resp = client.get(f'/accounts-payable/{bill.id}', follow_redirects=True)
    assert _POST_TRIGGER not in resp.data
    assert b'>Edit<' not in resp.data
