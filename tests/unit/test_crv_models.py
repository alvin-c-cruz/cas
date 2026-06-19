"""Unit tests for CRVRevenueLine and CashReceiptVoucher model methods."""
import pytest
from decimal import Decimal
from app.cash_receipts.models import (
    CashReceiptVoucher, CRVArLine, CRVRevenueLine
)

pytestmark = [pytest.mark.unit]


@pytest.mark.usefixtures("app")
class TestCRVRevenueLineCalculateAmounts:

    def _make_line(self, amount, vat_rate=Decimal('0'), wt_rate=None):
        line = CRVRevenueLine()
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

    def test_revenue_line_extracts_vat_and_wt(self):
        """VAT extraction: 1120 at 12% → vat 120, net 1000, wt 2% of 1000 = 20."""
        line = CRVRevenueLine(line_number=1, description='x',
                              amount=Decimal('1120.00'), vat_rate=Decimal('12.00'),
                              wt_rate=Decimal('2.00'))
        line.calculate_amounts()
        assert line.line_total == Decimal('1120.00')
        assert line.vat_amount == Decimal('120.00')      # 1120 - 1000
        assert line.wt_amount == Decimal('20.00')        # 2% of 1000 net


@pytest.mark.usefixtures("app")
class TestCRVCalculateTotals:

    def _make_revenue_line(self, amount, vat_rate=Decimal('0'), wt_rate=None):
        line = CRVRevenueLine()
        line.amount = Decimal(str(amount))
        line.vat_rate = Decimal(str(vat_rate))
        line.wt_rate = Decimal(str(wt_rate)) if wt_rate is not None else None
        line.calculate_amounts()
        return line

    def _make_ar_line(self, amount_applied):
        line = CRVArLine()
        line.amount_applied = Decimal(str(amount_applied))
        return line

    def _make_crv(self, ar_lines=None, revenue_lines=None):
        crv = CashReceiptVoucher()
        crv.vat_override = False
        crv.wt_override = False
        crv.ar_lines = ar_lines or []
        crv.revenue_lines = revenue_lines or []
        return crv

    def test_ar_only_crv(self):
        crv = self._make_crv(ar_lines=[self._make_ar_line('5000.00')])
        crv.calculate_totals()
        assert crv.total_ar_applied == Decimal('5000.00')
        assert crv.total_revenue == Decimal('0.00')
        assert crv.total_wt == Decimal('0.00')
        assert crv.total_amount == Decimal('5000.00')

    def test_revenue_only_crv(self):
        line = self._make_revenue_line('11200.00', vat_rate=Decimal('12'), wt_rate='2')
        crv = self._make_crv(revenue_lines=[line])
        crv.calculate_totals()
        assert crv.total_revenue == Decimal('11200.00')
        assert crv.total_vat == Decimal('1200.00')
        assert crv.total_wt == Decimal('200.00')
        assert crv.total_amount == Decimal('11000.00')

    def test_mixed_crv(self):
        ar = self._make_ar_line('3000.00')
        rev = self._make_revenue_line('5600.00', vat_rate=Decimal('12'), wt_rate='2')
        crv = self._make_crv(ar_lines=[ar], revenue_lines=[rev])
        crv.calculate_totals()
        assert crv.total_ar_applied == Decimal('3000.00')
        assert crv.total_revenue == Decimal('5600.00')
        assert crv.total_wt == Decimal('100.00')
        assert crv.total_amount == Decimal('8500.00')

    def test_multiple_ar_lines_summed(self):
        crv = self._make_crv(ar_lines=[
            self._make_ar_line('1000.00'),
            self._make_ar_line('2000.00'),
        ])
        crv.calculate_totals()
        assert crv.total_ar_applied == Decimal('3000.00')
        assert crv.total_amount == Decimal('3000.00')

    def test_wt_override_not_recalculated(self):
        line = self._make_revenue_line('11200.00', vat_rate=Decimal('12'), wt_rate='2')
        crv = self._make_crv(revenue_lines=[line])
        crv.wt_override = True
        crv.total_wt = Decimal('500.00')
        crv.calculate_totals()
        assert crv.total_wt == Decimal('500.00')

    def test_vat_override_not_recalculated(self):
        line = self._make_revenue_line('11200.00', vat_rate=Decimal('12'))
        crv = self._make_crv(revenue_lines=[line])
        crv.vat_override = True
        crv.total_vat = Decimal('999.00')
        crv.calculate_totals()
        assert crv.total_vat == Decimal('999.00')

    def test_totals_ar_plus_revenue_minus_wt(self, db_session):
        """Integration: ar_applied + revenue - wt = total_amount."""
        crv = CashReceiptVoucher(crv_number='CR-2026-06-0001', crv_date=None,
                                 branch_id=1, customer_id=1, customer_name='C',
                                 cash_account_id=1)
        crv.ar_lines.append(CRVArLine(line_number=1, invoice_id=1,
                                      invoice_number='SI-2026-0001',
                                      original_balance=Decimal('500'),
                                      amount_applied=Decimal('500.00')))
        rl = CRVRevenueLine(line_number=1, description='svc',
                            amount=Decimal('1120.00'), vat_rate=Decimal('12.00'),
                            wt_rate=Decimal('2.00'))
        rl.calculate_amounts()
        crv.revenue_lines.append(rl)
        crv.calculate_totals()
        assert crv.total_ar_applied == Decimal('500.00')
        assert crv.total_revenue == Decimal('1120.00')
        assert crv.total_vat == Decimal('120.00')
        assert crv.total_wt == Decimal('20.00')
        assert crv.total_amount == Decimal('1600.00')    # 500 + 1120 - 20
