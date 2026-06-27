"""Unit tests for AccountsPayable and AccountsPayableItem model changes."""
import pytest
from decimal import Decimal
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
pytestmark = [pytest.mark.accounts_payable, pytest.mark.unit]




@pytest.mark.usefixtures("app")
class TestAccountsPayableItemCalculateAmounts:
    """Tests for AccountsPayableItem.calculate_amounts() with new VAT-inclusive Amount field."""

    def _make_item(self, amount, vat_rate=Decimal('0'), wt_rate=None):
        item = AccountsPayableItem()
        item.amount = Decimal(str(amount))
        item.vat_rate = vat_rate
        item.wt_rate = Decimal(str(wt_rate)) if wt_rate is not None else None
        item.calculate_amounts()
        return item

    def test_zero_vat_amount_equals_line_total(self):
        item = self._make_item(amount='1000.00', vat_rate=Decimal('0'))
        assert item.line_total == Decimal('1000.00')
        assert item.vat_amount == Decimal('0.00')

    def test_twelve_percent_vat_extracts_correctly(self):
        # 11200 VAT-inclusive at 12%: net = 11200/1.12 = 10000; vat = 1200
        item = self._make_item(amount='11200.00', vat_rate=Decimal('12'))
        assert item.line_total == Decimal('11200.00')
        assert item.vat_amount == Decimal('1200.00')

    def test_line_total_equals_amount(self):
        item = self._make_item(amount='5000.00', vat_rate=Decimal('12'))
        assert item.line_total == item.amount

    def test_wht_computed_on_net_base(self):
        # 11200 at 12% VAT -> net_base = 10000; WHT at 2% = 200
        item = self._make_item(amount='11200.00', vat_rate=Decimal('12'), wt_rate='2')
        assert item.wt_amount == Decimal('200.00')

    def test_wht_zero_when_no_rate(self):
        item = self._make_item(amount='5000.00', vat_rate=Decimal('0'), wt_rate=None)
        assert item.wt_amount == Decimal('0.00')

    def test_has_quantity_and_unit_price_not_unit_cost(self):
        # P-56 added optional quantity + unit_price (VAT-inclusive) to AP line items;
        # the model uses unit_price, never unit_cost.
        item = AccountsPayableItem()
        assert hasattr(item, 'quantity')
        assert hasattr(item, 'unit_price')
        assert not hasattr(item, 'unit_cost')


@pytest.mark.usefixtures("app")
class TestAccountsPayableCalculateTotals:
    """Tests for AccountsPayable.calculate_totals() with new VAT-inclusive design."""

    def _make_item(self, amount, vat_rate=Decimal('0'), wt_rate=None):
        item = AccountsPayableItem()
        item.amount = Decimal(str(amount))
        item.vat_rate = Decimal(str(vat_rate))
        item.wt_rate = Decimal(str(wt_rate)) if wt_rate is not None else None
        item.calculate_amounts()
        return item

    def test_subtotal_is_sum_of_vat_inclusive_amounts(self):
        bill = AccountsPayable()
        bill.amount_paid = Decimal('0.00')
        item1 = self._make_item('11200.00', vat_rate=Decimal('12'))
        item2 = self._make_item('2240.00', vat_rate=Decimal('12'))
        bill.line_items = [item1, item2]
        bill.calculate_totals()
        assert bill.subtotal == Decimal('13440.00')

    def test_vat_amount_extracted_not_added(self):
        bill = AccountsPayable()
        bill.amount_paid = Decimal('0.00')
        item = self._make_item('11200.00', vat_rate=Decimal('12'))
        bill.line_items = [item]
        bill.calculate_totals()
        # vat is extracted FROM the 11200, not added on top
        assert bill.vat_amount == Decimal('1200.00')
        assert bill.subtotal == Decimal('11200.00')
        assert bill.total_before_wt == Decimal('11200.00')  # equals subtotal, not subtotal+vat

    def test_total_amount_is_subtotal_minus_wht(self):
        bill = AccountsPayable()
        bill.amount_paid = Decimal('0.00')
        # 11200 at 12% VAT, 2% WHT: net_base=10000, wht=200, net_payable=11200-200=11000
        item = self._make_item('11200.00', vat_rate=Decimal('12'), wt_rate='2')
        bill.line_items = [item]
        bill.calculate_totals()
        assert bill.withholding_tax_amount == Decimal('200.00')
        assert bill.total_amount == Decimal('11000.00')

    def test_balance_equals_total_minus_amount_paid(self):
        bill = AccountsPayable()
        bill.amount_paid = Decimal('500.00')
        item = self._make_item('11200.00', vat_rate=Decimal('12'), wt_rate='2')
        bill.line_items = [item]
        bill.calculate_totals()
        assert bill.balance == Decimal('10500.00')


@pytest.mark.usefixtures("app")
class TestAccountsPayableItemToDict:
    def test_to_dict_has_amount_quantity_unit_price_not_unit_cost(self):
        item = AccountsPayableItem()
        item.id = 1
        item.line_number = 1
        item.description = 'Test'
        item.amount = Decimal('11200.00')
        item.vat_category = 'VAT12'
        item.vat_rate = Decimal('12')
        item.line_total = Decimal('11200.00')
        item.vat_amount = Decimal('1200.00')
        item.account_id = None
        item.wt_id = None
        item.wt_rate = None
        item.wt_amount = Decimal('0.00')
        d = item.to_dict()
        assert 'amount' in d
        assert 'quantity' in d
        assert 'unit_price' in d
        assert 'unit_cost' not in d
        assert d['amount'] == 11200.0
