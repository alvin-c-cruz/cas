"""The CDV deposit slip's Bank/Branch box, kept per cash account (owner, 13 Nov 2026: "BB-1 A").

Work order 2026-11-13-cdv-deposit-slip-bank-branch. Philgen's cheques are all Chinabank Eastwood
(owner, 12 Nov 2026: "CBC/Eastwood this is the bank/branch of both our bank account"), but the
slip filled Bank/Branch from the voucher's Bank ("CHINA BANK") and a typed value lasted one print
("why does the CBC/EASTWOOD rvert back to CHINA BANK"). The Bank Accounts module is off there and
stays off, and one cash account (091-9) serves two branches.

So a full-access user keeps the box's text for the CDV's GL cash account, in the setting row
`deposit_slip_bank:<cash account id>`; every later slip on that account starts from it. The box
fills from: the kept value, else the Bank Accounts master's bank name, else the voucher's Bank,
and a line under it says which. A blank keep clears it. The voucher's own Bank, its print and the
cheque are untouched; a CRV slip (a customer's cheque) keeps the customer's bank.
"""
import html as html_lib
import re
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.accounts.models import Account
from app.audit.models import AuditLog
from app.cash_disbursements.models import CashDisbursementVoucher
from app.common import deposit_slip as ds
from app.settings import AppSettings
from tests.integration.test_cd_check_print import _check_cdv, _open
from tests.integration.test_deposit_slip_cdv import _input, _slip, _value
from tests.integration.test_deposit_slip_crv import cheque_crv  # noqa: F401  (fixture)

pytestmark = [pytest.mark.integration, pytest.mark.cash_disbursements]

KEPT = 'CBC/EASTWOOD'


def _keep(client, cdv, bank):
    return client.post(f'/cash-disbursements/{cdv.id}/deposit-slip-bank', json={'bank': bank})


def _setting(cdv):
    return AppSettings.get_setting(f'deposit_slip_bank:{cdv.cash_account_id}')


def _source(html):
    m = re.search(r'<span class="ds-source" id="dsBankSource">([^<]*)</span>', html)
    assert m, 'no source line under Bank/Branch'
    return html_lib.unescape(m.group(1))


def _another_cdv(cdv, branch_id, cash_account_id, number='CD-CK-2', check='CHK-6000'):
    other = CashDisbursementVoucher(
        branch_id=branch_id, cdv_number=number, cdv_date=date(2026, 7, 9),
        vendor_id=cdv.vendor_id, vendor_name=cdv.vendor_name, payment_method='check',
        check_number=check, check_date=date(2026, 7, 9), check_bank='CHINA BANK',
        cash_account_id=cash_account_id, status='posted', total_amount=Decimal('100000.04'),
        notes='second cheque')
    db.session.add(other); db.session.commit()
    return other


