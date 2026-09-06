"""The requisition picker's status data, and the absence of a status chip.

Since 2026-08-26 the picker offers `submitted` requisitions alongside approved
ones. From 2026-08-26 to 2026-09-06 each submitted row carried a "Pending
approval" chip; the owner removed it on 2026-09-06, because pulling a submitted
requisition is the normal path and chipping it warned about the intended action.

`pr_status` deliberately REMAINS in the payload and the endpoint: the picker's
data contract did not change, only its presentation, and a future consumer
should find the field where it has always been.

Three layers, asserted separately because each can fail without the others:
  * the PAYLOAD carries pr_status                       (unit-ish, this file)
  * the ENDPOINT hands it to the browser                (integration)
  * the ROW TEMPLATE draws NO chip from it              (executed JS)

The third is executed rather than grepped. What a row draws is decided inside
the picker's `rows.map(...)` literal, so a page that merely CONTAINS -- or
lacks -- the string `pr_status` proves nothing about what is rendered.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.purchase_requests.allocation import open_lines_for_branch
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem

from tests.integration._pr_picker_render_js import picker_markup

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]


@pytest.fixture(autouse=True)
def po_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'purchase_requests'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _pr(branch, status, number='CHIP-PR-1'):
    pr = PurchaseRequest(pr_number=number, request_date=date(2026, 8, 26),
                         branch_id=branch.id, status=status)
    pr.line_items.append(PurchaseRequestItem(
        line_number=1, description='Cement', quantity=Decimal('10')))
    db.session.add(pr); db.session.commit()
    return pr


def _row(**over):
    """One open_lines_for_branch row, in the shape the modal receives."""
    row = {'pr_item_id': 1, 'pr_id': 1, 'pr_number': 'CHIP-PR-1',
           'date_needed': None, 'date_needed_asap': False, 'product_id': None,
           'product_code': None, 'product_name': None, 'description': 'Cement',
           'uom_id': None, 'uom_code': 'bag', 'requested': '10', 'ordered': '0',
           'open': '10', 'pr_status': 'approved'}
    row.update(over)
    return row


class TestThePayload:

    def test_a_submitted_line_carries_its_status(self, db_session, main_branch):
        _pr(main_branch, 'submitted')
        assert open_lines_for_branch(main_branch.id)[0]['pr_status'] == 'submitted'

    def test_an_approved_line_carries_its_status(self, db_session, main_branch):
        _pr(main_branch, 'approved')
        assert open_lines_for_branch(main_branch.id)[0]['pr_status'] == 'approved'

    def test_a_partially_converted_line_carries_its_status(self, db_session, main_branch):
        _pr(main_branch, 'partially_converted')
        assert (open_lines_for_branch(main_branch.id)[0]['pr_status']
                == 'partially_converted')


class TestTheEndpoint:

    def test_open_lines_json_carries_pr_status(self, client, admin_user,
                                               main_branch, db_session):
        """The browser cannot draw what the endpoint does not send."""
        _pr(main_branch, 'submitted')
        _login(client, admin_user, main_branch)
        resp = client.get('/purchase-requests/open-lines')
        assert resp.status_code == 200
        assert resp.get_json()['lines'][0]['pr_status'] == 'submitted'


class TestNoStatusChipIsDrawn:
    """EXECUTED. The picker's own row template, run over supplied rows.

    The per-row "Pending approval" chip was REMOVED on 2026-09-06 at the owner's
    request: pulling a `submitted` requisition is the normal path, so chipping
    every such row warned about the very thing the buyer was asked to do. These
    tests are the guard that it stays gone, for every status the picker offers.

    The consequence the chip announced no longer exists: the approve()-time
    block on an unapproved source, and its detail-page banner, were removed later
    the same day at the owner's request. See
    tests/integration/test_po_unapproved_source_not_blocking.py.
    """

    @pytest.fixture
    def form_html(self, client, admin_user, main_branch, db_session):
        _login(client, admin_user, main_branch)
        resp = client.get('/purchase-orders/create')
        assert resp.status_code == 200
        return resp.get_data(as_text=True)

    @pytest.mark.parametrize('status', ['submitted', 'approved', 'partially_converted'])
    def test_no_row_is_chipped(self, tmp_path, form_html, status):
        out = picker_markup(tmp_path, form_html, [_row(pr_status=status)])
        assert 'pr-status-chip' not in out['body'], out['body']
        assert 'Pending approval' not in out['body']

    def test_a_mixed_list_draws_no_chip_at_all(self, tmp_path, form_html):
        """The realistic modal: both kinds side by side, neither chipped."""
        out = picker_markup(tmp_path, form_html, [
            _row(pr_number='CHIP-OK', pr_status='approved'),
            _row(pr_number='CHIP-PENDING', pr_status='submitted', pr_item_id=2)])
        assert out['body'].count('pr-status-chip') == 0
        # CONTROL: both rows really were rendered, so the absence above is not
        # an empty-body false pass.
        assert 'CHIP-OK' in out['body'] and 'CHIP-PENDING' in out['body']

    def test_the_row_still_carries_its_data_payload(self, tmp_path, form_html):
        """CONTROL on the row template as a whole -- the chip was removed FROM an
        existing literal, so the edit is positioned to break the data-row
        attribute the Add half reads every picked line out of."""
        out = picker_markup(tmp_path, form_html, [_row(pr_status='submitted')])
        assert 'data-row=' in out['body']
        assert 'class="pr-pick"' in out['body']

    def test_the_pr_number_still_renders(self, tmp_path, form_html):
        """The chip lived inside the PR-number cell; removing it must not take
        the number with it."""
        out = picker_markup(tmp_path, form_html, [_row(pr_number='PR-KEEP-ME')])
        assert 'PR-KEEP-ME' in out['body']
