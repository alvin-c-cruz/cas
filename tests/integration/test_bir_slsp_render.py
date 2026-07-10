"""
Integration tests: BIR Summary List of Sales / Purchases pages render (not 500).
"""
import pytest

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


def test_bir_sales_page_renders(client, db_session, main_branch, admin_user):
    _set_company()
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/bir/sales')
    assert resp.status_code == 200
    assert b'Summary List of Sales' in resp.data


def test_bir_purchases_page_renders(client, db_session, main_branch, admin_user):
    _set_company()
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/bir/purchases')
    assert resp.status_code == 200
    assert b'Summary List of Purchases' in resp.data


def test_bir_sales_page_renders_with_unclassified_banner(
        client, db_session, main_branch, admin_user, posted_si_no_category):
    """R-08 Task 9: a populated SLS page (real vat_lines() data, including an
    unclassified line) must render without crashing and must surface the
    unclassified banner -- no currency symbol anywhere in the response."""
    _set_company()
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/bir/sales?year=2026&month=2')
    assert resp.status_code == 200
    assert b'could not be classified for BIR' in resp.data
    assert '₱'.encode('utf-8') not in resp.data
    assert b'$' not in resp.data


def test_bir_purchases_page_renders_with_unclassified_banner(
        client, db_session, main_branch, admin_user, posted_ap_no_category):
    """R-08 Task 9: same as above for SLP."""
    _set_company()
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/bir/purchases?year=2026&month=2')
    assert resp.status_code == 200
    assert b'could not be classified for BIR' in resp.data
    assert '₱'.encode('utf-8') not in resp.data
    assert b'$' not in resp.data
