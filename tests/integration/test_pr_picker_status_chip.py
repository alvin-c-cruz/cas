"""The picker tells the buyer which requisitions are still awaiting approval.

Since 2026-08-26 the picker offers `submitted` requisitions alongside approved
ones, so a buyer building an order can no longer assume every line in the modal
is authorised. Without a marker the two are indistinguishable, and the buyer only
finds out at approval -- after the order is built, priced and submitted.

Three layers, asserted separately because each can fail without the others:
  * the PAYLOAD carries pr_status                       (unit-ish, this file)
  * the ENDPOINT hands it to the browser                (integration)
  * the ROW TEMPLATE turns it into a chip               (executed JS)

The third is executed rather than grepped. The chip's whole content is decided
inside the picker's `rows.map(...)` literal, so a page that merely CONTAINS the
string `pr_status` proves nothing about what is drawn.
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


class TestTheChipMarkup:
    """EXECUTED. The picker's own row template, run over supplied rows."""

    @pytest.fixture
    def form_html(self, client, admin_user, main_branch, db_session):
        _login(client, admin_user, main_branch)
        resp = client.get('/purchase-orders/create')
        assert resp.status_code == 200
        return resp.get_data(as_text=True)

    def test_a_submitted_row_is_chipped(self, tmp_path, form_html):
        out = picker_markup(tmp_path, form_html, [_row(pr_status='submitted')])
        assert 'pr-status-chip' in out['body'], out['body']
        assert 'Pending approval' in out['body']

    def test_the_chip_carries_an_explanatory_title(self, tmp_path, form_html):
        """A two-word chip has to say what it means on hover -- the buyer's next
        question is 'so can I still order it?' and the answer is yes, but the
        order cannot be APPROVED until the requisition is."""
        out = picker_markup(tmp_path, form_html, [_row(pr_status='submitted')])
        assert 'title="' in out['body']
        assert 'cannot be approved' in out['body']

    def test_an_approved_row_is_NOT_chipped(self, tmp_path, form_html):
        """THE control. A chip on every row carries no information at all."""
        out = picker_markup(tmp_path, form_html, [_row(pr_status='approved')])
        assert 'pr-status-chip' not in out['body'], out['body']
        assert 'Pending approval' not in out['body']

    def test_a_partially_converted_row_is_NOT_chipped(self, tmp_path, form_html):
        """A post-approval state -- it HAS been approved, so nothing is pending."""
        out = picker_markup(tmp_path, form_html,
                            [_row(pr_status='partially_converted')])
        assert 'pr-status-chip' not in out['body'], out['body']

    def test_only_the_submitted_row_is_chipped_in_a_mixed_list(self, tmp_path,
                                                               form_html):
        """The realistic modal: both kinds side by side. Exactly one chip."""
        out = picker_markup(tmp_path, form_html, [
            _row(pr_number='CHIP-OK', pr_status='approved'),
            _row(pr_number='CHIP-PENDING', pr_status='submitted', pr_item_id=2)])
        assert out['body'].count('pr-status-chip') == 1
        # The chip must sit in the PENDING row, not merely somewhere on the page.
        pending_at = out['body'].index('CHIP-PENDING')
        ok_at = out['body'].index('CHIP-OK')
        chip_at = out['body'].index('pr-status-chip')
        assert chip_at > pending_at > ok_at, out['body']

    def test_the_row_still_carries_its_data_payload(self, tmp_path, form_html):
        """CONTROL on the row template as a whole -- the chip is added INTO an
        existing literal, so it is positioned to break the data-row attribute
        the Add half reads every picked line out of."""
        out = picker_markup(tmp_path, form_html, [_row(pr_status='submitted')])
        assert 'data-row=' in out['body']
        assert 'class="pr-pick"' in out['body']
