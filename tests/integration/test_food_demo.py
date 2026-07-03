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
