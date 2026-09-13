"""Company Settings -> Owners' View: full-access only; cannot enable with an unmapped
category; saves keys verbatim; writes a real before/after audit diff."""
import pytest
from flask import url_for

from app import db
from app.accounts.models import Account
from app.audit.models import AuditLog
from app.product_categories.models import ProductCategory
from app.settings import AppSettings
from app.reports.basis import ENABLED_KEY, vat_expense_setting_key, owners_basis_enabled

pytestmark = [pytest.mark.owners_basis, pytest.mark.integration]


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True


@pytest.fixture
def setup(db_session, main_branch):
    # main_branch: admin_user has no explicit branch assignment (has_full_access
    # sees every active branch); with exactly one active branch present, the
    # app's before_request branch gate auto-selects it instead of redirecting
    # to the branch picker, which would otherwise mask every assertion below
    # behind an unrelated 302.
    tin = ProductCategory(code='TIN', name='Tincan'); pla = ProductCategory(code='PLA', name='Plastic')
    parent = Account(code='811000', name='VAT EXPENSE', account_type='Other Expense', normal_balance='Debit')
    db.session.add_all([tin, pla, parent]); db.session.commit()
    a1 = Account(code='811001', name='VAT EXPENSE - TINCAN', account_type='Other Expense',
                 normal_balance='Debit', parent_id=parent.id)
    a2 = Account(code='811003', name='VAT EXPENSE - PLASTIC', account_type='Other Expense',
                 normal_balance='Debit', parent_id=parent.id)
    asset = Account(code='111001', name='CASH', account_type='Asset', normal_balance='Debit', parent_id=parent.id)
    db.session.add_all([a1, a2, asset]); db.session.commit()
    return {'tin': tin, 'pla': pla, 'a1': a1, 'a2': a2, 'asset': asset}


def test_page_requires_full_access(client, db_session, staff_user, main_branch, setup):
    # Give staff_user exactly one accessible branch so the app-wide branch-selection
    # before_request hook (validate_branch_session) auto-selects it instead of
    # redirecting to /select-branch -- otherwise the request never reaches the
    # view's own has_full_access gate and this test would pass even if that check
    # were deleted.
    staff_user.set_branches([main_branch])
    db.session.commit()
    _login(client, staff_user)
    resp = client.get('/settings/owners-view', follow_redirects=False)
    assert resp.status_code == 302
    assert '/select-branch' not in resp.headers['Location']
    with client.application.app_context():
        assert resp.headers['Location'] == url_for('dashboard.index')


def test_post_requires_full_access(client, db_session, staff_user, main_branch, setup):
    staff_user.set_branches([main_branch])
    db.session.commit()
    _login(client, staff_user)
    resp = client.post('/settings/owners-view', data={
        'owners_basis_enabled': '1',
        vat_expense_setting_key(setup['tin'].id): '811001',
        vat_expense_setting_key(setup['pla'].id): '811003',
    }, follow_redirects=False)
    assert resp.status_code == 302
    assert '/select-branch' not in resp.headers['Location']
    with client.application.app_context():
        assert resp.headers['Location'] == url_for('dashboard.index')
    assert owners_basis_enabled() is False


def test_page_renders_switch_and_one_select_per_category(client, db_session, admin_user, setup):
    _login(client, admin_user)
    resp = client.get('/settings/owners-view')
    html = resp.data.decode()
    assert resp.status_code == 200 and "Owners' View" in html
    assert 'name="owners_basis_enabled"' in html
    assert f'name="{vat_expense_setting_key(setup["tin"].id)}"' in html
    assert f'name="{vat_expense_setting_key(setup["pla"].id)}"' in html
    assert "Enable owners' reporting basis" in html


def test_cannot_enable_with_unmapped_category(client, db_session, admin_user, setup):
    _login(client, admin_user)
    resp = client.post('/settings/owners-view', data={
        'owners_basis_enabled': '1',
        vat_expense_setting_key(setup['tin'].id): '811001',
        vat_expense_setting_key(setup['pla'].id): '',
    }, follow_redirects=True)
    assert b'Plastic' in resp.data
    assert owners_basis_enabled() is False
    assert AppSettings.get_setting(vat_expense_setting_key(setup['tin'].id)) is None  # nothing saved


def test_rejects_non_expense_account(client, db_session, admin_user, setup):
    _login(client, admin_user)
    client.post('/settings/owners-view', data={
        vat_expense_setting_key(setup['tin'].id): '111001',
        vat_expense_setting_key(setup['pla'].id): '811003',
    }, follow_redirects=True)
    assert AppSettings.get_setting(vat_expense_setting_key(setup['tin'].id)) is None


def test_saves_mapping_then_enable_and_audits(client, db_session, admin_user, setup):
    _login(client, admin_user)
    client.post('/settings/owners-view', data={
        vat_expense_setting_key(setup['tin'].id): '811001',
        vat_expense_setting_key(setup['pla'].id): '811003',
    }, follow_redirects=True)
    assert owners_basis_enabled() is False
    resp = client.post('/settings/owners-view', data={
        'owners_basis_enabled': '1',
        vat_expense_setting_key(setup['tin'].id): '811001',
        vat_expense_setting_key(setup['pla'].id): '811003',
    }, follow_redirects=True)
    assert resp.status_code == 200 and owners_basis_enabled() is True
    log = AuditLog.query.filter_by(module='company_settings', record_identifier='owners_view').order_by(AuditLog.id.desc()).first()
    assert log is not None
    assert '"owners_basis_enabled": "0"' in (log.old_values or '') or "'owners_basis_enabled': '0'" in (log.old_values or '')
    assert 'owners_basis_enabled' in (log.new_values or '')


def test_rejects_two_categories_on_one_account(client, db_session, admin_user, setup):
    """income_statement_by_product_line.py builds {account_id: category_id}; a duplicate
    would silently attribute every peso on that account to one product line."""
    _login(client, admin_user)
    resp = client.post('/settings/owners-view', data={
        vat_expense_setting_key(setup['tin'].id): '811001',
        vat_expense_setting_key(setup['pla'].id): '811001',
    }, follow_redirects=True)
    html = resp.data.decode()
    assert '811001' in html and 'Tincan' in html and 'Plastic' in html
    assert AppSettings.get_setting(vat_expense_setting_key(setup['tin'].id)) is None
    assert AppSettings.get_setting(vat_expense_setting_key(setup['pla'].id)) is None
