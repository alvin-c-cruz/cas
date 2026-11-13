"""A search on the SI, CR, AP and JV lists looks across all dates, as on the CDV list.

Owner, 12 Nov 2026 (relayed by the root): "S8 A" (bug report #8, the CDV list), NAME-1 "A: search across
all dates too, like number searches.", and S8-ALL "A: do the same on those lists." The lists open on the
current month (owner, 22 Oct 2026) and their filter forms always submit From / To, so a search for an
older document found nothing. Now any search text ignores From / To, the date boxes show blank, the
page says so, and the Download Journal link keeps a real period (the month).

The JV list had no search box; it gets one (JV number, reference or description) to do the same.
The fixtures' documents are dated 15 Feb 2026, outside the current month.
"""
import re
from datetime import date

import pytest

from app import db
from app.utils_helpers import this_month_iso
from tests.integration.test_cd_check_print import _open

pytestmark = [pytest.mark.integration]


@pytest.fixture
def old_jv(db_session, main_branch, admin_user):
    from app.journal_entries.models import JournalEntry
    je = JournalEntry(entry_number='JV-2026-02-0007', entry_date=date(2026, 2, 15),
                      description='Accrual of February rent', reference='RENT-FEB',
                      entry_type='adjustment', branch_id=main_branch.id, status='draft',
                      created_by_id=admin_user.id)
    db.session.add(je)
    db.session.commit()
    return je


# list URL, fixture, its number, a name / text that matches it
LISTS = [
    ('/sales-invoices', 'posted_si_v12', 'SI-VL-0001', 'VAT Lines Customer'),
    ('/cash-receipts', 'posted_crv_v12', 'CRV-VL-0001', 'VAT Lines Customer'),
    ('/accounts-payable', 'posted_ap_v12sv', 'AP-VL-0001', 'VAT Lines Vendor'),
    ('/journals/voucher', 'old_jv', 'JV-2026-02-0007', 'February rent'),
]
IDS = ['si', 'cr', 'ap', 'jv']


def _page(client, url, **params):
    """The list as its filter form submits it: the month's From / To always come along."""
    bom, eom = this_month_iso()
    query = {'date_from': bom, 'date_to': eom, 'status': 'all'}
    query.update(params)
    return client.get(url, query_string=query).get_data(as_text=True)


def _listed(html, number):
    return re.search(r'>\s*%s\s*<' % re.escape(number), html) is not None


@pytest.mark.parametrize('url, fixture, number, text', LISTS, ids=IDS)
def test_a_number_search_finds_an_older_document(request, client, admin_user, main_branch, url, fixture, number, text):
    request.getfixturevalue(fixture)
    _open(client, main_branch)
    assert not _listed(_page(client, url), number), 'anti-vacuity: not in this month without a search'
    assert _listed(_page(client, url, q=number), number)


@pytest.mark.parametrize('url, fixture, number, text', LISTS, ids=IDS)
def test_a_name_search_finds_an_older_document(request, client, admin_user, main_branch, url, fixture, number, text):
    request.getfixturevalue(fixture)
    _open(client, main_branch)
    assert _listed(_page(client, url, q=text), number)


@pytest.mark.parametrize('url, fixture, number, text', LISTS, ids=IDS)
def test_the_page_says_so_and_blanks_the_range(request, client, admin_user, main_branch, url, fixture, number, text):
    request.getfixturevalue(fixture)
    _open(client, main_branch)
    html = _page(client, url, q=number)
    assert 'Searching all dates' in html
    assert 'name="date_from" value=""' in html and 'name="date_to" value=""' in html
    assert 'name="q"' in html, 'the list has a search box'


@pytest.mark.parametrize('url, fixture, number, text', LISTS, ids=IDS)
def test_the_download_keeps_a_real_period(request, client, admin_user, main_branch, url, fixture, number, text):
    bom, eom = this_month_iso()
    request.getfixturevalue(fixture)
    _open(client, main_branch)
    html = _page(client, url, q=number)
    link = re.search(r'href="([^"]*)"\s+id="journal-download"', html).group(1)
    assert f'date_from={bom}' in link and f'date_to={eom}' in link


@pytest.mark.parametrize('url, fixture, number, text', LISTS, ids=IDS)
def test_no_search_still_opens_on_this_month(request, client, admin_user, main_branch, url, fixture, number, text):
    bom, eom = this_month_iso()
    request.getfixturevalue(fixture)
    _open(client, main_branch)
    html = client.get(url).get_data(as_text=True)
    assert f'name="date_from" value="{bom}"' in html and f'name="date_to" value="{eom}"' in html
    assert 'Searching all dates' not in html
    assert not _listed(html, number)


def test_a_jv_search_prints_only_its_matches(client, admin_user, main_branch, old_jv):
    """The JV list's Print carries the search, so a search over all dates never prints every JV."""
    from app.journal_entries.models import JournalEntry
    from app.utils_helpers import ph_now
    db.session.add(JournalEntry(entry_number='JV-NOW-0001', entry_date=ph_now().date(),
                                description='Unrelated current entry', entry_type='adjustment',
                                branch_id=main_branch.id, status='draft', created_by_id=admin_user.id))
    db.session.commit()
    _open(client, main_branch)
    page = _page(client, '/journals/voucher', q='RENT-FEB')
    link = re.search(r'href="([^"]*voucher/print[^"]*)"', page).group(1)
    assert 'q=RENT-FEB' in link
    printed = client.get('/journals/voucher/print', query_string={'q': 'RENT-FEB', 'date_from': '',
                                                                 'date_to': '', 'status': 'all'})
    text = printed.get_data(as_text=True)
    assert 'JV-2026-02-0007' in text and 'JV-NOW-0001' not in text
