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


COMPANY_SETTINGS = [
    {'key': 'company_name', 'value': 'SavorPack Food Manufacturing Corp.'},
    {'key': 'company_tin', 'value': '009-888-777-000'},
    {'key': 'company_address', 'value': '12 Riverside Industrial Park, Cabuyao, Laguna'},
    {'key': 'fiscal_year_start', 'value': '01'},
    {'key': 'tin_branch_code', 'value': '000'},
]

# (code, name, rate, sales_name) — sales_name set => usable seller-side; None => purchase-only.
WHT_CODES = [
    {'code': 'WI010', 'name': 'Income payments to suppliers of goods (1%)', 'rate': 1.00,
     'sales_name': 'Sales of goods to top withholding agent (1%)'},
    {'code': 'WI020', 'name': 'Income payments to suppliers of services (2%)', 'rate': 2.00, 'sales_name': None},
    {'code': 'WC160', 'name': 'Rentals (5%)', 'rate': 5.00, 'sales_name': None},
    {'code': 'WC010', 'name': 'Professional fees (10%)', 'rate': 10.00, 'sales_name': None},
]


def seed_food_baseline():
    """Admin, MAIN branch, company settings, tax tables, periods Jan2024->Jun2026. Idempotent."""
    from app.users.models import User
    from app.branches.models import Branch
    from app.settings import AppSettings
    from app.vat_categories.models import VATCategory
    from app.sales_vat_categories.models import SalesVATCategory
    from app.withholding_tax.models import WithholdingTax
    from app.periods.models import AccountingPeriod

    seed_food_coa()

    admin = User.query.filter_by(username='admin').first()
    if admin is None:
        admin = User(username='admin', email='admin@savorpack.ph',
                     full_name='System Administrator', role='admin', is_active=True)
        admin.set_password('admin123')
        db.session.add(admin); db.session.commit()

    branch = Branch.query.filter_by(code='MAIN').first()
    if branch is None:
        branch = Branch(code='MAIN', name='Main Branch', address='Head Office', is_active=True)
        db.session.add(branch); db.session.commit()
    if branch not in admin.branches.all():
        admin.branches.append(branch); db.session.commit()

    if AppSettings.query.count() == 0:
        for s in COMPANY_SETTINGS:
            db.session.add(AppSettings(key=s['key'], value=s['value'], updated_by='system'))
        db.session.commit()

    if VATCategory.query.count() == 0:
        vat_acct = {a.code: a.id for a in Account.query.filter(
            Account.code.in_(['10501', '10502', '10503', '10504'])).all()}
        for c in [
            {'code': 'VEX', 'name': 'VAT Exempt', 'rate': 0.00, 'acct': None},
            {'code': 'V12CG', 'name': 'Input Tax Capital Goods', 'rate': 12.00, 'acct': '10501'},
            {'code': 'V12DG', 'name': 'Input Tax Domestic Goods', 'rate': 12.00, 'acct': '10502'},
            {'code': 'V12SV', 'name': 'Input Tax Services', 'rate': 12.00, 'acct': '10503'},
        ]:
            db.session.add(VATCategory(code=c['code'], name=c['name'], rate=c['rate'],
                                       description='', is_active=True,
                                       input_vat_account_id=vat_acct.get(c['acct']) if c['acct'] else None))
        db.session.commit()

    if SalesVATCategory.query.count() == 0:
        out_id = Account.query.filter_by(code='20201').first().id
        for c in [
            {'code': 'V12', 'name': 'VATable Sales (12%)', 'rate': 12.00, 'nature': 'regular', 'acct': out_id},
            {'code': 'VEX', 'name': 'VAT-Exempt Sales', 'rate': 0.00, 'nature': 'exempt', 'acct': None},
        ]:
            db.session.add(SalesVATCategory(code=c['code'], name=c['name'], rate=c['rate'],
                                            transaction_nature=c['nature'],
                                            output_vat_account_id=c['acct'], is_active=True))
        db.session.commit()

    if WithholdingTax.query.count() == 0:
        for w in WHT_CODES:
            db.session.add(WithholdingTax(code=w['code'], name=w['name'], description='',
                                          rate=w['rate'], sales_name=w['sales_name'], is_active=True))
        db.session.commit()

    py, pm = 2024, 1
    while (py, pm) <= (2026, 6):
        AccountingPeriod.get_or_create_period(py, pm)
        pm += 1
        if pm > 12:
            pm, py = 1, py + 1

    return {'admin': admin, 'branch': branch}


