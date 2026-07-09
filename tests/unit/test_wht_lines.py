import pytest
from datetime import date
from app.reports.wht_lines import wht_lines, WhtLine


class TestWhtLinesContract:
    def test_fields(self):
        assert WhtLine._fields == (
            'side', 'source', 'doc_no', 'doc_date',
            'partner_id', 'partner_name', 'partner_tin',
            'atc_code', 'atc_rate', 'tax_type',
            'income_payment', 'tax_withheld',
        )

    def test_rejects_unknown_side(self, db_session):
        with pytest.raises(ValueError, match='side'):
            wht_lines(date(2026, 1, 1), date(2026, 3, 31), side='both')

    def test_empty_db(self, db_session):
        assert wht_lines(date(2026, 1, 1), date(2026, 3, 31), 'payor') == []


class TestWhtLinesSources:
    def test_payor_includes_ap_lines(self, db_session, posted_ap_with_wht):
        rows = wht_lines(date(2026, 1, 1), date(2026, 3, 31), 'payor')
        assert [r.source for r in rows] == ['accounts_payable']

    def test_payor_includes_cdv_lines(self, db_session, posted_cdv_with_wht):
        """The hole in today's get_alphalist_of_payees(): AP only, misses CDV."""
        rows = wht_lines(date(2026, 1, 1), date(2026, 3, 31), 'payor')
        assert 'cash_disbursement' in {r.source for r in rows}

    def test_payee_includes_si_and_crv(self, db_session, posted_si_with_wht,
                                       posted_crv_with_wht):
        sources = {r.source for r in wht_lines(date(2026, 1, 1), date(2026, 3, 31), 'payee')}
        assert sources == {'sales_invoice', 'cash_receipt'}

    def test_lines_without_wt_id_excluded(self, db_session, posted_ap_v12sv):
        assert wht_lines(date(2026, 1, 1), date(2026, 3, 31), 'payor') == []

    def test_tax_type_filter_excludes_final(self, db_session, posted_ap_with_final_wht):
        assert wht_lines(date(2026, 1, 1), date(2026, 3, 31), 'payor',
                         tax_type='expanded') == []
        assert len(wht_lines(date(2026, 1, 1), date(2026, 3, 31), 'payor',
                             tax_type='final')) == 1

    def test_no_filter_returns_both_regimes(self, db_session, posted_ap_with_wht,
                                            posted_ap_with_final_wht):
        rows = wht_lines(date(2026, 1, 1), date(2026, 3, 31), 'payor')
        assert {r.tax_type for r in rows} == {'expanded', 'final'}

    def test_income_payment_is_net_of_vat(self, db_session, posted_ap_with_wht):
        row = wht_lines(date(2026, 1, 1), date(2026, 3, 31), 'payor')[0]
        item = posted_ap_with_wht.line_items[0]
        assert row.income_payment == item.amount - item.vat_amount


class TestWhtLinesExclusions:
    """Task 6's reviewer flagged that CRV/CDV voided-exclusion is only proven
    structurally, never by a test. Close the same gap for the withholding
    reader: a voided SI and a cancelled CDV must both be excluded."""

    def test_voided_si_excluded(self, db_session, voided_si_with_wht):
        assert wht_lines(date(2026, 1, 1), date(2026, 3, 31), 'payee') == []

    def test_cancelled_cdv_excluded(self, db_session, cancelled_cdv_with_wht):
        assert wht_lines(date(2026, 1, 1), date(2026, 3, 31), 'payor') == []
