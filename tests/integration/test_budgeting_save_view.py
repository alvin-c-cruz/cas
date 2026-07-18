import pytest
from decimal import Decimal

from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache
from app.accounts.models import Account
from app.audit.models import AuditLog
from app.budgeting.models import BudgetLine

pytestmark = [pytest.mark.integration]


def _enable_budgeting(db_session):
    AppSettings.set_setting('module_enabled:budgeting', '1')
    db_session.commit()
    clear_module_config_cache()


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def _login_admin(client, db_session, main_branch, login_user):
    _enable_budgeting(db_session)
    login_user(client, 'admin', 'admin123')
    _select_branch(client, main_branch.id)


def _revenue_leaf(db_session, code='4001', name='Sales Revenue'):
    # A top-level account with no parent is always a header (hierarchy is derived --
    # top-level or has-children -> header); a leaf fixture needs a parent group.
    group = Account(code='4000', name='Revenue', account_type='Revenue',
                    normal_balance='Credit', is_active=True)
    db_session.add(group)
    db_session.commit()
    leaf = Account(code=code, name=name, account_type='Revenue',
                   normal_balance='Credit', is_active=True, parent_id=group.id)
    db_session.add(leaf)
    db_session.commit()
    return leaf


def _asset_leaf(db_session, code='1001', name='Cash on Hand'):
    group = Account(code='1000', name='Assets', account_type='Asset',
                    normal_balance='Debit', is_active=True)
    db_session.add(group)
    db_session.commit()
    leaf = Account(code=code, name=name, account_type='Asset',
                   normal_balance='Debit', is_active=True, parent_id=group.id)
    db_session.add(leaf)
    db_session.commit()
    return leaf


def test_save_creates_new_lines(client, db_session, main_branch, admin_user, login_user):
    rev = _revenue_leaf(db_session)
    _login_admin(client, db_session, main_branch, login_user)

    resp = client.post('/budgeting/save', data={
        'fiscal_year': '2027',
        f'amount_{rev.id}_1': '15000.00',
        f'amount_{rev.id}_2': '16000.00',
    }, follow_redirects=True)
    assert resp.status_code == 200

    lines = BudgetLine.query.filter_by(branch_id=main_branch.id, fiscal_year=2027).all()
    by_month = {l.month: l.amount for l in lines}
    assert by_month[1] == Decimal('15000.00')
    assert by_month[2] == Decimal('16000.00')


def test_save_updates_existing_line(client, db_session, main_branch, admin_user, login_user):
    rev = _revenue_leaf(db_session)
    db_session.add(BudgetLine(branch_id=main_branch.id, account_id=rev.id,
                              fiscal_year=2027, month=1, amount=Decimal('1000')))
    db_session.commit()
    _login_admin(client, db_session, main_branch, login_user)

    client.post('/budgeting/save', data={
        'fiscal_year': '2027', f'amount_{rev.id}_1': '2500.00',
    }, follow_redirects=True)

    lines = BudgetLine.query.filter_by(branch_id=main_branch.id, fiscal_year=2027, month=1).all()
    assert len(lines) == 1
    assert lines[0].amount == Decimal('2500.00')


def test_save_deletes_cleared_line(client, db_session, main_branch, admin_user, login_user):
    rev = _revenue_leaf(db_session)
    db_session.add(BudgetLine(branch_id=main_branch.id, account_id=rev.id,
                              fiscal_year=2027, month=1, amount=Decimal('1000')))
    db_session.commit()
    _login_admin(client, db_session, main_branch, login_user)

    client.post('/budgeting/save', data={
        'fiscal_year': '2027', f'amount_{rev.id}_1': '',
    }, follow_redirects=True)

    assert BudgetLine.query.filter_by(
        branch_id=main_branch.id, fiscal_year=2027, month=1).first() is None


def test_save_rejects_negative_amount(client, db_session, main_branch, admin_user, login_user):
    rev = _revenue_leaf(db_session)
    _login_admin(client, db_session, main_branch, login_user)

    resp = client.post('/budgeting/save', data={
        'fiscal_year': '2027', f'amount_{rev.id}_1': '-500.00',
    }, follow_redirects=True)
    assert b'cannot be negative' in resp.data
    assert BudgetLine.query.filter_by(branch_id=main_branch.id, fiscal_year=2027).count() == 0


def test_save_rejects_ineligible_account(client, db_session, main_branch, admin_user, login_user):
    asset = _asset_leaf(db_session)
    _login_admin(client, db_session, main_branch, login_user)

    resp = client.post('/budgeting/save', data={
        'fiscal_year': '2027', f'amount_{asset.id}_1': '500.00',
    }, follow_redirects=True)
    assert b'postable Revenue/Expense account' in resp.data
    assert BudgetLine.query.count() == 0


def test_save_branch_isolation(client, db_session, main_branch, branch_manila, admin_user,
                               login_user):
    rev = _revenue_leaf(db_session)
    db_session.add(BudgetLine(branch_id=branch_manila.id, account_id=rev.id,
                              fiscal_year=2027, month=1, amount=Decimal('9999')))
    db_session.commit()
    _login_admin(client, db_session, main_branch, login_user)

    client.post('/budgeting/save', data={
        'fiscal_year': '2027', f'amount_{rev.id}_1': '1000.00',
    }, follow_redirects=True)

    manila_line = BudgetLine.query.filter_by(
        branch_id=branch_manila.id, fiscal_year=2027, month=1).first()
    assert manila_line.amount == Decimal('9999')  # untouched by main_branch's save


def test_save_preserves_lines_for_deactivated_account(client, db_session, main_branch,
                                                       admin_user, login_user):
    rev = _revenue_leaf(db_session)
    db_session.add(BudgetLine(branch_id=main_branch.id, account_id=rev.id,
                              fiscal_year=2027, month=1, amount=Decimal('1000')))
    db_session.commit()
    rev.is_active = False
    db_session.commit()
    _login_admin(client, db_session, main_branch, login_user)

    # The now-inactive account no longer appears in the grid, so the submitted
    # form carries no amount_<rev.id>_* field at all -- same as a real browser save.
    client.post('/budgeting/save', data={'fiscal_year': '2027'}, follow_redirects=True)

    line = BudgetLine.query.filter_by(branch_id=main_branch.id, fiscal_year=2027, month=1).first()
    assert line is not None
    assert line.amount == Decimal('1000')


def test_save_logs_audit_entry(client, db_session, main_branch, admin_user, login_user):
    rev = _revenue_leaf(db_session)
    _login_admin(client, db_session, main_branch, login_user)

    client.post('/budgeting/save', data={
        'fiscal_year': '2027', f'amount_{rev.id}_1': '5000.00',
    }, follow_redirects=True)

    entry = AuditLog.query.filter_by(module='budgeting', action='update').first()
    assert entry is not None
    assert 'FY2027' in entry.record_identifier


def test_save_requires_admin_or_chief_accountant(client, db_session, main_branch, staff_user,
                                                  login_user):
    # full_access_required redirects to dashboard.index (no flash rendering there) --
    # a 302 (not the save actually happening) is the proof of denial here.
    staff_user.set_branches([main_branch])
    db_session.commit()
    _enable_budgeting(db_session)
    login_user(client, 'staff', 'staff123')
    resp = client.post('/budgeting/save', data={'fiscal_year': '2027'})
    assert resp.status_code == 302
