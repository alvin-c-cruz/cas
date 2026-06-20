"""
Integration tests for sales VAT category seed and WT sales_name backfill.
"""
from app.fixtures import load_default_sales_vat_categories, load_default_withholding_tax
from app.sales_vat_categories.models import SalesVATCategory
from app.withholding_tax.models import WithholdingTax
from app.accounts.models import Account
import app.seeds.seed_data as seed_data


def test_seed_sales_vat_categories(db_session):
    # output account 2100 must exist for rated rows
    db_session.add(Account(code='2100', name='Output Tax', account_type='Liability',
                           classification='Current', normal_balance='credit', is_active=True))
    db_session.commit()
    load_default_sales_vat_categories()
    codes = {c.code for c in SalesVATCategory.query.all()}
    assert {'V12', 'V0', 'VEX'} <= codes
    vatable = SalesVATCategory.query.filter_by(code='V12').first()
    assert vatable.transaction_nature == 'regular'
    assert vatable.output_vat_account.code == '2100'
    exempt = SalesVATCategory.query.filter_by(code='VEX').first()
    assert exempt.output_vat_account_id is None


def test_seed_all_sales_vat_links_to_output_vat_sales(db_session):
    """
    seed_sales_vat_categories() (used by seed_all) must link rated rows to
    account 20201 'Output VAT - Sales', NOT 20401 'Income Tax Payable'.
    """
    seed_data.seed_chart_of_accounts()  # builds the full COA including 20201 and 20401
    seed_data.seed_sales_vat_categories()

    # Rated row must resolve to account 20201 (Output VAT - Sales)
    v12 = SalesVATCategory.query.filter_by(code='V12').first()
    assert v12 is not None, "V12 row not created"
    assert v12.output_vat_account is not None, "V12 has no output_vat_account"
    assert v12.output_vat_account.code == '20201', (
        f"Expected 20201 but got {v12.output_vat_account.code} "
        f"({v12.output_vat_account.name!r}) — wrong account linked"
    )
    assert 'Output VAT' in v12.output_vat_account.name, (
        f"Account name does not contain 'Output VAT': {v12.output_vat_account.name!r}"
    )

    # Zero-rate/exempt row must have no output account
    vex = SalesVATCategory.query.filter_by(code='VEX').first()
    assert vex is not None, "VEX row not created"
    assert vex.output_vat_account_id is None, "VEX should have no output_vat_account"


def test_seed_wht_sales_name_backfill(db_session):
    db_session.add(WithholdingTax(code='WC010', name='Professional Fees - Individuals',
                                  rate=10, is_active=True))
    db_session.commit()
    load_default_withholding_tax()  # idempotent; must backfill missing sales_name
    wt = WithholdingTax.query.filter_by(code='WC010').first()
    assert wt.sales_name == 'Professional Fees Income - Individual'
