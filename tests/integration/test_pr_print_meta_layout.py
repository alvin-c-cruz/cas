"""The printed requisition's header block: dates on the left, PR Number spanning.

Owner directive 2026-08-14. The meta table was PR # | Date on one row and Date
Needed spanning the next. It becomes two columns:

    | Date        | 14 August 2026 | PR Number | 25-0909 |   <- spans
    | Date Needed | ASAP           |           | (both)  |      2 rows
    | Note        | ...                                   |

Every assertion is scoped to the META TABLE, never the whole page. A page-wide
check is answered by anything else on the sheet carrying the same letters -- the
document number appears in the <title>, and "Date" appears in the printed-on
footer. That trap already produced one false failure in this module's tests.
"""
import re
from datetime import date

import pytest

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


def _meta(html):
    """The <table class="meta"> block only."""
    m = re.search(r'<table class="meta">(.*?)</table>', html, re.S)
    assert m, 'the printed form has no meta table'
    return m.group(1)


def _rows(meta):
    return re.findall(r'<tr>(.*?)</tr>', meta, re.S)


@pytest.fixture
def pr(db_session, admin_user, main_branch):
    p = PurchaseRequest(pr_number='META-1', request_date=date(2026, 8, 14),
                        date_needed=date(2026, 9, 15), reason='Attention: Anissa Tang',
                        branch_id=main_branch.id, status='draft',
                        created_by_id=admin_user.id)
    db_session.add(p)
    db_session.commit()
    return p


def _print(client, pr):
    resp = client.get(f'/purchase-requests/{pr.id}/print')
    assert resp.status_code == 200
    return resp.data.decode()


class TestTheLabel:

    def test_it_reads_pr_number(self, client, admin_user, main_branch, pr):
        _login(client, admin_user, main_branch)
        assert 'PR Number' in _meta(_print(client, pr))

    def test_the_old_abbreviation_is_gone(self, client, admin_user, main_branch, pr):
        _login(client, admin_user, main_branch)
        assert '>PR #<' not in _meta(_print(client, pr))


class TestTheTwoColumnLayout:

    def test_the_first_row_leads_with_the_date(self, client, admin_user, main_branch, pr):
        """'Date should be on left side' -- its label must precede PR Number."""
        _login(client, admin_user, main_branch)
        row = _rows(_meta(_print(client, pr)))[0]
        assert '<th>Date</th>' in row
        assert row.index('<th>Date</th>') < row.index('PR Number'), (
            'PR Number still sits to the left of the date')

    def test_pr_number_spans_both_date_rows(self, client, admin_user, main_branch, pr):
        _login(client, admin_user, main_branch)
        row = _rows(_meta(_print(client, pr)))[0]
        assert re.search(r'<th[^>]*rowspan="2"[^>]*>PR Number</th>', row), (
            'the PR Number label does not span two rows')
        assert re.search(r'<td[^>]*rowspan="2"', row), (
            'the PR Number value does not span two rows')

    def test_the_second_row_is_date_needed_and_nothing_else(self, client, admin_user,
                                                            main_branch, pr):
        """Only two cells -- the right-hand pair is occupied by the rowspan."""
        _login(client, admin_user, main_branch)
        row = _rows(_meta(_print(client, pr)))[1]
        assert '<th>Date Needed</th>' in row
        assert len(re.findall(r'<t[hd]', row)) == 2, (
            'the Date Needed row carries extra cells, so it collides with the '
            'spanning PR Number column')

    def test_both_dates_are_in_the_left_column(self, client, admin_user, main_branch, pr):
        _login(client, admin_user, main_branch)
        rows = _rows(_meta(_print(client, pr)))
        assert rows[0].lstrip().startswith('<th>Date</th>')
        assert rows[1].lstrip().startswith('<th>Date Needed</th>')

    def test_the_values_still_render(self, client, admin_user, main_branch, pr):
        """Control: restructuring must not drop the data it reorganises."""
        _login(client, admin_user, main_branch)
        meta = _meta(_print(client, pr))
        assert 'META-1' in meta
        assert 'August 14, 2026' in meta
        assert 'September 15, 2026' in meta


