"""SavorPack Food Manufacturing Corp. — contract food-manufacturer demo dataset.
Mirrors demo_seed.py (Zhiyuan) but with a food-manufacturing COA + full periodic
inventory (RM->WIP->FG->COGS) at the GL level. Reuses demo_seed's generic builders.
Span: Jan 2024 -> Jun 2026, single MAIN branch. NOT idempotent (refuses re-run).
"""
from decimal import Decimal
from app import db
from app.accounts.models import Account

# (code, name, account_type, classification, normal_balance, parent_code)
# classification is None for Equity/Revenue/expense; set for every Asset/Liability.
FOOD_COA = [
    # ---- preserve baseline parents + leaves (idempotent add) ----
    ('10100', 'Cash and Cash Equivalents', 'Asset', 'Current', 'debit', None),
    ('10101', 'Cash on Hand', 'Asset', 'Current', 'debit', '10100'),
    ('10110', 'Cash in Bank - Current Account', 'Asset', 'Current', 'debit', '10100'),
    ('10200', 'Trade and Other Receivables', 'Asset', 'Current', 'debit', None),
    ('10201', 'Accounts Receivable - Trade', 'Asset', 'Current', 'debit', '10200'),
    ('10212', 'Creditable Withholding Tax', 'Asset', 'Current', 'debit', '10200'),
    ('10500', 'Input VAT', 'Asset', 'Current', 'debit', None),
    ('10501', 'Input VAT - Capital Goods', 'Asset', 'Current', 'debit', '10500'),
    ('10502', 'Input VAT - Domestic Goods', 'Asset', 'Current', 'debit', '10500'),
    ('10503', 'Input VAT - Services', 'Asset', 'Current', 'debit', '10500'),
    ('10504', 'Input VAT - Importation', 'Asset', 'Current', 'debit', '10500'),
    ('20100', 'Trade and Other Payables', 'Liability', 'Current', 'credit', None),
    ('20101', 'Accounts Payable - Trade', 'Liability', 'Current', 'credit', '20100'),
    ('20200', 'Output VAT', 'Liability', 'Current', 'credit', None),
    ('20201', 'Output VAT - Sales', 'Liability', 'Current', 'credit', '20200'),
    ('20300', 'Withholding and Other Taxes Payable', 'Liability', 'Current', 'credit', None),
    ('20301', 'Withholding Tax Payable - Expanded', 'Liability', 'Current', 'credit', '20300'),
    ('30200', 'Retained Earnings', 'Equity', None, 'credit', None),
    ('30201', 'Retained Earnings - Unappropriated', 'Equity', None, 'credit', '30200'),
    ('30301', 'Current Year Earnings', 'Equity', None, 'credit', None),
    ('40100', 'Sales', 'Revenue', None, 'credit', None),
    ('40101', 'Sales - Goods', 'Revenue', None, 'credit', '40100'),
    ('40102', 'Sales - Services', 'Revenue', None, 'credit', '40100'),
    # ---- additions ----
    ('10300', 'Inventories', 'Asset', 'Current', 'debit', None),
    ('10301', 'Raw Materials Inventory', 'Asset', 'Current', 'debit', '10300'),
    ('10302', 'Work-in-Process Inventory', 'Asset', 'Current', 'debit', '10300'),
    ('10303', 'Finished Goods Inventory', 'Asset', 'Current', 'debit', '10300'),
    ('10304', 'Packaging Materials Inventory', 'Asset', 'Current', 'debit', '10300'),
    ('10400', 'Prepaid Expenses', 'Asset', 'Current', 'debit', None),
    ('10401', 'Prepaid Insurance', 'Asset', 'Current', 'debit', '10400'),
    ('10402', 'Prepaid Rent', 'Asset', 'Current', 'debit', '10400'),
    ('12000', 'Property, Plant and Equipment', 'Asset', 'Non-Current', 'debit', None),
    ('12010', 'Machinery and Packing Equipment', 'Asset', 'Non-Current', 'debit', '12000'),
    ('12011', 'Accumulated Depreciation - Machinery', 'Asset', 'Non-Current', 'credit', '12000'),
    ('12020', 'Building and Leasehold Improvements', 'Asset', 'Non-Current', 'debit', '12000'),
    ('12021', 'Accumulated Depreciation - Building', 'Asset', 'Non-Current', 'credit', '12000'),
    ('12030', 'Office and Furniture Equipment', 'Asset', 'Non-Current', 'debit', '12000'),
    ('12031', 'Accumulated Depreciation - Office Equipment', 'Asset', 'Non-Current', 'credit', '12000'),
    ('12040', 'Delivery Vehicles', 'Asset', 'Non-Current', 'debit', '12000'),
    ('12041', 'Accumulated Depreciation - Vehicles', 'Asset', 'Non-Current', 'credit', '12000'),
    ('20302', 'Withholding Tax Payable - Compensation', 'Liability', 'Current', 'credit', '20300'),
    ('20400', 'Accrued and Statutory Payables', 'Liability', 'Current', 'credit', None),
    ('20401', 'Accrued Salaries and Wages', 'Liability', 'Current', 'credit', '20400'),
    ('20402', 'SSS Premiums Payable', 'Liability', 'Current', 'credit', '20400'),
    ('20403', 'PhilHealth Contributions Payable', 'Liability', 'Current', 'credit', '20400'),
    ('20404', 'Pag-IBIG Contributions Payable', 'Liability', 'Current', 'credit', '20400'),
    ('20405', 'Accrued Utilities', 'Liability', 'Current', 'credit', '20400'),
    ('20406', 'Income Tax Payable', 'Liability', 'Current', 'credit', '20400'),
    ('25000', 'Loans Payable', 'Liability', 'Non-Current', 'credit', None),
    ('25001', 'Bank Loan Payable', 'Liability', 'Non-Current', 'credit', '25000'),
    ('30100', 'Share Capital', 'Equity', None, 'credit', None),
    ('30101', 'Paid-in Capital', 'Equity', None, 'credit', '30100'),
    ('40200', 'Other Income', 'Other Income', None, 'credit', None),
    ('40201', 'Scrap and By-product Sales', 'Other Income', None, 'credit', '40200'),
    ('40202', 'Interest Income', 'Other Income', None, 'credit', '40200'),
    ('50000', 'Cost of Sales', 'Cost of Goods Sold', None, 'debit', None),
    ('50001', 'Cost of Goods Sold', 'Cost of Goods Sold', None, 'debit', '50000'),
    ('60000', 'Administrative Expenses', 'Administrative Expense', None, 'debit', None),
    ('60101', 'Salaries and Wages - Administrative', 'Administrative Expense', None, 'debit', '60000'),
    ('60102', 'SSS/PhilHealth/Pag-IBIG - Employer Share', 'Administrative Expense', None, 'debit', '60000'),
    ('60103', 'Rent Expense', 'Administrative Expense', None, 'debit', '60000'),
    ('60104', 'Utilities Expense - Office', 'Administrative Expense', None, 'debit', '60000'),
    ('60105', 'Office Supplies', 'Administrative Expense', None, 'debit', '60000'),
    ('60106', 'Repairs and Maintenance', 'Administrative Expense', None, 'debit', '60000'),
    ('60107', 'Depreciation Expense - Administrative', 'Administrative Expense', None, 'debit', '60000'),
    ('60108', 'Professional Fees', 'Administrative Expense', None, 'debit', '60000'),
    ('60109', 'Taxes and Licenses', 'Administrative Expense', None, 'debit', '60000'),
    ('60110', 'Insurance Expense', 'Administrative Expense', None, 'debit', '60000'),
    ('60111', 'Communication Expense', 'Administrative Expense', None, 'debit', '60000'),
    ('61000', 'Selling and Distribution Expenses', 'Selling Expense', None, 'debit', None),
    ('61101', 'Delivery and Freight-out', 'Selling Expense', None, 'debit', '61000'),
    ('61102', 'Fuel and Oil', 'Selling Expense', None, 'debit', '61000'),
    ('61103', 'Advertising and Promotions', 'Selling Expense', None, 'debit', '61000'),
    ('61104', 'Depreciation Expense - Delivery Vehicles', 'Selling Expense', None, 'debit', '61000'),
    ('70000', 'Other Expenses', 'Other Expense', None, 'debit', None),
    ('70101', 'Interest Expense', 'Other Expense', None, 'debit', '70000'),
    ('70102', 'Bank Charges', 'Other Expense', None, 'debit', '70000'),
    ('80000', 'Income Tax Expense', 'Income Tax Expense', None, 'debit', None),
    ('80101', 'Income Tax Expense - Current', 'Income Tax Expense', None, 'debit', '80000'),
]


def seed_food_coa():
    """Two-pass COA build with classification + normal_balance. Idempotent (any-accounts guard)."""
    if Account.query.count() > 0:
        return 0
    by_code = {}
    for code, name, atype, classif, nb, _parent in FOOD_COA:
        acct = Account(code=code, name=name, account_type=atype,
                       classification=classif, normal_balance=nb, is_active=True)
        db.session.add(acct)
        by_code[code] = acct
    db.session.flush()
    for code, _n, _t, _c, _nb, parent in FOOD_COA:
        if parent:
            by_code[code].parent_id = by_code[parent].id
    db.session.commit()
    return len(FOOD_COA)
