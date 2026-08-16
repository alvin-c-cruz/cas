"""`receiving_reports.purchase_order_id` -- the still-NOT-NULL header column -- is
populated from the FIRST submitted line's purchase order, on create AND on edit.

Pinned because nothing else could distinguish it. Every other RR test posts lines
drawn from a SINGLE purchase order, where "the first line's PO", "the last line's
PO" and "whatever the header already said" are all the same value, so all three
answers pass. Three single-edit mutations survived the whole receiving_reports
marker before this file existed:

  * `rr.line_items[0]` -> `rr.line_items[-1]` in create()
  * the same swap in edit()
  * deleting edit()'s re-derivation outright

That last one is the one with teeth: create a draft holding a PO-A line, edit it to
carry only a PO-B line, and the header still names PO-A -- so the pre-printed
overlay prints "PO-A" on a receipt containing no PO-A line at all.

This pins the CURRENT behaviour deliberately, without endorsing it as the only
possible one: the column is a leftover with no single true value once a receipt can
span several of one vendor's orders, and Task 6 drops it. Until then it must at
least be DETERMINISTIC and must at least AGREE with a line the receipt really
carries. Both routes reach the assignment only after the payload guard has resolved
every PO line and its order, and `_parse_rr_lines` raises before `kept` can be
empty -- so `[0]` and `.order.id` are unreachable-by-construction as a None/IndexError.
"""
import json
from datetime import date
from decimal import Decimal

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]


@pytest.fixture(autouse=True)
def rr_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'receiving_reports'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _approved_po(db_session, branch, vendor, number, qty=10):
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    po = PurchaseOrder(branch_id=branch.id, po_number=number, order_date=date(2026, 7, 11),
                       vendor_id=vendor.id, vendor_name=vendor.name, status='approved',
                       vat_treatment='inclusive')
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description=f'Cement for {number}', quantity=Decimal(str(qty)),
        unit_price=Decimal('10'), amount=Decimal(str(qty * 10))))
    po.calculate_totals()
    db_session.add(po); db_session.commit()
    return po


def _make_draft_rr(db_session, branch, header_po, pairs, number):
    from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
    rr = ReceivingReport(branch_id=branch.id, rr_number=number,
                         receipt_date=date(2026, 7, 11), purchase_order_id=header_po.id,
                         vendor_id=header_po.vendor_id, vendor_name=header_po.vendor_name,
                         status='draft')
    for i, (poi, qty) in enumerate(pairs, start=1):
        rr.line_items.append(ReceivingReportItem(line_number=i, purchase_order_item_id=poi.id,
                                                 received_quantity=Decimal(str(qty))))
    db_session.add(rr); db_session.commit()
    return rr


def _post_create(client, vendor_id, pairs, rr_number):
    lines = [{'purchase_order_item_id': poi.id, 'received_quantity': str(qty)}
             for poi, qty in pairs]
    return client.post('/receiving-reports/create', data={
        'vendor_id': str(vendor_id), 'receipt_date': '2026-07-11', 'remarks': '',
        'rr_number': rr_number, 'lines': json.dumps(lines),
    }, follow_redirects=True)


def _post_edit(client, rr, pairs):
    lines = [{'purchase_order_item_id': poi.id, 'received_quantity': str(qty)}
             for poi, qty in pairs]
    return client.post(f'/receiving-reports/{rr.id}/edit', data={
        'vendor_id': str(rr.vendor_id), 'receipt_date': '2026-07-11', 'remarks': '',
        'rr_number': rr.rr_number, 'row_version': str(rr.row_version),
        'lines': json.dumps(lines),
    }, follow_redirects=True)


@pytest.fixture
def two_pos(db_session, main_branch, vl_vendor):
    """Two approved POs of ONE vendor -- the multi-PO receipt this feature exists for."""
    return (_approved_po(db_session, main_branch, vl_vendor, 'PO-HDR-A'),
            _approved_po(db_session, main_branch, vl_vendor, 'PO-HDR-B'))