def _lines_headers(html):
    """The line grid's header labels, in document order."""
    m = re.search(r'<table class="lines">.*?<thead>(.*?)</thead>', html, re.S)
    assert m, 'the printed form has no line grid'
    return [re.sub(r'<[^>]+>', '', c).strip()
            for c in re.findall(r'<th[^>]*>(.*?)</th>', m.group(1), re.S)]


class TestTheLineColumns:
    """Owner directive: Qty, Unit, Item Description, Purpose/Remarks -- in that
    order. The leading # gutter stays; it numbers the fixed 25-row grid so a
    blank sheet can still be filled in by hand."""

    EXPECTED = ['#', 'Qty', 'Unit', 'Item Description', 'Purpose/Remarks']

    def test_the_headers_read_in_the_requested_order(self, client, admin_user,
                                                     main_branch, pr):
        _login(client, admin_user, main_branch)
        assert _lines_headers(_print(client, pr)) == self.EXPECTED

    def test_the_body_cells_follow_the_same_order(self, client, db_session, admin_user,
                                                  main_branch, pr):
        """Headers and data must move together -- reordering one alone silently
        prints every value under the wrong heading, which is precisely the
        failure the export headers just had."""
        from app.products.models import Product
        from app.purchase_requests.models import PurchaseRequestItem
        from app.units_of_measure.models import UnitOfMeasure
        prod = Product(code='RM0003', name='CARBIDE', is_active=True)
        uom = UnitOfMeasure(code='PAIL', name='Pail', is_active=True)
        db_session.add_all([prod, uom])
        db_session.commit()
        pr.line_items.append(PurchaseRequestItem(
            line_number=1, product_id=prod.id, description='FOR PRODUCTION USE',
            quantity=20, unit_of_measure_id=uom.id))
        db_session.commit()

        _login(client, admin_user, main_branch)
        html = _print(client, pr)
        body = re.search(r'<tbody>(.*?)</tbody>', html, re.S).group(1)
        first = re.search(r'<tr>(.*?)</tr>', body, re.S).group(1)
        cells = [re.sub(r'<[^>]+>', '', c).strip()
                 for c in re.findall(r'<td[^>]*>(.*?)</td>', first, re.S)]

        assert cells[0] == '1'                     # the # gutter
        assert cells[1] == '20'                    # Qty
        assert cells[2] == 'PAIL'                  # Unit
        assert cells[3] == 'CARBIDE'               # Item Description
        assert cells[4] == 'FOR PRODUCTION USE'    # Purpose/Remarks

    def test_the_filler_rows_have_the_same_cell_count(self, client, admin_user,
                                                      main_branch, pr):
        """A filler row short of a cell collapses the ruled grid on the right."""
        _login(client, admin_user, main_branch)
        html = _print(client, pr)
        filler = re.search(r'<tr class="filler">(.*?)</tr>', html, re.S).group(1)
        assert len(re.findall(r'<td', filler)) == len(self.EXPECTED)


class TestTheRestOfTheBlockIsIntact:

    def test_the_note_row_still_spans_the_table(self, client, admin_user, main_branch, pr):
        _login(client, admin_user, main_branch)
        meta = _meta(_print(client, pr))
        assert '<th>Note</th>' in meta
        assert 'Attention: Anissa Tang' in meta

    def test_asap_still_shows_in_the_date_needed_cell(self, client, db_session,
                                                      admin_user, main_branch):
        p = PurchaseRequest(pr_number='META-2', request_date=date(2026, 8, 14),
                            date_needed_asap=True, branch_id=main_branch.id,
                            status='draft', created_by_id=admin_user.id)
        db_session.add(p)
        db_session.commit()
        _login(client, admin_user, main_branch)

        row = _rows(_meta(_print(client, p)))[1]
        assert 'Date Needed' in row and 'ASAP' in row

    def test_a_blank_date_needed_still_renders_its_ruled_row(self, client, db_session,
                                                             admin_user, main_branch):
        """The row is a box to fill in by hand -- it must not disappear."""
        p = PurchaseRequest(pr_number='META-3', request_date=date(2026, 8, 14),
                            branch_id=main_branch.id, status='draft',
                            created_by_id=admin_user.id)
        db_session.add(p)
        db_session.commit()
        _login(client, admin_user, main_branch)

        assert '<th>Date Needed</th>' in _rows(_meta(_print(client, p)))[1]
