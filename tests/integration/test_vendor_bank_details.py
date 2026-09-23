"""A vendor carries the bank account it is paid into, and a deposit-paid CDV shows it.

Owner, 2026-09-23: "some vendors accepts payment via bank deposits. therefore its good
to have the bank details in our vendor master data" -- and on the CV: "having the bank
details on the CV is a bright idea".

Decisions taken with the owner, pinned here so they are not reopened as bugs:

1. ONE account per vendor -- three columns on `vendors`, not a child table.
2. Read LIVE from the vendor, never snapshotted onto the CDV. The owner does not reprint
   CVs; the same ruling already governs check_payee_name.
3. Shown only for the deposit methods (Bank Transfer, Online), the way check details
   show only for a check. A deposit CDV whose vendor has no details stays BLANK -- owner,
   2026-09-24, reversing a first cut that printed "Bank details not on file".
4. The pre-printed voucher gets a `deposit_account` field that ships HIDDEN, like
   check_payee: a new field must never appear unbidden on a client's pad.
"""
import re

import pytest

from app.audit.models import AuditLog
from app.settings import AppSettings
from app.vendors.models import Vendor
from tests.integration.test_cdv_print_form import login, _cdv_with_je
from tests.integration.test_vendor_views import make_vat_category, make_vendor

pytestmark = [pytest.mark.integration, pytest.mark.vendors, pytest.mark.cash_disbursements]

BANK = {'bank_name': 'BDO Unibank', 'bank_account_name': 'Meralco Payee Inc.',
        'bank_account_number': '001234567890'}


def _vendor_post(**extra):
    data = {'code': 'BK001', 'name': 'Bank Vendor', 'payment_terms': 'Net 30',
            'default_vat_category': 'V12DG', 'is_active': '1'}
    data.update(extra)
    return data


def _input_value(html, name):
    m = re.search(r'<input[^>]*name="%s"[^>]*>' % name, html)
    assert m, '%s is not rendered on the vendor form' % name
    v = re.search(r'value="([^"]*)"', m.group(0))
    return v.group(1) if v else ''


# ------------------------------------------------------------- the vendor master
class TestVendorMaster:

    def test_create_stores_the_bank_details_and_audits_them(self, client, db_session,
                                                            admin_user, main_branch):
        login(client)
        make_vat_category(db_session)
        client.post('/vendors/create', data=_vendor_post(**BANK), follow_redirects=True)
        vendor = Vendor.query.filter_by(code='BK001').first()
        assert vendor is not None, 'anti-vacuity: the vendor was not created'
        assert vendor.bank_name == 'BDO Unibank'
        assert vendor.bank_account_name == 'Meralco Payee Inc.'
        # Text, not a number: the leading zeros are part of the account number.
        assert vendor.bank_account_number == '001234567890'

        audit = AuditLog.query.filter_by(module='vendor', action='create',
                                         record_id=vendor.id).first()
        assert audit is not None
        assert '001234567890' in (audit.new_values or '')

    def test_edit_changes_the_account_and_audits_before_and_after(
            self, client, db_session, admin_user, main_branch):
        login(client)
        make_vat_category(db_session)
        vendor = make_vendor(db_session, code='BK002', name='Edit Bank')
        vendor.bank_account_number = '1111'
        db_session.commit()

        client.post('/vendors/%d/edit' % vendor.id,
                    data=_vendor_post(code='BK002', name='Edit Bank', bank_name='BPI',
                                      bank_account_name='Edit Bank',
                                      bank_account_number='2222'),
                    follow_redirects=True)
        db_session.refresh(vendor)
        assert vendor.bank_account_number == '2222'
        assert vendor.bank_name == 'BPI'

        audit = AuditLog.query.filter_by(module='vendor', action='update',
                                         record_id=vendor.id).first()
        assert audit is not None
        assert '1111' in (audit.old_values or '')
        assert '2222' in (audit.new_values or '')

    def test_the_edit_form_shows_the_stored_details(self, client, db_session,
                                                    admin_user, main_branch):
        login(client)
        vendor = make_vendor(db_session, code='BK003', name='Show Bank')
        for k, v in BANK.items():
            setattr(vendor, k, v)
        db_session.commit()
        html = client.get('/vendors/%d/edit' % vendor.id).get_data(as_text=True)
        for k, v in BANK.items():
            assert _input_value(html, k) == v

    def test_the_detail_page_shows_them(self, client, db_session, admin_user, main_branch):
        login(client)
        vendor = make_vendor(db_session, code='BK004', name='Detail Bank')
        for k, v in BANK.items():
            setattr(vendor, k, v)
        db_session.commit()
        html = client.get('/vendors/%d' % vendor.id).get_data(as_text=True)
        assert 'BDO Unibank' in html and '001234567890' in html

    def test_the_export_carries_them(self, db_session):
        from app.vendors.views import (_VENDOR_EXPORT_COLUMNS, _VENDOR_EXPORT_HEADERS,
                                       _vendor_export_rows)
        vendor = make_vendor(db_session, code='BK005', name='Export Bank')
        vendor.bank_account_number = '0099'
        db_session.commit()
        for col in BANK:
            assert col in _VENDOR_EXPORT_COLUMNS
        assert len(_VENDOR_EXPORT_COLUMNS) == len(_VENDOR_EXPORT_HEADERS)
        row = next(r for r in _vendor_export_rows() if r['code'] == 'BK005')
        assert row['bank_account_number'] == '0099'
        assert row['bank_name'] == ''          # blank, never the text "None"


