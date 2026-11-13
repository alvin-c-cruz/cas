"""A CDV-number search on the CDV list looks across all dates.

In-app bug report #8 (Philgen): a CDV searched by number did not show, because the list's From / To
open on the current month (owner, 22 Oct 2026) and the filter form always submits them. Owner, 12 Nov
2026, relayed by the root: "S8 A" -- a CDV-number search looks across all dates.

Owner, 12 Nov 2026, NAME-1: "A: search across all dates too, like number searches." So ANY search
text (a CDV number or a payee name) ignores From / To.
"""
import re
from datetime import date

import pytest

from app import db
from app.utils_helpers import this_month_iso
from tests.integration.test_cd_check_print import _check_cdv, _open

pytestmark = [pytest.mark.integration, pytest.mark.cash_disbursements]


def _old_cdv(db_session, main_branch, number='1365E'):
    cdv = _check_cdv(db_session, main_branch)
    cdv.cdv_number = number
    cdv.cdv_date = date(2025, 3, 14)                 # far outside this month
    db.session.commit()
    return cdv


def _list(client, **params):
    """The list as the filter form submits it: the month's From / To always come along."""
    bom, eom = this_month_iso()
    query = {'date_from': bom, 'date_to': eom, 'status': 'all', 'payee': 'all', 'payment_method': 'all'}
    query.update(params)
    return client.get('/cash-disbursements', query_string=query).get_data(as_text=True)


def _listed(html, number):
    return re.search(r'>\s*%s\s*<' % re.escape(number), html) is not None


def test_a_number_search_finds_a_cdv_outside_the_month(client, db_session, admin_user, main_branch):
    _old_cdv(db_session, main_branch)
    _open(client, main_branch)
    assert not _listed(_list(client), '1365E'), 'anti-vacuity: not in this month without a search'
    assert _listed(_list(client, q='1365E'), '1365E')


def test_a_partial_number_search_also_spans_all_dates(client, db_session, admin_user, main_branch):
    _old_cdv(db_session, main_branch)
    _open(client, main_branch)
    assert _listed(_list(client, q='1365'), '1365E')


def test_the_page_says_it_searched_all_dates_and_blanks_the_range(client, db_session, admin_user, main_branch):
    _old_cdv(db_session, main_branch)
    _open(client, main_branch)
    html = _list(client, q='1365E')
    assert 'Searching all dates' in html
    assert re.search(r'name="date_from" value=""', html)
    assert re.search(r'name="date_to" value=""', html)


def test_a_payee_name_search_also_spans_all_dates(client, db_session, admin_user, main_branch):
    """Owner, 12 Nov 2026, NAME-1: "A: search across all dates too, like number searches." """
    _old_cdv(db_session, main_branch)                # payee Meralco, dated 2025
    _open(client, main_branch)
    html = _list(client, q='Meralco')
    assert _listed(html, '1365E')
    assert 'Searching all dates' in html


def test_no_search_still_opens_on_this_month(client, db_session, admin_user, main_branch):
    bom, eom = this_month_iso()
    _open(client, main_branch)
    html = client.get('/cash-disbursements').get_data(as_text=True)
    assert f'name="date_from" value="{bom}"' in html and f'name="date_to" value="{eom}"' in html
    assert 'Searching all dates' not in html


def test_the_journal_download_keeps_a_real_period_during_a_number_search(
        client, db_session, admin_user, main_branch):
    bom, eom = this_month_iso()
    _old_cdv(db_session, main_branch)
    _open(client, main_branch)
    html = _list(client, q='1365E')
    link = re.search(r'href="([^"]*)"\s+id="journal-download"', html).group(1)
    assert f'date_from={bom}' in link and f'date_to={eom}' in link
