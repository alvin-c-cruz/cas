"""SalesInvoice.calculate_totals() rounds VAT/WHT once per (vat_category,
vat_rate, wt_id, wt_rate) group, not per line then summed.

Confirmed real, RIC SI 34043 (2026-07-29): legacy's own VAT formula rounds
once on the whole invoice total (`round(amount_due / 1.12 * .12, 2)`); CAS's
old per-line-then-sum approach could drift +/-0.01 from that on a multi-line
invoice with the same VAT category on every line. See
app/sales_invoices/models.py::SalesInvoice._grouped_tax_totals.
"""
import pytest
from decimal import Decimal

from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem

pytestmark = [pytest.mark.unit]


@pytest.mark.usefixtures("app")
class TestGroupedVatWhtRounding:
    def _invoice_with_lines(self, lines, vat_override=False, wt_override=False):
        inv = SalesInvoice(invoice_number='TEST', customer_name='x', notes='',
                           status='draft', amount_paid=Decimal('0.00'),
                           vat_override=vat_override, wt_override=wt_override)
        for i, (amount, vat_category, vat_rate, wt_id, wt_rate) in enumerate(lines, start=1):
            item = SalesInvoiceItem(
                line_number=i, description='x', amount=Decimal(str(amount)),
                vat_category=vat_category, vat_rate=Decimal(str(vat_rate)),
                wt_id=wt_id, wt_rate=Decimal(str(wt_rate)) if wt_rate else None,
            )
            item.calculate_amounts()
            inv.line_items.append(item)
        return inv

    def test_ric_si_34043_ties_to_legacy_single_total_vat(self):
        # 2 lines, same VAT category/rate and WHT code -- the exact RIC SI
        # 34043 shape. Legacy: VAT = round(90576.00/1.12*.12, 2) = 9704.57.
        # Old CAS (per-line sum): 8434.29 + 1270.29 = 9704.58 -- 0.01 off.
        inv = self._invoice_with_lines([
            (78720.00, 'V12', 12, 1, 1.00),
            (11856.00, 'V12', 12, 1, 1.00),
        ])
        inv.calculate_totals()
        assert inv.subtotal == Decimal('90576.00')
        assert inv.vat_amount == Decimal('9704.57')
        assert inv.withholding_tax_amount == Decimal('808.71')
        assert inv.total_amount == Decimal('89767.29')

    def test_single_line_unchanged_from_per_line_formula(self):
        # A single-line group is mathematically identical whether "grouped" or
        # "per line" -- pins that the RIC canonical-formula unit tests
        # (test_sales_invoice_wht_formula.py) stay consistent at the header level.
        inv = self._invoice_with_lines([(363992.72, 'V12', 12, 1, 1.00)])
        inv.calculate_totals()
        assert inv.vat_amount == Decimal('38999.22')
        assert inv.withholding_tax_amount == Decimal('3249.94')

    def test_mixed_vat_categories_round_independently_per_group(self):
        # Different vat_category -> different groups, each rounded on its own
        # subtotal (matches the existing output_vat_buckets per-category model).
        inv = self._invoice_with_lines([
            (2240.00, 'SVG', 12, None, 0),
            (1120.00, 'SVS', 12, None, 0),
        ])
        inv.calculate_totals()
        assert inv.vat_amount == Decimal('360.00')  # 240.00 + 120.00, exact division
        assert inv.withholding_tax_amount == Decimal('0.00')

    def test_no_vat_no_wht(self):
        inv = self._invoice_with_lines([(1000.00, 'VEX', 0, None, 0)])
        inv.calculate_totals()
        assert inv.vat_amount == Decimal('0.00')
        assert inv.withholding_tax_amount == Decimal('0.00')
        assert inv.total_amount == Decimal('1000.00')

    def test_vat_override_skips_grouped_calc(self):
        inv = self._invoice_with_lines([
            (78720.00, 'V12', 12, 1, 1.00),
            (11856.00, 'V12', 12, 1, 1.00),
        ], vat_override=True)
        inv.vat_amount = Decimal('9999.99')
        inv.calculate_totals()
        assert inv.vat_amount == Decimal('9999.99')  # untouched by the grouped calc

    def test_wt_override_skips_grouped_calc(self):
        inv = self._invoice_with_lines([
            (78720.00, 'V12', 12, 1, 1.00),
            (11856.00, 'V12', 12, 1, 1.00),
        ], wt_override=True)
        inv.withholding_tax_amount = Decimal('1.00')
        inv.calculate_totals()
        assert inv.vat_amount == Decimal('9704.57')  # VAT still auto
        assert inv.withholding_tax_amount == Decimal('1.00')  # WHT untouched
