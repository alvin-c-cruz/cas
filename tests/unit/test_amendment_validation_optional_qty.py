"""Two shared-validator defects found by slice 3's whole-branch review.

F1 -- ABSENT is not UNREADABLE. The validator collapsed both to None and refused
     with "could not read the submitted quantity". That is correct for a document
     whose lines must carry a quantity (PO, SO), and WRONG for one where the
     column is nullable and the create parser accepts a line on product-or-
     description alone. Purchase Request is the first such adopter, so an
     ordinary requisition line with no quantity could not be amended at all --
     not even re-saved unchanged, which the spec requires to be a no-op. The
     message was also a lie: the value read fine, it was legally absent.

F2 -- MAX_LINE_QUANTITY did not bound a NEW line. parse_submission `continue`d on
     id-less rows BEFORE the range check, so `{"pr_item_id": null,
     "quantity": "1E+9999"}` was accepted and stored as Decimal('Infinity').
     Once convert() copies that into a Purchase Order line, po_line_open_qty
     returns Infinity - received forever and the over-receiving guard is
     permanently satisfied. Slice 4 is RR/DR, which builds directly on that value.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.amendments.validation import MAX_LINE_QUANTITY, parse_submission, validate_amendment
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem

pytestmark = [pytest.mark.unit]


@pytest.fixture
def pr(db_session):
    """A requisition line with NO quantity -- an ordinary shape here, not a
    crafted one: the column is nullable and _parse_and_attach_pr_lines keeps a
    line that carries a product OR a description."""
    pr = PurchaseRequest(pr_number='PR-QTY-1', request_date=date(2026, 8, 11),
                         status='approved', reason='x')
    pr.line_items.append(PurchaseRequestItem(
        line_number=1, description='Cement, quantity to follow', quantity=None))
    db.session.add(pr)
    db.session.commit()
    return pr


@pytest.fixture
def po(db_session):
    po = PurchaseOrder(po_number='00998', order_date=date(2026, 8, 5), status='approved',
                       vendor_name='ACME', notes='', payment_terms='Net 30',
                       vat_treatment='inclusive')
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description='widget', quantity=Decimal('10'),
        unit_price=Decimal('5.00'), amount=Decimal('50.00'), line_total=Decimal('50.00'),
        vat_rate=Decimal('0'), vat_amount=Decimal('0')))
    db.session.add(po)
    db.session.commit()
    return po


class TestAbsentQuantityIsNotUnreadable:

    def test_a_quantity_less_pr_line_can_be_resaved_unchanged(self, pr):
        rows = [{'pr_item_id': pr.line_items[0].id,
                 'description': 'Cement, quantity to follow', 'quantity': None}]
        assert validate_amendment(pr, rows, 'pr_item_id') == [], (
            'an ordinary requisition line with no quantity must be amendable; '
            're-saving it unchanged is required to be a no-op')

    def test_an_omitted_quantity_key_is_also_accepted(self, pr):
        rows = [{'pr_item_id': pr.line_items[0].id, 'description': 'Cement'}]
        assert validate_amendment(pr, rows, 'pr_item_id') == []

    def test_an_UNREADABLE_quantity_is_still_refused(self, pr):
        # The distinction that makes the above safe: garbage is still garbage.
        rows = [{'pr_item_id': pr.line_items[0].id, 'quantity': 'abc'}]
        errors = validate_amendment(pr, rows, 'pr_item_id')
        assert errors and 'could not read' in errors[0]

    def test_a_document_that_REQUIRES_a_quantity_still_refuses_an_absent_one(self, po):
        # CONTROL: the default is unchanged, so PO and SO keep today's behaviour.
        assert PurchaseOrder.LINE_QUANTITY_REQUIRED is True
        rows = [{'po_item_id': po.line_items[0].id, 'quantity': None}]
        errors = validate_amendment(po, rows, 'po_item_id')
        assert errors and 'could not read' in errors[0]

    def test_pr_declares_the_quantity_optional(self):
        assert PurchaseRequest.LINE_QUANTITY_REQUIRED is False


class TestNewLinesAreRangeBounded:

    def test_a_new_line_out_of_range_is_refused(self, pr):
        submitted, errors = parse_submission(
            [{'pr_item_id': None, 'quantity': '1E+9999'}], 'pr_item_id')
        assert errors, (
            'an id-less row skipped the range check entirely, so Infinity reached '
            'the column and every later open-quantity computation on it')
        assert 'out of range' in errors[0]

    def test_a_new_line_that_is_not_finite_is_refused(self, pr):
        # NaN/Infinity get their OWN message: they are neither absent nor merely
        # too large, and calling Infinity "out of range (maximum 99999999999.9999)"
        # invites the reader to retype a smaller number when the value was never
        # a number at all.
        _, errors = parse_submission(
            [{'pr_item_id': None, 'quantity': 'Infinity'}], 'pr_item_id')
        assert errors and 'not a valid number' in errors[0]

    def test_a_new_line_at_the_maximum_is_allowed(self, pr):
        # Boundary is INCLUSIVE, matching the existing-line rule.
        _, errors = parse_submission(
            [{'pr_item_id': None, 'quantity': str(MAX_LINE_QUANTITY)}], 'pr_item_id')
        assert errors == []

    def test_an_ordinary_new_line_is_still_allowed(self, pr):
        # CONTROL: the range check must not start refusing ordinary new lines.
        submitted, errors = parse_submission(
            [{'pr_item_id': None, 'quantity': '7'}], 'pr_item_id')
        assert errors == []
        assert submitted == {}, 'a new line still contributes no per-row identity'

    def test_the_route_refuses_an_out_of_range_new_line(self, pr):
        errors = validate_amendment(
            pr, [{'pr_item_id': pr.line_items[0].id, 'quantity': None},
                 {'pr_item_id': None, 'quantity': '1E+9999'}], 'pr_item_id')
        assert errors and any('out of range' in e for e in errors)
