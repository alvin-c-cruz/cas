"""A Cash Disbursement Voucher can pay an EMPLOYEE.

Owner, 2026-09-24: "I cant access the employee names from CV extra. they should
be available for both branches." Not a branch bug: the CV had no employee payee
at all, so the nine employee APVs on production could not be paid by any CV.
Design: docs/design/2026-09-24-cv-employee-payee-design.md.
"""
import json
import re
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.accounts_payable.models import AccountsPayable
from app.audit.models import AuditLog
from app.cash_disbursements.models import CashDisbursementVoucher
from app.employees.models import Employee
from tests.integration.test_cdv_number_editable import login, setup_accounts, make_vendor

pytestmark = [pytest.mark.integration, pytest.mark.cash_disbursements]


@pytest.fixture
def accounts(db_session):
    ap, wt, cash, exp = setup_accounts(db_session)
    return dict(ap=ap, wt=wt, cash=cash, exp=exp)


@pytest.fixture
def employees(db_session, main_branch, branch_manila):
    corp = Employee(employee_no='E-CORP-1', first_name='Anissa', last_name='Tang',
                    tin='111-111-111-000', branch_id=main_branch.id, is_active=True)
    other = Employee(employee_no='E-OTHER-1', first_name='Lawrence', last_name='Kiok',
                     branch_id=branch_manila.id, is_active=True)
    db_session.add_all([corp, other]); db_session.commit()
    return corp, other


def _open(client, branch, username='admin', password='admin123'):
    login(client) if username == 'admin' else client.post(
        '/login', data={'username': username, 'password': password}, follow_redirects=True)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id


def _employee_apv(db_session, employee, branch, number, total='1000.00'):
    """A POSTED employee-payee APV, the shape the nine on production have."""
    today = date(2026, 9, 24)
    ap = AccountsPayable(ap_number=number, ap_date=today, due_date=today + timedelta(days=30),
                         payee_type='employee', payee_id=employee.id, vendor_id=None,
                         vendor_name=employee.full_name, vendor_tin=employee.tin or '',
                         vendor_address='', branch_id=branch.id, status='posted',
                         subtotal=Decimal(total), vat_amount=Decimal('0'), total_before_wt=Decimal(total),
                         withholding_tax_rate=Decimal('0'), withholding_tax_amount=Decimal('0'),
                         total_amount=Decimal(total), amount_paid=Decimal('0'), balance=Decimal(total),
                         payment_terms='Net 30')
    db_session.add(ap); db_session.commit()
    return ap


