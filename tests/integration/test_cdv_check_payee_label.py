"""The voucher's cheque-payee line and its label vanish together when the cheque payee is the payee.

Work order 2026-11-10-cdv-print-payee-name-twice (owner, 10 Nov 2026: "if vendor name and name on check
is the same, there is no need to show the second one"); owner, 12 Nov 2026: "PNT B" -- blank the line
AND its label together. The label was a free layout text ("NAME ON CHECK" on Philgen's CORP layout),
independent of the field, so it printed with nothing beside it. It becomes part of the field: a
"Check Payee label" field whose wording lives in the layout, editable in the designer, printed only
when the cheque-payee line prints.

The cheque-payee line prints the voucher's own cheque payee (plan 2.3), else the vendor's live alias,
and is blank whenever that equals the payee name -- including a vendor whose alias IS its name.
"""
import re
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.cash_disbursements.models import CashDisbursementVoucher
from app.cash_disbursements import preprinted_layout as pl
from app.settings import AppSettings
from app.vendors.models import Vendor
from tests.integration.test_cdv_number_editable import login, setup_accounts

pytestmark = [pytest.mark.integration, pytest.mark.cash_disbursements]


@pytest.fixture
def cash(db_session):
    return setup_accounts(db_session)[2]


def _vendor(db_session, code, name, alias=None):
    v = Vendor(code=code, name=name, check_payee_name=alias, is_active=True)
    db_session.add(v); db_session.commit()
    return v


def _cdv(db_session, branch, cash, vendor, check_payee_name=None, number='LBL-1'):
    cdv = CashDisbursementVoucher(
        branch_id=branch.id, cdv_number=number, cdv_date=date(2026, 11, 12),
        payee_type='vendor', payee_id=vendor.id, vendor_id=vendor.id, vendor_name=vendor.name,
        payment_method='check', check_number=number + '-S', check_date=date(2026, 11, 12),
        check_bank='CHINA BANK', cash_account_id=cash.id, notes='label test', status='posted',
        total_amount=Decimal('500.00'), check_payee_name=check_payee_name)
    db_session.add(cdv); db_session.commit()
    return cdv


def _printed(client, branch, cdv, label_text='NAME ON CHECK'):
    layout = pl.get_layout(branch.id)          # the print reads the voucher's branch layout
    layout['fields']['check_payee']['hidden'] = False
    layout['fields']['check_payee_label']['hidden'] = False
    layout['fields']['check_payee_label']['text'] = label_text
    pl.save_layout(layout, 'test', branch_id=branch.id)
    AppSettings.set_setting('cd_print_form', 'preprinted'); db.session.commit()
    login(client)
    with client.session_transaction() as s:
        s['selected_branch_id'] = branch.id
    html = client.get(f'/cash-disbursements/{cdv.id}/print').get_data(as_text=True)

    def value(key):
        m = re.search(r'data-el="%s"[^>]*>([^<]*)<' % key, html)
        assert m, f'{key} not drawn'
        return m.group(1).strip()
    return html, value('check_payee'), value('check_payee_label')


# ------------------------------------------------------------- the layout
class TestTheLayout:

    def test_the_label_is_a_field_that_ships_hidden(self):
        assert 'check_payee_label' in pl.FIELD_KEYS
        assert pl.FIELD_KEYS.index('check_payee_label') == pl.FIELD_KEYS.index('check_payee') + 1
        assert pl.FIELD_LABELS['check_payee_label'] == 'Check Payee label'
        d = pl.sanitize_layout({})['fields']['check_payee_label']
        assert d['hidden'] is True and d['text'] == 'NAME ON CHECK'

    def test_its_wording_is_kept_and_capped(self):
        f = pl.sanitize_layout({'fields': {'check_payee_label': {'text': 'Pay to (name on cheque)', 'x': 48,
                                                                 'y': 158, 'width': 58}}})['fields']['check_payee_label']
        assert f['text'] == 'Pay to (name on cheque)' and f['x'] == 48 and f['y'] == 158 and f['width'] == 58
        long = pl.sanitize_layout({'fields': {'check_payee_label': {'text': 'x' * 500}}})
        assert len(long['fields']['check_payee_label']['text']) == 200
        odd = pl.sanitize_layout({'fields': {'check_payee_label': {'text': None}}})
        assert odd['fields']['check_payee_label']['text'] == 'NAME ON CHECK'

    def test_other_fields_carry_no_text(self):
        f = pl.sanitize_layout({'fields': {'vendor_name': {'text': 'smuggled'}}})['fields']['vendor_name']
        assert 'text' not in f


