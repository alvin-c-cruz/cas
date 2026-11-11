"""The vendor's deposit slip form: which bank form a vendor's CDV slip opens on.

Owner, 10 Nov 2026, on the slip page's form dropdown (which did not stick): "I think its
better to have the same dropdown in vendor maintenance". Design approved the same day,
"VS-1 A, VS-2 A, VS-3 A, VS-4 A, VS-5 A" (work order
app-docs/bug-reports/2026-11-10-employee-bank-fields-for-deposit-slip.md, beside the checkout):

VS-1  A blank choice, "follow bank name", so no existing vendor changes.
VS-2  The slip opens on the vendor's form; the slip page's dropdown still changes it for that
      one print and saves nothing.
VS-3  A blank field follows the bank name: CBC / Chinabank -> Chinabank, BDO -> BDO; any other
      bank opens with a notice instead of quietly starting on Chinabank.
VS-5  One nullable column, its own migration.
CRV slips are not affected: they follow Philgen's own Bank Accounts record.
"""
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app import db
from app.audit.models import AuditLog
from app.vendors.models import Vendor
from tests.integration.test_cd_check_print import _check_cdv, _open
from tests.integration.test_cdv_print_form import login
from tests.integration.test_vendor_views import make_vat_category, make_vendor

pytestmark = [pytest.mark.integration, pytest.mark.vendors, pytest.mark.cash_disbursements]

BDO, CBC = 'bdo_v062019', 'chinabank_bnk108'


def _vendor_post(**extra):
    data = {'code': 'DS001', 'name': 'Slip Vendor', 'payment_terms': 'Net 30',
            'default_vat_category': 'V12DG', 'is_active': '1'}
    data.update(extra)
    return data


def _selected(html, name):
    m = re.search(r'<select[^>]*name="%s"[^>]*>(.*?)</select>' % name, html, re.S)
    assert m, '%s is not rendered' % name
    opt = re.search(r'<option selected value="([^"]*)"|<option value="([^"]*)" selected', m.group(1))
    return (opt.group(1) or opt.group(2)) if opt else None


def _slip(client, cdv, query=''):
    return client.get(f'/cash-disbursements/{cdv.id}/deposit-slip{query}').get_data(as_text=True)


def _notice(html):
    m = re.search(r'<div class="ds-notice[^"]*"[^>]*>(.*?)</div>', html, re.S)
    return m.group(1).strip() if m else None