def _post_cdv(client, payee, cash, ap_lines=(), expense_lines=(), number='EMP-0001', method='cash'):
    return client.post('/cash-disbursements/create', data={
        'cdv_number': number, 'cdv_date': '2026-09-24', 'payee': payee,
        'payment_method': method, 'cash_account_id': cash.id, 'notes': 'employee payee test',
        'ap_lines': json.dumps(list(ap_lines)), 'expense_lines': json.dumps(list(expense_lines)),
        'vat_override': '0', 'vat_override_value': '0', 'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=True)


class TestThePicker:

    def test_offers_employees_of_every_reachable_branch(self, client, db_session, admin_user,
                                                        main_branch, branch_manila, employees, accounts):
        """From a session in ONE branch an admin sees BOTH branches' employees --
        'available for both branches'."""
        corp, other = employees
        make_vendor(db_session)          # so the page has a [Vendor] option to tag
        _open(client, branch_manila)
        html = client.get('/cash-disbursements/create').get_data(as_text=True)
        assert f'value="employee:{corp.id}"' in html
        assert f'value="employee:{other.id}"' in html
        assert '[Employee]' in html and '[Vendor]' in html

    def test_a_scoped_user_does_not_see_an_unreachable_branch(self, client, db_session, admin_user,
                                                              staff_user, main_branch, branch_manila,
                                                              employees, accounts):
        corp, other = employees
        staff_user.set_branches([main_branch]); db_session.commit()
        _open(client, main_branch, 'staff', 'staff123')
        html = client.get('/cash-disbursements/create').get_data(as_text=True)
        assert f'value="employee:{corp.id}"' in html
        assert f'value="employee:{other.id}"' not in html

    def test_a_hand_posted_unreachable_employee_is_refused(self, client, db_session, admin_user,
                                                           staff_user, main_branch, branch_manila,
                                                           employees, accounts):
        corp, other = employees
        staff_user.set_branches([main_branch]); db_session.commit()
        _open(client, main_branch, 'staff', 'staff123')
        resp = _post_cdv(client, f'employee:{other.id}', accounts['cash'],
                         expense_lines=[{'description': 'x', 'amount': 10.0, 'vat_category': '',
                                         'account_id': accounts['exp'].id, 'wt_id': None}])
        assert b'Selected payee not found.' in resp.data
        assert CashDisbursementVoucher.query.filter_by(cdv_number='EMP-0001').first() is None


class TestSectionA:

    def test_open_bills_lists_the_employees_apvs_and_no_vendors(self, client, db_session, admin_user,
                                                                main_branch, employees, accounts):
        corp, _ = employees
        vendor = make_vendor(db_session)
        a1 = _employee_apv(db_session, corp, main_branch, 'E-APV-1')
        a2 = _employee_apv(db_session, corp, main_branch, 'E-APV-2', total='250.00')
        from tests.integration.test_accounts_payable_views import make_ap
        make_ap(db_session, vendor, main_branch, 'V-APV-1')                # a vendor's, must not appear
        _open(client, main_branch)
        bills = client.get(f'/cash-disbursements/open-bills?payee=employee:{corp.id}').get_json()
        assert {b['bill_number'] for b in bills} == {'E-APV-1', 'E-APV-2'}
        assert client.get(f'/cash-disbursements/open-bills?vendor_id={vendor.id}').get_json()[0]['bill_number'] == 'V-APV-1'

    def test_a_cv_settles_an_employee_apv(self, client, db_session, admin_user, main_branch,
                                          employees, accounts):
        corp, _ = employees
        apv = _employee_apv(db_session, corp, main_branch, 'E-APV-3', total='500.00')
        _open(client, main_branch)
        resp = _post_cdv(client, f'employee:{corp.id}', accounts['cash'],
                         ap_lines=[{'bill_id': apv.id, 'amount_applied': 500.0}])
        assert resp.status_code == 200
        cdv = CashDisbursementVoucher.query.filter_by(cdv_number='EMP-0001').one()
        assert cdv.payee_type == 'employee' and cdv.payee_id == corp.id
        assert cdv.vendor_id is None and cdv.vendor_name == 'Anissa Tang'
        assert cdv.vendor_tin == '111-111-111-000'
        assert len(cdv.ap_lines) == 1

    def test_the_create_is_audited_with_the_payee(self, client, db_session, admin_user, main_branch,
                                                  employees, accounts):
        corp, _ = employees
        apv = _employee_apv(db_session, corp, main_branch, 'E-APV-4', total='100.00')
        _open(client, main_branch)
        _post_cdv(client, f'employee:{corp.id}', accounts['cash'],
                  ap_lines=[{'bill_id': apv.id, 'amount_applied': 100.0}])
        cdv = CashDisbursementVoucher.query.filter_by(cdv_number='EMP-0001').one()
        audit = AuditLog.query.filter_by(module='cash_disbursement', action='create', record_id=cdv.id).first()
        assert audit is not None and '"employee"' in (audit.new_values or '')


class TestVendorPathUnchanged:

    def test_the_legacy_vendor_id_field_still_creates_a_vendor_cv(self, client, db_session,
                                                                  admin_user, main_branch, accounts):
        vendor = make_vendor(db_session)
        _open(client, main_branch)
        resp = client.post('/cash-disbursements/create', data={
            'cdv_number': 'LEG-0001', 'cdv_date': '2026-09-24', 'vendor_id': vendor.id,
            'payment_method': 'cash', 'cash_account_id': accounts['cash'].id, 'notes': 'legacy field',
            'ap_lines': json.dumps([]),
            'expense_lines': json.dumps([{'description': 'Supplies', 'amount': 500.0, 'vat_category': '',
                                          'account_id': accounts['exp'].id, 'wt_id': None}]),
            'vat_override': '0', 'vat_override_value': '0', 'wt_override': '0', 'wt_override_value': '0',
        }, follow_redirects=True)
        assert resp.status_code == 200
        cdv = CashDisbursementVoucher.query.filter_by(cdv_number='LEG-0001').one()
        assert (cdv.payee_type, cdv.payee_id, cdv.vendor_id) == ('vendor', vendor.id, vendor.id)
