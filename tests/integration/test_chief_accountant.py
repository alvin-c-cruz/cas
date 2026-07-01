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
