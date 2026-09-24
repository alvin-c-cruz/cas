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


# --- Employee payees (CV employee payee, 2026-09-24) ------------------------
# An employee-payee CDV carries vendor_id NULL. Groupings keyed on vendor_id
# collapsed every employee into ONE row/certificate keyed None, named after
# whichever line came first and with no address. They key on the payee now.

def _employee(no, first, last, address, branch):
    from app.employees.models import Employee
    e = Employee(employee_no=no, first_name=first, last_name=last,
                 address=address, tin=f'{no}-000', branch_id=branch.id)
    db.session.add(e); db.session.commit()
    return e


def _posted_employee_cdv_wht(branch, cash_acct, exp_acct, emp, wt, amount, wt_amount,
                             when=date(2025, 8, 10)):
    from app.cash_disbursements.models import CashDisbursementVoucher, CDVExpenseLine
    cdv = CashDisbursementVoucher(
        branch_id=branch.id,
        cdv_number=f'CDV-{emp.employee_no}-{when.strftime("%Y%m%d")}', cdv_date=when,
        payee_type='employee', payee_id=emp.id, vendor_id=None,
        vendor_name=emp.full_name, vendor_tin=emp.tin,
        cash_account_id=cash_acct.id, status='posted')
    cdv.expense_lines.append(CDVExpenseLine(
        line_number=1, description='svc', amount=Decimal(str(amount)),
        vat_rate=Decimal('0'), vat_amount=Decimal('0.00'),
        line_total=Decimal(str(amount)), wt_id=wt.id, wt_rate=wt.rate,
        wt_amount=Decimal(str(wt_amount)), account_id=exp_acct.id))
    db.session.add(cdv); db.session.commit()
    return cdv


def test_two_employees_get_two_2307s_and_two_alphalist_rows(
        client, db_session, main_branch, cash_account, revenue_account, admin_user):
    from app.reports.bir import get_2307_certificates, get_alphalist_of_payees
    wt = _wt('WC158', 2)
    ana = _employee('E-901', 'Ana', 'Reyes', '1 Mabini St', main_branch)
    ben = _employee('E-902', 'Ben', 'Santos', '2 Rizal Ave', main_branch)
    # A vendor whose id may equal an employee's id must stay a separate payee.
    v = _vendor('CTRL')
    _posted_employee_cdv_wht(main_branch, cash_account, revenue_account, ana, wt, 10000, 200)
    _posted_employee_cdv_wht(main_branch, cash_account, revenue_account, ben, wt, 20000, 400)
    _posted_cdv_wht(main_branch, cash_account, revenue_account, v, wt, 5000, 100)

    certs = {c['vendor_name']: c for c in get_2307_certificates(2025, 3)}
    assert set(certs) == {ana.full_name, ben.full_name, 'Vendor CTRL'}
    assert certs[ana.full_name]['vendor_address'] == '1 Mabini St'
    assert certs[ana.full_name]['total_tax'] == Decimal('200.00')
    assert certs[ben.full_name]['vendor_address'] == '2 Rizal Ave'
    assert certs[ben.full_name]['total_tax'] == Decimal('400.00')
    assert certs['Vendor CTRL']['vendor_id'] == v.id
    assert certs['Vendor CTRL']['vendor_address'] == '9 Ayala Ave'

    rows = {r['payee_name']: r for r in get_alphalist_of_payees(2025, 3)}
    assert rows[ana.full_name]['tax_withheld'] == Decimal('200.00')
    assert rows[ana.full_name]['payee_address'] == '1 Mabini St'
    assert rows[ben.full_name]['tax_withheld'] == Decimal('400.00')
    assert rows['TOTAL']['tax_withheld'] == Decimal('700.00')

    # Summary List of Purchases groups by the same payee key.
    from app.reports.bir import get_summary_list_of_purchases
    slp = {r['vendor_name']: r for r in get_summary_list_of_purchases(2025, 8)}
    assert slp[ana.full_name]['total_purchases'] == Decimal('10000.00')
    assert slp[ana.full_name]['vendor_address'] == '1 Mabini St'
    assert slp[ben.full_name]['total_purchases'] == Decimal('20000.00')
    assert slp[ben.full_name]['vendor_address'] == '2 Rizal Ave'

    # Each employee's certificate prints on its own, through the index link.
    _login(client)
    index = client.get('/reports/bir/2307?year=2025&quarter=3').get_data(as_text=True)
    link = f'payee_type=employee&amp;payee_id={ben.id}'
    assert link in index
    resp = client.get(f'/reports/bir/2307/print?year=2025&quarter=3'
                      f'&payee_type=employee&payee_id={ben.id}')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert ben.full_name in body and '2 Rizal Ave' in body
    assert ana.full_name not in body
