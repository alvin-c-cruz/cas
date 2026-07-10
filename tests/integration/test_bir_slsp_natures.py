from decimal import Decimal
from app.reports.bir import get_summary_list_of_sales, get_summary_list_of_purchases


class TestSlsNatures:
    def test_zero_rated_sale_lands_in_zero_rated_not_vatable(self, db_session,
                                                             posted_si_zero_rated):
        rows = get_summary_list_of_sales(2026, 2)
        row = rows[0]
        assert row['zero_rated_sales'] > 0
        assert row['vatable_sales'] == Decimal('0.00')

    def test_exempt_sale_lands_in_exempt(self, db_session, posted_si_exempt):
        assert get_summary_list_of_sales(2026, 2)[0]['vat_exempt_sales'] > 0

    def test_unclassified_sale_is_not_folded_into_vatable(self, db_session,
                                                          posted_si_no_category):
        row = get_summary_list_of_sales(2026, 2)[0]
        assert row['unclassified_sales'] > 0
        assert row['vatable_sales'] == Decimal('0.00')

    def test_crv_revenue_appears_in_sls(self, db_session, posted_crv_v12):
        """Today's SLS reads sales_invoices only. A cash sale was invisible."""
        assert get_summary_list_of_sales(2026, 2) != []

    def test_totals_row_foots(self, db_session, posted_si_v12, posted_si_zero_rated):
        rows = get_summary_list_of_sales(2026, 2)
        totals = rows[-1]
        assert totals['customer_name'] == 'TOTAL'
        body = rows[:-1]
        for key in ('vatable_sales', 'zero_rated_sales', 'vat_exempt_sales',
                    'unclassified_sales', 'vat_amount'):
            assert totals[key] == sum(r[key] for r in body), key


class TestSlpNatures:
    def test_capital_goods_bucket(self, db_session, posted_ap_capital_goods):
        assert get_summary_list_of_purchases(2026, 2)[0]['capital_goods'] > 0

    def test_services_bucket(self, db_session, posted_ap_v12sv):
        assert get_summary_list_of_purchases(2026, 2)[0]['domestic_services'] > 0

    def test_cdv_expense_appears_in_slp(self, db_session, posted_cdv_v12sv):
        """Today's SLP reads accounts_payable only. A cash purchase was invisible."""
        assert get_summary_list_of_purchases(2026, 2) != []

    def test_unclassified_purchase_not_folded_into_vatable(self, db_session,
                                                           posted_ap_no_category):
        assert get_summary_list_of_purchases(2026, 2)[0]['unclassified_purchases'] > 0


class TestSlpVendorInvoiceNumber:
    """Review finding 1: vendor_invoice_number must never render the literal
    string 'None' on a BIR filing document. AccountsPayable.vendor_invoice_number
    is nullable and Optional() at the form layer, so a vendor with exactly one
    bill and no invoice number on file is a real, unremarkable case."""

    def test_none_invoice_number_coalesces_to_empty_string(
            self, db_session, posted_ap_v12sv):
        """One vendor, one bill, vendor_invoice_number left unset (None)."""
        row = get_summary_list_of_purchases(2026, 2)[0]
        assert row['vendor_invoice_number'] == ''

    def test_real_invoice_number_renders_verbatim(
            self, db_session, posted_ap_capital_goods):
        """One vendor, one bill, a real invoice number on file."""
        row = get_summary_list_of_purchases(2026, 2)[0]
        assert row['vendor_invoice_number'] == 'INV-CG-0001'

    def test_two_bills_different_invoice_numbers_render_various(
            self, db_session, main_branch, revenue_account, vl_vendor):
        """One vendor, two bills, two distinct real invoice numbers -> 'Various'.

        Deliberate choice: a vendor with one bill carrying None and another
        carrying a real number ALSO renders 'Various' (None and the real value
        are two distinct doc_no's) -- there genuinely isn't a single invoice
        number to print, so folding to the real one would be misleading."""
        from datetime import date
        from decimal import Decimal
        from app.accounts_payable.models import AccountsPayable, AccountsPayableItem

        for i, inv_no in enumerate(['INV-A-0001', 'INV-B-0001']):
            bill = AccountsPayable(
                branch_id=main_branch.id,
                ap_number=f'AP-VARIOUS-{i:04d}',
                ap_date=date(2026, 2, 15),
                due_date=date(2026, 3, 17),
                payee_type='vendor', payee_id=vl_vendor.id,
                vendor_id=vl_vendor.id,
                vendor_name=vl_vendor.name,
                vendor_tin=vl_vendor.tin,
                vendor_invoice_number=inv_no,
                status='posted',
            )
            item = AccountsPayableItem(
                line_number=1, description='Line',
                amount=Decimal('1120.00'), vat_rate=Decimal('12.00'),
                vat_category='V12SV', vat_nature='domestic_services',
                line_total=Decimal('1120.00'), vat_amount=Decimal('120.00'),
                account_id=revenue_account.id,
            )
            bill.line_items.append(item)
            db_session.add(bill)
        db_session.commit()

        row = get_summary_list_of_purchases(2026, 2)[0]
        assert row['vendor_invoice_number'] == 'Various'
