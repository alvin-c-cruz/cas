import pytest
from datetime import date
from decimal import Decimal

from app import db
from tests.unit.test_alphalist_wht_lines import _wt, _vendor, _posted_cdv_wht

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def _fresh_module_cache(db_session):
    # bir_reports now defaults OFF (registry flip, chore/bir-reports-default-off) and is
    # read through an app-level cache not reset per test; a sibling test that disables it
    # can also leak a stale '0'. Explicitly enable it and clear the cache before/after so
    # each test in this file (which exercises the BIR pages themselves) reads it as ON.
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:bir_reports', '1', updated_by='test')
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'},
                follow_redirects=True)


# --- Task 2: Alphalist / QAP page ------------------------------------------

def test_alphalist_page_renders_with_cdv_payee(client, db_session, main_branch,
                                               cash_account, revenue_account, admin_user):
    wt = _wt('WC158', 2); v = _vendor('CDVP')
    _posted_cdv_wht(main_branch, cash_account, revenue_account, v, wt, 10000, 200)
    _login(client)
    resp = client.get('/reports/bir/alphalist?year=2025&quarter=3')
    assert resp.status_code == 200
    assert b'Vendor CDVP' in resp.data


def test_alphalist_shows_final_tax_advisory(client, db_session, main_branch,
                                            cash_account, revenue_account, admin_user):
    fwt = _wt('WI999', 15, tax_type='final'); v = _vendor('FIN')
    _posted_cdv_wht(main_branch, cash_account, revenue_account, v, fwt, 10000, 1500)
    _login(client)
    resp = client.get('/reports/bir/alphalist?year=2025&quarter=3')
    assert resp.status_code == 200
    assert b'final-tax' in resp.data.lower()


# --- Task 4: BIR 2307 issued -----------------------------------------------

def test_2307_index_lists_vendor(client, db_session, main_branch, cash_account,
                                 revenue_account, admin_user):
    wt = _wt('WC158', 2); v = _vendor('CERT')
    _posted_cdv_wht(main_branch, cash_account, revenue_account, v, wt, 10000, 200)
    _login(client)
    resp = client.get('/reports/bir/2307?year=2025&quarter=3')
    assert resp.status_code == 200
    assert b'Vendor CERT' in resp.data


def test_2307_certificate_prints_for_vendor(client, db_session, main_branch, cash_account,
                                            revenue_account, admin_user):
    wt = _wt('WC158', 2); v = _vendor('CERT')
    _posted_cdv_wht(main_branch, cash_account, revenue_account, v, wt, 10000, 200)
    _login(client)
    resp = client.get(f'/reports/bir/2307/print?year=2025&quarter=3&vendor_id={v.id}')
    assert resp.status_code == 200
    assert b'2307' in resp.data
    assert b'Vendor CERT' in resp.data
    assert b'WC158' in resp.data
    assert b'200.00' in resp.data


def test_2307_builder_three_month_breakdown(db_session, main_branch, cash_account, revenue_account):
    from app.reports.bir import get_2307_certificates
    wt = _wt('WC158', 2); v = _vendor('CERT')
    # two CDVs in different months of Q3 (Jul, Aug)
    _posted_cdv_wht(main_branch, cash_account, revenue_account, v, wt, 10000, 200,
                    when=date(2025, 7, 5))
    _posted_cdv_wht(main_branch, cash_account, revenue_account, v, wt, 20000, 400,
                    when=date(2025, 8, 5))
    certs = get_2307_certificates(2025, 3)
    assert len(certs) == 1
    cert = certs[0]
    assert cert['vendor_name'] == 'Vendor CERT'
    atc = cert['atc_rows'][0]
    assert atc['atc_code'] == 'WC158'
    assert atc['m1'] == Decimal('10000.00')   # July income payment
    assert atc['m2'] == Decimal('20000.00')   # August
    assert atc['total_tax'] == Decimal('600.00')


# --- Task 3: BIR reports landing -------------------------------------------

def test_bir_index_renders_with_report_links(client, db_session, main_branch, admin_user):
    _login(client)
    resp = client.get('/reports/bir')
    assert resp.status_code == 200
    for link in (b'/reports/bir/sales', b'/reports/bir/purchases',
                 b'/reports/bir/vat-return', b'/reports/bir/alphalist',
                 b'/reports/bir/2307'):
        assert link in resp.data, link
