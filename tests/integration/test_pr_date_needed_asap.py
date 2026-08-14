"""Purchase Requisition: ASAP as an alternative to a specific Date Needed.

Owner directive 2026-08-14: a requestor who needs the goods immediately ticks
ASAP rather than inventing a date. ASAP and a date are MUTUALLY EXCLUSIVE -- one
meaning per record. Ticking ASAP clears date_needed, so a printout can never read
"ASAP" while a report sorts the same row by a stale date left behind from before
the box was ticked.

The exclusivity is enforced SERVER-SIDE, not merely by the JS that greys out the
date input. A disabled input is a convenience; a POST can carry both fields
regardless (curl, a stale tab, a future refactor), and the rule has to hold there
too. TestTheServerEnforcesExclusivity is the half that matters.
"""
from datetime import date

import pytest

from app import db
from app.purchase_requests.models import PurchaseRequest

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def pr_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_requests', 'units_of_measure'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _date_needed_cell(html):
    """The Date Needed <td> from the printed meta table, so an assertion about
    that field cannot be answered by text elsewhere on the sheet."""
    i = html.index('Date Needed')
    j = html.index('</td>', i)
    return html[i:j]


@pytest.fixture
def asap_pr(db_session, admin_user, main_branch):
    p = PurchaseRequest(pr_number='DN-A1', request_date=date(2026, 8, 14),
                        date_needed_asap=True, branch_id=main_branch.id,
                        status='draft', created_by_id=admin_user.id)
    db_session.add(p)
    db_session.commit()
    return p


@pytest.fixture
def dated_pr(db_session, admin_user, main_branch):
    p = PurchaseRequest(pr_number='DN-A2', request_date=date(2026, 8, 14),
                        date_needed=date(2026, 9, 15), branch_id=main_branch.id,
                        status='draft', created_by_id=admin_user.id)
    db_session.add(p)
    db_session.commit()
    return p


class TestTheColumn:

    def test_it_defaults_to_false(self, dated_pr):
        """Existing requisitions are not ASAP -- the column arrives with a
        server default so the rows already in PhilGen's database stay valid."""
        assert dated_pr.date_needed_asap is False

    def test_it_is_in_the_amendment_snapshot(self):
        assert 'date_needed_asap' in PurchaseRequest.SNAPSHOT_HEADER_FIELDS

    def test_to_dict_exposes_it(self, asap_pr):
        d = asap_pr.to_dict()
        assert d['date_needed_asap'] is True
        assert d['date_needed'] is None


class TestTheFormRendersIt:

    def test_create_form_renders_the_checkbox(self, client, admin_user, main_branch):
        _login(client, admin_user, main_branch)
        html = client.get('/purchase-requests/create').data.decode()
        assert 'name="date_needed_asap"' in html, 'the checkbox is not rendered'
        assert 'ASAP' in html

    def test_edit_form_reflects_a_ticked_box(self, client, admin_user, main_branch, asap_pr):
        """A checkbox rendered without its checked state silently unticks itself
        on the next save."""
        _login(client, admin_user, main_branch)
        html = client.get(f'/purchase-requests/{asap_pr.id}/edit').data.decode()
        i = html.index('name="date_needed_asap"')
        assert 'checked' in html[max(0, i - 160):i + 160]

    def test_edit_form_leaves_it_unticked_when_a_date_is_set(self, client, admin_user,
                                                             main_branch, dated_pr):
        """Control: the checked state must be conditional, not always emitted."""
        _login(client, admin_user, main_branch)
        html = client.get(f'/purchase-requests/{dated_pr.id}/edit').data.decode()
        i = html.index('name="date_needed_asap"')
        assert 'checked' not in html[max(0, i - 160):i + 160]


