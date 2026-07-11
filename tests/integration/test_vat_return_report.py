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


def test_vat_return_summary_for_settled_quarter_uses_snapshot(db_session, main_branch, admin_user):
    from app.vat_settlement import service
    w = _vat_world(main_branch)
    _je(main_branch.id, date(2025, 7, 10), [(w['ar'].id, 120000, 0), (w['out'].id, 0, 120000)])
    _je(main_branch.id, date(2025, 8, 10), [(w['inp'].id, 50000, 0), (w['ap'].id, 0, 50000)])
    db.session.commit()
    service.settle_quarter(2025, 3, admin_user.id); db.session.commit()
    r = get_vat_return_summary(2025, 3)
    assert 'error' not in r
    assert r['net_payable'] == Decimal('70000.00')
    assert r['output_vat'] == Decimal('120000.00') and r['input_vat'] == Decimal('50000.00')


def test_vat_return_page_renders(client, db_session, main_branch, admin_user):
    _vat_world(main_branch); db.session.commit()
    client.post('/login', data={'username': 'admin', 'password': 'admin123'},
                follow_redirects=True)
    resp = client.get('/reports/bir/vat-return?year=2025&quarter=3')
    assert resp.status_code == 200
    assert b'VAT' in resp.data


# --- Phase 2: 2550Q schedules + reconciliation -----------------------------

def _posted_crv_regular(branch, cash_acct, rev_acct):
    """A posted CRV with one regular-VAT revenue line (1200 output VAT)."""
    from app.customers.models import Customer
    from app.cash_receipts.models import CashReceiptVoucher, CRVRevenueLine
    cust = Customer(code='VR-2550', name='Cash Customer', tin='111-222-333-000',
                    address='1 Rizal St')
    db.session.add(cust); db.session.commit()
    crv = CashReceiptVoucher(
        branch_id=branch.id, crv_number='CRV-2550-0001', crv_date=date(2025, 8, 10),
        customer_id=cust.id, customer_name=cust.name, customer_tin=cust.tin,
        cash_account_id=cash_acct.id, status='posted')
    crv.revenue_lines.append(CRVRevenueLine(
        line_number=1, description='cash sale', amount=Decimal('11200.00'),
        vat_rate=Decimal('12.00'), vat_category='V12', vat_nature='regular',
        line_total=Decimal('11200.00'), vat_amount=Decimal('1200.00'),
        account_id=rev_acct.id))
    db.session.add(crv); db.session.commit()
    return crv


def test_summary_gains_schedules_and_reconciliation(db_session, main_branch,
                                                    cash_account, revenue_account):
    _posted_crv_regular(main_branch, cash_account, revenue_account)
    r = get_vat_return_summary(2025, 3)
    assert 'sales_schedule' in r and 'input_schedule' in r and 'reconciliation' in r
    row_12a = next(x for x in r['sales_schedule']['rows'] if x['box'] == '12A')
    assert row_12a['tax'] == Decimal('1200.00')
    assert r['reconciliation']['output_docs'] == Decimal('1200.00')


def test_summary_reconciliation_gl_unavailable_on_error(db_session, main_branch):
    # No VAT accounts / settlement settings -> compute_vat_position raises ->
    # summary carries an error, GL side is None, but schedules still render.
    r = get_vat_return_summary(2025, 3)
    assert r['reconciliation']['output_gl'] is None
    assert r['reconciliation']['in_balance'] is False
    assert 'sales_schedule' in r
