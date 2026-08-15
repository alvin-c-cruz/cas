"""PurchaseRequest as the third Amendable adopter -- and the ways it is NOT a small PO.

PR was originally the first adopter with **no children at all**. Line-level
allocation gave it one: `PurchaseOrderItem.source_pr_item_id`. The hooks are
therefore no longer constants, and this module now pins their NEGATIVE half --
a line no purchase order points at must still report nothing consumed, or the
validator degenerates into a blanket freeze. The header-level edge
(`PurchaseRequest.purchase_order_id` / `PurchaseOrder.purchase_request_id`)
survives as a back-link only, and deliberately proves nothing per line.

It is also the one document whose lines carry no money at all: no unit price, no
amount, no VAT. The buyer supplies pricing at PO conversion.
"""
from datetime import date, datetime
from decimal import Decimal

import pytest

from app import db
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem

pytestmark = [pytest.mark.unit]


def _pr(status='approved', lines=(('widget', None, '3'),), **over):
    """A PR with (description, product_id, quantity) line tuples."""
    pr = PurchaseRequest(pr_number=over.pop('pr_number', 'PR0001'),
                         request_date=date(2026, 8, 10), status=status,
                         reason='stock replenishment', **over)
    for n, (desc, product_id, qty) in enumerate(lines, start=1):
        pr.line_items.append(PurchaseRequestItem(
            line_number=n, description=desc, product_id=product_id,
            quantity=Decimal(qty) if qty is not None else None,
            uom_text='BOX'))
    db.session.add(pr)
    db.session.commit()
    return pr


class TestAmendContract:

    def test_document_type_matches_the_audit_module_name(self):
        assert PurchaseRequest.DOCUMENT_TYPE == 'purchase_requests'

    def test_amend_statuses_is_approved_and_partially_converted(self):
        # 'partially_converted' joined 'approved' with line-level allocation:
        # the validator's consumed_qty/has_any_child_reference hooks are real
        # now, so it refuses to shrink or delete an already-ordered line while
        # still permitting the untouched remainder to be amended.
        assert PurchaseRequest.AMEND_STATUSES == ('approved', 'partially_converted')

    @pytest.mark.parametrize('status', ['draft', 'submitted', 'rejected',
                                        'converted', 'cancelled'])
    def test_every_other_status_is_excluded(self, status):
        # 'submitted' is past draft but PRE-approval, and the spec's trigger is
        # approval. 'converted' means every line is consumed -- the only edit
        # the validator would still allow is ADDING demand to a fully ordered
        # requisition, which belongs on a new requisition.
        assert status not in PurchaseRequest.AMEND_STATUSES


class TestConversionGuard:

    def test_an_approved_unconverted_pr_is_not_converted(self, db_session):
        pr = _pr(status='approved')
        assert pr.is_converted() is False

    def test_the_status_alone_marks_it_converted(self, db_session):
        pr = _pr(status='converted')
        assert pr.is_converted() is True

    def test_a_dangling_purchase_order_id_no_longer_marks_it_converted(self, db_session):
        # INVERTED by line-level allocation, deliberately. The back-link used to
        # be the only trace conversion left, because convert() COPIED the lines.
        # It now sets purchase_order_id on a PARTIAL pull as well, so treating
        # it as proof of consumption would freeze a requisition that still has
        # an unordered remainder. Consumption is proven by the PO lines
        # themselves (source_pr_item_id) -- see the case below.
        pr = _pr(status='approved')
        pr.purchase_order_id = 99
        db.session.commit()
        assert pr.is_converted() is False

    def test_every_line_ordered_marks_it_converted(self, db_session):
        # The replacement evidence: status still 'approved', but nothing is open.
        from decimal import Decimal
        from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
        pr = _pr(status='approved')
        po = PurchaseOrder(po_number='HOOK-PO-1', order_date=date(2026, 8, 15),
                           status='draft', vat_treatment='inclusive',
                           branch_id=pr.branch_id)
        for n, li in enumerate(pr.line_items, start=1):
            po.line_items.append(PurchaseOrderItem(
                line_number=n, description=li.description, quantity=li.quantity,
                unit_price=1, amount=Decimal(str(li.quantity)),
                source_pr_item_id=li.id))
        db.session.add(po)
        db.session.commit()
        assert pr.is_converted() is True


class TestUsableLine:
    """PR's own rule, lifted from _parse_and_attach_pr_lines: a line needs a
    product OR a free-text description. It is already enforced on the way IN;
    this makes it assertable as a POSTcondition too."""

    def test_a_line_with_a_description_counts(self, db_session):
        assert _pr(lines=(('widget', None, '3'),)).has_requested_line() is True

    def test_a_line_with_only_a_product_counts(self, db_session):
        assert _pr(lines=((None, 7, '3'),)).has_requested_line() is True

    def test_a_line_with_neither_does_not_count(self, db_session):
        assert _pr(lines=((None, None, '3'),)).has_requested_line() is False

    def test_a_blank_description_does_not_count(self, db_session):
        # '' and '   ' are what an emptied text input actually posts.
        assert _pr(lines=(('   ', None, '3'),)).has_requested_line() is False

    def test_a_pr_with_no_lines_at_all_does_not_count(self, db_session):
        assert _pr(lines=()).has_requested_line() is False

    def test_one_usable_line_among_unusable_ones_counts(self, db_session):
        assert _pr(lines=((None, None, '1'), ('widget', None, '2'))).has_requested_line() is True


