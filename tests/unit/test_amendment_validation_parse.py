"""parse_submission turns raw POSTed JSON into a per-row map, or messages. Never raises."""
from decimal import Decimal

import pytest

from app.amendments.validation import (MAX_LINE_QUANTITY, OUT_OF_RANGE, UNREADABLE,
                                       parse_submission)


class TestParseSubmission:
    def test_keys_per_row_not_per_product(self):
        # THE exploit this pins: two rows of the same product must stay separate.
        rows = [{'po_item_id': 1, 'quantity': '0'}, {'po_item_id': 2, 'quantity': '5000'}]
        submitted, errors = parse_submission(rows, 'po_item_id')
        assert errors == []
        assert submitted == {1: Decimal('0'), 2: Decimal('5000')}

    def test_duplicate_row_id_is_refused(self):
        rows = [{'po_item_id': 1, 'quantity': '1'}, {'po_item_id': 1, 'quantity': '9'}]
        submitted, errors = parse_submission(rows, 'po_item_id')
        assert any('same original row' in e for e in errors)

    def test_non_dict_line_is_refused_not_raised(self):
        submitted, errors = parse_submission(['not-a-line', 42, None], 'po_item_id')
        assert submitted == {}
        assert len(errors) == 3

    @pytest.mark.parametrize('crafted', [123, 1.5, True, False, 'x', None,
                                         {'po_item_id': 1}, ()])
    def test_a_submission_that_is_not_a_list_is_refused_not_raised(self, crafted):
        # `for line in (new_lines or [])` raises TypeError on an int/float/bool
        # and silently iterates the CHARACTERS of a string or the KEYS of a dict.
        # The route calls validate_amendment outside its try block, so the raise
        # was an unhandled 500 -- the exact outcome this module's docstring says
        # cannot happen. A tuple is refused too: the applier's `items or []`
        # contract is a JSON array, and json.loads never produces a tuple, so
        # anything else is a caller that has not been through json.loads.
        submitted, errors = parse_submission(crafted, 'po_item_id')
        assert submitted == {}
        assert len(errors) == 1
        assert 'Malformed submission' in errors[0]

    def test_an_empty_list_is_a_valid_submission(self):
        # CONTROL for the guard above: `[]` is a well-formed submission (the user
        # removed every line) and must stay judgeable on its own terms. Whether it
        # is ALLOWED is a document-level question the route answers -- see
        # PurchaseOrder.has_approvable_line -- not a parse error.
        submitted, errors = parse_submission([], 'po_item_id')
        assert submitted == {} and errors == []

    def test_new_line_without_an_id_is_skipped(self):
        submitted, errors = parse_submission([{'po_item_id': None, 'quantity': '3'}], 'po_item_id')
        assert submitted == {} and errors == []

    def test_unparseable_id_is_treated_as_a_new_line(self):
        submitted, errors = parse_submission([{'po_item_id': 'abc', 'quantity': '3'}], 'po_item_id')
        assert submitted == {} and errors == []

    def test_unreadable_quantity_is_its_own_sentinel_not_zero(self):
        # Zero is the most destructive value; never guess it. The sentinel changed
        # from None to UNREADABLE in slice 3: None now means LEGITIMATELY ABSENT,
        # which some documents allow (Purchase Request lines may carry no
        # quantity). The rule this test exists for -- never guess zero, and never
        # let garbage become a comparable Decimal -- is unchanged.
        submitted, _ = parse_submission([{'po_item_id': 1, 'quantity': 'wat'}], 'po_item_id')
        assert submitted == {1: UNREADABLE}
        assert submitted[1] is not None
        assert submitted[1] != 0

    def test_missing_quantity_is_None(self):
        submitted, _ = parse_submission([{'po_item_id': 1}], 'po_item_id')
        assert submitted == {1: None}

    def test_nan_and_infinity_are_refused_with_their_own_message(self):
        # A later ordered comparison against a quiet NaN signals InvalidOperation,
        # which in a route is a 500 rather than a flashed refusal -- so these must
        # never become a comparable Decimal. Slice 3 made them REFUSE rather than
        # silently null: an id-less row carrying 'Infinity' otherwise reached the
        # column, and a converted Purchase Order line then reports an infinite
        # open quantity forever. They are neither absent nor merely too large, so
        # the message is their own rather than the range one.
        for bad in ('NaN', 'Infinity', '-Infinity'):
            submitted, errors = parse_submission(
                [{'po_item_id': 1, 'quantity': bad}], 'po_item_id')
            assert submitted == {1: OUT_OF_RANGE}, bad
            assert errors and 'not a valid number' in errors[0], bad

    def test_out_of_range_is_its_own_sentinel_with_its_own_message(self):
        # Decimal('1E+9999') IS finite -- is_finite() does not catch it.
        rows = [{'po_item_id': 1, 'quantity': '1E+9999'}]
        submitted, errors = parse_submission(rows, 'po_item_id')
        assert submitted[1] is OUT_OF_RANGE
        assert submitted[1] is not None
        assert any('out of range' in e for e in errors)

    def test_max_line_quantity_boundary(self):
        ok, errors = parse_submission(
            [{'po_item_id': 1, 'quantity': str(MAX_LINE_QUANTITY)}], 'po_item_id')
        assert ok[1] == MAX_LINE_QUANTITY and errors == []
