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
