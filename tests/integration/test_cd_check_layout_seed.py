"""Every cash account gets its own cheque layout, seeded from the last one saved.

BUG-CHECK-BOXED-DATE-NO-PREVIEW (Philgen, 2 Nov 2026): CDV 1722 is paid from CHINABANK
046-3, which had no saved cheque layout, so its print-check page fell back to the
hardcoded default (date not boxed, placeholder positions) while CBC 091-9 had a fitted,
boxed layout. Owner's rule, Alvin, 2 Nov 2026: "every cash account should have its saved
check layout. if none, then copy the last user used layout as base template".

So opening print-check for a CDV whose cash account has no `cd_check_layout:<id>` row
writes one: a copy of the most recently saved cheque layout, audited with its source. The
hardcoded default stays only for a company that has never saved any cheque layout.
"""
import json
from datetime import datetime

import pytest

from app.settings import AppSettings
from app.audit.models import AuditLog
from app.cash_disbursements.check_layout import LAYOUT_SETTING_KEY, save_layout, get_layout
from tests.integration.test_cd_check_print import _check_cdv, _open

pytestmark = [pytest.mark.cash_disbursements, pytest.mark.integration]

BOXED_SOURCE = {'fields': {
    'payee': {'x': 333, 'y': 170},
    'check_date': {'x': 600, 'y': 80, 'boxed': True, 'pitch': 26, 'digitOffsets': [0, 26, 70, 96, 140, 166, 192, 218]},
}}


def _row(key):
    return AppSettings.query.filter_by(key=key).first()


def _stamp(db_session, key, when):
    row = _row(key)
    row.updated_at = when
    db_session.commit()


def _print(client, cdv):
    return client.get(f'/cash-disbursements/{cdv.id}/print-check')


def test_a_bare_account_opens_with_a_copy_of_the_saved_layout(client, db_session, admin_user, main_branch):
    cdv = _check_cdv(db_session, main_branch)
    save_layout(BOXED_SOURCE, 'admin', account_id=9001)
    _open(client, main_branch)
    body = _print(client, cdv).data.decode()
    assert 'class="pp-el pp-boxed' in body, 'the date did not arrive boxed from the copied layout'
    own = _row(f'{LAYOUT_SETTING_KEY}:{cdv._cash_acct_id}')
    assert own is not None, 'the account did not get its own layout row'
    assert json.loads(own.value) == json.loads(_row(f'{LAYOUT_SETTING_KEY}:9001').value)


def test_the_most_recently_saved_layout_is_the_source(client, db_session, admin_user, main_branch):
    cdv = _check_cdv(db_session, main_branch)
    save_layout({'fields': {'payee': {'x': 211, 'y': 170}}}, 'admin', account_id=9001)
    save_layout({'fields': {'payee': {'x': 422, 'y': 170}}}, 'admin', account_id=9002)
    # 9001 saved LATER than 9002, whatever the insertion order.
    _stamp(db_session, f'{LAYOUT_SETTING_KEY}:9001', datetime(2026, 11, 2, 9, 45))
    _stamp(db_session, f'{LAYOUT_SETTING_KEY}:9002', datetime(2026, 9, 18, 10, 0))
    _open(client, main_branch)
    _print(client, cdv)
    assert get_layout(cdv._cash_acct_id)['fields']['payee']['x'] == 211


def test_the_default_layout_counts_as_a_saved_layout(client, db_session, admin_user, main_branch):
    cdv = _check_cdv(db_session, main_branch)
    save_layout({'fields': {'payee': {'x': 377, 'y': 170}}}, 'admin', account_id=None)
    _open(client, main_branch)
    _print(client, cdv)
    own = _row(f'{LAYOUT_SETTING_KEY}:{cdv._cash_acct_id}')
    assert own is not None and json.loads(own.value)['fields']['payee']['x'] == 377


def test_seeding_is_audited_with_its_source(client, db_session, admin_user, main_branch):
    cdv = _check_cdv(db_session, main_branch)
    save_layout(BOXED_SOURCE, 'admin', account_id=9001)
    _open(client, main_branch)
    _print(client, cdv)
    entry = (AuditLog.query
             .filter_by(module='cash_disbursements', record_identifier='cd_check_layout')
             .order_by(AuditLog.id.desc()).first())
    assert entry is not None and entry.action == 'create'
    assert f'{LAYOUT_SETTING_KEY}:9001' in (entry.notes or '')
    assert f'account {cdv._cash_acct_id}' in (entry.notes or '')