FOOD_CUSTOMERS = [
    {'code': 'C001', 'name': 'Golden Harvest Foods Inc.', 'vat': 'V12', 'tin': '111-222-333-000'},
    {'code': 'C002', 'name': 'Metro Grocers Corporation', 'vat': 'V12', 'tin': '222-333-444-000'},
    {'code': 'C003', 'name': 'FreshMart Distribution Co.', 'vat': 'V12', 'tin': '333-444-555-000'},
    {'code': 'C004', 'name': 'Island Pantry Trading', 'vat': 'V12', 'tin': '444-555-666-000'},
    {'code': 'C005', 'name': 'SunRise Retail Ventures', 'vat': 'V12', 'tin': '555-666-777-000'},
]

# expense_code = the account each vendor's purchase/expense posts to.
FOOD_VENDORS = [
    {'code': 'V001', 'name': 'AgriSource Raw Materials Inc.', 'tin': '611-000-001-000',
     'vat': 'V12DG', 'wht': None, 'expense_code': '10301'},   # raw materials -> RM inventory
    {'code': 'V002', 'name': 'PackRight Packaging Supply', 'tin': '611-000-002-000',
     'vat': 'V12DG', 'wht': None, 'expense_code': '10304'},   # packaging -> Pkg inventory
    {'code': 'V003', 'name': 'Laguna Power & Water District', 'tin': '611-000-003-000',
     'vat': 'V12SV', 'wht': None, 'expense_code': '60104'},   # utilities (office)
    {'code': 'V004', 'name': 'RiverPark Realty (Landlord)', 'tin': '611-000-004-000',
     'vat': 'V12SV', 'wht': 'WC160', 'expense_code': '60103'},  # rent (5% EWT)
    {'code': 'V005', 'name': 'Ledesma & Co. CPAs', 'tin': '611-000-005-000',
     'vat': 'V12SV', 'wht': 'WC010', 'expense_code': '60108'},  # professional (10% EWT)
    {'code': 'V006', 'name': 'FastLane Logistics Services', 'tin': '611-000-006-000',
     'vat': 'V12SV', 'wht': 'WI020', 'expense_code': '61101'},  # freight (2% EWT)
]


def seed_food_customers():
    from app.customers.models import Customer
    if Customer.query.count() > 0:
        return 0
    for c in FOOD_CUSTOMERS:
        db.session.add(Customer(code=c['code'], name=c['name'], tin=c['tin'],
                                address='Metro Manila', default_vat_category=c['vat'],
                                is_active=True))
    db.session.commit()
    return len(FOOD_CUSTOMERS)


def seed_food_vendors():
    """Create vendors; return the spec list (with expense_code/vat/wht) for the builders."""
    from app.vendors.models import Vendor
    if Vendor.query.count() == 0:
        for v in FOOD_VENDORS:
            db.session.add(Vendor(code=v['code'], name=v['name'], tin=v['tin'], is_active=True))
        db.session.commit()
    by_code = {v.code: v for v in Vendor.query.all()}
    return [{'vendor': by_code[v['code']], 'vat': v['vat'], 'wht': v['wht'],
             'expense_code': v['expense_code']} for v in FOOD_VENDORS]


def resolve_food_refs():
    """Account-object lookups the transaction builders need."""
    a = {x.code: x for x in Account.query.all()}
    expense_codes = ['60103', '60104', '60105', '60106', '60108', '60109', '60110',
                     '60111', '61101', '61102', '61103', '10301', '10304']
    return {
        'cash_on_hand': a['10101'], 'cash_bank': a['10110'],
        'inv': {'rm': a['10301'], 'wip': a['10302'], 'fg': a['10303'], 'pkg': a['10304']},
        'ppe': {'machinery': a['12010'], 'accum_machinery': a['12011'],
                'building': a['12020'], 'accum_building': a['12021'],
                'office': a['12030'], 'accum_office': a['12031'],
                'vehicles': a['12040'], 'accum_vehicles': a['12041']},
        'revenue': a['40101'], 'cogs': a['50001'],
        'expense': {code: a[code] for code in expense_codes},
        'accrued_salaries': a['20401'], 'sss': a['20402'], 'phic': a['20403'], 'hdmf': a['20404'],
        'wt_comp': a['20302'], 'income_tax_payable': a['20406'],
        'loan': a['25001'], 'share_capital': a['30101'],
        'interest_expense': a['70101'], 'admin_salaries': a['60101'],
        'employer_share': a['60102'], 'admin_depr': a['60107'], 'vehicle_depr': a['61104'],
    }


