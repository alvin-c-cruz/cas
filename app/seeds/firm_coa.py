"""Chart of Accounts for a combined accounting firm + software company (PH, VAT-registered).

Same 6-tuple shape as BASELINE_COA (seed_data.py) so _seed_accounts() can seed either:
    (code, name, account_type, classification, normal_balance, parent_code)

account_type carries the FS taxonomy (app/accounts/account_types.py); hierarchy is DERIVED
(top-level or has-children = non-postable group; else postable leaf) -- no stored is_header.
Contra accounts (Accumulated Depreciation/Amortization, Allowance, Drawings) carry the
opposite normal_balance. Six magic codes required by the posting engine are kept at their
exact values: 10201, 10212, 20101, 20301, 30201, 30301.
"""

FIRM_COA = [
    # ===== ASSETS - Current =====
    ('10100', 'Cash and Cash Equivalents',                  'Asset', 'Current', 'debit',  None),
    ('10101', 'Cash on Hand',                               'Asset', 'Current', 'debit',  '10100'),
    ('10102', 'Petty Cash Fund',                            'Asset', 'Current', 'debit',  '10100'),
    ('10110', 'Cash in Bank - Current Account',             'Asset', 'Current', 'debit',  '10100'),
    ('10111', 'Cash in Bank - Savings Account',             'Asset', 'Current', 'debit',  '10100'),
    ('10200', 'Trade and Other Receivables',                'Asset', 'Current', 'debit',  None),
    ('10201', 'Accounts Receivable - Trade',                'Asset', 'Current', 'debit',  '10200'),   # MAGIC
    ('10202', 'Allowance for Doubtful Accounts',            'Asset', 'Current', 'credit', '10200'),   # contra
    ('10210', 'Advances to Employees',                      'Asset', 'Current', 'debit',  '10200'),
    ('10211', 'Advances to Officers',                       'Asset', 'Current', 'debit',  '10200'),
    ('10212', 'Creditable Withholding Tax',                 'Asset', 'Current', 'debit',  '10200'),   # MAGIC
    ('10213', 'Inter-branch Due from',                      'Asset', 'Current', 'debit',  '10200'),
    ('10400', 'Prepaid Expenses and Other Current Assets',  'Asset', 'Current', 'debit',  None),
    ('10401', 'Prepaid Rent',                               'Asset', 'Current', 'debit',  '10400'),
    ('10402', 'Prepaid Insurance',                          'Asset', 'Current', 'debit',  '10400'),
    ('10403', 'Prepaid Software Subscriptions',             'Asset', 'Current', 'debit',  '10400'),
    ('10404', 'Other Current Assets',                       'Asset', 'Current', 'debit',  '10400'),
    ('10500', 'Input VAT',                                  'Asset', 'Current', 'debit',  None),
    ('10501', 'Input VAT - Capital Goods',                  'Asset', 'Current', 'debit',  '10500'),
    ('10502', 'Input VAT - Domestic Goods',                 'Asset', 'Current', 'debit',  '10500'),
    ('10503', 'Input VAT - Services',                       'Asset', 'Current', 'debit',  '10500'),
    ('10504', 'Input VAT - Importation',                    'Asset', 'Current', 'debit',  '10500'),
    ('10505', 'Excess Input Tax Carry-Over',                'Asset', 'Current', 'debit',  '10500'),
    # ===== ASSETS - Non-Current =====
    ('11100', 'Property and Equipment',                            'Asset', 'Non-Current', 'debit',  None),
    ('11110', 'Office Equipment',                                  'Asset', 'Non-Current', 'debit',  '11100'),
    ('11111', 'Accumulated Depreciation - Office Equipment',       'Asset', 'Non-Current', 'credit', '11100'),  # contra
    ('11120', 'Computer Equipment',                               'Asset', 'Non-Current', 'debit',  '11100'),
    ('11121', 'Accumulated Depreciation - Computer Equipment',    'Asset', 'Non-Current', 'credit', '11100'),  # contra
    ('11130', 'Furniture and Fixtures',                          'Asset', 'Non-Current', 'debit',  '11100'),
    ('11131', 'Accumulated Depreciation - Furniture and Fixtures','Asset', 'Non-Current', 'credit', '11100'),  # contra
    ('11140', 'Leasehold Improvements',                          'Asset', 'Non-Current', 'debit',  '11100'),
    ('11141', 'Accumulated Depreciation - Leasehold Improvements','Asset', 'Non-Current', 'credit', '11100'),  # contra
    ('11200', 'Intangible Assets',                                'Asset', 'Non-Current', 'debit',  None),
    ('11201', 'Capitalized Software Development Costs',           'Asset', 'Non-Current', 'debit',  '11200'),
    ('11202', 'Accumulated Amortization - Software Development Costs', 'Asset', 'Non-Current', 'credit', '11200'),  # contra
    ('11203', 'Software and Licenses',                           'Asset', 'Non-Current', 'debit',  '11200'),
    ('11204', 'Accumulated Amortization - Software and Licenses','Asset', 'Non-Current', 'credit', '11200'),  # contra
    ('11300', 'Other Non-Current Assets',                        'Asset', 'Non-Current', 'debit',  None),
    ('11301', 'Security Deposits',                               'Asset', 'Non-Current', 'debit',  '11300'),
    # ===== LIABILITIES - Current =====
    ('20100', 'Trade and Other Payables',                  'Liability', 'Current', 'credit', None),
    ('20101', 'Accounts Payable - Trade',                  'Liability', 'Current', 'credit', '20100'),  # MAGIC
    ('20102', 'Accounts Payable - Others',                 'Liability', 'Current', 'credit', '20100'),
    ('20103', 'Accrued Expenses',                          'Liability', 'Current', 'credit', '20100'),
    ('20104', 'Accrued Salaries and Wages',               'Liability', 'Current', 'credit', '20100'),
    ('20111', 'Inter-branch Due to',                      'Liability', 'Current', 'credit', '20100'),
    ('20200', 'Output VAT',                                'Liability', 'Current', 'credit', None),
    ('20201', 'Output VAT - Sales',                        'Liability', 'Current', 'credit', '20200'),
    ('20202', 'VAT Payable',                               'Liability', 'Current', 'credit', '20200'),
    ('20300', 'Withholding and Other Taxes Payable',       'Liability', 'Current', 'credit', None),
    ('20301', 'Withholding Tax Payable - Expanded',        'Liability', 'Current', 'credit', '20300'),  # MAGIC
    ('20302', 'Withholding Tax Payable - Compensation',    'Liability', 'Current', 'credit', '20300'),
    ('20303', 'Income Tax Payable',                        'Liability', 'Current', 'credit', '20300'),
    ('20400', 'Statutory Payables',                        'Liability', 'Current', 'credit', None),
    ('20401', 'SSS Contributions Payable',                 'Liability', 'Current', 'credit', '20400'),
    ('20402', 'PhilHealth Contributions Payable',          'Liability', 'Current', 'credit', '20400'),
    ('20403', 'Pag-IBIG Contributions Payable',            'Liability', 'Current', 'credit', '20400'),
    ('20500', 'Unearned and Deferred Revenue',             'Liability', 'Current', 'credit', None),
    ('20501', 'Unearned Subscription Revenue',             'Liability', 'Current', 'credit', '20500'),
    ('20502', 'Unearned Service Revenue',                  'Liability', 'Current', 'credit', '20500'),
    # ===== LIABILITIES - Non-Current =====
    ('21100', 'Long-Term Liabilities',                     'Liability', 'Non-Current', 'credit', None),
    ('21101', 'Loans Payable',                             'Liability', 'Non-Current', 'credit', '21100'),
    ('21102', 'Lease Liability',                           'Liability', 'Non-Current', 'credit', '21100'),
    # ===== EQUITY =====
    ('30100', "Owners' Equity",                            'Equity', None, 'credit', None),
    ('30101', "Owners' Capital",                           'Equity', None, 'credit', '30100'),
    ('30102', "Owners' Drawings",                          'Equity', None, 'debit',  '30100'),  # contra
    ('30200', 'Retained Earnings',                         'Equity', None, 'credit', None),
    ('30201', 'Retained Earnings - Unappropriated',        'Equity', None, 'credit', '30200'),  # MAGIC
    ('30301', 'Current Year Earnings',                     'Equity', None, 'credit', None),      # MAGIC (top-level; close writes here)
    # ===== REVENUE =====
    ('40100', 'Accounting Services Revenue',               'Revenue', None, 'credit', None),
    ('40101', 'Bookkeeping Fees',                          'Revenue', None, 'credit', '40100'),
    ('40102', 'Audit and Assurance Fees',                  'Revenue', None, 'credit', '40100'),
    ('40103', 'Tax Compliance Fees',                       'Revenue', None, 'credit', '40100'),
    ('40104', 'Advisory and Consulting Fees',              'Revenue', None, 'credit', '40100'),
    ('40200', 'Software Revenue',                          'Revenue', None, 'credit', None),
    ('40201', 'Subscription (SaaS) Revenue',               'Revenue', None, 'credit', '40200'),
    ('40202', 'Software License Revenue',                  'Revenue', None, 'credit', '40200'),
    ('40203', 'Custom Development Revenue',                'Revenue', None, 'credit', '40200'),
    ('40204', 'Support and Maintenance Revenue',           'Revenue', None, 'credit', '40200'),
    ('40205', 'Implementation and Setup Revenue',          'Revenue', None, 'credit', '40200'),
    ('40300', 'Other Income',                              'Other Income', None, 'credit', None),
    ('40301', 'Interest Income',                           'Other Income', None, 'credit', '40300'),
    ('40302', 'Miscellaneous Income',                      'Other Income', None, 'credit', '40300'),
    # ===== COST OF SERVICES (Cost of Goods Sold) =====
    ('50100', 'Cost of Accounting Services',              'Cost of Goods Sold', None, 'debit', None),
    ('50101', 'Salaries - Professional Staff',            'Cost of Goods Sold', None, 'debit', '50100'),
    ('50102', 'Direct Engagement Costs',                  'Cost of Goods Sold', None, 'debit', '50100'),
    ('50150', 'Cost of Software Services',                'Cost of Goods Sold', None, 'debit', None),
    ('50151', 'Salaries - Developers',                    'Cost of Goods Sold', None, 'debit', '50150'),
    ('50152', 'Cloud Hosting and Infrastructure',        'Cost of Goods Sold', None, 'debit', '50150'),
    ('50153', 'Third-Party Software and API Costs',      'Cost of Goods Sold', None, 'debit', '50150'),
    ('50154', 'Amortization - Capitalized Software Development', 'Cost of Goods Sold', None, 'debit', '50150'),
    # ===== SELLING EXPENSE =====
    ('50210', 'Selling and Marketing Expenses',          'Selling Expense', None, 'debit', None),
    ('50211', 'Advertising and Marketing',               'Selling Expense', None, 'debit', '50210'),
    ('50212', 'Representation and Entertainment',        'Selling Expense', None, 'debit', '50210'),
    ('50213', 'Sales Commissions',                       'Selling Expense', None, 'debit', '50210'),
    # ===== ADMINISTRATIVE EXPENSE =====
    ('50220', 'General and Administrative Expenses',     'Administrative Expense', None, 'debit', None),
    ('50221', 'Salaries and Wages - Administrative',     'Administrative Expense', None, 'debit', '50220'),
    ('50222', 'SSS, PhilHealth and Pag-IBIG - Employer Share', 'Administrative Expense', None, 'debit', '50220'),
    ('50223', '13th Month Pay and Other Benefits',       'Administrative Expense', None, 'debit', '50220'),
    ('50224', 'Rent Expense',                            'Administrative Expense', None, 'debit', '50220'),
    ('50225', 'Utilities Expense',                       'Administrative Expense', None, 'debit', '50220'),
    ('50226', 'Communications and Internet Expense',     'Administrative Expense', None, 'debit', '50220'),
    ('50227', 'Office Supplies Expense',                 'Administrative Expense', None, 'debit', '50220'),
    ('50228', 'Software Subscriptions - Internal Tools', 'Administrative Expense', None, 'debit', '50220'),
    ('50229', 'Depreciation Expense',                    'Administrative Expense', None, 'debit', '50220'),
    ('50230', 'Amortization Expense',                    'Administrative Expense', None, 'debit', '50220'),
    ('50231', 'Insurance Expense',                       'Administrative Expense', None, 'debit', '50220'),
    ('50232', 'Taxes and Licenses',                      'Administrative Expense', None, 'debit', '50220'),
    ('50233', 'Professional Fees',                       'Administrative Expense', None, 'debit', '50220'),
    ('50234', 'Transportation and Travel',               'Administrative Expense', None, 'debit', '50220'),
    ('50235', 'Training and Seminars',                   'Administrative Expense', None, 'debit', '50220'),
    ('50236', 'Repairs and Maintenance',                 'Administrative Expense', None, 'debit', '50220'),
    ('50237', 'Bank Charges',                            'Administrative Expense', None, 'debit', '50220'),
    ('50238', 'Bad Debts Expense',                       'Administrative Expense', None, 'debit', '50220'),
    ('50239', 'Miscellaneous Expense',                   'Administrative Expense', None, 'debit', '50220'),
    # ===== OTHER EXPENSE =====
    ('50300', 'Other Expenses',                          'Other Expense', None, 'debit', None),
    ('50301', 'Interest Expense',                        'Other Expense', None, 'debit', '50300'),
    ('50302', 'Loss on Disposal of Assets',              'Other Expense', None, 'debit', '50300'),
    ('50303', 'Cash Short/Over',                          'Other Expense', None, 'debit', '50300'),
    # ===== INCOME TAX EXPENSE =====
    ('50400', 'Income Tax Expense',                      'Income Tax Expense', None, 'debit', None),
    ('50401', 'Income Tax Expense - Current',            'Income Tax Expense', None, 'debit', '50400'),
]
