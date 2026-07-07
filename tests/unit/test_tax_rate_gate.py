import pytest
from decimal import Decimal
from app.utils.admin_approval import _rate_equal, tax_rate_changed

pytestmark = [pytest.mark.unit]


class TestRateEqual:
    def test_int_vs_two_dp_float_equal(self):
        assert _rate_equal(12, 12.00) is True

    def test_str_vs_decimal_equal(self):
        assert _rate_equal("12.00", Decimal("12.00")) is True

    def test_different_rates_not_equal(self):
        assert _rate_equal(Decimal("12.00"), Decimal("2.00")) is False

    def test_unparseable_is_not_equal_failclosed(self):
        assert _rate_equal(None, 10) is False
        assert _rate_equal("abc", 10) is False

    def test_tax_rate_changed_is_inverse(self):
        assert tax_rate_changed(Decimal("10.00"), Decimal("10.00")) is False
        assert tax_rate_changed(Decimal("10.00"), Decimal("12.00")) is True
        assert tax_rate_changed(None, Decimal("10.00")) is True