# ------------------------------------------------------------- the vendor master
class TestVendorMaster:

    def test_create_stores_the_form_and_audits_it(self, client, db_session, admin_user, main_branch):
        login(client)
        make_vat_category(db_session)
        client.post('/vendors/create', data=_vendor_post(deposit_slip_form=BDO), follow_redirects=True)
        vendor = Vendor.query.filter_by(code='DS001').first()
        assert vendor is not None, 'anti-vacuity: the vendor was not created'
        assert vendor.deposit_slip_form == BDO
        audit = AuditLog.query.filter_by(module='vendor', action='create', record_id=vendor.id).first()
        assert BDO in (audit.new_values or '')

    def test_blank_means_follow_the_bank_name(self, client, db_session, admin_user, main_branch):
        login(client)
        make_vat_category(db_session)
        client.post('/vendors/create', data=_vendor_post(deposit_slip_form=''), follow_redirects=True)
        vendor = Vendor.query.filter_by(code='DS001').first()
        assert vendor is not None
        assert vendor.deposit_slip_form is None          # stored as NULL, never ''

    def test_a_form_left_out_of_the_post_is_blank(self, client, db_session, admin_user, main_branch):
        """The quick-add modals post no such field."""
        login(client)
        make_vat_category(db_session)
        client.post('/vendors/create', data=_vendor_post(), follow_redirects=True)
        vendor = Vendor.query.filter_by(code='DS001').first()
        assert vendor is not None, 'a post without the field must still create the vendor'
        assert vendor.deposit_slip_form is None

    def test_an_unknown_form_is_refused(self, client, db_session, admin_user, main_branch):
        login(client)
        make_vat_category(db_session)
        client.post('/vendors/create', data=_vendor_post(deposit_slip_form='bpi_nope'), follow_redirects=True)
        assert Vendor.query.filter_by(code='DS001').first() is None

    def test_edit_changes_it_and_audits_before_and_after(self, client, db_session, admin_user, main_branch):
        login(client)
        make_vat_category(db_session)
        vendor = make_vendor(db_session, code='DS002', name='Edit Slip')
        vendor.deposit_slip_form = CBC
        db_session.commit()
        client.post('/vendors/%d/edit' % vendor.id,
                    data=_vendor_post(code='DS002', name='Edit Slip', deposit_slip_form=BDO),
                    follow_redirects=True)
        db_session.refresh(vendor)
        assert vendor.deposit_slip_form == BDO
        audit = AuditLog.query.filter_by(module='vendor', action='update', record_id=vendor.id).first()
        assert CBC in (audit.old_values or '') and BDO in (audit.new_values or '')

    def test_an_edit_that_leaves_the_field_out_saves_and_keeps_the_form(
            self, client, db_session, admin_user, main_branch):
        """Posts that predate the field (older tests, scripts) must not be refused or wipe it."""
        login(client)
        make_vat_category(db_session)
        vendor = make_vendor(db_session, code='DS008', name='Keep Slip')
        vendor.deposit_slip_form = BDO
        db_session.commit()
        client.post('/vendors/%d/edit' % vendor.id,
                    data=_vendor_post(code='DS008', name='Kept Slip'), follow_redirects=True)
        db_session.refresh(vendor)
        assert vendor.name == 'Kept Slip', 'the edit was refused'
        assert vendor.deposit_slip_form == BDO

    def test_an_edit_of_a_blank_vendor_without_the_field_saves(
            self, client, db_session, admin_user, main_branch):
        login(client)
        make_vat_category(db_session)
        vendor = make_vendor(db_session, code='DS009', name='Blank Slip')
        client.post('/vendors/%d/edit' % vendor.id,
                    data=_vendor_post(code='DS009', name='Blank Slip 2'), follow_redirects=True)
        db_session.refresh(vendor)
        assert vendor.name == 'Blank Slip 2', 'the edit was refused'
        assert vendor.deposit_slip_form is None

    def test_the_form_offers_follow_bank_name_then_every_slip_form(
            self, client, db_session, admin_user, main_branch):
        from app.common import deposit_slip as ds
        login(client)
        vendor = make_vendor(db_session, code='DS003', name='Show Slip')
        vendor.deposit_slip_form = BDO
        db_session.commit()
        html = client.get('/vendors/%d/edit' % vendor.id).get_data(as_text=True)
        assert _selected(html, 'deposit_slip_form') == BDO
        m = re.search(r'<select[^>]*name="deposit_slip_form"[^>]*>(.*?)</select>', html, re.S)
        values = re.findall(r'<option[^>]*value="([^"]*)"', m.group(1))
        assert values == [''] + list(ds.FORMS)
        assert 'follow bank name' in m.group(1)
        for form in ds.FORMS.values():
            assert form['label'] in m.group(1)

    def test_the_detail_page_names_the_form(self, client, db_session, admin_user, main_branch):
        login(client)
        vendor = make_vendor(db_session, code='DS004', name='Detail Slip')
        vendor.deposit_slip_form = BDO
        db_session.commit()
        html = client.get('/vendors/%d' % vendor.id).get_data(as_text=True)
        assert 'BDO Check Transaction Slip (V062019)' in html

    def test_the_detail_page_says_blank_follows_the_bank(self, client, db_session, admin_user, main_branch):
        login(client)
        vendor = make_vendor(db_session, code='DS005', name='Detail Blank')
        html = client.get('/vendors/%d' % vendor.id).get_data(as_text=True)
        assert 'Follows bank name' in html

    def test_the_export_carries_the_form_by_name(self, db_session):
        from app.vendors.views import _VENDOR_EXPORT_COLUMNS, _VENDOR_EXPORT_HEADERS, _vendor_export_rows
        a = make_vendor(db_session, code='DS006', name='Export Slip')
        a.deposit_slip_form = BDO
        make_vendor(db_session, code='DS007', name='Export Blank')
        db_session.commit()
        assert 'deposit_slip_form' in _VENDOR_EXPORT_COLUMNS
        assert len(_VENDOR_EXPORT_COLUMNS) == len(_VENDOR_EXPORT_HEADERS)
        rows = {r['code']: r for r in _vendor_export_rows()}
        assert rows['DS006']['deposit_slip_form'] == 'BDO Check Transaction Slip (V062019)'
        assert rows['DS007']['deposit_slip_form'] == ''


