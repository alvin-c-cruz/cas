"""A voucher keeps its own deposit-slip details; the voucher page says where the cheque and the deposit go; and the
withholding is questioned when the cheque goes to someone other than the supplier (CVS-1..4 A, owner 14 Nov 2026;
work order 2026-11-13-cv-level-cheque-payee-and-deposit-slip).

The Fiesta case: Resaida paid Fiesta's cash invoice in full; the reimbursement cheque was made out to CASH and had to be
deposited to Resaida's Chinabank account. Before this, getting that slip meant changing the vendor master for one
voucher, or printing an interim slip outside CAS.

CVS-1 A  "Save on this voucher" keeps Account Name, Account Number, Bank/Branch and the slip form ON THE CDV -- only what
         differs from the defaults, so the defaults stay live; "Use the defaults" clears them; nothing writes to any
         master; saves are audited; reprints keep them; the CDV page shows the deposit-to account.
CVS-2 A  anyone who may print the voucher's cheque and slip may save.
CVS-3 A  the CDV page says "Cheque to CASH, not to <payee>" when the cheque payee differs.
CVS-4 A  when the cheque goes to someone other than the payee and the voucher withholds, the CDV page and the CV form
         say so. Nothing is blocked.
"""
import re
from decimal import Decimal

import pytest

from app import db
from app.audit.models import AuditLog
from app.cash_disbursements.models import CashDisbursementVoucher
from app.common import deposit_slip as ds
from app.settings import AppSettings
from tests.integration.test_cd_check_print import _check_cdv, _open
from tests.integration.test_deposit_slip_cdv import _input, _slip, _value

pytestmark = [pytest.mark.integration, pytest.mark.cash_disbursements]

RESAIDA = {'account_name': 'RESAIDA DELOS SANTOS', 'account_number': '1881109718', 'check_bank': 'CBC/EASTWOOD'}


def _save(client, cdv, values=None, form=None):
    body = dict(values or RESAIDA)
    if form:
        body['form'] = form
    return client.post(f'/cash-disbursements/{cdv.id}/deposit-slip/save', json=body)


def _reset(client, cdv):
    return client.post(f'/cash-disbursements/{cdv.id}/deposit-slip/reset')


def _detail(client, cdv):
    return client.get(f'/cash-disbursements/{cdv.id}').get_data(as_text=True)


