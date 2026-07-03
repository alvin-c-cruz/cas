# tests/integration/test_food_demo.py
from decimal import Decimal
import pytest


def test_seed_food_coa_builds_typed_classified_accounts(db_session):
    from app.seeds.food_demo import seed_food_coa
    from app.accounts.models import Account
    n = seed_food_coa()
    assert n >= 70
    codes = {a.code: a for a in Account.query.all()}
    # New manufacturing accounts exist with the right rich types + classification.
    assert codes['10301'].account_type == 'Asset' and codes['10301'].classification == 'Current'   # Raw Materials
    assert codes['12010'].account_type == 'Asset' and codes['12010'].classification == 'Non-Current' # Machinery
    assert codes['12011'].normal_balance == 'credit'   # Accum Depr (contra-asset)
    assert 'Accumulated Depreciation' in codes['12011'].name
    assert codes['50001'].account_type == 'Cost of Goods Sold'
    assert codes['60101'].account_type == 'Administrative Expense'
    assert codes['61101'].account_type == 'Selling Expense'
    assert codes['70101'].account_type == 'Other Expense'
    assert codes['80101'].account_type == 'Income Tax Expense'
    assert codes['40201'].account_type == 'Other Income'
    # Existing baseline parents preserved.
    assert codes['10100'].name == 'Cash and Cash Equivalents'
    # Year-end close needs these.
    assert '30201' in codes and '30301' in codes


def test_seed_food_baseline(db_session):
    from app.seeds.food_demo import seed_food_baseline
    from app.settings import AppSettings
    from app.vat_categories.models import VATCategory
    from app.sales_vat_categories.models import SalesVATCategory
    from app.withholding_tax.models import WithholdingTax
    from app.periods.models import AccountingPeriod
    refs0 = seed_food_baseline()
    assert refs0['admin'].username == 'admin'
    assert refs0['branch'].code == 'MAIN'
    assert AppSettings.get_setting('company_name') == 'SavorPack Food Manufacturing Corp.'
    assert VATCategory.query.count() >= 4
    assert SalesVATCategory.query.filter_by(code='V12').first() is not None
    assert WithholdingTax.query.count() >= 3
    # Periods span Jan 2024 -> Jun 2026 (30 months).
    assert AccountingPeriod.query.count() >= 30
    assert AccountingPeriod.query.filter_by(year=2024, month=1).first() is not None
    assert AccountingPeriod.query.filter_by(year=2026, month=6).first() is not None
