"""PR and RR layout declarations.

Two document-shape facts are pinned here because they are easy to get wrong by
copying PO:
  * a requisition carries NO money -- PurchaseRequestItem has no price column
  * an RR line stores only line_number / product / received_quantity; its
    description, ordered qty and UoM come from the PO line it receives
"""
import pytest

from app.purchase_requests import preprinted_layout as pr_pl
from app.receiving_reports import preprinted_layout as rr_pl

pytestmark = [pytest.mark.unit, pytest.mark.purchase_requests, pytest.mark.receiving_reports]


class TestPurchaseRequisition:

    def test_setting_key(self):
        assert pr_pl.LAYOUT_SETTING_KEY == 'pr_preprinted_layout'

    def test_fields(self):
        assert pr_pl.FIELD_KEYS == ['pr_number', 'request_date', 'date_needed', 'reason', 'branch']

    def test_columns_carry_no_money(self):
        """A requisition asks for goods, not spend -- pricing arrives at PO."""
        assert pr_pl.COLUMN_KEYS == ['line_number', 'product', 'description', 'quantity', 'uom']
        for money in ('unit_price', 'amount', 'total'):
            assert money not in pr_pl.COLUMN_KEYS
            assert money not in pr_pl.FIELD_KEYS

    def test_every_label_is_exactly_right(self):
        """Membership is not enough -- these are user-visible strings on a printed
        document, so a typo ships silently. Assert the VALUES, not `k in LABELS`.
        (Task 3 shipped with the membership-only form and a review caught it; the
        same weakness was about to be cloned here for both PR and RR.)"""
        assert pr_pl.FIELD_LABELS == {
            'pr_number': 'PR No.', 'request_date': 'Request Date',
            # 'Note', NOT 'Reason' -- commit 7d1e3d9b renamed this label on the
            # requisition and the printed form must use the module's own word.
            'date_needed': 'Date Needed', 'reason': 'Note', 'branch': 'Branch',
        }
        assert pr_pl.COLUMN_LABELS == {
            'line_number': '#', 'product': 'Product', 'description': 'Description',
            'quantity': 'Qty', 'uom': 'UOM',
        }


class TestReceivingReport:

    def test_setting_key(self):
        assert rr_pl.LAYOUT_SETTING_KEY == 'rr_preprinted_layout'

    def test_fields(self):
        """`po_number` is NOT a header field -- one receipt may settle several of
        a vendor's orders, so it moved to a per-line COLUMN (Task 5)."""
        assert rr_pl.FIELD_KEYS == ['rr_number', 'receipt_date', 'vendor_name',
                                    'remarks']
        assert 'po_number' not in rr_pl.FIELD_KEYS

    def test_columns(self):
        assert rr_pl.COLUMN_KEYS == ['line_number', 'product', 'description',
                                     'po_number', 'ordered_qty', 'received_quantity',
                                     'uom']

    def test_every_label_is_exactly_right(self):
        assert rr_pl.FIELD_LABELS == {
            'rr_number': 'RR No.', 'receipt_date': 'Receipt Date',
            'vendor_name': 'Vendor', 'remarks': 'Remarks',
        }
        assert rr_pl.COLUMN_LABELS == {
            'line_number': '#', 'product': 'Product', 'description': 'Description',
            'po_number': 'PO No.', 'ordered_qty': 'Ordered',
            'received_quantity': 'Received', 'uom': 'UOM',
        }


class TestNoLabelCarriesACurrencySymbol:
    """CAS prints no currency symbol in a column header. Enforce the convention
    rather than describing it in a comment -- a comment is checked by nobody."""

    @pytest.mark.parametrize('mod', ['pr_pl', 'rr_pl'])
    def test_no_currency_glyph_in_any_label(self, mod):
        pl = {'pr_pl': pr_pl, 'rr_pl': rr_pl}[mod]
        for labels in (pl.FIELD_LABELS, pl.COLUMN_LABELS):
            for key, text in labels.items():
                for glyph in ('₱', '$', '&#8369;'):
                    assert glyph not in text, f'{mod}.{key} carries {glyph!r}'


class TestTheDefaultGeometryIsPinned:
    """Nothing else regresses a coordinate edit. `build_layout_api` validates
    RANGE at import time, so an out-of-bounds box never reaches a test -- but two
    individually-valid boxes parked on top of each other is invisible to it.

    Derive the comparisons from the declaration; do not hardcode their results.

    NOTE the constant names: Task 3 established `DEFAULT_<DOC>_PREPRINTED_LAYOUT`,
    so these are `DEFAULT_PR_PREPRINTED_LAYOUT` and `DEFAULT_RR_PREPRINTED_LAYOUT`.
    There is no generic `DEFAULT_LAYOUT` alias -- parametrise over the layout dicts
    themselves rather than trying to reach one through the module.
    """

    LAYOUTS = [pr_pl.DEFAULT_PR_PREPRINTED_LAYOUT, rr_pl.DEFAULT_RR_PREPRINTED_LAYOUT]

    @pytest.mark.parametrize('layout', LAYOUTS)
    def test_columns_tile_without_overlapping(self, layout):
        from app.common import preprinted_base as base
        cols = sorted(layout['lineItems']['columns'], key=lambda c: c['x'])
        for left, right in zip(cols, cols[1:]):
            assert left['x'] + left['width'] <= right['x'], \
                f"{left['key']} overlaps {right['key']}"
        last = cols[-1]
        assert last['x'] + last['width'] <= base.CANVAS_W - base.SAFE_MARGIN

    @pytest.mark.parametrize('layout', LAYOUTS)
    def test_no_two_fields_on_the_same_row_overlap(self, layout):
        boxes = layout['fields']
        by_row = {}
        for key, b in boxes.items():
            by_row.setdefault(b['y'], []).append((b['x'], b['x'] + b['w'], key))
        for y, row in by_row.items():
            row.sort()
            for (_, lend, lkey), (rstart, _, rkey) in zip(row, row[1:]):
                assert lend <= rstart, f'{lkey} overlaps {rkey} at y={y}'

    @pytest.mark.parametrize('layout', LAYOUTS)
    def test_every_field_prints_by_default(self, layout):
        for key, b in layout['fields'].items():
            assert b['hidden'] is False, f'{key} is hidden by default'


class TestTheyDoNotShareIdentity:
    """Control: three declarations built from one factory must stay distinct."""

    def test_keys_differ(self):
        from app.purchase_orders import preprinted_layout as po_pl
        keys = {pr_pl.LAYOUT_SETTING_KEY, rr_pl.LAYOUT_SETTING_KEY, po_pl.LAYOUT_SETTING_KEY}
        assert len(keys) == 3

    def test_a_po_field_is_rejected_by_the_pr_sanitiser(self):
        out = pr_pl.sanitize_layout({'fields': {'vendor_name': {'x': 10, 'y': 10}}})
        assert 'vendor_name' not in out['fields']
