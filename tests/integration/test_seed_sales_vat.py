"""
Integration tests for sales VAT category seed and WT sales_name backfill.
"""
from app.fixtures import load_default_sales_vat_categories, load_default_withholding_tax
from app.sales_vat_categories.models import SalesVATCategory
from app.withholding_tax.models import WithholdingTax
from app.accounts.models import Account


def test_seed_sales_vat_categories(db_session):
    # output account 2100 must exist for rated rows
    db_session.add(Account(code='2100', name='Output Tax', account_type='Liability',
                           classification='Current', normal_balance='credit', is_active=True))
    db_session.commit()
    load_default_sales_vat_categories()
    codes = {c.code for c in SalesVATCategory.query.all()}
    assert {'SVAT-G', 'SVAT-S', 'SVAT-EX', 'SVAT-ZR', 'SVAT-GOV'} <= codes
    goods = SalesVATCategory.query.filter_by(code='SVAT-G').first()
    assert goods.transaction_nature == 'regular'
    assert goods.output_vat_account.code == '2100'
    exempt = SalesVATCategory.query.filter_by(code='SVAT-EX').first()
    assert exempt.output_vat_account_id is None


def test_seed_wht_sales_name_backfill(db_session):
    db_session.add(WithholdingTax(code='WC010', name='Professional Fees - Individuals',
                                  rate=10, is_active=True))
    db_session.commit()
    load_default_withholding_tax()  # idempotent; must backfill missing sales_name
    wt = WithholdingTax.query.filter_by(code='WC010').first()
    assert wt.sales_name == 'Professional Fees Income - Individual'
