"""Philgen Pacific Food Products Corporation — food-manufacturer + EXPORTER demo.

Mirrors food_demo.py (SavorPack) but reflects Philgen's real profile: a dried-fruit and
fruit-juice manufacturer in Malungon, Sarangani whose sales are ~80% VAT ZERO-RATED export
and ~20% domestic (12% output VAT, 1% goods EWT). The zero-rated majority means little output
VAT but steadily accumulating CREDITABLE input VAT — the classic Philippine exporter position.

Reuses food_demo's proven, balanced manufacturing/payroll/depreciation/loan builders verbatim;
only the company identity, the sales VAT categories, the customers, and the sales generator differ.
Span: Jan 2024 -> Jun 2026, single MAIN branch. NOT idempotent (refuses re-run).

This is a SAMPLE / DEMO dataset for proposal purposes only.
"""
from decimal import Decimal
from app import db
from app.accounts.models import Account

# Reuse the food-manufacturing COA + every proven balanced builder unchanged.
from app.seeds.food_demo import (
    FOOD_COA, seed_food_coa, WHT_CODES, FOOD_VENDORS,
    seed_food_vendors, resolve_food_refs, build_food_opening,
    build_production_jv, build_cogs_jv, build_payroll_jv,
    build_payroll_settlement_jv, build_depreciation_jv, build_loan_amort_jv,
)


PHILGEN_COMPANY_SETTINGS = [
    {'key': 'company_name', 'value': 'Philgen Pacific Food Products Corporation'},
    {'key': 'company_tin', 'value': '000-000-000-000'},   # placeholder — fill real TIN
    {'key': 'company_address',
     'value': 'Sitio Lamcanal, Brgy. Malandag, Malungon, Sarangani Province'},
    {'key': 'fiscal_year_start', 'value': '01'},
    {'key': 'tin_branch_code', 'value': '000'},
]

# export=True -> VAT zero-rated (V0) foreign buyer; export=False -> domestic 12% VAT.
PHILGEN_CUSTOMERS = [
    {'code': 'C001', 'name': 'Pacific Rim Dried Fruits LLC', 'vat': 'V0',
     'tin': '000-000-001-000', 'address': 'Los Angeles, California, USA', 'export': True},
    {'code': 'C002', 'name': 'Nihon Tropical Foods K.K.', 'vat': 'V0',
     'tin': '000-000-002-000', 'address': 'Osaka, Japan', 'export': True},
    {'code': 'C003', 'name': 'Golden Orient Trading Ltd.', 'vat': 'V0',
     'tin': '000-000-003-000', 'address': 'Kowloon, Hong Kong', 'export': True},
    {'code': 'C004', 'name': 'EuroFruit Imports B.V.', 'vat': 'V0',
     'tin': '000-000-004-000', 'address': 'Rotterdam, Netherlands', 'export': True},
    {'code': 'C005', 'name': 'Metro Grocers Corporation', 'vat': 'V12',
     'tin': '222-333-444-000', 'address': 'Quezon City, Metro Manila', 'export': False},
    {'code': 'C006', 'name': 'FreshMart Distribution Co.', 'vat': 'V12',
     'tin': '333-444-555-000', 'address': 'Davao City', 'export': False},
]

# Vendors: raw fruit -> RM inventory, packaging -> Pkg inventory, plus opex (same shape as food_demo,
# renamed to Philgen's supply chain). expense_code = the account each purchase/expense posts to.
PHILGEN_VENDORS = [
    {'code': 'V001', 'name': 'AgriSource Fresh Fruit Supply Inc.', 'tin': '611-000-001-000',
     'vat': 'V12DG', 'wht': None, 'expense_code': '10301'},   # fresh mango/papaya/pineapple -> RM
    {'code': 'V002', 'name': 'PackRight Packaging Supply', 'tin': '611-000-002-000',
     'vat': 'V12DG', 'wht': None, 'expense_code': '10304'},   # pouches/cartons -> Pkg inventory
    {'code': 'V003', 'name': 'SOCOTECO II Power & Water', 'tin': '611-000-003-000',
     'vat': 'V12SV', 'wht': None, 'expense_code': '60104'},   # utilities (office)
    {'code': 'V004', 'name': 'Malandag Realty (Landlord)', 'tin': '611-000-004-000',
     'vat': 'V12SV', 'wht': 'WC160', 'expense_code': '60103'},  # rent (5% EWT)
    {'code': 'V005', 'name': 'Sarangani & Co. CPAs', 'tin': '611-000-005-000',
     'vat': 'V12SV', 'wht': 'WC010', 'expense_code': '60108'},  # professional (10% EWT)
    {'code': 'V006', 'name': 'GenSan Freight & Cold Chain', 'tin': '611-000-006-000',
     'vat': 'V12SV', 'wht': 'WI020', 'expense_code': '61101'},  # freight (2% EWT)
]


