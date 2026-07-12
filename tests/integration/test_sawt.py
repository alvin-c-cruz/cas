import pytest
from datetime import date
from decimal import Decimal

from app import db
from app.withholding_certificates.service import get_sawt, reconcile_sawt

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def _fresh_module_cache(db_session):
    # This file's pages are gated behind bir_reports, which now defaults OFF (registry
    # flip, chore/bir-reports-default-off) -- explicitly enable it so the routes aren't
    # 404'd. Matches the pattern in test_bir_2307.py.
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:bir_reports', '1', updated_by='test')
    clear_module_config_cache(); yield; clear_module_config_cache()


def _login(client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'},
                follow_redirects=True)


def _customer(code='SAWT-C'):
    from app.customers.models import Customer
    c = Customer(code=code, name=f'Customer {code}', tin='111-222-333-000', is_active=True)
    db.session.add(c); db.session.commit()
    return c


def _wt(code='WC158', rate=2):
    from app.withholding_tax.models import WithholdingTax
    wt = WithholdingTax(code=code, name=code, rate=Decimal(str(rate)), tax_type='expanded')
    db.session.add(wt); db.session.commit()
    return wt


def _register_cert(branch, cust, wt, income, tax):
    from app.withholding_certificates.models import WithholdingCertificateReceived
    rec = WithholdingCertificateReceived(
        branch_id=branch.id, customer_id=cust.id, certificate_number=f'2307-{cust.code}',
        date_received=date(2025, 10, 5), period_from=date(2025, 7, 1),
        period_to=date(2025, 9, 30), wt_id=wt.id,
        income_payment=Decimal(str(income)), tax_withheld=Decimal(str(tax)))
    db.session.add(rec); db.session.commit()
    return rec


def _booked_payee_wht(branch, cash_acct, rev_acct, cust, wt, income, tax):
    """A posted CRV whose revenue line records WHT the customer withheld from us."""
    from app.cash_receipts.models import CashReceiptVoucher, CRVRevenueLine
    crv = CashReceiptVoucher(
        branch_id=branch.id, crv_number=f'CRV-{cust.code}', crv_date=date(2025, 8, 10),
        customer_id=cust.id, customer_name=cust.name, customer_tin=cust.tin,
        cash_account_id=cash_acct.id, status='posted')
    crv.revenue_lines.append(CRVRevenueLine(
        line_number=1, description='sale', amount=Decimal(str(income)),
        vat_rate=Decimal('0'), vat_amount=Decimal('0.00'), line_total=Decimal(str(income)),
        wt_id=wt.id, wt_rate=wt.rate, wt_amount=Decimal(str(tax)), account_id=rev_acct.id))
    db.session.add(crv); db.session.commit()
    return crv


def test_sawt_renders_from_register(db_session, main_branch):
    cust, wt = _customer(), _wt()
    _register_cert(main_branch, cust, wt, 50000, 1000)
    s = get_sawt(2025, 3)
    assert len(s['rows']) == 1
    assert s['rows'][0]['tax_withheld'] == Decimal('1000.00')
    assert s['total_tax'] == Decimal('1000.00')


def test_sawt_ignores_books(db_session, main_branch, cash_account, revenue_account):
    # A booked payee WHT with NO certificate must NOT appear in the SAWT.
    cust, wt = _customer(), _wt()
    _booked_payee_wht(main_branch, cash_account, revenue_account, cust, wt, 50000, 1000)
    s = get_sawt(2025, 3)
    assert s['rows'] == []


def test_reconciliation_flags_booked_no_cert(db_session, main_branch, cash_account, revenue_account):
    cust, wt = _customer(), _wt()
    _booked_payee_wht(main_branch, cash_account, revenue_account, cust, wt, 50000, 1000)
    rec = reconcile_sawt(2025, 3)
    assert len(rec['booked_no_cert']) == 1
    assert rec['booked_no_cert'][0]['booked_tax'] == Decimal('1000.00')
    assert rec['cert_not_booked'] == []


def test_reconciliation_flags_cert_not_booked(db_session, main_branch):
    cust, wt = _customer(), _wt()
    _register_cert(main_branch, cust, wt, 50000, 1000)
    rec = reconcile_sawt(2025, 3)
    assert len(rec['cert_not_booked']) == 1
    assert rec['booked_no_cert'] == []


def test_reconciliation_flags_amount_mismatch(db_session, main_branch, cash_account, revenue_account):
    cust, wt = _customer(), _wt()
    _booked_payee_wht(main_branch, cash_account, revenue_account, cust, wt, 50000, 1000)
    _register_cert(main_branch, cust, wt, 50000, 800)   # cert says 800, books say 1000
    rec = reconcile_sawt(2025, 3)
    assert len(rec['amount_mismatch']) == 1
    m = rec['amount_mismatch'][0]
    assert m['booked_tax'] == Decimal('1000.00') and m['cert_tax'] == Decimal('800.00')
    assert m['delta'] == Decimal('200.00')


def test_sawt_and_reconciliation_pages_render(client, db_session, main_branch, admin_user):
    cust, wt = _customer(), _wt()
    _register_cert(main_branch, cust, wt, 50000, 1000)
    _login(client)
    r1 = client.get('/withholding-certificates/sawt?year=2025&quarter=3')
    assert r1.status_code == 200
    assert b'Customer SAWT-C' in r1.data
    r2 = client.get('/withholding-certificates/reconciliation?year=2025&quarter=3')
    assert r2.status_code == 200
