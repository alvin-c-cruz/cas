"""The PR printout always carries a Note row -- blank when there is no note.

Owner directive 2026-08-21: "always show the Note row on the print."

The row was `{% if pr.reason %}`, so a requisition with no note printed no Note
row at all. On a sheet that is otherwise a fixed form -- a padded 20-row grid,
ruled signature lines that print whether or not a name is set -- a row that
VANISHES was the odd one out, and it left nowhere to write a note by hand.

Scope is the PRINTOUT. The detail page keeps hiding an empty note: a blank
field on screen is noise, not a place to write.

The Sales Order printout still hides its own empty Notes box (`{% if so.notes %}`)
-- that box is `flex: 1` and stretches to fill the sheet, so an always-on empty
version would be a large empty panel rather than a writable line. Different
shape, different call; pinned below so the difference is deliberate.
"""
import datetime
import pytest
import re
from decimal import Decimal
from app import db
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem

pytestmark = [pytest.mark.integration, pytest.mark.purchase_requests]

NOTE = 'Deliver to the plant gate, not the office.'


@pytest.fixture(autouse=True)
def pr_enabled(db_session):
    """purchase_requests is an OPTIONAL module -- without this the print route
    404s and every assertion below would be vacuous. Same fixture the other PR
    integration tests use."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_requests', 'units_of_measure'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)
        s['_fresh'] = True
        s['selected_branch_id'] = branch.id


def _pr(db_session, main_branch, number, reason):
    pr = PurchaseRequest(pr_number=number, request_date=datetime.date(2026, 6, 15),
                         branch_id=main_branch.id, status='draft', reason=reason)
    db.session.add(pr); db.session.flush()
    db.session.add(PurchaseRequestItem(purchase_request_id=pr.id, line_number=1,
                                       description='Cement', quantity=Decimal('10'),
                                       uom_text='bag'))
    db.session.commit()
    return pr


def _note_cell(html):
    """The Note row's data cell, or None when the row is absent."""
    m = re.search(r'<tr><th>Note</th><td[^>]*>(.*?)</td></tr>', html, re.S)
    return m.group(1) if m else None


def test_the_note_row_prints_even_with_no_note(client, db_session, admin_user, main_branch):
    pr = _pr(db_session, main_branch, 'PR-NOTE-EMPTY', None)
    _login(client, admin_user, main_branch)

    html = client.get(f'/purchase-requests/{pr.id}/print').get_data(as_text=True)

    cell = _note_cell(html)
    assert cell is not None, 'the Note row is missing entirely'
    assert cell.strip() == '', f'expected an empty cell to write in, got {cell!r}'
    assert 'None' not in (cell or ''), 'a NULL reason leaked into the page as the text "None"'


def test_the_note_row_still_shows_a_real_note(client, db_session, admin_user, main_branch):
    """CONTROL: always-on must not mean always-empty."""
    pr = _pr(db_session, main_branch, 'PR-NOTE-FULL', NOTE)
    _login(client, admin_user, main_branch)

    html = client.get(f'/purchase-requests/{pr.id}/print').get_data(as_text=True)

    assert NOTE in _note_cell(html)


def test_the_empty_note_cell_is_tall_enough_to_write_in(client, db_session, admin_user,
                                                        main_branch):
    """An empty <td> collapses to its padding.

    Without a height the "always show" row prints as a hairline the width of the
    page -- present, but useless for the hand-written note it exists to hold.
    """
    pr = _pr(db_session, main_branch, 'PR-NOTE-H', None)
    _login(client, admin_user, main_branch)

    html = client.get(f'/purchase-requests/{pr.id}/print').get_data(as_text=True)

    assert re.search(r'table\.meta td\.note \{[^}]*height:\s*\d', html), \
        'the Note cell has no height -- an empty row collapses'
    assert re.search(r'<td class="note"|<td[^>]*class="[^"]*note', html), \
        'the Note cell does not carry the class the height rule targets'


def test_the_detail_page_still_hides_an_empty_note(client, db_session, admin_user, main_branch):
    """CONTROL / scope: only the PRINTOUT gained the always-on row.

    A blank field on a screen is noise; the change was about leaving writable
    space on paper.
    """
    pr = _pr(db_session, main_branch, 'PR-NOTE-DET', None)
    _login(client, admin_user, main_branch)

    html = client.get(f'/purchase-requests/{pr.id}').get_data(as_text=True)

    assert '<strong>Note:</strong>' not in html


def test_the_sales_order_still_hides_its_empty_notes_box():
    """CONTROL / scope pin: the SO's Notes box is a different shape.

    It is flex:1 and stretches to fill the sheet, so an always-on empty version
    is a large blank panel, not a writable line. If that should change too, this
    test is where the decision gets taken.
    """
    from pathlib import Path
    so = (Path(__file__).resolve().parents[2]
          / 'app/sales_orders/templates/sales_orders/print.html')
    assert '{% if so.notes %}' in so.read_text(encoding='utf-8')