class TestAnUnreferencedLineIsFree:
    """The control half of the hooks: they must stay ZERO/False for a line no
    purchase order points at, or the validator becomes a blanket freeze.

    These were once absolute ("nothing can ever consume a PR line"). Line-level
    allocation made them conditional -- PurchaseOrderItem.source_pr_item_id is
    the per-line child that did not exist then. The positive half lives in
    tests/integration/test_pr_amend_allocation_guard.py.
    """

    def test_an_unordered_line_reports_nothing_consumed(self, db_session):
        pr = _pr()
        assert pr.consumed_qty(pr.line_items[0]) == Decimal('0')

    def test_an_unordered_line_has_no_child_reference(self, db_session):
        pr = _pr()
        assert pr.has_any_child_reference(pr.line_items[0]) is False

    def test_a_header_back_link_alone_creates_no_line_reference(self, db_session):
        # purchase_order_id is HEADER-level and says nothing about which lines
        # were taken. Only a PO line carrying source_pr_item_id does.
        pr = _pr(status='converted')
        pr.purchase_order_id = 42
        db.session.commit()
        assert pr.consumed_qty(pr.line_items[0]) == Decimal('0')
        assert pr.has_any_child_reference(pr.line_items[0]) is False


class TestSnapshot:

    def test_every_declared_header_field_is_emitted(self, db_session):
        snap = _pr().build_snapshot()
        for field in PurchaseRequest.SNAPSHOT_HEADER_FIELDS:
            assert field in snap['header'], f'{field} missing from the header snapshot'

    def test_every_declared_line_field_is_emitted(self, db_session):
        """Guards the mixin's plumbing: whatever is declared actually appears.

        NOT sufficient on its own -- it iterates the declaration, so DELETING a
        field from SNAPSHOT_LINE_FIELDS simply makes it check fewer things and it
        stays green (proven by mutation m12). The by-name test below is what
        pins the field set itself.
        """
        snap = _pr().build_snapshot()
        for field in PurchaseRequest.SNAPSHOT_LINE_FIELDS:
            assert field in snap['lines'][0], f'{field} missing from the line snapshot'

    def test_the_line_snapshot_carries_what_a_requisition_actually_says(self, db_session):
        # Named explicitly, not derived from the declaration. A requisition
        # records WHAT is needed and HOW MANY; a snapshot missing `quantity` or
        # the item identity is not a record of the document.
        snap = _pr(lines=(('widget', None, '3'),)).build_snapshot()
        row = snap['lines'][0]
        assert row['quantity'] == '3'
        assert row['description'] == 'widget'
        assert row['line_number'] == '1'
        assert row['uom_text'] == 'BOX'
        assert 'product_id' in row
        assert 'unit_of_measure_id' in row

    def test_the_header_snapshot_carries_the_requisition_itself(self, db_session):
        # Same reasoning as the line test above: by name, so dropping a field
        # from SNAPSHOT_HEADER_FIELDS fails here rather than silently narrowing
        # what the declaration-iterating test checks.
        header = _pr().build_snapshot()['header']
        assert header['pr_number'] == 'PR0001'
        assert header['request_date'] == '2026-08-10'
        assert header['reason'] == 'stock replenishment'
        assert header['status'] == 'approved'

    def test_the_header_carries_the_conversion_target(self, db_session):
        # purchase_order_id is LIVE STATE, the way PO's accounts_payable_id is.
        # Omitting it was slice 1's first defect: the snapshot then cannot say
        # whether this requisition was ever converted, or into what.
        pr = _pr(status='converted')
        pr.purchase_order_id = 42
        db.session.commit()
        assert pr.build_snapshot()['header']['purchase_order_id'] == '42'

    def test_provenance_is_captured(self, db_session):
        pr = _pr()
        pr.approved_at = datetime(2026, 8, 10, 13, 7, 5)
        pr.approved_by_id = 3
        db.session.commit()
        header = pr.build_snapshot()['header']
        assert header['approved_by_id'] == '3'
        assert header['approved_at'] == '2026-08-10T13:07:05'

    def test_pr_declares_no_money_fields(self, db_session):
        # PurchaseRequestItem has no unit_price/amount/vat columns at all -- the
        # buyer supplies pricing at conversion. Declaring a money field here
        # would emit a *_display key for a value that does not exist.
        assert PurchaseRequest.SNAPSHOT_MONEY_FIELDS == ()

    def test_no_display_keys_are_emitted(self, db_session):
        header = _pr().build_snapshot()['header']
        assert [k for k in header if k.endswith('_display')] == []

    def test_lines_carry_their_row_identity(self, db_session):
        pr = _pr(lines=(('a', None, '1'), ('b', None, '2')))
        snap = pr.build_snapshot()
        assert [row['line_id'] for row in snap['lines']] == [li.id for li in pr.line_items]
