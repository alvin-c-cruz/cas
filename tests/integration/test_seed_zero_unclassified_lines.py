"""Proves Part B of Task 8: a freshly seeded demo DB has zero unclassified
VAT-bearing lines. demo_seed builds all four VAT-bearing line types (AP, SI,
CRV revenue, CDV expense), so it gives the richest single-seeder coverage.
"""
from app.seeds.demo_seed import run_seed_demo
from app.accounts_payable.models import AccountsPayableItem
from app.sales_invoices.models import SalesInvoiceItem
from app.cash_receipts.models import CRVRevenueLine
from app.cash_disbursements.models import CDVExpenseLine


def test_demo_seed_leaves_zero_unclassified_vat_lines(db_session):
    run_seed_demo(reset=False)

    for model in (AccountsPayableItem, SalesInvoiceItem, CRVRevenueLine, CDVExpenseLine):
        lines = model.query.filter(model.vat_category.isnot(None)).all()
        assert lines, f'{model.__name__}: no VAT-bearing lines seeded to check'
        unclassified = [l.id for l in lines if not l.vat_nature]
        assert not unclassified, \
            f'{model.__name__}: lines with a vat_category but NULL vat_nature: {unclassified}'