# ------------------------------------------------------------- what the box starts from
class TestTheFill:

    def test_nothing_kept_starts_from_the_vouchers_bank(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        html = _slip(client, cdv).get_data(as_text=True)
        assert _value(html, 'check_bank') == 'Chinabank'
        assert _source(html) == "From this voucher's Bank. Nothing kept for 1011 Cash in Bank."

    def test_a_kept_value_fills_the_box_and_the_print(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        ds.keep_bank(cdv.cash_account_id, KEPT, 'admin')
        _open(client, main_branch)
        html = _slip(client, cdv).get_data(as_text=True)
        assert _value(html, 'check_bank') == KEPT and _input(html, 'check_bank') == KEPT
        assert _source(html) == 'Kept for 1011 Cash in Bank.'
        assert _value(html, 'check_number') == 'CHK-5000'          # the rest unchanged
        assert _value(html, 'check_amount') == '5,550.00'

    def test_the_kept_value_beats_the_bank_accounts_master(self, client, db_session, admin_user, main_branch):
        from app.bank_accounts.models import BankAccount
        cdv = _check_cdv(db_session, main_branch)
        db.session.add(BankAccount(branch_id=main_branch.id, code='CBC-463', name='CBC 46-3',
                                   account_id=cdv.cash_account_id, bank_name='CHINA BANK CORP',
                                   account_number='1016-00-00046-3'))
        db.session.commit()
        _open(client, main_branch)
        html = _slip(client, cdv).get_data(as_text=True)
        assert _value(html, 'check_bank') == 'CHINA BANK CORP'
        assert _source(html) == 'From Bank Accounts for 1011 Cash in Bank.'
        ds.keep_bank(cdv.cash_account_id, KEPT, 'admin')
        assert _value(_slip(client, cdv).get_data(as_text=True), 'check_bank') == KEPT

    def test_it_is_kept_per_cash_account(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        other_cash = Account(code='1012', name='Cash in Bank 2', account_type='Asset',
                             normal_balance='debit', is_active=True)
        db.session.add(other_cash); db.session.commit()
        other = _another_cdv(cdv, main_branch.id, other_cash.id)
        ds.keep_bank(cdv.cash_account_id, KEPT, 'admin')
        _open(client, main_branch)
        assert _value(_slip(client, cdv).get_data(as_text=True), 'check_bank') == KEPT
        html = _slip(client, other).get_data(as_text=True)
        assert _value(html, 'check_bank') == 'CHINA BANK'
        assert _source(html) == "From this voucher's Bank. Nothing kept for 1012 Cash in Bank 2."

    def test_one_cash_account_used_by_two_branches_shares_it(self, client, db_session, admin_user, main_branch):
        """091-9 is drawn on by CORP and EXTRA: the value follows the GL account, not the branch."""
        from app.branches.models import Branch
        cdv = _check_cdv(db_session, main_branch)
        extra = Branch(code='EXTRA', name='Extra', is_active=True)
        db.session.add(extra); db.session.commit()
        other = _another_cdv(cdv, extra.id, cdv.cash_account_id, number='1372E', check='3596992')
        ds.keep_bank(cdv.cash_account_id, KEPT, 'admin')
        _open(client, extra)
        html = _slip(client, other).get_data(as_text=True)
        assert _value(html, 'check_bank') == KEPT
        assert _value(html, 'check_number') == '3596992' and _value(html, 'check_amount') == '100,000.04'


# ------------------------------------------------------------- Keep
class TestKeep:

    def test_full_access_keeps_the_box_for_the_cash_account(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        resp = _keep(client, cdv, '  CBC/EASTWOOD  ')
        assert resp.status_code == 200
        body = resp.get_json()
        assert body == {'ok': True, 'bank': KEPT, 'source': 'Kept for 1011 Cash in Bank.'}
        assert _setting(cdv) == KEPT

    def test_the_voucher_itself_is_not_changed(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        _keep(client, cdv, KEPT)
        db.session.expire_all()
        assert db.session.get(CashDisbursementVoucher, cdv.id).check_bank == 'Chinabank'

    def test_each_keep_is_audited_old_to_new(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        _keep(client, cdv, 'CBC')
        _keep(client, cdv, KEPT)
        rows = (AuditLog.query.filter_by(record_identifier=f'deposit_slip_bank:{cdv.cash_account_id}')
                .order_by(AuditLog.id).all())
        assert len(rows) == 2
        assert rows[1].action == 'update' and rows[1].module == 'cash_disbursements'
        assert 'CBC' in rows[1].old_values and KEPT in rows[1].new_values
        assert '1011 Cash in Bank' in rows[1].notes

    def test_a_blank_keep_clears_it(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        _keep(client, cdv, KEPT)
        resp = _keep(client, cdv, '   ')
        assert resp.get_json() == {'ok': True, 'bank': 'Chinabank',
                                   'source': "From this voucher's Bank. Nothing kept for 1011 Cash in Bank."}
        assert _setting(cdv) is None
        assert AppSettings.query.filter_by(key=f'deposit_slip_bank:{cdv.cash_account_id}').count() == 0
        assert _value(_slip(client, cdv).get_data(as_text=True), 'check_bank') == 'Chinabank'

    def test_a_long_value_is_cut_to_the_bank_fields_length(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        _keep(client, cdv, 'X' * 300)
        assert _setting(cdv) == 'X' * 100

    def test_staff_cannot_keep(self, client, db_session, staff_user, main_branch):
        staff_user.set_branches([main_branch]); db_session.commit()
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch, u=staff_user.username, p='staff123')
        assert _keep(client, cdv, KEPT).status_code == 403
        assert _setting(cdv) is None

    def test_get_is_not_allowed(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        assert client.get(f'/cash-disbursements/{cdv.id}/deposit-slip-bank').status_code == 405


# ------------------------------------------------------------- the page
class TestThePage:

    def test_full_access_gets_the_keep_button(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        html = _slip(client, cdv).get_data(as_text=True)
        assert re.search(r'<button type="button" id="dsKeepBank"[^>]*'
                         r'data-url="/cash-disbursements/%d/deposit-slip-bank"[^>]*>'
                         r'Keep for 1011 Cash in Bank</button>' % cdv.id, html)

    def test_staff_see_where_it_came_from_but_no_button(self, client, db_session, staff_user, main_branch):
        staff_user.set_branches([main_branch]); db_session.commit()
        cdv = _check_cdv(db_session, main_branch)
        ds.keep_bank(cdv.cash_account_id, KEPT, 'admin')
        _open(client, main_branch, u=staff_user.username, p='staff123')
        html = _slip(client, cdv).get_data(as_text=True)
        assert _value(html, 'check_bank') == KEPT
        assert _source(html) == 'Kept for 1011 Cash in Bank.'
        assert 'id="dsKeepBank"' not in html


# ------------------------------------------------------------- a customer's cheque
class TestTheReceiptSlip:

    def test_a_crv_slip_keeps_the_customers_bank_and_has_no_keep(
            self, client, db_session, admin_user, main_branch, cheque_crv):  # noqa: F811
        ds.keep_bank(cheque_crv.cash_account_id, KEPT, 'admin')
        _open(client, main_branch)
        html = client.get(f'/cash-receipts/{cheque_crv.id}/deposit-slip').get_data(as_text=True)
        assert _value(html, 'check_bank') == 'PBB / MAKATI'
        assert 'id="dsKeepBank"' not in html and 'id="dsBankSource"' not in html
