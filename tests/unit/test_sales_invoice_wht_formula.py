"""WHT formula for SalesInvoiceItem (RIC migration canonical formula).

Owner-specified formula (2026-06-21), matching the legacy accounting books:
  1. VAT = round2(Gross - Gross/1.12)            # HALF_UP
  2. Net of VAT = Gross - VAT                     # net derived from the ROUNDED vat
  3. WHT = round2(Net of VAT x wt_rate%)          # HALF_UP
  4. Receivable = Gross - WHT

The distinguishing point from the old implementation is step 2: WHT is computed
on (Gross - rounded VAT), NOT on the unrounded Gross/1.12.
"""
import pytest
from decimal import Decimal
from app.sales_invoices.models import SalesInvoiceItem

pytestmark = [pytest.mark.withholding_tax, pytest.mark.unit]


@pytest.mark.usefixtures("app")
class TestSalesInvoiceItemWhtFormula:
    def _item(self, **kw):
        defaults = dict(line_number=1, description='x',
                        amount=Decimal('0'), vat_rate=Decimal('12.00'),
                        wt_id=None, wt_rate=None)
        defaults.update(kw)
        return SalesInvoiceItem(**defaults)

    def test_wht_on_net_of_rounded_vat(self):
        # Gross 100.07 @ 12% -> VAT round2(100.07 - 100.07/1.12) = 10.72
        #                       Net = 100.07 - 10.72 = 89.35
        #                       WHT @10% = round2(89.35 * 0.10) = round2(8.935) = 8.94
        # (old code on unrounded net 89.348.. gives 8.93)
        item = self._item(amount=Decimal('100.07'), wt_rate=Decimal('10.00'))
        item.calculate_amounts()
        assert item.vat_amount == Decimal('10.72')
        assert item.wt_amount == Decimal('8.94')

    def test_monde_0029235_figures(self):
        # The first migrated sale: Gross 363,992.72 @ 12% VAT, 1% EWT.
        # Legacy GL: VAT 38,999.22, Net 324,993.50, WHT 3,249.94, AR 360,742.78.
        item = self._item(amount=Decimal('363992.72'), wt_rate=Decimal('1.00'))
        item.calculate_amounts()
        assert item.vat_amount == Decimal('38999.22')
        assert item.wt_amount == Decimal('3249.94')

    def test_no_wht_is_zero(self):
        item = self._item(amount=Decimal('1120.00'), wt_rate=None)
        item.calculate_amounts()
        assert item.wt_amount == Decimal('0.00')