# ------------------------------------------------------------- the CDV screens
def _cdv(db_session, main_branch, method, bank=True):
    cdv = _cdv_with_je(db_session, main_branch)
    cdv.payment_method = method
    if bank:
        for k, v in BANK.items():
            setattr(cdv.vendor, k, v)
    db_session.commit()
    return cdv


def _deposit_block(html):
    """The rendered Deposit-to block, or None. Scoped to its data attribute so the
    absence assertions cannot pass on stray label text elsewhere on the page."""
    m = re.search(r'data-deposit-to[^>]*>(.*?)</(?:div|table|tbody)>', html, re.S)
    return m.group(1) if m else None


def _get(client, main_branch, url):
    login(client)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    resp = client.get(url)
    assert resp.status_code == 200, resp.headers.get('Location')
    return resp.get_data(as_text=True)


@pytest.mark.parametrize('page', ['detail', 'print'])
class TestCdvShowsTheDepositAccount:

    def _url(self, cdv, page):
        return '/cash-disbursements/%d%s' % (cdv.id, '' if page == 'detail' else '/print')

    @pytest.mark.parametrize('method', ['bank_transfer', 'online'])
    def test_a_deposit_cdv_shows_the_account(self, client, db_session, admin_user,
                                             main_branch, page, method):
        cdv = _cdv(db_session, main_branch, method)
        block = _deposit_block(_get(client, main_branch, self._url(cdv, page)))
        assert block is not None, 'no Deposit-to block on a %s CDV' % method
        for v in BANK.values():
            assert v in block

    @pytest.mark.parametrize('method', ['check', 'cash'])
    def test_a_non_deposit_cdv_does_not(self, client, db_session, admin_user,
                                        main_branch, page, method):
        cdv = _cdv(db_session, main_branch, method)
        html = _get(client, main_branch, self._url(cdv, page))
        assert 'data-deposit-to' not in html
        assert '001234567890' not in html, 'anti-leak: the account printed anyway'

    def test_a_deposit_cdv_with_no_details_stays_blank(self, client, db_session,
                                                       admin_user, main_branch, page):
        cdv = _cdv(db_session, main_branch, 'bank_transfer', bank=False)
        html = _get(client, main_branch, self._url(cdv, page))
        assert 'data-deposit-to' not in html
        assert 'not on file' not in html

    def test_it_reads_the_vendor_live(self, client, db_session, admin_user, main_branch,
                                      page):
        """Decision 2: an edited vendor account shows on the existing CDV."""
        cdv = _cdv(db_session, main_branch, 'bank_transfer')
        cdv.vendor.bank_account_number = '777000'
        db_session.commit()
        block = _deposit_block(_get(client, main_branch, self._url(cdv, page)))
        assert '777000' in block and '001234567890' not in block


# ------------------------------------------------------------- the pre-printed voucher
def _open_tag(html, needle):
    start = html.rindex('<div', 0, html.index(needle))
    return html[start:html.index('>', start) + 1]


def _field_text(html, key):
    m = re.search(r'data-el="%s"[^>]*>([^<]*)<' % key, html)
    assert m, '%s not rendered' % key
    return m.group(1)


class TestPreprintedField:

    def test_it_is_a_labelled_field_key(self):
        from app.cash_disbursements.preprinted_layout import FIELD_KEYS, FIELD_LABELS
        assert 'deposit_account' in FIELD_KEYS
        assert FIELD_LABELS['deposit_account'] == 'Deposit Account'

    def test_it_ships_hidden_and_hides_nothing_else(self):
        from app.cash_disbursements.preprinted_layout import sanitize_layout
        fields = sanitize_layout({})['fields']
        assert fields['deposit_account']['hidden'] is True
        assert fields['vendor_name']['hidden'] is False       # control

    def test_a_legacy_layout_gets_it_hidden(self):
        from app.cash_disbursements.preprinted_layout import sanitize_layout
        out = sanitize_layout({'fields': {'vendor_name': {'x': 100, 'y': 100}}})
        assert out['fields']['deposit_account']['hidden'] is True
        assert out['fields']['vendor_name']['x'] == 100

    def _render(self, client, db_session, main_branch, method, bank=True):
        from app.cash_disbursements.preprinted_layout import get_layout, save_layout
        cdv = _cdv(db_session, main_branch, method, bank=bank)
        lay = get_layout(main_branch.id)
        lay['fields']['deposit_account']['hidden'] = False
        save_layout(lay, 'admin', main_branch.id)
        AppSettings.set_setting('cd_print_form', 'preprinted', 'admin')
        db_session.commit()
        return _get(client, main_branch, '/cash-disbursements/%d/print' % cdv.id)

    def test_unhidden_it_prints_the_account_on_one_line(self, client, db_session,
                                                        admin_user, main_branch):
        html = self._render(client, db_session, main_branch, 'bank_transfer')
        assert 'pp-field-hidden' not in _open_tag(html, 'data-el="deposit_account"')
        text = _field_text(html, 'deposit_account')
        for v in BANK.values():
            assert v in text

    def test_it_is_blank_for_a_check(self, client, db_session, admin_user, main_branch):
        html = self._render(client, db_session, main_branch, 'check')
        assert _field_text(html, 'deposit_account').strip() == ''

    def test_a_deposit_with_no_details_prints_blank(self, client, db_session, admin_user,
                                                    main_branch):
        html = self._render(client, db_session, main_branch, 'bank_transfer', bank=False)
        assert _field_text(html, 'deposit_account').strip() == ''
