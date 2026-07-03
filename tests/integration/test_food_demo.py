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


def test_food_customers_vendors_and_refs(db_session):
    from app.seeds.food_demo import (seed_food_baseline, seed_food_customers,
                                      seed_food_vendors, resolve_food_refs)
    from app.customers.models import Customer
    from app.vendors.models import Vendor
    seed_food_baseline()
    seed_food_customers()
    specs = seed_food_vendors()
    assert Customer.query.count() >= 4
    assert Vendor.query.count() >= 4
    assert all({'vendor', 'vat', 'wht', 'expense_code'} <= set(s) for s in specs)
    refs = resolve_food_refs()
    for k in ('cash_on_hand', 'cash_bank', 'revenue', 'cogs', 'share_capital', 'loan'):
        assert refs[k] is not None
    assert refs['inv']['rm'].code == '10301' and refs['inv']['fg'].code == '10303'
    assert refs['expense']  # non-empty expense map for build_apv/build_cdv_expense


def test_build_food_si_posts_balanced(db_session):
    from datetime import date
    from decimal import Decimal
    from app.seeds.food_demo import (seed_food_baseline, seed_food_customers,
                                      resolve_food_refs, build_food_si)
    from app.customers.models import Customer
    r0 = seed_food_baseline(); seed_food_customers()
    refs = resolve_food_refs()
    cust = Customer.query.filter_by(code='C001').first()
    counters = {}
    si = build_food_si(date(2024, 3, 15), cust, Decimal('112000.00'),
                       refs, r0['admin'].id, r0['branch'].id, counters)
    assert si.status == 'posted' and si.journal_entry_id is not None
    je = si.journal_entry
    tot_d = sum((l.debit_amount for l in je.lines.all()), Decimal('0'))
    tot_c = sum((l.credit_amount for l in je.lines.all()), Decimal('0'))
    assert tot_d == tot_c
    # Revenue line posts to Sales - Goods.
    assert any(l.account_id == refs['revenue'].id for l in je.lines.all())


def test_build_food_opening_balances(db_session):
    from decimal import Decimal
    from app.seeds.food_demo import (seed_food_baseline, resolve_food_refs, build_food_opening)
    r0 = seed_food_baseline(); refs = resolve_food_refs()
    je = build_food_opening(refs, r0['admin'].id, r0['branch'].id)
    assert je.is_balanced
    from datetime import date
    assert je.entry_date == date(2024, 1, 1)


def test_manufacturing_jvs_balance_and_move_inventory(db_session):
    from datetime import date
    from decimal import Decimal
    from app.seeds.food_demo import (seed_food_baseline, resolve_food_refs,
                                      build_food_opening, build_production_jv, build_cogs_jv)
    r0 = seed_food_baseline(); refs = resolve_food_refs()
    build_food_opening(refs, r0['admin'].id, r0['branch'].id)
    p = build_production_jv(date(2024, 2, 29), Decimal('500000.00'), refs, r0['admin'].id, r0['branch'].id)
    c = build_cogs_jv(date(2024, 2, 29), Decimal('420000.00'), refs, r0['admin'].id, r0['branch'].id)
    assert p.is_balanced and c.is_balanced
    # Production debits Finished Goods; COGS credits Finished Goods.
    assert any(l.account_id == refs['inv']['fg'].id and l.debit_amount > 0 for l in p.lines.all())
    assert any(l.account_id == refs['inv']['fg'].id and l.credit_amount > 0 for l in c.lines.all())
    assert any(l.account_id == refs['cogs'].id and l.debit_amount > 0 for l in c.lines.all())


def test_payroll_depr_loan_jvs_balance(db_session):
    from datetime import date
    from decimal import Decimal
    from app.seeds.food_demo import (seed_food_baseline, resolve_food_refs,
                                      build_payroll_jv, build_depreciation_jv, build_loan_amort_jv)
    r0 = seed_food_baseline(); refs = resolve_food_refs()
    a = r0['admin'].id; b = r0['branch'].id
    assert build_payroll_jv(date(2024, 1, 31), Decimal('250000.00'), refs, a, b).is_balanced
    assert build_depreciation_jv(date(2024, 1, 31), refs, a, b).is_balanced
    assert build_loan_amort_jv(date(2024, 1, 31), Decimal('100000.00'), Decimal('50000.00'), refs, a, b).is_balanced
