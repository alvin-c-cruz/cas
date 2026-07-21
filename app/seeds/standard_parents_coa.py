"""Standard 27-account top-level Chart of Accounts scaffold, seeded once at
first-run UI bootstrap (see app/users/views.py::register). Every row is a
top-level parent account (parent_code=None) -- under CAS's derived-hierarchy
rule (top-level or has-children -> non-postable header), none of these are
postable on their own; they exist to give a brand-new instance a sensible
top-level structure to build its real, postable Chart of Accounts under.

Same 6-tuple shape as firm_coa.py/BASELINE_COA so _seed_accounts() can seed
this list unchanged: (code, name, account_type, classification,
normal_balance, parent_code).
"""

STANDARD_PARENT_ACCOUNTS = [
    # (code, name, account_type, classification, normal_balance, parent_code)
    ('111000', 'Cash & Cash Equivalents', 'Asset', 'Current', 'debit', None),
    ('112000', 'Trade Receivables', 'Asset', 'Current', 'debit', None),
    ('113000', 'Non-Trade Receivables', 'Asset', 'Current', 'debit', None),
    ('114000', 'Inventory', 'Asset', 'Current', 'debit', None),
    ('115000', 'Supplies Inventory', 'Asset', 'Current', 'debit', None),
    ('116000', 'Prepaid Expenses', 'Asset', 'Current', 'debit', None),
    ('117000', 'Prepaid Taxes', 'Asset', 'Current', 'debit', None),
    ('119000', 'Other Current Assets', 'Asset', 'Current', 'debit', None),
    ('121000', 'Property, Plant & Equipment', 'Asset', 'Non-Current', 'debit', None),
    ('122000', 'Accumulated Depreciation', 'Asset', 'Non-Current', 'credit', None),
    ('129000', 'Other Assets', 'Asset', 'Non-Current', 'debit', None),
    ('211000', 'Accounts Payable', 'Liability', 'Current', 'credit', None),
    ('212000', 'Statutory Payables', 'Liability', 'Current', 'credit', None),
    ('213000', 'Tax & Withholding Payables', 'Liability', 'Current', 'credit', None),
    ('219000', 'Other Current Liabilities', 'Liability', 'Current', 'credit', None),
    ('229000', 'Non Current Liabilities', 'Liability', 'Non-Current', 'credit', None),
    ("311000", "Stockholders' Equity", 'Equity', None, 'credit', None),
    ('411000', 'Sales', 'Revenue', None, 'credit', None),
    ('511000', 'Other Income & Gains', 'Other Income', None, 'credit', None),
    ('611000', 'Cost of Sales', 'Cost of Goods Sold', None, 'debit', None),
    ('621000', 'Direct Material', 'Cost of Goods Sold', None, 'debit', None),
    ('631000', 'Direct Labor', 'Cost of Goods Sold', None, 'debit', None),
    ('641000', 'Indirect Labor', 'Cost of Goods Sold', None, 'debit', None),
    ('651000', 'Manufacturing Overhead', 'Cost of Goods Sold', None, 'debit', None),
    ('711000', 'Selling Expenses', 'Selling Expense', None, 'debit', None),
    ('721000', 'Administrative Expenses', 'Administrative Expense', None, 'debit', None),
    ('811000', 'Other Expenses & Losses', 'Other Expense', None, 'debit', None),
]