class TestCreateTakesTheFirstSubmittedLinesPO:

    def test_the_header_names_the_first_submitted_lines_po(
            self, client, db_session, admin_user, main_branch, vl_vendor, two_pos):
        from app.receiving_reports.models import ReceivingReport
        _login(client, admin_user, main_branch)
        po_a, po_b = two_pos

        _post_create(client, vl_vendor.id,
                     [(po_a.line_items[0], 4), (po_b.line_items[0], 6)], 'RR-HDR-0001')

        rr = ReceivingReport.query.one()
        assert [po.po_number for po in rr.purchase_orders] == ['PO-HDR-A', 'PO-HDR-B']
        assert rr.purchase_order_id == po_a.id      # first submitted, not last, not lowest id

    def test_flipping_the_payload_order_flips_the_stored_po(
            self, client, db_session, admin_user, main_branch, vl_vendor, two_pos):
        """The SAME two lines in the other order. Nothing but submission order
        differs, so a `[-1]` (or a min/max over the ids) cannot answer both this
        and the test above."""
        from app.receiving_reports.models import ReceivingReport
        _login(client, admin_user, main_branch)
        po_a, po_b = two_pos

        _post_create(client, vl_vendor.id,
                     [(po_b.line_items[0], 6), (po_a.line_items[0], 4)], 'RR-HDR-0002')

        rr = ReceivingReport.query.one()
        assert rr.purchase_order_id == po_b.id

    def test_a_single_po_receipt_still_names_that_po(
            self, client, db_session, admin_user, main_branch, vl_vendor, two_pos):
        """CONTROL on the ordinary path this must not change: one PO, one line."""
        from app.receiving_reports.models import ReceivingReport
        _login(client, admin_user, main_branch)
        po_a, _ = two_pos

        _post_create(client, vl_vendor.id, [(po_a.line_items[0], 4)], 'RR-HDR-0003')

        rr = ReceivingReport.query.one()
        assert rr.purchase_order_id == po_a.id


class TestEditReDerivesTheHeader:
    """Editing the lines can change which orders a receipt draws on. A header left
    at its create-time value then names a PO the receipt no longer touches -- and
    the pre-printed overlay prints that number on the receiver's stationery."""

    def test_replacing_the_first_lines_po_moves_the_header(
            self, client, db_session, admin_user, main_branch, two_pos):
        po_a, po_b = two_pos
        _login(client, admin_user, main_branch)
        rr = _make_draft_rr(db_session, main_branch, po_a,
                            [(po_a.line_items[0], 3)], 'RR-HDR-EDIT-1')
        assert rr.purchase_order_id == po_a.id                      # precondition

        # PO-B first, PO-A second: a header left un-re-derived stays on PO-A, and
        # so does a `[-1]` read. Only "the first submitted line" answers PO-B.
        _post_edit(client, rr, [(po_b.line_items[0], 5), (po_a.line_items[0], 3)])

        db_session.expire_all()
        assert {po.po_number for po in rr.purchase_orders} == {'PO-HDR-A', 'PO-HDR-B'}
        assert rr.purchase_order_id == po_b.id

    def test_dropping_the_only_po_a_line_leaves_no_header_pointing_at_it(
            self, client, db_session, admin_user, main_branch, two_pos):
        """The scenario in full: a draft whose sole line is PO-A's, edited to carry
        only PO-B's. The header must not still name an order the receipt no longer
        contains a single line from."""
        po_a, po_b = two_pos
        _login(client, admin_user, main_branch)
        rr = _make_draft_rr(db_session, main_branch, po_a,
                            [(po_a.line_items[0], 3)], 'RR-HDR-EDIT-2')

        _post_edit(client, rr, [(po_b.line_items[0], 5)])

        db_session.expire_all()
        assert [po.po_number for po in rr.purchase_orders] == ['PO-HDR-B']
        assert rr.purchase_order_id == po_b.id
        assert rr.purchase_order_id != po_a.id

    def test_an_edit_that_keeps_the_same_po_keeps_the_same_header(
            self, client, db_session, admin_user, main_branch, two_pos):
        """CONTROL. Re-deriving must not disturb the ordinary quantity-only edit."""
        po_a, _ = two_pos
        _login(client, admin_user, main_branch)
        rr = _make_draft_rr(db_session, main_branch, po_a,
                            [(po_a.line_items[0], 3)], 'RR-HDR-EDIT-3')

        _post_edit(client, rr, [(po_a.line_items[0], 7)])

        db_session.expire_all()
        assert rr.purchase_order_id == po_a.id
        assert [Decimal(str(li.received_quantity)) for li in rr.line_items] == [Decimal('7')]
