import pytest
from datetime import date

from app.sales_invoices.models import SalesInvoiceItem
from app.accounts_payable.models import AccountsPayableItem
from app.cash_receipts.models import CRVRevenueLine
from app.cash_disbursements.models import CDVExpenseLine
from app.reports.vat_lines import (
    vat_lines, VatLine, UNCLASSIFIED,
    SALES_BUCKET_BY_NATURE, PURCHASE_BUCKET_BY_NATURE,
)


class TestVatNatureColumn:
    def test_all_four_line_models_have_vat_nature(self):
        for model in (SalesInvoiceItem, AccountsPayableItem,
                      CRVRevenueLine, CDVExpenseLine):
            assert hasattr(model, 'vat_nature'), model.__name__

    def test_vat_nature_is_nullable(self):
        for model in (SalesInvoiceItem, AccountsPayableItem,
                      CRVRevenueLine, CDVExpenseLine):
            col = model.__table__.c['vat_nature']
            assert col.nullable is True, model.__name__
            assert col.type.length == 24, model.__name__

    def test_vat_nature_is_indexed(self):
        for model in (SalesInvoiceItem, AccountsPayableItem,
                      CRVRevenueLine, CDVExpenseLine):
            col = model.__table__.c['vat_nature']
            assert col.index is True, model.__name__


def row_amount_of(doc):
    """Return the single line's VAT-inclusive `amount` for a posted_* fixture
    that builds exactly one document with exactly one line."""
    if hasattr(doc, 'line_items'):
        return doc.line_items[0].amount
    if hasattr(doc, 'revenue_lines'):
        return doc.revenue_lines[0].amount
    if hasattr(doc, 'expense_lines'):
        return doc.expense_lines[0].amount
    raise TypeError(f'row_amount_of: unsupported document type {type(doc)!r}')


class TestBucketMaps:
    def test_sales_buckets(self):
        assert SALES_BUCKET_BY_NATURE == {
            'regular': 'vatable',
            'zero_export': 'zero_rated',
            'zero_other': 'zero_rated',
            'exempt': 'exempt',
            'government': 'government',
            UNCLASSIFIED: UNCLASSIFIED,
        }

    def test_purchase_buckets_cover_all_eight_natures(self):
        from app.vat_categories.models import PURCHASE_NATURES
        for n in PURCHASE_NATURES:
            assert n in PURCHASE_BUCKET_BY_NATURE, n
        assert PURCHASE_BUCKET_BY_NATURE[UNCLASSIFIED] == UNCLASSIFIED


class TestVatLinesContract:
    def test_rejects_unknown_side(self, db_session):
        with pytest.raises(ValueError, match='side'):
            vat_lines(date(2026, 1, 1), date(2026, 3, 31), side='sideways')

    def test_empty_db_returns_empty_list(self, db_session):
        assert vat_lines(date(2026, 1, 1), date(2026, 3, 31), 'sales') == []
        assert vat_lines(date(2026, 1, 1), date(2026, 3, 31), 'purchases') == []

    def test_returns_vatline_namedtuples(self, db_session):
        assert VatLine._fields == (
            'side', 'source', 'doc_id', 'doc_no', 'doc_date',
            'partner_id', 'partner_name', 'partner_tin',
            'nature', 'base', 'vat_amount',
        )


class TestVatLinesSources:
    """The whole point of this module: all four tables contribute."""

    def test_sales_includes_sales_invoice_lines(self, db_session, posted_si_v12):
        rows = vat_lines(date(2026, 1, 1), date(2026, 3, 31), 'sales')
        assert [r.source for r in rows] == ['sales_invoice']
        assert rows[0].nature == 'regular'

    def test_sales_includes_crv_revenue_lines(self, db_session, posted_crv_v12):
        rows = vat_lines(date(2026, 1, 1), date(2026, 3, 31), 'sales')
        assert 'cash_receipt' in {r.source for r in rows}

    def test_purchases_includes_ap_lines(self, db_session, posted_ap_v12sv):
        rows = vat_lines(date(2026, 1, 1), date(2026, 3, 31), 'purchases')
        assert [r.source for r in rows] == ['accounts_payable']
        assert rows[0].nature == 'domestic_services'

    def test_purchases_includes_cdv_expense_lines(self, db_session, posted_cdv_v12sv):
        rows = vat_lines(date(2026, 1, 1), date(2026, 3, 31), 'purchases')
        assert 'cash_disbursement' in {r.source for r in rows}

    def test_draft_documents_excluded(self, db_session, draft_si_v12):
        assert vat_lines(date(2026, 1, 1), date(2026, 3, 31), 'sales') == []

    def test_voided_documents_excluded(self, db_session, voided_si_v12):
        """A `!= 'draft'` predicate would wrongly sweep in voided documents --
        instance/cas.db has a real voided SI, so this is exercised by live data."""
        assert vat_lines(date(2026, 1, 1), date(2026, 3, 31), 'sales') == []

    def test_null_nature_becomes_unclassified_not_regular(self, db_session, posted_si_no_category):
        rows = vat_lines(date(2026, 1, 1), date(2026, 3, 31), 'sales')
        assert rows[0].nature == UNCLASSIFIED

    def test_base_is_amount_minus_vat(self, db_session, posted_si_v12):
        row = vat_lines(date(2026, 1, 1), date(2026, 3, 31), 'sales')[0]
        assert row.base == row_amount_of(posted_si_v12) - row.vat_amount

    def test_branch_filter_scopes_results(self, db_session, posted_si_v12, branch_manila):
        assert vat_lines(date(2026, 1, 1), date(2026, 3, 31), 'sales',
                         branch_id=branch_manila.id) == []

    def test_date_range_is_inclusive_on_both_ends(self, db_session, posted_si_on_mar_31):
        assert len(vat_lines(date(2026, 1, 1), date(2026, 3, 31), 'sales')) == 1
        assert vat_lines(date(2026, 1, 1), date(2026, 3, 30), 'sales') == []
