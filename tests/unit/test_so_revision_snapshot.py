"""Unit tests -- SO snapshot serialisation."""
import pytest
from decimal import Decimal
from app.sales_orders.revisions import _s, _money

pytestmark = [pytest.mark.unit, pytest.mark.sales_orders]


def test_decimal_from_db_and_from_form_serialise_identically():
    """Numeric(15,4) reads back as Decimal('3000.0000'); the form parser gives
    Decimal('3000'). Two snapshots of an UNCHANGED order must be equal, so these
    must serialise the same."""
    assert _s(Decimal('3000.0000')) == _s(Decimal('3000')) == '3000'
    assert _s(Decimal('4.2000')) == _s(Decimal('4.20')) == '4.2'


def test_large_integral_decimal_does_not_become_scientific_notation():
    """Decimal('3000').normalize() is Decimal('3E+3'); format(..., 'f') fixes it."""
    assert _s(Decimal('3000')) == '3000'


def test_negative_zero_serialises_identically_to_zero():
    assert _s(Decimal('-0')) == _s(Decimal('0')) == '0'


def test_dates_serialise_iso():
    import datetime
    assert _s(datetime.date(2026, 8, 4)) == '2026-08-04'


def test_none_survives_as_none():
    assert _s(None) is None


def test_money_formatter_keeps_two_decimals_where_s_collapses_them():
    """_s canonicalises for EQUALITY; _money renders for a printed slip."""
    assert _s(Decimal('4.20')) == '4.2'
    assert _money(Decimal('4.20')) == '4.20'
    assert _money(Decimal('12600')) == '12600.00'
    assert _money(None) is None
