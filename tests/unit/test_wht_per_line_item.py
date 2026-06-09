"""Unit tests for WHT per line item on PurchaseBillItem."""
import pytest
from decimal import Decimal
from app.purchase_bills.models import PurchaseBillItem


class TestPurchaseBillItemWht:
    @pytest.fixture(autouse=True)
    def setup_app_context(self, app):
        """Ensure the Flask app context is active so SQLAlchemy can resolve mappers."""
        with app.app_context():
            yield

    def _make_item(self, **kwargs):
        defaults = dict(
            line_number=1,
            description='Office supplies',
            quantity=Decimal('2.0000'),
            unit_cost=Decimal('500.00'),
            vat_rate=Decimal('12.00'),
            wt_id=None,
            wt_rate=None,
        )
        defaults.update(kwargs)
        return PurchaseBillItem(**defaults)

    def test_wt_amount_zero_when_no_wht(self):
        item = self._make_item()
        item.calculate_amounts()
        assert item.wt_amount == Decimal('0.00')

    def test_wt_amount_computed_from_line_total(self):
        # line_total = 2 * 500 = 1000; wt = 1000 * 10 / 100 = 100
        item = self._make_item(wt_rate=Decimal('10.00'))
        item.calculate_amounts()
        assert item.line_total == Decimal('1000.00')
        assert item.wt_amount == Decimal('100.00')

    def test_calculate_amounts_still_sets_line_total_and_vat(self):
        item = self._make_item(wt_rate=Decimal('2.00'))
        item.calculate_amounts()
        assert item.line_total == Decimal('1000.00')
        assert item.vat_amount == Decimal('120.00')  # 1000 * 12%

    def test_to_dict_includes_wt_fields(self):
        item = self._make_item(wt_id=3, wt_rate=Decimal('10.00'))
        item.calculate_amounts()
        d = item.to_dict()
        assert d['wt_id'] == 3
        assert d['wt_rate'] == 10.0
        assert d['wt_amount'] == 100.0

    def test_to_dict_wt_none_when_no_wht(self):
        item = self._make_item()
        item.calculate_amounts()
        d = item.to_dict()
        assert d['wt_id'] is None
        assert d['wt_rate'] is None
        assert d['wt_amount'] == 0.0
