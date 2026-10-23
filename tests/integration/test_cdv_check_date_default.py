"""An empty check date takes the voucher's date (owner, 21 Oct 2026: "this was first printed without a date.
the check date was empty, before this was not an issue. the empty check date takes the voucher's date").
Work order: app-docs/bug-reports/2026-10-21-check-printed-without-date-when-check-date-empty.md beside the
checkout. Philgen CDV 1704 was saved with no check date (the form's script default never ran) and its
check printed undated."""
import json
import re
from datetime import date

import pytest

from app import db
from app.cash_disbursements.models import CashDisbursementVoucher
from tests.integration.test_cd_check_print import _check_cdv, _open
from tests.integration.test_cdv_number_editable import login, make_vendor, setup_accounts

pytestmark = [pytest.mark.integration, pytest.mark.cash_disbursements]

CDV_DATE = date(2026, 10, 21)


def _post(client, url, vendor, cash, exp, cdv_number, method='check', check_date='', **extra):
    """The create or edit form as a script that never fired the form's own default would send it."""
    return client.post(url, data={
        'cdv_number': cdv_number,
        'cdv_date': CDV_DATE.isoformat(),
        'vendor_id': vendor.id,
        'payment_method': method,
        'check_number': '000123' if method == 'check' else '',
        'check_bank': 'CBC' if method == 'check' else '',
        'check_date': check_date,
        'cash_account_id': cash.id,
        'notes': 'Petty cash replenishment',
        'ap_lines': json.dumps([]),
        'expense_lines': json.dumps([{'description': 'Supplies', 'amount': 500.0, 'vat_category': '',
                                      'account_id': exp.id, 'wt_id': None}]),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
        **extra,
    }, follow_redirects=True)


@pytest.fixture
def book(client, db_session, admin_user, main_branch):
    _ap, _wt, cash, exp = setup_accounts(db_session)
    vendor = make_vendor(db_session)
    login(client)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    return vendor, cash, exp


def _saved(number):
    db.session.expire_all()
    return CashDisbursementVoucher.query.filter_by(cdv_number=number).one()


class TestSaving:

    def test_a_check_voucher_saved_without_a_check_date_takes_the_voucher_date(self, client, book):
        resp = _post(client, '/cash-disbursements/create', *book, cdv_number='1704')
        assert resp.status_code == 200
        assert _saved('1704').check_date == CDV_DATE

    def test_a_typed_check_date_is_kept(self, client, book):
        """1699, 1700 and 1296E-1299E carry later check dates on purpose."""
        _post(client, '/cash-disbursements/create', *book, cdv_number='1699', check_date='2026-10-30')
        assert _saved('1699').check_date == date(2026, 10, 30)

    def test_a_cash_voucher_gets_no_check_date(self, client, book):
        _post(client, '/cash-disbursements/create', *book, cdv_number='1705', method='cash')
        assert _saved('1705').check_date is None

    def test_clearing_the_check_date_on_edit_puts_the_voucher_date_back(self, client, book):
        _post(client, '/cash-disbursements/create', *book, cdv_number='1706', check_date='2026-10-30')
        cdv = _saved('1706')
        resp = _post(client, f'/cash-disbursements/{cdv.id}/edit', *book, cdv_number='1706',
                     row_version=cdv.row_version)
        assert resp.status_code == 200
        assert _saved('1706').check_date == CDV_DATE


class TestAVoucherAlreadySavedBlank:
    """Like 1704 on 21 Oct: the stored check date is NULL. It prints and shows the voucher date."""

    def test_the_rule(self, db_session, main_branch):
        cdv = CashDisbursementVoucher(cdv_date=CDV_DATE, payment_method='check', check_date=None)
        assert cdv.effective_check_date == CDV_DATE
        cdv.check_date = date(2026, 10, 30)
        assert cdv.effective_check_date == date(2026, 10, 30)
        assert CashDisbursementVoucher(cdv_date=CDV_DATE, payment_method='cash').effective_check_date is None

    def test_the_check_prints_the_voucher_date(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)            # CDV date 7 Jul 2026, check date 8 Jul
        cdv.check_date = None
        db.session.commit()
        _open(client, main_branch)
        body = client.get(f'/cash-disbursements/{cdv.id}/print-check').get_data(as_text=True)
        assert '07-07-2026' in body                           # the layout's default MM-DD-YYYY

    def test_the_voucher_pages_show_the_voucher_date(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        cdv.check_date = None
        db.session.commit()
        _open(client, main_branch)
        detail = client.get(f'/cash-disbursements/{cdv.id}').get_data(as_text=True)
        assert re.search(r'Check Date</span>\s*<span>Jul 07, 2026</span>', detail)
        printed = client.get(f'/cash-disbursements/{cdv.id}/print').get_data(as_text=True)
        assert '<td class="label">Check Date</td><td>07 July 2026</td>' in printed
