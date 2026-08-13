"""format_line_qty: a quantity reads the way it was entered, whatever the unit.

This used to special-case pieces -- whole for PC/PCS/PCE, 4 decimals for
everything else -- which was wrong in both directions:

  * it ROUNDED, so 1.5 PCS printed as "2" and 0.25 PCS as "0", misstating a
    quantity on documents people act on (SI, SO, DR and Quotation printouts all
    run through this filter);
  * and it left every other unit reading "12.0000 KG" when there was no decimal
    to show.

Dropping the unit test entirely also removes a list of unit codes that had to be
kept in step with each client's own master data.
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


class TestWholeQuantitiesLoseTheDecimals:

    @pytest.mark.parametrize('code', ['PCS', 'KG', 'BOX', 'LITERS', None])
    def test_whole_qty_prints_bare(self, code):
        """The unit is irrelevant -- KG must not read '12.0000' either."""
        assert format_line_qty(_Line(Decimal('12'), code)) == '12'

    def test_thousands_separator_kept(self):
        assert format_line_qty(_Line(Decimal('1250'), 'PCS')) == '1,250'

    def test_trailing_zero_in_the_integer_part_survives(self):
        """rstrip('0') must not eat a significant zero. Safe because '.4f'
        always emits the point: '20.0000' -> '20.' -> '20'."""
        assert format_line_qty(_Line(Decimal('20'), 'KG')) == '20'
        assert format_line_qty(_Line(Decimal('100'), 'KG')) == '100'

    def test_zero_prints_as_zero(self):
        assert format_line_qty(_Line(Decimal('0'), 'PCS')) == '0'


class TestFractionsAreKept:

    def test_fractional_piece_qty_is_NOT_rounded(self):
        """The regression this replaced: 1.5 became "2"."""
        assert format_line_qty(_Line(Decimal('1.5'), 'PCS')) == '1.5'

    def test_fraction_below_one_is_not_swallowed(self):
        """0.25 became "0" -- a quantity that reads as nothing at all."""
        assert format_line_qty(_Line(Decimal('0.25'), 'PCS')) == '0.25'

    def test_full_four_decimals_survive(self):
        assert format_line_qty(_Line(Decimal('1250.5555'), 'KG')) == '1,250.5555'

    def test_stored_trailing_zeros_are_trimmed(self):
        """Numeric(15, 4) stores 1.5000; it should read as entered."""
        assert format_line_qty(_Line(Decimal('1.5000'), 'KG')) == '1.5'

    def test_partial_decimals_keep_only_what_matters(self):
        assert format_line_qty(_Line(Decimal('2.2500'), 'BOX')) == '2.25'


class TestTheUnitIsIgnoredEntirely:
    """Absorbed from the older tests/unit/test_qty_format.py, which split its
    cases into "pieces" and "non-pieces". That distinction no longer exists, so
    these assert the opposite: the same number formats identically however the
    unit is spelled, named, or absent."""

    @pytest.mark.parametrize('kwargs', [
        {'uom_code': 'PCS'}, {'uom_code': 'pcs'}, {'uom_code': 'KG'},
    ])
    def test_unit_code_case_and_value_make_no_difference(self, kwargs):
        line = _Line(Decimal('2'), kwargs['uom_code'])
        assert format_line_qty(line) == '2'

    @pytest.mark.parametrize('text', ['piece', 'Pieces', 'Kilogram', 'Liter', None])
    def test_free_text_unit_makes_no_difference(self, text):
        assert format_line_qty(_Line(Decimal('5'), None, uom_text=text)) == '5'

    def test_a_fraction_formats_the_same_for_kg_and_pcs(self):
        assert (format_line_qty(_Line(Decimal('2.5'), 'KG'))
                == format_line_qty(_Line(Decimal('2.5'), 'PCS'))
                == '2.5')


class TestBlank:

    def test_none_quantity_returns_the_blank(self):
        assert format_line_qty(_Line(None, 'PCS'), '-') == '-'

    def test_blank_defaults_to_empty_string(self):
        assert format_line_qty(_Line(None, 'PCS')) == ''
