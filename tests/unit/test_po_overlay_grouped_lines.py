"""Grouping the PO lines for the PRE-PRINTED overlay.

Owner directive 2026-08-21: group the overlay by Description too.

The overlay is not a table. Each column is an absolutely-positioned stack of
fixed-height cells, and the columns line up only because every stack holds the
SAME NUMBER OF ROWS -- the template says so itself ("all share the band top and
rowHeight so rows align").

So grouping here cannot work the way the standard printout does. Heading rows
and subtotal rows would consume boxes on the client's real pre-printed
stationery, and unless inserted identically into every stack they would drift
the columns out of alignment with the physical form.

Grouping is therefore expressed the way a pre-printed form expresses it: the
SAME rows, reordered so each group sits together, with the Description written
ONCE at the top of its group and blank on the lines beneath. Row count is
unchanged, so alignment is structurally untouched.
"""
from decimal import Decimal

import pytest

from app.purchase_orders.models import grouped_lines_for_overlay

pytestmark = [pytest.mark.unit, pytest.mark.purchase_orders]


class _Line:
    def __init__(self, line_number, description, amount=0):
        self.line_number = line_number
        self.description = description
        self.amount = Decimal(str(amount))


def test_lines_of_a_group_become_contiguous():
    rows = grouped_lines_for_overlay([
        _Line(1, 'ZINC'), _Line(2, 'ALU'), _Line(3, 'ZINC'), _Line(4, 'ALU'),
    ])
    assert [i.line_number for i, _show in rows] == [1, 3, 2, 4]


def test_group_order_is_first_appearance_not_alphabetical():
    rows = grouped_lines_for_overlay([_Line(1, 'ZINC'), _Line(2, 'ALU')])
    assert [i.description for i, _s in rows] == ['ZINC', 'ALU']


def test_the_description_is_flagged_once_per_group():
    rows = grouped_lines_for_overlay([
        _Line(1, 'A'), _Line(2, 'A'), _Line(3, 'B'), _Line(4, 'A'),
    ])
    assert [show for _i, show in rows] == [True, False, False, True]
    #                                       A(1)  A(2)   A(4)   B(3)
    assert [i.line_number for i, _s in rows] == [1, 2, 4, 3]


def test_no_row_is_added_or_lost():
    """THE alignment invariant, at the data level.

    Every column stack renders one cell per row of this list. If grouping ever
    adds a heading row or drops a line, the stacks stop matching the pre-printed
    boxes -- which is a defect you only see on paper.
    """
    lines = [_Line(1, 'A'), _Line(2, 'B'), _Line(3, 'A'), _Line(4, None)]
    rows = grouped_lines_for_overlay(lines)
    assert len(rows) == len(lines)
    assert sorted(i.line_number for i, _s in rows) == [1, 2, 3, 4]


def test_undescribed_lines_are_kept_and_flagged_once():
    rows = grouped_lines_for_overlay([_Line(1, None), _Line(2, 'A'), _Line(3, '  ')])
    nums = [i.line_number for i, _s in rows]
    assert nums == [1, 3, 2], 'the blank-description lines should group together'
    assert [s for _i, s in rows] == [True, False, True]


def test_line_numbers_are_not_renumbered():
    """Non-contiguous numbers survive grouping unchanged.

    Deliberately 10/20/30: with 1/2/3 a renumbering bug would produce the same
    output as correct code and the test would prove nothing. "First appearance"
    is evaluated AFTER sorting by line_number, so group A (10) leads group B (20).
    """
    rows = grouped_lines_for_overlay([_Line(30, 'A'), _Line(20, 'B'), _Line(10, 'A')])
    assert [i.line_number for i, _s in rows] == [10, 30, 20]
    assert [i.description for i, _s in rows] == ['A', 'A', 'B']


def test_no_lines_yields_no_rows():
    assert grouped_lines_for_overlay([]) == []
