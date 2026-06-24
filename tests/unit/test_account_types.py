import pytest
from app.accounts.account_types import (
    ACCOUNT_TYPES, BS_TYPES, IS_TYPES, CLASSIFICATIONS,
    TYPES_NEEDING_CLASSIFICATION, BASE_CATEGORY, DEFAULT_NORMAL_BALANCE)
from app.accounts.models import Account

pytestmark = [pytest.mark.unit]

def test_taxonomy_shape():
    assert BS_TYPES == ['Asset', 'Liability', 'Equity']
    assert IS_TYPES == ['Revenue', 'Contra-Revenue', 'Cost of Goods Sold',
                        'Selling Expense', 'Administrative Expense',
                        'Other Income', 'Other Expense', 'Income Tax Expense']
    assert ACCOUNT_TYPES == BS_TYPES + IS_TYPES
    assert CLASSIFICATIONS == ['Current', 'Non-Current']
    assert TYPES_NEEDING_CLASSIFICATION == ('Asset', 'Liability')

def test_every_type_maps_to_base_and_normal_balance():
    for t in ACCOUNT_TYPES:
        assert BASE_CATEGORY[t] in ('Asset', 'Liability', 'Equity', 'Revenue', 'Expense')
        assert DEFAULT_NORMAL_BALANCE[t] in ('debit', 'credit')

def test_base_category_examples():
    assert BASE_CATEGORY['Contra-Revenue'] == 'Revenue'
    assert BASE_CATEGORY['Cost of Goods Sold'] == 'Expense'
    assert BASE_CATEGORY['Other Income'] == 'Revenue'
    assert BASE_CATEGORY['Income Tax Expense'] == 'Expense'

def test_account_base_category_property():
    # base_category is a pure-Python property on an unsaved object — no DB needed.
    assert Account(code='1', name='x', account_type='Cost of Goods Sold',
                   normal_balance='debit').base_category == 'Expense'
    assert Account(code='2', name='y', account_type='Other Income',
                   normal_balance='credit').base_category == 'Revenue'
