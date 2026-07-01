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
    assert b'Only Administrators can access VAT Categories' not in resp.data