def test_the_copy_does_not_follow_later_edits_of_its_source(client, db_session, admin_user, main_branch):
    cdv = _check_cdv(db_session, main_branch)
    save_layout(BOXED_SOURCE, 'admin', account_id=9001)
    _open(client, main_branch)
    _print(client, cdv)
    save_layout({'fields': {'payee': {'x': 500, 'y': 170}}}, 'admin', account_id=9001)
    _print(client, cdv)
    assert get_layout(cdv._cash_acct_id)['fields']['payee']['x'] == 333


def test_editing_the_copy_never_changes_its_source(client, db_session, admin_user, main_branch):
    cdv = _check_cdv(db_session, main_branch)
    save_layout(BOXED_SOURCE, 'admin', account_id=9001)
    _open(client, main_branch)
    _print(client, cdv)
    resp = client.post(f'/cash-disbursements/check-layout?account_id={cdv._cash_acct_id}',
                       json={'fields': {'payee': {'x': 150, 'y': 170}}})
    assert resp.status_code == 200
    assert get_layout(9001)['fields']['payee']['x'] == 333


def test_an_account_with_its_own_layout_keeps_it(client, db_session, admin_user, main_branch):
    cdv = _check_cdv(db_session, main_branch)
    save_layout({'fields': {'payee': {'x': 260, 'y': 170}}}, 'admin', account_id=cdv._cash_acct_id)
    save_layout(BOXED_SOURCE, 'admin', account_id=9001)       # newer, but not this account's
    _open(client, main_branch)
    before = AuditLog.query.count()
    _print(client, cdv)
    assert get_layout(cdv._cash_acct_id)['fields']['payee']['x'] == 260
    assert AuditLog.query.filter_by(record_identifier='cd_check_layout').count() == 2
    assert AuditLog.query.count() == before + 1               # the print_check row only


def test_with_no_saved_layout_anywhere_nothing_is_written(client, db_session, admin_user, main_branch):
    cdv = _check_cdv(db_session, main_branch)
    _open(client, main_branch)
    resp = _print(client, cdv)
    assert resp.status_code == 200
    assert AppSettings.query.filter(AppSettings.key.like(f'{LAYOUT_SETTING_KEY}%')).count() == 0


def test_a_corrupt_newest_layout_is_skipped(client, db_session, admin_user, main_branch):
    cdv = _check_cdv(db_session, main_branch)
    save_layout(BOXED_SOURCE, 'admin', account_id=9001)
    AppSettings.set_setting(f'{LAYOUT_SETTING_KEY}:9002', 'not-json{', 'admin')
    _stamp(db_session, f'{LAYOUT_SETTING_KEY}:9001', datetime(2026, 9, 18, 10, 0))
    _stamp(db_session, f'{LAYOUT_SETTING_KEY}:9002', datetime(2026, 11, 2, 9, 45))
    _open(client, main_branch)
    _print(client, cdv)
    assert get_layout(cdv._cash_acct_id)['fields']['payee']['x'] == 333


def test_a_staff_print_also_seeds_the_account(client, db_session, admin_user, staff_user, main_branch):
    """Anyone allowed to print the cheque gets the copied layout -- the copy is not an
    edit, so it does not need the designer's full access."""
    staff_user.set_branches([main_branch]); db_session.commit()
    cdv = _check_cdv(db_session, main_branch)
    save_layout(BOXED_SOURCE, 'admin', account_id=9001)
    _open(client, main_branch, 'staff', 'staff123')
    resp = _print(client, cdv)
    assert resp.status_code == 200
    assert 'class="pp-el pp-boxed' in resp.data.decode()
    assert _row(f'{LAYOUT_SETTING_KEY}:{cdv._cash_acct_id}') is not None


class TestPlainDateOnTheField:
    """The designer needs the formatted date to turn a boxed run back into one string
    (and to build cells from a plain one), so the check-date field carries it."""

    def test_a_plain_date_carries_data_plain(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        body = _print(client, cdv).data.decode()
        assert 'data-plain="07-08-2026"' in body

    def test_a_boxed_date_carries_data_plain(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        save_layout({'fields': {'check_date': {'boxed': True}}}, 'admin', account_id=cdv._cash_acct_id)
        _open(client, main_branch)
        body = _print(client, cdv).data.decode()
        assert 'class="pp-el pp-boxed' in body
        assert 'data-plain="07-08-2026"' in body