# ------------------------------------------------------------- the CDV slip
class TestTheSlip:

    def test_the_vendors_form_wins_over_its_bank_name(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        cdv.vendor.bank_name = 'CBC'
        cdv.vendor.deposit_slip_form = BDO
        db.session.commit()
        _open(client, main_branch)
        html = _slip(client, cdv)
        assert f'<option value="{BDO}" selected>' in html
        assert _notice(html) is None

    def test_the_slip_page_still_changes_it_for_one_print_and_saves_nothing(
            self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        cdv.vendor.deposit_slip_form = BDO
        db.session.commit()
        _open(client, main_branch)
        html = _slip(client, cdv, f'?form={CBC}')
        assert f'<option value="{CBC}" selected>' in html
        db.session.refresh(cdv.vendor)
        assert cdv.vendor.deposit_slip_form == BDO

    @pytest.mark.parametrize('bank, form', [
        ('CBC', CBC), ('CHINA BANK', CBC), ('Chinabank', CBC), ('CBC / Eastwood', CBC),
        ('BDO', BDO), ('BDO Unibank', BDO), ('Banco de Oro', BDO),
    ])
    def test_blank_follows_a_known_bank_without_a_notice(
            self, client, db_session, admin_user, main_branch, bank, form):
        cdv = _check_cdv(db_session, main_branch)
        cdv.vendor.bank_name = bank
        db.session.commit()
        _open(client, main_branch)
        html = _slip(client, cdv)
        assert f'<option value="{form}" selected>' in html
        assert _notice(html) is None

    @pytest.mark.parametrize('bank', ['BPI', 'METROBANK', 'Sterling Bank of Asia'])
    def test_another_bank_opens_with_a_notice(self, client, db_session, admin_user, main_branch, bank):
        cdv = _check_cdv(db_session, main_branch)
        cdv.vendor.bank_name = bank
        db.session.commit()
        _open(client, main_branch)
        html = _slip(client, cdv)
        notice = _notice(html)
        assert notice is not None, 'an unknown bank must not open quietly'
        assert bank in notice and 'vendor maintenance' in notice
        assert f'<option value="{CBC}" selected>' in html         # the page still renders on a form

    def test_choosing_a_form_on_the_page_clears_the_notice(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        cdv.vendor.bank_name = 'BPI'
        db.session.commit()
        _open(client, main_branch)
        assert _notice(_slip(client, cdv, f'?form={BDO}')) is None

    def test_no_bank_at_all_opens_on_chinabank_without_a_notice(
            self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        html = _slip(client, cdv)
        assert f'<option value="{CBC}" selected>' in html
        assert _notice(html) is None

    def test_a_stored_form_that_no_longer_exists_falls_back_to_the_bank(
            self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        cdv.vendor.bank_name = 'BDO'
        cdv.vendor.deposit_slip_form = 'retired_form'
        db.session.commit()
        _open(client, main_branch)
        assert f'<option value="{BDO}" selected>' in _slip(client, cdv)


class TestReceiptsUnaffected:

    def test_a_receipt_into_a_bank_without_a_form_has_no_notice(
            self, client, db_session, admin_user, main_branch, posted_crv_v12):
        from decimal import Decimal
        from app.bank_accounts.models import BankAccount
        crv = posted_crv_v12
        crv.payment_method, crv.check_number, crv.total_amount = 'check', '0001104995', Decimal('100')
        db.session.add(BankAccount(branch_id=main_branch.id, code='BPI-1', name='BPI 1',
                                   account_id=crv.cash_account_id, bank_name='BPI', account_number='1'))
        db.session.commit()
        _open(client, main_branch)
        html = client.get(f'/cash-receipts/{crv.id}/deposit-slip').get_data(as_text=True)
        assert f'<option value="{CBC}" selected>' in html
        assert _notice(html) is None


# ------------------------------------------------------------- the migration
CAS_ROOT = Path(__file__).resolve().parents[2]


def _run_flask(args, db_path):
    env = dict(os.environ, SECRET_KEY='migration-test', FLASK_APP='flask_app.py',
               SQLALCHEMY_DATABASE_URI=f'sqlite:///{db_path}')
    env.pop('CAS_EXPECT_COMPANY', None)
    return subprocess.run([sys.executable, '-m', 'flask', 'db', *args], cwd=CAS_ROOT, env=env,
                          capture_output=True, text=True, check=True)


def test_the_migration_adds_a_blank_column_and_downgrades_cleanly(tmp_path):
    db_path = tmp_path / 'dslip.db'; db_path.touch()
    _run_flask(['upgrade', 'invunit_0001'], db_path)
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO vendors (code, name, is_active) VALUES ('V1', 'Vendor One', 1)")

    con.execute("INSERT INTO branches (code, name, is_active) VALUES ('B', 'B', 1)")
    con.execute("INSERT INTO employees (employee_no, first_name, last_name, branch_id, is_active, "
                "is_salesperson, created_at, updated_at) VALUES ('E1', 'Ana', 'Tang', 1, 1, 0, "
                "'2026-11-10 00:00:00', '2026-11-10 00:00:00')")
    con.commit(); con.close()

    _run_flask(['upgrade', 'dslip_0001'], db_path)
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT deposit_slip_form FROM vendors").fetchall() == [(None,)]   # VS-1: no vendor changes
    assert con.execute("SELECT bank_name, bank_account_name, bank_account_number, deposit_slip_form "
                       "FROM employees").fetchall() == [(None, None, None, None)]          # VS-4, VS-5: one migration
    con.close()

    _run_flask(['downgrade', 'invunit_0001'], db_path)
    con = sqlite3.connect(db_path)
    assert 'deposit_slip_form' not in {r[1] for r in con.execute("PRAGMA table_info(vendors)")}
    emp_cols = {r[1] for r in con.execute("PRAGMA table_info(employees)")}
    assert not emp_cols & {'bank_name', 'bank_account_name', 'bank_account_number', 'deposit_slip_form'}
    assert con.execute("SELECT employee_no FROM employees").fetchall() == [('E1',)]
    assert con.execute("SELECT code FROM vendors").fetchall() == [('V1',)]
    assert con.execute("PRAGMA integrity_check").fetchone() == ('ok',)
    con.close()