class TestTheServerEnforcesExclusivity:
    """The JS greys the date input out; these prove the RULE, not the courtesy."""

    def _payload(self, **over):
        data = {'pr_number': 'DN-ANEW', 'request_date': '2026-08-14',
                'reason': 'urgent',
                'line_items': '[{"description": "Gasket", "quantity": "1"}]'}
        data.update(over)
        return data

    def test_asap_clears_a_date_submitted_alongside_it(self, client, db_session,
                                                       admin_user, main_branch):
        """A POST carrying BOTH -- exactly what a disabled input cannot prevent."""
        _login(client, admin_user, main_branch)
        client.post('/purchase-requests/create',
                    data=self._payload(date_needed='2026-09-15',
                                       date_needed_asap='y'),
                    follow_redirects=True)

        p = PurchaseRequest.query.filter_by(pr_number='DN-ANEW').first()
        assert p is not None, 'the requisition was not created'
        assert p.date_needed_asap is True
        assert p.date_needed is None, (
            'both meanings stored at once -- the printout would read ASAP while '
            'a report sorted this row by September')

    def test_a_plain_date_is_untouched(self, client, db_session, admin_user, main_branch):
        """Control: without ASAP the date behaves exactly as before."""
        _login(client, admin_user, main_branch)
        client.post('/purchase-requests/create',
                    data=self._payload(pr_number='DN-ADATE',
                                       date_needed='2026-09-15'),
                    follow_redirects=True)

        p = PurchaseRequest.query.filter_by(pr_number='DN-ADATE').first()
        assert p.date_needed == date(2026, 9, 15)
        assert p.date_needed_asap is False

    def test_neither_is_still_allowed(self, client, db_session, admin_user, main_branch):
        """Control: both remain optional. A requestor who knows neither must
        still be able to raise the requisition."""
        _login(client, admin_user, main_branch)
        client.post('/purchase-requests/create',
                    data=self._payload(pr_number='DN-ANONE'), follow_redirects=True)

        p = PurchaseRequest.query.filter_by(pr_number='DN-ANONE').first()
        assert p is not None
        assert p.date_needed is None and p.date_needed_asap is False

    def test_editing_can_switch_from_asap_to_a_date(self, client, db_session,
                                                    admin_user, main_branch, asap_pr):
        _login(client, admin_user, main_branch)
        client.post(f'/purchase-requests/{asap_pr.id}/edit', data={
            'pr_number': 'DN-A1', 'request_date': '2026-08-14',
            'date_needed': '2026-10-05', 'reason': 'WITNESS-TO-DATE',
            'row_version': asap_pr.row_version,
            'line_items': '[{"description": "Gasket", "quantity": "1"}]',
        }, follow_redirects=True)

        p = db.session.get(PurchaseRequest, asap_pr.id)
        assert p.reason == 'WITNESS-TO-DATE', 'the edit never applied'
        assert p.date_needed_asap is False
        assert p.date_needed == date(2026, 10, 5)

    def test_editing_can_switch_from_a_date_to_asap(self, client, db_session,
                                                    admin_user, main_branch, dated_pr):
        _login(client, admin_user, main_branch)
        client.post(f'/purchase-requests/{dated_pr.id}/edit', data={
            'pr_number': 'DN-A2', 'request_date': '2026-08-14',
            'date_needed': '2026-09-15', 'date_needed_asap': 'y',
            'reason': 'WITNESS-TO-ASAP', 'row_version': dated_pr.row_version,
            'line_items': '[{"description": "Gasket", "quantity": "1"}]',
        }, follow_redirects=True)

        p = db.session.get(PurchaseRequest, dated_pr.id)
        assert p.reason == 'WITNESS-TO-ASAP', 'the edit never applied'
        assert p.date_needed_asap is True
        assert p.date_needed is None, 'the old date survived the switch to ASAP'


class TestItIsVisible:

    def test_the_detail_page_reads_asap(self, client, admin_user, main_branch, asap_pr):
        _login(client, admin_user, main_branch)
        html = client.get(f'/purchase-requests/{asap_pr.id}').data.decode()
        assert 'ASAP' in html

    def test_the_printout_reads_asap(self, client, admin_user, main_branch, asap_pr):
        _login(client, admin_user, main_branch)
        html = client.get(f'/purchase-requests/{asap_pr.id}/print').data.decode()
        assert 'ASAP' in html

    def test_a_dated_printout_still_shows_the_date(self, client, admin_user,
                                                   main_branch, dated_pr):
        """Control: ASAP must not leak onto every requisition.

        Scoped to the Date Needed CELL, not the whole page. A page-wide
        `'ASAP' not in html` is defeated by anything else on the sheet that
        happens to contain those letters -- it first failed here because the
        fixture had numbered the requisition ASAP-2 and the number is echoed in
        the <title>. The template was correct; the assertion was not.
        """
        _login(client, admin_user, main_branch)
        html = client.get(f'/purchase-requests/{dated_pr.id}/print').data.decode()
        cell = _date_needed_cell(html)
        assert 'September 15, 2026' in cell
        assert 'ASAP' not in cell