def seed_philgen_baseline():
    """Admin, MAIN branch, Philgen company settings, tax tables (incl. V0 zero-rated),
    periods Jan2024->Jun2026. Idempotent."""
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
        admin = User(username='admin', email='admin@philgen.ph',
                     full_name='System Administrator', role='admin', is_active=True)
        admin.set_password('admin123')
        db.session.add(admin); db.session.commit()

    branch = Branch.query.filter_by(code='MAIN').first()
    if branch is None:
        branch = Branch(code='MAIN', name='Main Plant — Malungon', address='Malandag, Malungon, Sarangani',
                        is_active=True)
        db.session.add(branch); db.session.commit()
    if branch not in admin.branches.all():
        admin.branches.append(branch); db.session.commit()

    if AppSettings.query.count() == 0:
        for s in PHILGEN_COMPANY_SETTINGS:
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
            {'code': 'V0', 'name': 'VAT Zero-Rated Sales (Export)', 'rate': 0.00,
             'nature': 'zero_export', 'acct': None},
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


def seed_philgen_customers():
    from app.customers.models import Customer
    if Customer.query.count() > 0:
        return 0
    for c in PHILGEN_CUSTOMERS:
        db.session.add(Customer(code=c['code'], name=c['name'], tin=c['tin'],
                                address=c['address'], default_vat_category=c['vat'],
                                is_active=True))
    db.session.commit()
    return len(PHILGEN_CUSTOMERS)


def seed_philgen_vendors():
    """Create vendors; return the spec list (with expense_code/vat/wht) for the builders."""
    from app.vendors.models import Vendor
    if Vendor.query.count() == 0:
        for v in PHILGEN_VENDORS:
            db.session.add(Vendor(code=v['code'], name=v['name'], tin=v['tin'], is_active=True))
        db.session.commit()
    by_code = {v.code: v for v in Vendor.query.all()}
    return [{'vendor': by_code[v['code']], 'vat': v['vat'], 'wht': v['wht'],
             'expense_code': v['expense_code']} for v in PHILGEN_VENDORS]


