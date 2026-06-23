"""Canonical Chart-of-Accounts type taxonomy and FS classification.

`account_type` is the single source of truth for financial-statement placement.
`classification` ('Current'/'Non-Current') refines Asset/Liability for the Balance Sheet.
`BASE_CATEGORY` maps each rich type back to one of the five legacy base categories so
normal-balance defaults and any residual base-type logic keep working.
"""

BS_TYPES = ['Asset', 'Liability', 'Equity']
IS_TYPES = ['Revenue', 'Contra-Revenue', 'Cost of Goods Sold',
            'Selling Expense', 'Administrative Expense',
            'Other Income', 'Other Expense', 'Income Tax Expense']
ACCOUNT_TYPES = BS_TYPES + IS_TYPES

CLASSIFICATIONS = ['Current', 'Non-Current']
TYPES_NEEDING_CLASSIFICATION = ('Asset', 'Liability')

BASE_CATEGORY = {
    'Asset': 'Asset', 'Liability': 'Liability', 'Equity': 'Equity',
    'Revenue': 'Revenue', 'Contra-Revenue': 'Revenue',
    'Cost of Goods Sold': 'Expense', 'Selling Expense': 'Expense',
    'Administrative Expense': 'Expense', 'Other Income': 'Revenue',
    'Other Expense': 'Expense', 'Income Tax Expense': 'Expense',
}

DEFAULT_NORMAL_BALANCE = {
    'Asset': 'debit', 'Liability': 'credit', 'Equity': 'credit',
    'Revenue': 'credit', 'Contra-Revenue': 'debit',
    'Cost of Goods Sold': 'debit', 'Selling Expense': 'debit',
    'Administrative Expense': 'debit', 'Other Income': 'credit',
    'Other Expense': 'debit', 'Income Tax Expense': 'debit',
}
