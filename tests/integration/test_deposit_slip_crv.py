"""Deposit slip from a CRV: a customer's cheque into Philgen's own account (owner, 10 Nov 2026:
"CAS-Q1: CRV, CDV, both"; design approved "CAS-D, approve as is")."""
from decimal import Decimal

import pytest

from app import db
from app.settings import AppSettings
from tests.integration.test_cd_check_print import _open
from tests.integration.test_deposit_slip_cdv import _input, _value

pytestmark = [pytest.mark.integration, pytest.mark.cash_receipts]


@pytest.fixture
def cheque_crv(posted_crv_v12):
    crv = posted_crv_v12
    crv.payment_method = 'check'
    crv.check_number = '0001104995'
    crv.check_bank = 'PBB / MAKATI'
    crv.total_amount = Decimal('2002863.09')
    db.session.commit()
    return crv


def _slip(client, crv, query=''):
    return client.get(f'/cash-receipts/{crv.id}/deposit-slip{query}')


def _bank_account(crv, branch, bank_name='CBC / EASTWOOD', number='1016-00-00046-3'):
    from app.bank_accounts.models import BankAccount
    db.session.add(BankAccount(branch_id=branch.id, code='CBC-463', name='CBC 46-3',
                               account_id=crv.cash_account_id, bank_name=bank_name,
                               account_number=number))
    db.session.commit()


class TestThePage:
    def test_a_posted_cheque_receipt_prints_into_the_companys_account(
            self, client, db_session, admin_user, main_branch, cheque_crv):
        AppSettings.set_setting('company_name', 'PHILGEN PACIFIC FOOD PRODUCTS CORP.')
        _bank_account(cheque_crv, main_branch)
        _open(client, main_branch)
        resp = _slip(client, cheque_crv)
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert _value(html, 'account_name') == 'PHILGEN PACIFIC FOOD PRODUCTS CORP.'
        assert _value(html, 'account_number') == '1016-00-00046-3'
        assert _value(html, 'check_bank') == 'PBB / MAKATI'           # the customer's cheque
        assert _value(html, 'check_number') == '0001104995'
        assert _value(html, 'check_amount') == '2,002,863.09'
        assert _value(html, 'total_amount') == '2,002,863.09'
        assert _value(html, 'deposit_date') == ''
        assert _input(html, 'account_number') == '1016-00-00046-3'
        assert 'data-save-url="/cash-disbursements/deposit-slip-layout/chinabank_bnk108"' in html
        assert 'class="cas-print-report"' in html

    def test_no_bank_account_on_file_leaves_the_number_to_type(
            self, client, db_session, admin_user, main_branch, cheque_crv):
        _open(client, main_branch)
        assert _value(_slip(client, cheque_crv).get_data(as_text=True), 'account_number') == ''

    def test_a_bdo_account_gets_the_bdo_form(self, client, db_session, admin_user, main_branch, cheque_crv):
        _bank_account(cheque_crv, main_branch, bank_name='BDO Unibank', number='0026 9001 8582')
        _open(client, main_branch)
        html = _slip(client, cheque_crv).get_data(as_text=True)
        assert '<option value="bdo_v062019" selected>' in html

    def test_an_unknown_form_is_404(self, client, db_session, admin_user, main_branch, cheque_crv):
        _open(client, main_branch)
        assert _slip(client, cheque_crv, '?form=nope').status_code == 404


class TestTheGate:
    @pytest.mark.parametrize('changes, message', [
        ({'payment_method': 'cash'}, b'This receipt is not a cheque.'),
        ({'check_number': ''}, b'A check number is required to print a deposit slip.'),
        ({'status': 'voided'}, b'This receipt is not eligible for a deposit slip.'),
        ({'status': 'draft'}, b'This receipt is not eligible for a deposit slip.'),   # posted_only
        ({'total_amount': Decimal('0')}, b'Cannot print a deposit slip for a zero amount.'),
    ])
    def test_refused(self, client, db_session, admin_user, main_branch, cheque_crv, changes, message):
        for k, v in changes.items():
            setattr(cheque_crv, k, v)
        db.session.commit()
        _open(client, main_branch)
        resp = _slip(client, cheque_crv)
        assert resp.status_code == 302 and resp.headers['Location'].endswith(f'/cash-receipts/{cheque_crv.id}')
        assert message in client.get(resp.headers['Location']).data

    def test_a_draft_prints_when_drafts_print(self, client, db_session, admin_user, main_branch, cheque_crv):
        AppSettings.set_setting('cr_print_access', 'draft_and_posted')
        cheque_crv.status = 'draft'
        db.session.commit()
        _open(client, main_branch)
        assert _slip(client, cheque_crv).status_code == 200


class TestTheButton:
    def test_a_cheque_receipt_shows_print_deposit_slip(
            self, client, db_session, admin_user, main_branch, cheque_crv):
        _open(client, main_branch)
        html = client.get(f'/cash-receipts/{cheque_crv.id}').get_data(as_text=True)
        assert f'href="/cash-receipts/{cheque_crv.id}/deposit-slip"' in html
        assert '>Print Deposit Slip</a>' in html

    def test_a_cash_receipt_does_not(self, client, db_session, admin_user, main_branch, cheque_crv):
        cheque_crv.payment_method = 'cash'
        db.session.commit()
        _open(client, main_branch)
        html = client.get(f'/cash-receipts/{cheque_crv.id}').get_data(as_text=True)
        assert f'href="/cash-receipts/{cheque_crv.id}/deposit-slip"' not in html
