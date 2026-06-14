"""Unit tests for CDVExpenseLine and CashDisbursementVoucher model methods."""
import pytest
from decimal import Decimal
from app.cash_disbursements.models import (
    CashDisbursementVoucher, CDVApLine, CDVExpenseLine
)

pytestmark = [pytest.mark.unit]


@pytest.mark.usefixtures("app")
class TestCDVExpenseLineCalculateAmounts:

    def _make_line(self, amount, vat_rate=Decimal('0'), wt_rate=None):
        line = CDVExpenseLine()
        line.amount = Decimal(str(amount))
        line.vat_rate = vat_rate
        line.wt_rate = Decimal(str(wt_rate)) if wt_rate is not None else None
        line.calculate_amounts()
        return line

    def test_zero_vat_line_total_equals_amount(self):
        line = self._make_line('1000.00', vat_rate=Decimal('0'))
        assert line.line_total == Decimal('1000.00')
        assert line.vat_amount == Decimal('0.00')

    def test_twelve_percent_vat_extracted(self):
        # 11200 VAT-inclusive at 12%: net = 10000, vat = 1200
        line = self._make_line('11200.00', vat_rate=Decimal('12'))
        assert line.line_total == Decimal('11200.00')
        assert line.vat_amount == Decimal('1200.00')

    def test_line_total_always_equals_amount(self):
        line = self._make_line('5000.00', vat_rate=Decimal('12'))
        assert line.line_total == line.amount

    def test_wht_computed_on_net_base(self):
        # net_base = 10000, wt at 2% = 200
        line = self._make_line('11200.00', vat_rate=Decimal('12'), wt_rate='2')
        assert line.wt_amount == Decimal('200.00')

    def test_wht_zero_when_no_rate(self):
        line = self._make_line('5000.00', vat_rate=Decimal('0'), wt_rate=None)
        assert line.wt_amount == Decimal('0.00')

    def test_zero_vat_no_wht(self):
        line = self._make_line('3000.00')
        assert line.vat_amount == Decimal('0.00')
        assert line.wt_amount == Decimal('0.00')
        assert line.line_total == Decimal('3000.00')


@pytest.mark.usefixtures("app")
class TestCDVCalculateTotals:

    def _make_expense_line(self, amount, vat_rate=Decimal('0'), wt_rate=None):
        line = CDVExpenseLine()
        line.amount = Decimal(str(amount))
        line.vat_rate = Decimal(str(vat_rate))
        line.wt_rate = Decimal(str(wt_rate)) if wt_rate is not None else None
        line.calculate_amounts()
        return line

    def _make_ap_line(self, amount_applied):
        line = CDVApLine()
        line.amount_applied = Decimal(str(amount_applied))
        return line

    def _make_cdv(self, ap_lines=None, expense_lines=None):
        cdv = CashDisbursementVoucher()
        cdv.vat_override = False
        cdv.wt_override = False
        cdv.ap_lines = ap_lines or []
        cdv.expense_lines = expense_lines or []
        return cdv

    def test_ap_only_cdv(self):
        cdv = self._make_cdv(ap_lines=[self._make_ap_line('5000.00')])
        cdv.calculate_totals()
        assert cdv.total_ap_applied == Decimal('5000.00')
        assert cdv.total_expense == Decimal('0.00')
        assert cdv.total_wt == Decimal('0.00')
        assert cdv.total_amount == Decimal('5000.00')

    def test_expense_only_cdv(self):
        line = self._make_expense_line('11200.00', vat_rate=Decimal('12'), wt_rate='2')
        cdv = self._make_cdv(expense_lines=[line])
        cdv.calculate_totals()
        assert cdv.total_expense == Decimal('11200.00')
        assert cdv.total_vat == Decimal('1200.00')
        assert cdv.total_wt == Decimal('200.00')
        assert cdv.total_amount == Decimal('11000.00')

    def test_mixed_cdv(self):
        ap = self._make_ap_line('3000.00')
        exp = self._make_expense_line('5600.00', vat_rate=Decimal('12'), wt_rate='2')
        cdv = self._make_cdv(ap_lines=[ap], expense_lines=[exp])
        cdv.calculate_totals()
        assert cdv.total_ap_applied == Decimal('3000.00')
        assert cdv.total_expense == Decimal('5600.00')
        assert cdv.total_wt == Decimal('100.00')
        assert cdv.total_amount == Decimal('8500.00')

    def test_multiple_ap_lines_summed(self):
        cdv = self._make_cdv(ap_lines=[
            self._make_ap_line('1000.00'),
            self._make_ap_line('2000.00'),
        ])
        cdv.calculate_totals()
        assert cdv.total_ap_applied == Decimal('3000.00')
        assert cdv.total_amount == Decimal('3000.00')

    def test_wt_override_not_recalculated(self):
        line = self._make_expense_line('11200.00', vat_rate=Decimal('12'), wt_rate='2')
        cdv = self._make_cdv(expense_lines=[line])
        cdv.wt_override = True
        cdv.total_wt = Decimal('500.00')
        cdv.calculate_totals()
        assert cdv.total_wt == Decimal('500.00')
