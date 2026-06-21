"""Mirror of the SI WHT formula across AP / CDV / CRV line items.

Canonical RIC formula: WHT is computed on Net of VAT = Gross - ROUNDED VAT,
NOT on the unrounded Gross/1.12.  Divergent witness: 100.07 @ 12% VAT, 10% WHT
-> VAT 10.72, Net 89.35, WHT round2(8.935) = 8.94  (old unrounded-net = 8.93).
"""
import pytest
from decimal import Decimal
from app.accounts_payable.models import AccountsPayableItem
from app.cash_disbursements.models import CDVExpenseLine
from app.cash_receipts.models import CRVRevenueLine

pytestmark = [pytest.mark.withholding_tax, pytest.mark.unit]


@pytest.mark.usefixtures("app")
@pytest.mark.parametrize("cls", [AccountsPayableItem, CDVExpenseLine, CRVRevenueLine])
class TestWhtOnNetOfRoundedVat:
    def test_divergent_case_uses_rounded_net(self, cls):
        item = cls(line_number=1, description='x',
                   amount=Decimal('100.07'), vat_rate=Decimal('12.00'),
                   wt_rate=Decimal('10.00'))
        item.calculate_amounts()
        assert item.vat_amount == Decimal('10.72')
        assert item.wt_amount == Decimal('8.94')

    def test_clean_case_unchanged(self, cls):
        # 1120 @ 12% -> net 1000; WHT @10% = 100.00 (no rounding residual)
        item = cls(line_number=1, description='x',
                   amount=Decimal('1120.00'), vat_rate=Decimal('12.00'),
                   wt_rate=Decimal('10.00'))
        item.calculate_amounts()
        assert item.vat_amount == Decimal('120.00')
        assert item.wt_amount == Decimal('100.00')