class TestSaveOnThisVoucher:

    def test_saved_values_print_and_reprint(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        resp = _save(client, cdv)
        assert resp.status_code == 200 and resp.get_json()['saved'] is True
        html = _slip(client, cdv).get_data(as_text=True)
        for key, val in RESAIDA.items():
            assert _input(html, key) == val and _value(html, key) == val
        assert 'Saved on this voucher' in html
        assert _value(html, 'check_number') == 'CHK-5000', 'cheque number always from the voucher'
        assert _value(html, 'check_amount') == '5,550.00', 'amounts always from the voucher'

    def test_only_what_differs_is_stored(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        defaults, _ = ds.cdv_values(cdv)
        _save(client, cdv, {'account_name': defaults['account_name'], 'account_number': '1881109718',
                            'check_bank': defaults['check_bank']})
        db_session.refresh(cdv)
        assert cdv.slip_account_name is None and cdv.slip_check_bank is None
        assert cdv.slip_account_number == '1881109718'

    def test_use_the_defaults_clears_it(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        _save(client, cdv)
        _reset(client, cdv)
        db_session.refresh(cdv)
        assert (cdv.slip_account_name, cdv.slip_account_number, cdv.slip_check_bank, cdv.slip_form) == \
            (None, None, None, None)
        html = _slip(client, cdv).get_data(as_text=True)
        assert _input(html, 'account_name') != RESAIDA['account_name']

    def test_nothing_is_written_to_any_master(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        vendor = cdv.vendor
        before = (vendor.bank_account_name, vendor.bank_account_number, vendor.check_payee_name)
        _open(client, main_branch)
        _save(client, cdv)
        db_session.refresh(vendor)
        assert (vendor.bank_account_name, vendor.bank_account_number, vendor.check_payee_name) == before
        assert AppSettings.get_setting(f'deposit_slip_bank:{cdv.cash_account_id}') is None

    def test_saves_and_resets_are_audited(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        _save(client, cdv)
        _reset(client, cdv)
        actions = [r.action for r in AuditLog.query.filter_by(module='cash_disbursements', record_id=cdv.id)
                   .order_by(AuditLog.id)]
        assert 'save_deposit_slip' in actions and 'reset_deposit_slip' in actions

    def test_the_saved_form_is_used_on_reprint(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        other_form = next(k for k in ds.FORMS if k != ds.pick_form(None, '', payee='vendor')[0])
        _save(client, cdv, form=other_form)
        html = _slip(client, cdv).get_data(as_text=True)
        assert re.search(r'<option value="%s"[^>]*selected' % re.escape(other_form), html)

    def test_a_voided_voucher_cannot_be_saved(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch, status='voided')
        _open(client, main_branch)
        assert _save(client, cdv).status_code == 400
        db_session.refresh(cdv)
        assert cdv.slip_account_name is None

    def test_the_slip_page_offers_both_buttons(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        html = _slip(client, cdv).get_data(as_text=True)
        assert 'id="dsSaveOnVoucher"' in html and 'id="dsUseDefaults"' in html


class TestTheVoucherPage:

    def test_it_shows_the_saved_deposit_to(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        _save(client, cdv)
        html = _detail(client, cdv)
        assert 'data-cdv-deposit-to' in html
        assert 'RESAIDA DELOS SANTOS' in html and '1881109718' in html and 'saved on this voucher' in html

    def test_cheque_to_someone_else_is_said(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        cdv.check_payee_name = 'CASH'
        db_session.commit()
        _open(client, main_branch)
        html = _detail(client, cdv)
        assert 'data-cdv-cheque-to-other' in html and 'Cheque to CASH, not to Meralco' in html

    @pytest.mark.parametrize('payee', [None, '', 'Meralco', ' meralco '])
    def test_no_marker_when_the_cheque_names_the_payee(self, client, db_session, admin_user, main_branch, payee):
        cdv = _check_cdv(db_session, main_branch)
        cdv.check_payee_name = payee
        db_session.commit()
        _open(client, main_branch)
        assert 'data-cdv-cheque-to-other' not in _detail(client, cdv)

    def test_withholding_is_questioned_when_the_cheque_goes_elsewhere(self, client, db_session, admin_user,
                                                                       main_branch):
        cdv = _check_cdv(db_session, main_branch)
        cdv.check_payee_name = 'CASH'
        cdv.total_wt = Decimal('474.98')
        db_session.commit()
        _open(client, main_branch)
        html = _detail(client, cdv)
        assert 'data-cdv-wt-other-payee' in html and '474.98' in html

    def test_no_withholding_question_without_withholding(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        cdv.check_payee_name = 'CASH'
        cdv.total_wt = Decimal('0')
        db_session.commit()
        _open(client, main_branch)
        assert 'data-cdv-wt-other-payee' not in _detail(client, cdv)


class TestTheVoucherForm:

    def test_the_form_can_question_the_withholding(self, client, db_session, admin_user, main_branch):
        _open(client, main_branch)
        html = client.get('/cash-disbursements/create').get_data(as_text=True)
        assert 'id="cdvWtOtherPayeeWarning"' in html and 'updateWtOtherPayeeWarning' in html


class TestWhoMaySave:

    def test_a_staff_user_who_may_print_may_save(self, client, db_session, admin_user, staff_user, main_branch):
        """CVS-2 A: the same people who may print the voucher's cheque and slip."""
        cdv = _check_cdv(db_session, main_branch)
        staff_user.set_branches([main_branch])
        db_session.commit()
        _open(client, main_branch, u='staff', p='staff123')
        assert _slip(client, cdv).status_code == 200, 'precondition: staff may print the slip'
        assert _save(client, cdv).status_code == 200
        db_session.refresh(cdv)
        assert cdv.slip_account_number == RESAIDA['account_number']
