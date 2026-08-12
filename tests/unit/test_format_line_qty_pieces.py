"""format_line_qty: pieces print whole -- unless a fraction was actually entered.

The piece branch used '{:,.0f}', which ROUNDS. 1.5 PCS printed as "2" and
0.25 PCS as "0", silently misstating a quantity on documents people act on
(SI, SO, DR and Quotation printouts all run through this filter).
"""
from decimal import Decimal

import pytest

from app.utils import format_line_qty

pytestmark = [pytest.mark.unit]


class _Uom:
    def __init__(self, code, name=None):
        self.code = code
        self.name = name or code


class _Line:
    def __init__(self, quantity, uom_code=None, uom_text=None):
        self.quantity = quantity
        self.unit_of_measure = _Uom(uom_code) if uom_code else None
        self.uom_text = uom_text


class TestPieceQuantities:

    @pytest.mark.parametrize('code', ['PC', 'PCS', 'PCE'])
    def test_whole_piece_qty_has_no_decimal_point(self, code):
        assert format_line_qty(_Line(Decimal('12'), code)) == '12'

    @pytest.mark.parametrize('name', ['Pieces', 'piece', 'pcs'])
    def test_recognised_by_uom_name_too(self, name):
        line = _Line(Decimal('3'), None, uom_text=name)
        assert format_line_qty(line) == '3'

    def test_thousands_separator_kept(self):
        assert format_line_qty(_Line(Decimal('1250'), 'PCS')) == '1,250'

    def test_fractional_piece_qty_is_NOT_rounded(self):
        """The regression. 1.5 became "2"."""
        assert format_line_qty(_Line(Decimal('1.5'), 'PCS')) == '1.5'

    def test_fraction_below_one_is_not_swallowed(self):
        """0.25 became "0" -- a quantity that reads as nothing at all."""
        assert format_line_qty(_Line(Decimal('0.25'), 'PCS')) == '0.25'

    def test_trailing_zeros_trimmed(self):
        """Numeric(15, 4) stores 1.5000; it should read as entered."""
        assert format_line_qty(_Line(Decimal('1.5000'), 'PCS')) == '1.5'


class TestNonPieceQuantitiesUnchanged:
    """Control on the path this change did not mean to touch. A weight or volume
    keeps 4 decimals whether or not it is whole."""

    def test_whole_kg_keeps_four_decimals(self):
        assert format_line_qty(_Line(Decimal('12'), 'KG')) == '12.0000'

    def test_fractional_kg_keeps_four_decimals(self):
        assert format_line_qty(_Line(Decimal('1250.5555'), 'KG')) == '1,250.5555'

    def test_no_uom_at_all_keeps_four_decimals(self):
        assert format_line_qty(_Line(Decimal('2'))) == '2.0000'


class TestBlank:

    def test_none_quantity_returns_the_blank(self):
        assert format_line_qty(_Line(None, 'PCS'), '-') == '-'
