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


def _post(branch_id, debit_acct, credit_acct, amount, number):
    """Balanced posted JE: debit one account, credit the other."""
    amt = Decimal(str(amount))
    je = JournalEntry(entry_number=number, entry_date=date.today(), description='d',
                      reference=number, entry_type='adjustment', branch_id=branch_id,
                      status='posted', is_balanced=True, total_debit=amt, total_credit=amt)
    db.session.add(je)
    db.session.flush()
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=1, account_id=debit_acct.id,
                                    debit_amount=amt, credit_amount=Decimal('0')))
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=2, account_id=credit_acct.id,
                                    debit_amount=Decimal('0'), credit_amount=amt))
    db.session.commit()
    return je


def _seed_pl(branch_id, cash, revenue, expense):
    # Revenue 100 (credit 4xxxx); Expense 40 (debit 5xxxx) -> net income +60.
    _post(branch_id, cash, revenue, 100, 'IS-REV')
    _post(branch_id, expense, cash, 40, 'IS-EXP')


def test_income_statement_requires_login(client):
    resp = client.get('/reports/income-statement')
    assert resp.status_code in (302, 401)


def test_income_statement_no_longer_redirects(client, db_session, main_branch, admin_user):
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/income-statement', follow_redirects=False)
    assert resp.status_code == 200
    assert b'Income Statement' in resp.data


def test_income_statement_admin_renders(client, db_session, main_branch, admin_user,
                                        cash_account, revenue_account, expense_account):
    _seed_pl(main_branch.id, cash_account, revenue_account, expense_account)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/income-statement')
    assert resp.status_code == 200
    assert revenue_account.code.encode() in resp.data        # 4xxxx revenue (child, in markup)
    assert expense_account.code.encode() in resp.data        # 5xxxx expense (child, in markup)
    assert b'NET INCOME' in resp.data
    assert b'Gross Profit' in resp.data                       # P&L subtotal
    assert b'Operating Income' in resp.data                  # P&L subtotal
    assert b'Net Margin' in resp.data                         # net income line (positive revenue)


def test_income_statement_staff_without_grant_denied(client, db_session, main_branch, staff_user):
    staff_user.branches.append(main_branch)
    db_session.commit()
    _login(client, staff_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/income-statement', follow_redirects=False)
    assert resp.status_code == 302


def test_income_statement_staff_with_grant_allowed(client, db_session, main_branch, staff_user):
    perms = staff_user.get_book_permissions()
    perms['income_statement'] = True
    staff_user.set_book_permissions(perms)
    staff_user.branches.append(main_branch)
    db_session.commit()
    _login(client, staff_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/income-statement', follow_redirects=False)
    assert resp.status_code == 200


def test_income_statement_viewer_allowed(client, db_session, main_branch, viewer_user):
    viewer_user.branches.append(main_branch)
    db_session.commit()
    _login(client, viewer_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/income-statement', follow_redirects=False)
    assert resp.status_code == 200


def test_income_statement_excel_export(client, db_session, main_branch, admin_user,
                                       cash_account, revenue_account, expense_account):
    _seed_pl(main_branch.id, cash_account, revenue_account, expense_account)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/income-statement/export/excel')
    assert resp.status_code == 200
    assert 'spreadsheetml' in resp.headers['Content-Type']


def test_income_statement_csv_export(client, db_session, main_branch, admin_user,
                                     cash_account, revenue_account, expense_account):
    _seed_pl(main_branch.id, cash_account, revenue_account, expense_account)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/income-statement/export/csv')
    assert resp.status_code == 200
    assert 'text/csv' in resp.headers['Content-Type']
    assert revenue_account.code.encode() in resp.data


def test_income_statement_print_renders(client, db_session, main_branch, admin_user,
                                        cash_account, revenue_account, expense_account):
    from app.settings import AppSettings
    AppSettings.set_setting('company_name', 'ACME Trading Corp')
    _seed_pl(main_branch.id, cash_account, revenue_account, expense_account)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/income-statement/print')
    assert resp.status_code == 200
    assert b'Income Statement' in resp.data
    assert b'ACME Trading Corp' in resp.data


def test_income_statement_defaults_to_year_to_date(client, db_session, main_branch, admin_user):
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/income-statement')
    assert resp.status_code == 200
    jan1 = f'{date.today().year}-01-01'
    assert f'value="{jan1}"'.encode() in resp.data           # start_date defaults to Jan 1
