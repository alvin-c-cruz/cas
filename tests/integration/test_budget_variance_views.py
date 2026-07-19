import pytest
from datetime import date
from decimal import Decimal

from app import db
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache
from app.accounts.models import Account
from app.budgeting.models import BudgetLine
from app.journal_entries.models import JournalEntry, JournalEntryLine

pytestmark = [pytest.mark.integration]


def _enable_budgeting(db_session):
    AppSettings.set_setting('module_enabled:budgeting', '1')
    db_session.commit()
    clear_module_config_cache()


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def _revenue_leaf(db_session, code='4001', name='Sales Revenue'):
    group = Account(code='4000', name='Revenue', account_type='Revenue',
                    normal_balance='Credit', is_active=True)
    db_session.add(group)
    db_session.commit()
    leaf = Account(code=code, name=name, account_type='Revenue',
                   normal_balance='Credit', is_active=True, parent_id=group.id)
    db_session.add(leaf)
    db_session.commit()
    return leaf


def _je(db_session, branch_id, account, debit, credit, entry_date, number):
    je = JournalEntry(entry_number=number, entry_date=entry_date, description='d',
                      reference=number, entry_type='adjustment', branch_id=branch_id,
                      status='posted', is_balanced=True, total_debit=Decimal('0'),
                      total_credit=Decimal('0'))
    db_session.add(je)
    db_session.flush()
    db_session.add(JournalEntryLine(entry_id=je.id, line_number=1, account_id=account.id,
                                    debit_amount=Decimal(str(debit)), credit_amount=Decimal(str(credit))))
    db_session.commit()


def test_screen_shows_budget_actual_variance(client, db_session, main_branch, admin_user,
                                             login_user):
    _enable_budgeting(db_session)
    rev = _revenue_leaf(db_session)
    db_session.add(BudgetLine(branch_id=main_branch.id, account_id=rev.id,
                              fiscal_year=2027, month=3, amount=Decimal('10000')))
    db_session.commit()
    _je(db_session, main_branch.id, rev, 0, 12000, date(2027, 3, 15), 'JE-1')

    login_user(client, 'admin', 'admin123')
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/budget-variance?fiscal_year=2027&month=3')
    assert resp.status_code == 200
    assert b'Sales Revenue' in resp.data
    assert b'10,000.00' in resp.data
    assert b'12,000.00' in resp.data


def test_print_renders(client, db_session, main_branch, admin_user, login_user):
    _enable_budgeting(db_session)
    _revenue_leaf(db_session)
    login_user(client, 'admin', 'admin123')
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/budget-variance/print?fiscal_year=2027&month=3')
    assert resp.status_code == 200


def test_excel_export_downloads(client, db_session, main_branch, admin_user, login_user):
    _enable_budgeting(db_session)
    _revenue_leaf(db_session)
    login_user(client, 'admin', 'admin123')
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/budget-variance/export/excel?fiscal_year=2027&month=3')
    assert resp.status_code == 200
    assert 'spreadsheet' in resp.headers.get('Content-Type', '')


def test_routes_404_when_module_off(client, db_session, main_branch, admin_user, login_user):
    AppSettings.set_setting('module_enabled:budgeting', '0')
    db_session.commit()
    clear_module_config_cache()
    login_user(client, 'admin', 'admin123')
    resp = client.get('/reports/budget-variance')
    assert resp.status_code == 404


def test_denies_staff(client, db_session, main_branch, staff_user, login_user):
    _enable_budgeting(db_session)
    staff_user.set_branches([main_branch])
    db_session.commit()
    login_user(client, 'staff', 'staff123')
    resp = client.get('/reports/budget-variance')
    assert resp.status_code == 302  # full_access_required denies


def test_allows_chief_accountant(client, db_session, main_branch, chief_accountant_user,
                                 login_user):
    _enable_budgeting(db_session)
    login_user(client, 'chief', 'chief123')
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/budget-variance')
    assert resp.status_code == 200


def test_grid_links_to_variance_report(client, db_session, main_branch, admin_user, login_user):
    _enable_budgeting(db_session)
    login_user(client, 'admin', 'admin123')
    _select_branch(client, main_branch.id)
    resp = client.get('/budgeting')
    assert b'/reports/budget-variance' in resp.data
