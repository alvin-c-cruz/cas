"""canonical() normalises for EQUALITY; money() formats for DISPLAY. Never interchangeable."""
from datetime import date, datetime
from decimal import Decimal

from app.amendments.snapshot import canonical, money


class TestCanonical:
    def test_none_passes_through(self):
        assert canonical(None) is None

    def test_same_value_from_different_origins_compares_equal(self):
        # A Numeric(15,4) read back from SQLite gives Decimal('3000.0000');
        # the form parser gives Decimal('3000'). Both must canonicalise the same.
        assert canonical(Decimal('3000.0000')) == canonical(Decimal('3000'))

    def test_large_integral_decimal_is_not_scientific(self):
        # Decimal('3000').normalize() is 3E+3 -- unusable as a snapshot key.
        assert canonical(Decimal('3000')) == '3000'

    def test_negative_zero_matches_zero(self):
        # Decimal('-0') == Decimal('0') is True but they render '-0' and '0';
        # equal values with unequal text is exactly the failure this guards.
        assert canonical(Decimal('-0')) == canonical(Decimal('0'))

    def test_dates_are_iso(self):
        assert canonical(date(2026, 8, 5)) == '2026-08-05'
        assert canonical(datetime(2026, 8, 5, 14, 30)).startswith('2026-08-05T14:30')

    def test_other_types_stringify(self):
        assert canonical(True) == 'True'
        assert canonical('PO-1') == 'PO-1'


class TestMoney:
    def test_none_passes_through(self):
        assert money(None) is None

    def test_always_two_decimals(self):
        assert money(Decimal('4.2')) == '4.20'
        assert money(Decimal('1130.5')) == '1130.50'
        assert money(0) == '0.00'

    def test_differs_from_canonical_on_purpose(self):
        # canonical collapses 4.20 -> '4.2' (right for equality, wrong on a printed form).
        assert canonical(Decimal('4.20')) == '4.2'
        assert money(Decimal('4.20')) == '4.20'
