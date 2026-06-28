"""Integration tests for Books of Accounts Print-All and Export-All (Task 8)."""
from io import BytesIO

import pytest
from openpyxl import load_workbook

from app import db
from app.settings import AppSettings

pytestmark = [pytest.mark.integration]


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def _set_company():
    db.session.add(AppSettings(key='company_name', value='Acme Trading Inc.'))
    db.session.commit()


def test_print_all_renders_six_sections(client, db_session, main_branch, admin_user):
    _set_company()
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get(
        '/reports/books-of-accounts/print-all?date_from=2026-01-01&date_to=2026-12-31'
    )
    assert resp.status_code == 200
    for t in [b'GENERAL JOURNAL', b'GENERAL LEDGER', b'SALES JOURNAL',
              b'PURCHASE JOURNAL', b'CASH RECEIPTS BOOK', b'CASH DISBURSEMENTS BOOK']:
        assert t in resp.data
    assert resp.data.count(b'page-break-before') >= 5


def test_export_all_has_six_sheets(client, db_session, main_branch, admin_user):
    _set_company()
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get(
        '/reports/books-of-accounts/export-all?date_from=2026-01-01&date_to=2026-12-31'
    )
    assert resp.status_code == 200
    wb = load_workbook(BytesIO(resp.data))
    assert set(wb.sheetnames) == {
        'General Journal', 'General Ledger', 'Sales Journal',
        'Purchase Journal', 'Cash Receipts Book', 'Cash Disbursements Book',
    }


def test_print_all_requires_login(client, db_session):
    resp = client.get('/reports/books-of-accounts/print-all')
    assert resp.status_code in (302, 401)


def test_export_all_requires_login(client, db_session):
    resp = client.get('/reports/books-of-accounts/export-all')
    assert resp.status_code in (302, 401)


def test_print_all_requires_accountant_or_admin(client, db_session, main_branch, staff_user):
    _login(client, staff_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/books-of-accounts/print-all', follow_redirects=False)
    assert resp.status_code == 302


def test_export_all_requires_accountant_or_admin(client, db_session, main_branch, staff_user):
    _login(client, staff_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/books-of-accounts/export-all', follow_redirects=False)
    assert resp.status_code == 302
