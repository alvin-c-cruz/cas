"""Grouping PO print lines by their Description.

Owner directive 2026-08-21: "the PO should be grouped by the Description field
instead" -- the printout was a flat list, and worse, a line's description was
dropped entirely whenever the line carried a product
(`{{ li.product.name if li.product else li.description }}`), so text the buyer
typed never reached the paper.

The grouping is a PURE FUNCTION over the line items, tested here without a
request. Three decisions it encodes, each of which could reasonably have gone
the other way and so is pinned:

* **First-appearance order, not alphabetical.** Jinja's own `groupby` sorts by
  the key, which would silently reshuffle a PO the buyer typed in a deliberate
  order. Groups appear in the order their first line does.
* **Line numbers are NOT renumbered.** The printed PO has to tie back to the
  record; renumbering would make line 3 print as line 1.
* **Lines with no description form a real group with an empty key**, so they
  still print -- they are not silently dropped, and the template decides not to
  draw a heading for them.
"""
from decimal import Decimal

import pytest

from app.purchase_orders.models import group_lines_by_description

pytestmark = [pytest.mark.unit, pytest.mark.purchase_orders]


class _Line:
    """Stand-in for PurchaseOrderItem -- the function must not need the ORM."""

    def __init__(self, line_number, description, amount):
        self.line_number = line_number
        self.description = description
        self.amount = Decimal(str(amount))


def test_lines_sharing_a_description_are_grouped():
    groups = group_lines_by_description([
        _Line(1, 'FOR BOILER USE', 250000),
        _Line(2, 'FOR PLANT MAINTENANCE', 5000),
        _Line(3, 'FOR PLANT MAINTENANCE', 1000),
    ])
    assert [g[0] for g in groups] == ['FOR BOILER USE', 'FOR PLANT MAINTENANCE']
    assert [len(g[1]) for g in groups] == [1, 2]


def test_a_group_subtotals_its_own_lines():
    groups = group_lines_by_description([
        _Line(1, 'A', '10.50'), _Line(2, 'B', '5.25'), _Line(3, 'A', '1.25'),
    ])
    by_key = {k: sub for k, _items, sub in groups}
    assert by_key['A'] == Decimal('11.75')
    assert by_key['B'] == Decimal('5.25')


def test_subtotals_sum_to_the_line_total():
    """The invariant that makes the printed subtotals trustworthy.

    If grouping ever drops or double-counts a line, this catches it -- a
    per-group assertion alone would not.
    """
    lines = [_Line(1, 'A', 100), _Line(2, 'B', 250), _Line(3, 'A', 3), _Line(4, '', 7)]
    groups = group_lines_by_description(lines)
    assert sum(sub for _k, _i, sub in groups) == sum(l.amount for l in lines)
    assert sum(len(i) for _k, i, _s in groups) == len(lines)


def test_group_order_follows_first_appearance_not_the_alphabet():
    """Mutation target: implement with Jinja/itertools groupby over a SORTED key
    and this goes RED -- the buyer's deliberate ordering would be reshuffled.
    """
    groups = group_lines_by_description([
        _Line(1, 'ZINC', 1), _Line(2, 'ALUMINIUM', 1), _Line(3, 'ZINC', 1),
    ])
    assert [g[0] for g in groups] == ['ZINC', 'ALUMINIUM']


def test_line_numbers_are_preserved():
    """Lines keep their own numbers, so the paper ties back to the record."""
    groups = group_lines_by_description([
        _Line(1, 'A', 1), _Line(2, 'B', 1), _Line(3, 'A', 1),
    ])
    a_items = [i for k, i, _s in groups if k == 'A'][0]
    assert [i.line_number for i in a_items] == [1, 3]


def test_lines_without_a_description_still_appear():
    """CONTROL: an undescribed line must not vanish from the printout."""
    groups = group_lines_by_description([
        _Line(1, None, 10), _Line(2, 'A', 5), _Line(3, '   ', 2),
    ])
    keys = [g[0] for g in groups]
    assert '' in keys, 'undescribed lines were dropped'
    blank = [i for k, i, _s in groups if k == ''][0]
    assert [i.line_number for i in blank] == [1, 3], 'whitespace-only is the same as empty'
    assert sum(sub for _k, _i, sub in groups) == Decimal('17')


def test_out_of_order_line_numbers_are_sorted_within_the_group():
    """The relationship is defined by line_number, not by list order."""
    groups = group_lines_by_description([
        _Line(3, 'A', 1), _Line(1, 'A', 1), _Line(2, 'B', 1),
    ])
    assert [g[0] for g in groups] == ['A', 'B']
    a_items = groups[0][1]
    assert [i.line_number for i in a_items] == [1, 3]


def test_a_null_amount_counts_as_zero_not_a_crash():
    """A service line can carry no amount; the subtotal must still compute."""
    line = _Line(1, 'A', 0)
    line.amount = None
    groups = group_lines_by_description([line, _Line(2, 'A', 5)])
    assert groups[0][2] == Decimal('5')


def test_no_lines_yields_no_groups():
    assert group_lines_by_description([]) == []