def build_food_si(doc_date, customer_obj, gross_amount, refs, admin_id, branch_id, counters):
    """One posted finished-goods Sales Invoice (12% VAT, 1% goods EWT) + balanced posted JE."""
    from datetime import date as _date
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
    from app.sales_invoices.views import _post_invoice_je
    from app.utils import ph_now
    from app.seeds.demo_seed import si_number, _money, _wht

    wt = _wht('WI010')  # 1% EWT on goods (seller records buyer's withholding -> CWT)
    si = SalesInvoice(
        branch_id=branch_id, invoice_number=si_number(counters), invoice_date=doc_date,
        due_date=_date.fromordinal(doc_date.toordinal() + 30),
        customer_id=customer_obj.id, customer_name=customer_obj.name,
        customer_tin=customer_obj.tin, customer_address=customer_obj.address,
        status='posted', amount_paid=Decimal('0.00'),
        created_by_id=admin_id, posted_by_id=admin_id, posted_at=ph_now(),
    )
    item = SalesInvoiceItem(
        line_number=1, description='Packed food products — finished goods',
        amount=_money(gross_amount), vat_category='V12', vat_rate=Decimal('12.00'),
        account_id=refs['revenue'].id,
        wt_id=wt.id if wt else None,
        wt_rate=Decimal(str(wt.rate)) if wt else Decimal('0.00'),
    )
    item.calculate_amounts()
    si.line_items.append(item)
    si.calculate_totals()
    db.session.add(si); db.session.flush()
    je = _post_invoice_je(si, admin_id)
    si.journal_entry_id = je.id
    db.session.commit()
    return si


def build_food_opening(refs, admin_id, branch_id):
    """2024-01-01 launch: capital + bank loan fund cash, equipment, and opening raw materials."""
    from datetime import date
    from decimal import Decimal
    from app.seeds.demo_seed import build_jv
    lines = [
        (refs['cash_bank'], Decimal('3000000.00'), Decimal('0.00')),
        (refs['ppe']['machinery'], Decimal('4000000.00'), Decimal('0.00')),
        (refs['ppe']['building'], Decimal('2500000.00'), Decimal('0.00')),
        (refs['ppe']['vehicles'], Decimal('1200000.00'), Decimal('0.00')),
        (refs['ppe']['office'], Decimal('300000.00'), Decimal('0.00')),
        (refs['inv']['rm'], Decimal('800000.00'), Decimal('0.00')),
        (refs['inv']['pkg'], Decimal('200000.00'), Decimal('0.00')),
        # Debits total 12,000,000 (3M+4M+2.5M+1.2M+0.3M+0.8M+0.2M) = funded 6M capital + 6M loan.
        (refs['share_capital'], Decimal('0.00'), Decimal('6000000.00')),
        (refs['loan'], Decimal('0.00'), Decimal('6000000.00')),
    ]
    return build_jv(date(2024, 1, 1), lines, refs, admin_id, branch_id,
                    entry_type='opening_balance', description='Opening balances — company launch',
                    reference='OPENING BALANCES')


def build_production_jv(doc_date, amount, refs, admin_id, branch_id):
    """Capitalize a month's factory costs into Finished Goods: RM + labor + factory depreciation.
    amount = total finished-goods value produced this period; split into cost components."""
    from decimal import Decimal
    from app.seeds.demo_seed import build_jv, _money
    amt = _money(amount)
    rm = _money(amount * Decimal('0.55'))          # raw materials consumed
    labor = _money(amount * Decimal('0.25'))       # factory direct labor (accrued)
    depr = _money(amount - rm - labor)             # factory machine depreciation (residual balancer)
    # Capitalize factory costs straight into Finished Goods (simple monthly full-completion model;
    # WIP is exercised separately by the orchestrator's optional partial-completion entry).
    lines = [
        (refs['inv']['fg'], amt, Decimal('0.00')),
        (refs['inv']['rm'], Decimal('0.00'), rm),
        (refs['accrued_salaries'], Decimal('0.00'), labor),
        (refs['ppe']['accum_machinery'], Decimal('0.00'), depr),
    ]
    return build_jv(doc_date, lines, refs, admin_id, branch_id,
                    entry_type='reclassification', description='Production — finished goods completed')


def build_cogs_jv(doc_date, amount, refs, admin_id, branch_id):
    """Recognize cost of goods sold for the period: Finished Goods -> COGS."""
    from decimal import Decimal
    from app.seeds.demo_seed import build_jv, _money
    amt = _money(amount)
    lines = [
        (refs['cogs'], amt, Decimal('0.00')),
        (refs['inv']['fg'], Decimal('0.00'), amt),
    ]
    return build_jv(doc_date, lines, refs, admin_id, branch_id,
                    entry_type='reclassification', description='Cost of goods sold — period')
