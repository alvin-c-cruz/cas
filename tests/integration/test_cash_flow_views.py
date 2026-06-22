from datetime import date
from decimal import Decimal
import pytest

from app import db
from app.accounts.models import Account
from app.journal_entries.models import JournalEntry, JournalEntryLine

pytestmark = [pytest.mark.integration]


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def _acct(code, name, atype, normal='Debit', parent=None):
    a = Account(code=code, name=name, account_type=atype, normal_balance=normal,
                is_active=True, parent_id=parent.id if parent else None)
    db.session.add(a)
    db.session.commit()
    return a


def _je(branch_id, lines, number):
    je = JournalEntry(entry_number=number, entry_date=date.today(), description='d',
                      reference=number, entry_type='adjustment', branch_id=branch_id,
                      status='posted', is_balanced=True, total_debit=Decimal('0'),
                      total_credit=Decimal('0'))
    db.session.add(je)
    db.session.flush()
    n = 1
    for acct, dr, cr in lines:
        db.session.add(JournalEntryLine(entry_id=je.id, line_number=n, account_id=acct.id,
                                        debit_amount=Decimal(str(dr)), credit_amount=Decimal(str(cr))))
        n += 1
    db.session.commit()
    return je


def _seed_cf(branch_id):
    ca = _acct('10000', 'CURRENT ASSETS', 'Asset')
    cash = _acct('10101', 'Cash on Hand', 'Asset', parent=ca)
    eq = _acct('30000', 'EQUITY', 'Equity', 'Credit')
    cap = _acct('30101', 'Capital Stock', 'Equity', 'Credit', parent=eq)
    _je(branch_id, [(cash, 1000, 0), (cap, 0, 1000)], 'CF1')


def test_cash_flow_requires_login(client):
    resp = client.get('/reports/cash-flow')
    assert resp.status_code in (302, 401)


def test_cash_flow_admin_renders(client, db_session, main_branch, admin_user):
    _seed_cf(main_branch.id)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/cash-flow')
    assert resp.status_code == 200
    body = resp.data
    assert b'CASH FLOWS FROM OPERATING ACTIVITIES' in body
    assert b'INVESTING' in body
    assert b'FINANCING' in body
    assert b'NET INCREASE' in body
    assert b'Reconciled' in body


def test_cash_flow_staff_without_grant_denied(client, db_session, main_branch, staff_user):
    staff_user.branches.append(main_branch)
    db_session.commit()
    _login(client, staff_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/cash-flow', follow_redirects=False)
    assert resp.status_code == 302


def test_cash_flow_staff_with_grant_allowed(client, db_session, main_branch, staff_user):
    perms = staff_user.get_book_permissions()
    perms['cash_flow'] = True
    staff_user.set_book_permissions(perms)
    staff_user.branches.append(main_branch)
    db_session.commit()
    _login(client, staff_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/cash-flow', follow_redirects=False)
    assert resp.status_code == 200


def test_cash_flow_viewer_allowed(client, db_session, main_branch, viewer_user):
    viewer_user.branches.append(main_branch)
    db_session.commit()
    _login(client, viewer_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/cash-flow', follow_redirects=False)
    assert resp.status_code == 200


def test_cash_flow_excel_export(client, db_session, main_branch, admin_user):
    _seed_cf(main_branch.id)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/cash-flow/export/excel')
    assert resp.status_code == 200
    assert 'spreadsheetml' in resp.headers['Content-Type']


def test_cash_flow_print_renders(client, db_session, main_branch, admin_user):
    from app.settings import AppSettings
    AppSettings.set_setting('company_name', 'ACME Trading Corp')
    _seed_cf(main_branch.id)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/cash-flow/print')
    assert resp.status_code == 200
    assert b'Statement of Cash Flows' in resp.data
    assert b'ACME Trading Corp' in resp.data
