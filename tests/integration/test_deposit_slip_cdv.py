"""Deposit slip from a CDV: Philgen's own cheque into the payee's account (owner, 10 Nov 2026:
"CAS-Q1: CRV, CDV, both"; design approved "CAS-D, approve as is").
Design: app-docs/superpowers/specs/2026-11-10-deposit-slip-print-design.md."""
import json
import re

import pytest

from app import db
from app.common import deposit_slip as ds
from tests.integration.test_cd_check_print import _check_cdv, _open

pytestmark = [pytest.mark.integration, pytest.mark.cash_disbursements]


def _slip(client, cdv, query=''):
    return client.get(f'/cash-disbursements/{cdv.id}/deposit-slip{query}')


def _value(html, key):
    m = re.search(r'<div class="pp-el[^"]*" data-el="%s"[^>]*>([^<]*)</div>' % key, html)
    assert m, f'field {key} not drawn'
    return m.group(1)


def _input(html, key):
    m = re.search(r'<input type="text" class="ds-value" data-for="%s" value="([^"]*)"' % key, html)
    assert m, f'no editable box for {key}'
    return m.group(1)


class TestThePage:
    def test_a_posted_cheque_cdv_prints_its_slip(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        resp = _slip(client, cdv)
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert _value(html, 'check_number') == 'CHK-5000'
        assert _value(html, 'check_amount') == '5,550.00'
        assert _value(html, 'total_amount') == '5,550.00'
        assert _value(html, 'check_bank') == 'Chinabank'          # the CDV's cheque bank
        assert _value(html, 'account_name') == 'Meralco'          # no bank name, no alias: the payee
        assert _value(html, 'account_number') == ''               # typed on the page when missing
        assert '@page { size: 8.5in 11in; margin: 0; }' in html
        assert 'class="cas-print-report"' in html                 # the print pages' report button

    def test_the_payees_bank_details_fill_the_account(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        cdv.vendor.bank_name = 'CHINABANK'
        cdv.vendor.bank_account_name = 'MERALCO CORP'
        cdv.vendor.bank_account_number = '188 1109 718'
        db.session.commit()
        _open(client, main_branch)
        html = _slip(client, cdv).get_data(as_text=True)
        assert _value(html, 'account_name') == 'MERALCO CORP'
        assert _value(html, 'account_number') == '188 1109 718'
        assert _input(html, 'account_number') == '188 1109 718'

    def test_the_cheque_payee_name_stands_in_for_a_missing_account_name(
            self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        cdv.vendor.check_payee_name = 'RESAIDA DELOS SANTOS'
        db.session.commit()
        _open(client, main_branch)
        assert _value(_slip(client, cdv).get_data(as_text=True), 'account_name') == 'RESAIDA DELOS SANTOS'

    def test_the_bank_accounts_master_names_the_cheque_bank_when_set(
            self, client, db_session, admin_user, main_branch):
        from app.bank_accounts.models import BankAccount
        cdv = _check_cdv(db_session, main_branch)
        db.session.add(BankAccount(branch_id=main_branch.id, code='CBC-463', name='CBC 46-3',
                                   account_id=cdv.cash_account_id, bank_name='CBC / EASTWOOD',
                                   account_number='1016-00-00046-3'))
        db.session.commit()
        _open(client, main_branch)
        assert _value(_slip(client, cdv).get_data(as_text=True), 'check_bank') == 'CBC / EASTWOOD'

    def test_the_date_is_blank_unless_asked_for(self, client, db_session, admin_user, main_branch):
        from app.utils import ph_now
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        html = _slip(client, cdv).get_data(as_text=True)
        assert _value(html, 'deposit_date') == ''
        assert '<input type="checkbox" id="dsPrintDate">' in html            # unticked
        assert f'<input type="date" id="dsDate" value="{ph_now().date().isoformat()}"' in html

    def test_every_value_can_be_edited_before_printing(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        html = _slip(client, cdv).get_data(as_text=True)
        for key in ('account_name', 'account_number', 'total_amount', 'check_bank',
                    'check_number', 'check_amount'):
            _input(html, key)


class TestTheForm:
    def test_chinabank_by_default(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        html = _slip(client, cdv).get_data(as_text=True)
        assert '<option value="chinabank_bnk108" selected>' in html
        assert 'data-save-url="/cash-disbursements/deposit-slip-layout/chinabank_bnk108"' in html

    def test_a_payee_banking_with_bdo_gets_the_bdo_form(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        cdv.vendor.bank_name = 'BDO'
        db.session.commit()
        _open(client, main_branch)
        html = _slip(client, cdv).get_data(as_text=True)
        assert '<option value="bdo_v062019" selected>' in html
        assert 'data-save-url="/cash-disbursements/deposit-slip-layout/bdo_v062019"' in html

    def test_the_form_can_be_chosen(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        html = _slip(client, cdv, '?form=bdo_v062019').get_data(as_text=True)
        assert '<option value="bdo_v062019" selected>' in html
        bdo = ds.default_layout('bdo_v062019')['fields']['account_name']
        assert f'data-el="account_name"' in html and f'left:{bdo["x"]}px;top:{bdo["y"]}px;' in html

    def test_an_unknown_form_is_404(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        assert _slip(client, cdv, '?form=nope').status_code == 404


class TestTheGate:
    """Same status rule as Print Check; a cheque with a number and an amount."""

    @pytest.mark.parametrize('kwargs, message', [
        ({'method': 'cash'}, b'This voucher is not paid by check.'),
        ({'check_number': '  '}, b'A check number is required to print a deposit slip.'),
        ({'status': 'voided'}, b'This voucher is not eligible for a deposit slip.'),
        ({'status': 'draft'}, b'This voucher is not eligible for a deposit slip.'),   # posted_only
        ({'total': '0'}, b'Cannot print a deposit slip for a zero amount.'),
    ])
    def test_refused(self, client, db_session, admin_user, main_branch, kwargs, message):
        cdv = _check_cdv(db_session, main_branch, **kwargs)
        _open(client, main_branch)
        resp = _slip(client, cdv)
        assert resp.status_code == 302 and resp.headers['Location'].endswith(f'/cash-disbursements/{cdv.id}')
        assert message in client.get(resp.headers['Location']).data

    def test_a_draft_prints_when_drafts_print(self, client, db_session, admin_user, main_branch):
        from app.settings import AppSettings
        AppSettings.set_setting('cd_check_print_access', 'draft_and_posted')
        cdv = _check_cdv(db_session, main_branch, status='draft')
        _open(client, main_branch)
        assert _slip(client, cdv).status_code == 200


class TestTheButton:
    def test_a_cheque_cdv_shows_print_deposit_slip(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        html = client.get(f'/cash-disbursements/{cdv.id}').get_data(as_text=True)
        assert f'href="/cash-disbursements/{cdv.id}/deposit-slip"' in html
        assert '>Print Deposit Slip</a>' in html

    def test_a_cash_cdv_does_not(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch, method='cash')
        _open(client, main_branch)
        html = client.get(f'/cash-disbursements/{cdv.id}').get_data(as_text=True)
        assert f'href="/cash-disbursements/{cdv.id}/deposit-slip"' not in html


class TestTheLayout:
    def test_full_access_saves_a_forms_layout(self, client, db_session, admin_user, main_branch):
        _open(client, main_branch)
        raw = ds.default_layout('bdo_v062019')
        raw['fields']['account_name']['x'] = 150
        raw['page']['offsetY'] = -1.2
        resp = client.post('/cash-disbursements/deposit-slip-layout/bdo_v062019', json=raw)
        assert resp.status_code == 200 and resp.get_json()['ok'] is True
        saved = ds.get_layout('bdo_v062019')
        assert saved['fields']['account_name']['x'] == 150 and saved['page']['offsetY'] == -1.2
        assert ds.get_layout('chinabank_bnk108') == ds.default_layout('chinabank_bnk108')   # untouched

    def test_others_cannot(self, client, db_session, staff_user, main_branch):
        staff_user.set_branches([main_branch]); db_session.commit()
        _open(client, main_branch, u=staff_user.username, p='staff123')
        resp = client.post('/cash-disbursements/deposit-slip-layout/bdo_v062019',
                           json=ds.default_layout('bdo_v062019'))
        assert resp.status_code == 403

    def test_an_unknown_form_cannot_be_saved(self, client, db_session, admin_user, main_branch):
        _open(client, main_branch)
        assert client.post('/cash-disbursements/deposit-slip-layout/nope', json={}).status_code == 404

    def test_full_access_gets_the_designer(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        html = _slip(client, cdv).get_data(as_text=True)
        assert 'id="editLayoutBtn"' in html and '/static/js/cd_check_designer.js' in html
        assert 'id="ppOffsetX"' in html and 'id="ppOffsetY"' in html

    def test_staff_print_without_the_designer(self, client, db_session, staff_user, main_branch):
        staff_user.set_branches([main_branch]); db_session.commit()
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch, u=staff_user.username, p='staff123')
        resp = _slip(client, cdv)
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'id="editLayoutBtn"' not in html and '/static/js/cd_check_designer.js' not in html

    def test_the_nudge_moves_the_whole_print_and_only_on_paper(
            self, client, db_session, admin_user, main_branch):
        ds.save_layout('chinabank_bnk108', dict(ds.default_layout('chinabank_bnk108'),
                                                page={'fontFamily': ds.ALLOWED_FONTS[0],
                                                      'offsetX': 0.5, 'offsetY': -1.2}), 'admin')
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        html = _slip(client, cdv).get_data(as_text=True)
        assert '--ds-dx:0.5mm;--ds-dy:-1.2mm;' in html
        assert '@media print { .pp-el { transform: translate(var(--ds-dx), var(--ds-dy)); } }' in html
