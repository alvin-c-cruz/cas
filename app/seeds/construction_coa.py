"""Chart of Accounts for a Philippine construction contractor (VAT-registered + EWT).

Same 6-tuple shape as FIRM_COA (firm_coa.py): (code, name, account_type,
classification, normal_balance, parent_code). Rich FS taxonomy per
app/accounts/account_types.py; hierarchy derived (top-level or has-children = group).
Six magic codes kept at exact values: 10201, 10212, 20101, 20301, 30201, 30301.
Construction-specific: Construction-in-Progress, Costs/Billings in Excess (PoC),
Contract Retention receivable/payable, direct-cost breakdown under Cost of Construction.
"""

CONSTRUCTION_COA = [
    # ===== ASSETS - Current =====
    ('10100', 'Cash and Cash Equivalents',                     'Asset', 'Current', 'debit',  None),
    ('10101', 'Cash on Hand',                                  'Asset', 'Current', 'debit',  '10100'),
    ('10102', 'Petty Cash Fund',                               'Asset', 'Current', 'debit',  '10100'),
    ('10110', 'Cash in Bank - Current Account',                'Asset', 'Current', 'debit',  '10100'),
    ('10111', 'Cash in Bank - Savings Account',                'Asset', 'Current', 'debit',  '10100'),
    ('10200', 'Trade and Other Receivables',                   'Asset', 'Current', 'debit',  None),
    ('10201', 'Accounts Receivable - Trade',                   'Asset', 'Current', 'debit',  '10200'),   # MAGIC
    ('10202', 'Allowance for Doubtful Accounts',               'Asset', 'Current', 'credit', '10200'),   # contra
    ('10203', 'Contract Retention Receivable',                 'Asset', 'Current', 'debit',  '10200'),
    ('10204', 'Progress Billings Receivable',                  'Asset', 'Current', 'debit',  '10200'),
    ('10210', 'Advances to Suppliers',                         'Asset', 'Current', 'debit',  '10200'),
    ('10211', 'Advances to Subcontractors',                    'Asset', 'Current', 'debit',  '10200'),
    ('10212', 'Creditable Withholding Tax',                    'Asset', 'Current', 'debit',  '10200'),   # MAGIC
    ('10213', 'Inter-branch Due from',                         'Asset', 'Current', 'debit',  '10200'),
    ('10300', 'Construction in Progress',                      'Asset', 'Current', 'debit',  None),
    ('10301', 'Construction in Progress - Costs',              'Asset', 'Current', 'debit',  '10300'),
    ('10302', 'Costs and Estimated Earnings in Excess of Billings', 'Asset', 'Current', 'debit', '10300'),
    ('10350', 'Inventories',                                   'Asset', 'Current', 'debit',  None),
    ('10351', 'Construction Materials Inventory',              'Asset', 'Current', 'debit',  '10350'),
    ('10352', 'Construction Supplies',                         'Asset', 'Current', 'debit',  '10350'),
    ('10353', 'Fuel, Oil and Lubricants',                     'Asset', 'Current', 'debit',  '10350'),
    ('10400', 'Prepaid Expenses and Other Current Assets',     'Asset', 'Current', 'debit',  None),
    ('10401', 'Prepaid Rent',                                  'Asset', 'Current', 'debit',  '10400'),
    ('10402', 'Prepaid Insurance',                             'Asset', 'Current', 'debit',  '10400'),
    ('10403', 'Prepaid Taxes and Licenses',                    'Asset', 'Current', 'debit',  '10400'),
    ('10404', 'Other Current Assets',                          'Asset', 'Current', 'debit',  '10400'),
    ('10500', 'Input VAT',                                     'Asset', 'Current', 'debit',  None),
    ('10501', 'Input VAT - Capital Goods',                     'Asset', 'Current', 'debit',  '10500'),
    ('10502', 'Input VAT - Domestic Goods',                    'Asset', 'Current', 'debit',  '10500'),
    ('10503', 'Input VAT - Services',                          'Asset', 'Current', 'debit',  '10500'),
    ('10504', 'Input VAT - Importation',                       'Asset', 'Current', 'debit',  '10500'),
    ('10505', 'Deferred Input VAT',                            'Asset', 'Current', 'debit',  '10500'),
    ('10506', 'Creditable VAT Withheld',                       'Asset', 'Current', 'debit',  '10500'),
    ('10507', 'Excess Input Tax Carry-Over',                   'Asset', 'Current', 'debit',  '10500'),
    # ===== ASSETS - Non-Current =====
    ('11100', 'Property, Plant and Equipment',                 'Asset', 'Non-Current', 'debit',  None),
    ('11110', 'Land',                                          'Asset', 'Non-Current', 'debit',  '11100'),
    ('11120', 'Buildings and Improvements',                    'Asset', 'Non-Current', 'debit',  '11100'),
    ('11121', 'Accumulated Depreciation - Buildings and Improvements', 'Asset', 'Non-Current', 'credit', '11100'),  # contra
    ('11130', 'Construction Equipment and Machinery',          'Asset', 'Non-Current', 'debit',  '11100'),
    ('11131', 'Accumulated Depreciation - Construction Equipment', 'Asset', 'Non-Current', 'credit', '11100'),  # contra
    ('11140', 'Transportation Equipment',                      'Asset', 'Non-Current', 'debit',  '11100'),
    ('11141', 'Accumulated Depreciation - Transportation Equipment', 'Asset', 'Non-Current', 'credit', '11100'),  # contra
    ('11150', 'Office Furniture and Equipment',                'Asset', 'Non-Current', 'debit',  '11100'),
    ('11151', 'Accumulated Depreciation - Office Furniture and Equipment', 'Asset', 'Non-Current', 'credit', '11100'),  # contra
    ('11160', 'Tools and Small Equipment',                     'Asset', 'Non-Current', 'debit',  '11100'),
    ('11300', 'Other Non-Current Assets',                      'Asset', 'Non-Current', 'debit',  None),
    ('11301', 'Long-Term Deposits',                            'Asset', 'Non-Current', 'debit',  '11300'),
    ('11302', 'Investments',                                   'Asset', 'Non-Current', 'debit',  '11300'),
    # ===== LIABILITIES - Current =====
    ('20100', 'Trade and Other Payables',                      'Liability', 'Current', 'credit', None),
    ('20101', 'Accounts Payable - Trade',                      'Liability', 'Current', 'credit', '20100'),  # MAGIC
    ('20102', 'Subcontractors Payable',                        'Liability', 'Current', 'credit', '20100'),
    ('20103', 'Retention Payable',                             'Liability', 'Current', 'credit', '20100'),
    ('20104', 'Accrued Expenses',                              'Liability', 'Current', 'credit', '20100'),
    ('20111', 'Inter-branch Due to',                           'Liability', 'Current', 'credit', '20100'),
    ('20200', 'Output VAT',                                    'Liability', 'Current', 'credit', None),
    ('20201', 'Output VAT - Sales',                            'Liability', 'Current', 'credit', '20200'),
    ('20202', 'VAT Payable',                                   'Liability', 'Current', 'credit', '20200'),
    ('20300', 'Withholding and Other Taxes Payable',           'Liability', 'Current', 'credit', None),
    ('20301', 'Withholding Tax Payable - Expanded',            'Liability', 'Current', 'credit', '20300'),  # MAGIC
    ('20302', 'Withholding Tax Payable - Compensation',        'Liability', 'Current', 'credit', '20300'),
    ('20303', 'Income Tax Payable',                            'Liability', 'Current', 'credit', '20300'),
    ('20304', 'Percentage and Other Taxes Payable',            'Liability', 'Current', 'credit', '20300'),
    ('20400', 'Statutory Payables',                            'Liability', 'Current', 'credit', None),
    ('20401', 'SSS Contributions Payable',                     'Liability', 'Current', 'credit', '20400'),
    ('20402', 'PhilHealth Contributions Payable',              'Liability', 'Current', 'credit', '20400'),
    ('20403', 'Pag-IBIG Contributions Payable',                'Liability', 'Current', 'credit', '20400'),
    ('20500', 'Other Current Liabilities',                     'Liability', 'Current', 'credit', None),
    ('20501', 'Billings in Excess of Costs and Estimated Earnings', 'Liability', 'Current', 'credit', '20500'),
    ('20502', 'Customers Deposits and Mobilization Advances',  'Liability', 'Current', 'credit', '20500'),
    ('20503', 'Current Portion of Long-Term Debt',             'Liability', 'Current', 'credit', '20500'),
    # ===== LIABILITIES - Non-Current =====
    ('21100', 'Long-Term Liabilities',                         'Liability', 'Non-Current', 'credit', None),
    ('21101', 'Loans Payable',                                 'Liability', 'Non-Current', 'credit', '21100'),
    ('21102', 'Notes Payable',                                 'Liability', 'Non-Current', 'credit', '21100'),
    # ===== EQUITY =====
    ('30100', 'Stockholders Equity',                           'Equity', None, 'credit', None),
    ('30101', 'Capital Stock',                                 'Equity', None, 'credit', '30100'),
    ('30102', 'Additional Paid-in Capital',                    'Equity', None, 'credit', '30100'),
    ('30103', 'Dividends Declared',                            'Equity', None, 'debit',  '30100'),  # contra
    ('30200', 'Retained Earnings',                             'Equity', None, 'credit', None),
    ('30201', 'Retained Earnings - Unappropriated',            'Equity', None, 'credit', '30200'),  # MAGIC
    ('30202', 'Retained Earnings - Appropriated',              'Equity', None, 'credit', '30200'),
    ('30301', 'Current Year Earnings',                         'Equity', None, 'credit', None),      # MAGIC (top-level; close writes here)
    # ===== REVENUE =====
    ('40100', 'Contract Revenue',                              'Revenue', None, 'credit', None),
    ('40101', 'Construction Contract Revenue',                 'Revenue', None, 'credit', '40100'),
    ('40102', 'Change Order and Variation Revenue',            'Revenue', None, 'credit', '40100'),
    ('40103', 'Design and Engineering Services',               'Revenue', None, 'credit', '40100'),
    ('40300', 'Other Income',                                  'Other Income', None, 'credit', None),
    ('40301', 'Equipment Rental Income',                       'Other Income', None, 'credit', '40300'),
    ('40302', 'Scrap and Salvage Sales',                       'Other Income', None, 'credit', '40300'),
    ('40303', 'Interest Income',                               'Other Income', None, 'credit', '40300'),
    ('40304', 'Gain on Sale of Assets',                        'Other Income', None, 'credit', '40300'),
    ('40305', 'Miscellaneous Income',                          'Other Income', None, 'credit', '40300'),
    # ===== COST OF CONSTRUCTION (Cost of Goods Sold) =====
    ('50100', 'Cost of Construction',                          'Cost of Goods Sold', None, 'debit', None),
    ('50101', 'Direct Materials',                              'Cost of Goods Sold', None, 'debit', '50100'),
    ('50102', 'Direct Labor',                                  'Cost of Goods Sold', None, 'debit', '50100'),
    ('50103', 'Subcontractor Costs',                           'Cost of Goods Sold', None, 'debit', '50100'),
    ('50104', 'Equipment Costs and Rentals',                  'Cost of Goods Sold', None, 'debit', '50100'),
    ('50105', 'Fuel, Oil and Lubricants - Project',           'Cost of Goods Sold', None, 'debit', '50100'),
    ('50106', 'Depreciation - Construction Equipment',        'Cost of Goods Sold', None, 'debit', '50100'),
    ('50107', 'Project Overhead',                             'Cost of Goods Sold', None, 'debit', '50100'),
    ('50108', 'Permits, Bonds and Insurance - Project',       'Cost of Goods Sold', None, 'debit', '50100'),
    ('50109', 'Mobilization and Demobilization',              'Cost of Goods Sold', None, 'debit', '50100'),
    # ===== SELLING EXPENSE =====
    ('50210', 'Selling and Marketing Expenses',               'Selling Expense', None, 'debit', None),
    ('50211', 'Bidding and Proposal Costs',                   'Selling Expense', None, 'debit', '50210'),
    ('50212', 'Representation and Entertainment',             'Selling Expense', None, 'debit', '50210'),
    # ===== ADMINISTRATIVE EXPENSE =====
    ('50220', 'General and Administrative Expenses',          'Administrative Expense', None, 'debit', None),
    ('50221', 'Salaries and Wages - Administrative',          'Administrative Expense', None, 'debit', '50220'),
    ('50222', 'SSS, PhilHealth and Pag-IBIG - Employer Share','Administrative Expense', None, 'debit', '50220'),
    ('50223', '13th Month Pay and Other Benefits',            'Administrative Expense', None, 'debit', '50220'),
    ('50224', 'Rent Expense',                                 'Administrative Expense', None, 'debit', '50220'),
    ('50225', 'Utilities Expense',                            'Administrative Expense', None, 'debit', '50220'),
    ('50226', 'Communications and Internet Expense',          'Administrative Expense', None, 'debit', '50220'),
    ('50227', 'Office Supplies Expense',                      'Administrative Expense', None, 'debit', '50220'),
    ('50228', 'Depreciation - Office and Transportation',     'Administrative Expense', None, 'debit', '50220'),
    ('50229', 'Taxes and Licenses',                           'Administrative Expense', None, 'debit', '50220'),
    ('50230', 'Professional Fees',                            'Administrative Expense', None, 'debit', '50220'),
    ('50231', 'Transportation and Travel',                    'Administrative Expense', None, 'debit', '50220'),
    ('50232', 'Insurance Expense',                            'Administrative Expense', None, 'debit', '50220'),
    ('50233', 'Repairs and Maintenance',                      'Administrative Expense', None, 'debit', '50220'),
    ('50234', 'Miscellaneous Expense',                        'Administrative Expense', None, 'debit', '50220'),
    # ===== OTHER EXPENSE =====
    ('50300', 'Other Expenses',                               'Other Expense', None, 'debit', None),
    ('50301', 'Interest Expense',                             'Other Expense', None, 'debit', '50300'),
    ('50302', 'Bank Charges',                                 'Other Expense', None, 'debit', '50300'),
    ('50303', 'Loss on Disposal of Assets',                   'Other Expense', None, 'debit', '50300'),
    # ===== INCOME TAX EXPENSE =====
    ('50400', 'Income Tax Expense',                           'Income Tax Expense', None, 'debit', None),
    ('50401', 'Income Tax Expense - Current',                 'Income Tax Expense', None, 'debit', '50400'),
]
