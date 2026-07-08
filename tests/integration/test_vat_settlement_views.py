import pytest
from decimal import Decimal
from datetime import date

from app import db
from app.vat_settlement.models import VatSettlement
from tests.integration.test_vat_settlement_compute import _vat_world, _je

pytestmark = [pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def test_index_renders(client, db_session, main_branch, admin_user):
    _vat_world(main_branch); db.session.commit()
    login(client)
    resp = client.get('/vat-settlement')
    assert resp.status_code == 200
    assert b'VAT Settlement' in resp.data


def test_settle_via_route(client, db_session, main_branch, admin_user):
    w = _vat_world(main_branch)
    _je(main_branch.id, date(2025, 7, 10), [(w['ar'].id, 120000, 0), (w['out'].id, 0, 120000)])
    _je(main_branch.id, date(2025, 8, 10), [(w['inp'].id, 50000, 0), (w['ap'].id, 0, 50000)])
    db.session.commit()
    login(client)
    resp = client.post('/vat-settlement/settle',
                       data={'year': '2025', 'quarter': '3'}, follow_redirects=True)
    assert resp.status_code == 200
    s = VatSettlement.query.filter_by(fiscal_year=2025, quarter=3).first()
    assert s is not None and s.status == 'settled'


def test_staff_denied(client, db_session, main_branch, staff_user):
    _vat_world(main_branch); db.session.commit()
    login(client, 'staff', 'staff123')
    resp = client.post('/vat-settlement/settle',
                       data={'year': '2025', 'quarter': '3'}, follow_redirects=True)
    assert VatSettlement.query.filter_by(fiscal_year=2025, quarter=3).first() is None


def test_assign_vat_accounts_saves_settings(client, db_session, main_branch, admin_user):
    from app.settings import AppSettings
    from app.accounts.models import Account
    _vat_world(main_branch); db.session.commit()
    login(client)
    pay = Account.query.filter_by(code='20202').first()
    carry = Account.query.filter_by(code='10505').first()
    resp = client.post('/vat-settlement/accounts',
                       data={'vat_payable_account_code': pay.code,
                             'input_vat_carryover_account_code': carry.code},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert AppSettings.get_setting('vat_payable_account_code') == '20202'
    assert AppSettings.get_setting('input_vat_carryover_account_code') == '10505'


def test_index_prompts_when_unassigned(client, db_session, main_branch, admin_user):
    from app.settings import AppSettings
    _vat_world(main_branch)
    AppSettings.query.filter(AppSettings.key.in_(
        ['vat_payable_account_code', 'input_vat_carryover_account_code'])).delete(
        synchronize_session=False)
    db.session.commit()
    login(client)
    resp = client.get('/vat-settlement')
    assert resp.status_code == 200
    assert b'assign' in resp.data.lower()