# ------------------------------------------------------------- the printed voucher
class TestThePrint:

    def test_an_override_prints_the_line_and_its_label(self, client, db_session, admin_user, main_branch, cash):
        v = _vendor(db_session, 'L1', 'ASHERPEAK COMPUTER STORE')
        html, line, label = _printed(client, main_branch, _cdv(db_session, main_branch, cash, v, 'CASH'))
        assert (line, label) == ('CASH', 'NAME ON CHECK')

    def test_the_payees_own_name_prints_neither(self, client, db_session, admin_user, main_branch, cash):
        v = _vendor(db_session, 'L2', 'FAHARRIUS LYSANDER ONG', alias='FAHARRIUS LYSANDER ONG')
        html, line, label = _printed(client, main_branch,
                                     _cdv(db_session, main_branch, cash, v, 'FAHARRIUS LYSANDER ONG'))
        assert (line, label) == ('', '')

    def test_an_alias_equal_to_the_name_prints_neither_on_an_older_voucher(
            self, client, db_session, admin_user, main_branch, cash):
        v = _vendor(db_session, 'L3', 'SOUTH COTABATO II ELECTRIC COOPERATIVE, INC.',
                    alias='SOUTH COTABATO II ELECTRIC COOPERATIVE, INC.')
        html, line, label = _printed(client, main_branch, _cdv(db_session, main_branch, cash, v, None))
        assert (line, label) == ('', '')

    def test_a_different_alias_on_an_older_voucher_still_prints(self, client, db_session, admin_user, main_branch, cash):
        v = _vendor(db_session, 'L4', 'SOUTH COTABATO II ELECTRIC COOPERATIVE, INC.', alias='SOCOTECO II')
        html, line, label = _printed(client, main_branch, _cdv(db_session, main_branch, cash, v, None))
        assert (line, label) == ('SOCOTECO II', 'NAME ON CHECK')

    def test_the_label_uses_the_layouts_wording(self, client, db_session, admin_user, main_branch, cash):
        v = _vendor(db_session, 'L5', 'GOODSCO 168 CORPORATION')
        html, line, label = _printed(client, main_branch, _cdv(db_session, main_branch, cash, v, 'CASH'),
                                     label_text='Pay to the order of')
        assert label == 'Pay to the order of'

    def test_the_designer_can_edit_the_wording(self, client, db_session, admin_user, main_branch, cash):
        """The label element carries its wording for the designer's text box, even when it prints blank."""
        v = _vendor(db_session, 'L6', 'PLAIN VENDOR')
        html, line, label = _printed(client, main_branch, _cdv(db_session, main_branch, cash, v, 'PLAIN VENDOR'))
        assert label == ''
        assert re.search(r'data-el="check_payee_label"[^>]*data-fieldtext="NAME ON CHECK"', html) or \
            re.search(r'data-fieldtext="NAME ON CHECK"[^>]*data-el="check_payee_label"', html)


def test_the_shared_designer_edits_and_saves_a_field_wording():
    """preprinted_je_designer.js (the CDV voucher's designer): a field with data-fieldtext gets the toolbar text box, and collect()
    saves its wording as the field's `text` (other fields and free texts are unchanged)."""
    from pathlib import Path
    js = (Path(__file__).resolve().parents[2] / 'app' / 'static' / 'js' / 'preprinted_je_designer.js').read_text(
        encoding='utf-8')
    assert 'dataset.fieldtext' in js
    assert re.search(r'fields\[el\.dataset\.el\]\.text\s*=\s*el\.dataset\.fieldtext', js)
