from datetime import date
from decimal import Decimal
import pytest

from app import db
from app.journal_entries.models import JournalEntry, JournalEntryLine

pytestmark = [pytest.mark.integration]


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def _post_je(branch_id, account, contra, when, number):
    je = JournalEntry(entry_number=number, entry_date=when, description='d',
                      reference=number, entry_type='adjustment', branch_id=branch_id,
                      status='posted', is_balanced=True,
                      total_debit=Decimal('100'), total_credit=Decimal('100'))
    db.session.add(je)
    db.session.flush()
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=1, account_id=account.id,
                                    debit_amount=Decimal('100'), credit_amount=Decimal('0'),
                                    description='dr'))
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=2, account_id=contra.id,
                                    debit_amount=Decimal('0'), credit_amount=Decimal('100'),
                                    description='cr'))
    db.session.commit()
    return je


def test_trial_balance_requires_login(client):
    resp = client.get('/reports/trial-balance')
    assert resp.status_code in (302, 401)


def test_trial_balance_no_longer_redirects_to_under_development(client, db_session, main_branch,
                                                                admin_user):
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/trial-balance', follow_redirects=False)
    # 200 (not a 302 redirect to the under-development page) proves the view is un-stubbed.
    assert resp.status_code == 200
    assert b'Trial Balance' in resp.data


def test_trial_balance_admin_renders_balanced(client, db_session, main_branch, admin_user,
                                              cash_account, revenue_account):
    _post_je(main_branch.id, cash_account, revenue_account, date.today(), 'JE-TB1')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/trial-balance')
    assert resp.status_code == 200
    assert b'Trial Balance' in resp.data
    assert cash_account.code.encode() in resp.data
    assert b'Balanced' in resp.data            # balanced banner


def test_trial_balance_staff_without_grant_denied(client, db_session, main_branch, staff_user):
    staff_user.branches.append(main_branch)
    db_session.commit()
    _login(client, staff_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/trial-balance', follow_redirects=False)
    assert resp.status_code == 302          # module gate denies ungranted staff


def test_trial_balance_staff_with_grant_allowed(client, db_session, main_branch, staff_user):
    perms = staff_user.get_book_permissions()
    perms['trial_balance'] = True
    staff_user.set_book_permissions(perms)
    staff_user.branches.append(main_branch)
    db_session.commit()
    _login(client, staff_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/trial-balance', follow_redirects=False)
    assert resp.status_code == 200


def test_trial_balance_viewer_allowed(client, db_session, main_branch, viewer_user):
    viewer_user.branches.append(main_branch)
    db_session.commit()
    _login(client, viewer_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/trial-balance', follow_redirects=False)
    assert resp.status_code == 200


def test_trial_balance_excel_export(client, db_session, main_branch, admin_user,
                                    cash_account, revenue_account):
    _post_je(main_branch.id, cash_account, revenue_account, date.today(), 'JE-TB2')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/trial-balance/export/excel')
    assert resp.status_code == 200
    assert 'spreadsheetml' in resp.headers['Content-Type']


def test_trial_balance_csv_export(client, db_session, main_branch, admin_user,
                                  cash_account, revenue_account):
    _post_je(main_branch.id, cash_account, revenue_account, date.today(), 'JE-TB3')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/trial-balance/export/csv')
    assert resp.status_code == 200
    assert 'text/csv' in resp.headers['Content-Type']
    assert cash_account.code.encode() in resp.data


def test_trial_balance_print_renders(client, db_session, main_branch, admin_user,
                                     cash_account, revenue_account):
    from app.settings import AppSettings
    AppSettings.set_setting('company_name', 'ACME Trading Corp')
    _post_je(main_branch.id, cash_account, revenue_account, date.today(), 'JE-TB4')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/trial-balance/print')
    assert resp.status_code == 200
    assert b'Trial Balance' in resp.data
    assert b'ACME Trading Corp' in resp.data
