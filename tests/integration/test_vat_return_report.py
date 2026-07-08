import pytest
from decimal import Decimal
from datetime import date

from app import db
from app.reports.bir import get_vat_return_summary
from tests.integration.test_vat_settlement_compute import _vat_world, _je

pytestmark = [pytest.mark.integration]


def test_vat_return_summary_payable(db_session, main_branch):
    w = _vat_world(main_branch)
    _je(main_branch.id, date(2025, 7, 10), [(w['ar'].id, 120000, 0), (w['out'].id, 0, 120000)])
    _je(main_branch.id, date(2025, 8, 10), [(w['inp'].id, 50000, 0), (w['ap'].id, 0, 50000)])
    db.session.commit()
    r = get_vat_return_summary(2025, 3)
    assert r['output_vat'] == Decimal('120000.00')
    assert r['input_vat'] == Decimal('50000.00')
    assert r['net_payable'] == Decimal('70000.00')
    assert r['new_carryover'] == Decimal('0.00')
    assert 'error' not in r


def test_vat_return_page_renders(client, db_session, main_branch, admin_user):
    _vat_world(main_branch); db.session.commit()
    client.post('/login', data={'username': 'admin', 'password': 'admin123'},
                follow_redirects=True)
    resp = client.get('/reports/bir/vat-return?year=2025&quarter=3')
    assert resp.status_code == 200
    assert b'VAT' in resp.data
