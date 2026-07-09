from app.sales_invoices.models import SalesInvoiceItem
from app.accounts_payable.models import AccountsPayableItem
from app.cash_receipts.models import CRVRevenueLine
from app.cash_disbursements.models import CDVExpenseLine


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