def build_philgen_si(doc_date, customer_obj, gross_amount, is_export, refs,
                     admin_id, branch_id, counters):
    """One posted finished-goods Sales Invoice + balanced posted JE.

    Export (is_export): VAT zero-rated (V0), no output VAT, no EWT (foreign buyer) ->
        JE is simply Dr AR = Cr Revenue = gross.
    Domestic: 12% output VAT extracted + 1% goods EWT (customer withholds -> CWT), same as food_demo.
    """
    from datetime import date as _date
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
    from app.sales_invoices.views import _post_invoice_je
    from app.utils import ph_now
    from app.seeds.demo_seed import si_number, _money, _wht

    wt = None if is_export else _wht('WI010')   # domestic: 1% EWT on goods
    vat_code = 'V0' if is_export else 'V12'
    vat_rate = Decimal('0.00') if is_export else Decimal('12.00')
    desc = ('Dried fruit & juice products — export shipment (dried mango / papaya / pineapple, mango juice)'
            if is_export else
            'Dried fruit & juice products — domestic delivery (finished goods)')

    si = SalesInvoice(
        branch_id=branch_id, invoice_number=si_number(counters), invoice_date=doc_date,
        due_date=_date.fromordinal(doc_date.toordinal() + 30),
        customer_id=customer_obj.id, customer_name=customer_obj.name,
        customer_tin=customer_obj.tin, customer_address=customer_obj.address,
        status='posted', amount_paid=Decimal('0.00'),
        created_by_id=admin_id, posted_by_id=admin_id, posted_at=ph_now(),
    )
    item = SalesInvoiceItem(
        line_number=1, description=desc,
        amount=_money(gross_amount), vat_category=vat_code, vat_rate=vat_rate,
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


def generate_philgen_transactions(refs, admin_id, branch_id):
    from datetime import date
    from decimal import Decimal
    from calendar import monthrange
    from app.journal_entries.models import JournalEntry
    from app.customers.models import Customer
    from app.seeds.demo_seed import (build_apv, build_crv_collecting, build_cdv_paying,
                                      build_cdv_expense, build_jv, _money)

    counters = {}
    summary = {'si': 0, 'si_export': 0, 'si_domestic': 0, 'ap': 0, 'crv': 0, 'cdv': 0,
               'jv': 0, 'unbalanced': 0}

    build_food_opening(refs, admin_id, branch_id); summary['jv'] += 1

    seed_philgen_customers()
    all_customers = Customer.query.order_by(Customer.code).all()
    export_custs = [c for c in all_customers if c.default_vat_category == 'V0']
    domestic_custs = [c for c in all_customers if c.default_vat_category != 'V0']

    vendor_specs = seed_philgen_vendors()
    rm_vendor = next(s for s in vendor_specs if s['expense_code'] == '10301')
    pkg_vendor = next(s for s in vendor_specs if s['expense_code'] == '10304')
    opex_vendors = [s for s in vendor_specs if s['expense_code'] not in ('10301', '10304')]

    y, m = 2024, 1
    idx = 0
    while (y, m) <= (2026, 6):
        last = monthrange(y, m)[1]
        eom = date(y, m, last)
        n_sales = 8 + (idx * 37) % 8          # 8..15

        # Sales + collections. ~80% VAT zero-rated export, ~20% domestic (1 in 5 domestic).
        exp_i = dom_i = 0
        for k in range(n_sales):
            is_export = (k % 5 != 0)          # 4 of every 5 -> export (~80%)
            gross = _money(Decimal('80000') + Decimal(str(((idx + k) * 6131) % 90000)))
            si_day = 1 + (k * 2) % last
            if is_export:
                cust = export_custs[exp_i % len(export_custs)]; exp_i += 1
                summary['si_export'] += 1
            else:
                cust = domestic_custs[dom_i % len(domestic_custs)]; dom_i += 1
                summary['si_domestic'] += 1
            si = build_philgen_si(date(y, m, si_day), cust, gross, is_export,
                                  refs, admin_id, branch_id, counters); summary['si'] += 1
            if k % 5 != 0:  # ~80% collected within the period -> aging spread
                build_crv_collecting(date(y, m, min(last, si_day + 5 + k % 6)), si, refs,
                                     admin_id, branch_id, counters); summary['crv'] += 1

        # Raw-material / packaging purchases sized to what THIS month's production consumes
        # (0.50 / 0.15 of produced), grossed up by 1.12 (VAT-DG vendors) so inventories stay flat.
        produced = _money(Decimal('600000') + Decimal(str((idx * 8123) % 300000)))
        rm_need = _money(produced * Decimal('0.50'))
        pkg_need = _money(produced * Decimal('0.15'))

        RM_BILLS = 4
        rm_share = _money(rm_need * Decimal('1.12') / RM_BILLS)
        for k in range(RM_BILLS):
            wobble = Decimal('90') + Decimal(str((idx * 41 + k * 97) % 21))  # 90..110
            gross = _money(rm_share * wobble / Decimal('100'))
            ap_day = 2 + (k * 7 + idx * 3) % (last - 1)
            ap = build_apv(date(y, m, ap_day), rm_vendor['vendor'], rm_vendor, gross,
                           refs, admin_id, branch_id, counters); summary['ap'] += 1
            if k % 4 != 0:
                build_cdv_paying(date(y, m, min(last, ap_day + 4 + k % 6)), ap, refs,
                                 admin_id, branch_id, counters); summary['cdv'] += 1

        pkg_gross = _money(pkg_need * Decimal('1.12'))
        pkg_day = 3 + (idx * 5) % (last - 2)
        pkg_ap = build_apv(date(y, m, pkg_day), pkg_vendor['vendor'], pkg_vendor, pkg_gross,
                           refs, admin_id, branch_id, counters); summary['ap'] += 1
        if idx % 4 != 0:
            build_cdv_paying(date(y, m, min(last, pkg_day + 4 + idx % 6)), pkg_ap, refs,
                             admin_id, branch_id, counters); summary['cdv'] += 1

        # Monthly opex (rent, utilities, professional, freight) via direct CDV expense
        for spec in opex_vendors:
            gross = _money(Decimal('15000') + Decimal(str((idx * 977) % 40000)))
            build_cdv_expense(eom, spec['vendor'], spec, gross, refs,
                              admin_id, branch_id, counters, method='check'); summary['cdv'] += 1

        # Manufacturing + payroll + depreciation + loan (month-end JVs)
        sold = _money(produced * Decimal('0.85'))
        build_production_jv(eom, produced, refs, admin_id, branch_id); summary['jv'] += 1
        build_cogs_jv(eom, sold, refs, admin_id, branch_id); summary['jv'] += 1
        build_payroll_jv(eom, _money(Decimal('280000')), refs, admin_id, branch_id); summary['jv'] += 1
        build_payroll_settlement_jv(eom, _money(Decimal('280000')), produced * Decimal('0.25'),
                                    refs, admin_id, branch_id); summary['jv'] += 1
        build_depreciation_jv(eom, refs, admin_id, branch_id); summary['jv'] += 1
        build_loan_amort_jv(eom, _money(Decimal('100000')), _money(Decimal('40000')),
                            refs, admin_id, branch_id); summary['jv'] += 1

        # Sundry opex + occasional other income (scrap / interest)
        sundry_targets = ['60105', '60106', '60109', '60110', '60111', '61102', '61103']
        opex_code = sundry_targets[idx % len(sundry_targets)]
        opex_amt = _money(Decimal('8000') + Decimal(str((idx * 311) % 4000)))
        bank_chg = _money(Decimal('2500'))
        build_jv(eom, [
            (refs['expense'][opex_code], opex_amt, Decimal('0.00')),
            (refs['expense']['70102'], bank_chg, Decimal('0.00')),
            (refs['cash_bank'], Decimal('0.00'), _money(opex_amt + bank_chg)),
        ], refs, admin_id, branch_id, entry_type='adjustment',
            description='Sundry operating expenses'); summary['jv'] += 1
        if idx % 3 == 0:
            inc_amt = _money(Decimal('5000') + Decimal(str((idx * 137) % 3000)))
            inc_tgt = refs['scrap_income'] if idx % 2 == 0 else refs['interest_income']
            build_jv(eom, [
                (refs['cash_bank'], inc_amt, Decimal('0.00')),
                (inc_tgt, Decimal('0.00'), inc_amt),
            ], refs, admin_id, branch_id, entry_type='adjustment',
                description='Sundry other income'); summary['jv'] += 1

        idx += 1
        m += 1
        if m > 12:
            m, y = 1, y + 1

    summary['unbalanced'] = JournalEntry.query.filter_by(status='posted', is_balanced=False).count()
    return summary


def run_seed_philgen_demo(reset=False):
    """Reset (optional), build baseline + masters + 30 months of transactions, close 2024/2025."""
    if reset:
        db.drop_all(); db.create_all()
    r0 = seed_philgen_baseline()
    seed_philgen_customers()
    seed_philgen_vendors()
    refs = resolve_food_refs()
    from app.sales_invoices.models import SalesInvoice
    if not reset and SalesInvoice.query.count() > 0:
        raise RuntimeError(
            "Philgen-demo transactions already present in this database. "
            "To rebuild: delete the DB file, run `flask db upgrade`, then `flask seed-philgen-demo`.")
    summary = generate_philgen_transactions(refs, r0['admin'].id, r0['branch'].id)
    # Year-end income-tax accrual (25% of pretax) before each close, then close 2024/2025.
    from datetime import date
    from decimal import Decimal
    from app.reports.financial import generate_income_statement
    from app.branches.models import Branch
    from app.seeds.demo_seed import build_jv, _money
    from app.year_end.service import close_fiscal_year
    for yr in (2024, 2025):
        ye = date(yr, 12, 31)
        is_ = generate_income_statement(date(yr, 1, 1), ye, branch_id=r0['branch'].id)
        pretax = Decimal(str(is_.get('net_income', 0)))
        tax = _money(pretax * Decimal('0.25')) if pretax > 0 else _money(Decimal('0'))
        if tax > 0:
            build_jv(ye,
                     [(refs['income_tax_expense'], tax, Decimal('0.00')),
                      (refs['income_tax_payable'], Decimal('0.00'), tax)],
                     refs, r0['admin'].id, r0['branch'].id,
                     entry_type='adjustment', description=f'Income tax accrual {yr}')
            summary['jv'] += 1
        close_fiscal_year(yr, r0['admin'].id)
    return summary
