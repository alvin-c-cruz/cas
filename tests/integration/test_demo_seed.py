from app.accounts.models import Account


def test_seed_construction_coa_creates_magic_codes(db_session):
    from app.seeds.demo_seed import seed_construction_coa
    n = seed_construction_coa()
    assert n >= 55
    # Magic codes the posting engine hardcodes must exist, be active, and be leaf (postable).
    for code in ['10201', '10212', '10501', '10502', '10503', '10504',
                 '20101', '20301', '20401']:
        a = Account.query.filter_by(code=code).first()
        assert a is not None, f'missing magic account {code}'
        assert a.is_active is True
        assert len(a.children) == 0, f'{code} must be a postable leaf'
    # Construction-specific accounts present
    assert Account.query.filter_by(code='40101').first().name == 'Construction Contract Revenue'
    assert Account.query.filter_by(code='10310').first() is not None  # CIP
    # Idempotent
    assert seed_construction_coa() == 0


def test_seed_demo_baseline(db_session):
    from app.seeds.demo_seed import seed_demo_baseline
    from app.settings import AppSettings
    from app.withholding_tax.models import WithholdingTax
    from app.sales_vat_categories.models import SalesVATCategory
    from app.periods.models import AccountingPeriod

    refs = seed_demo_baseline()
    assert refs['admin'].username == 'admin'
    assert refs['branch'].code == 'MAIN'
    assert AppSettings.query.filter_by(key='company_name').first().value == \
        'Zhiyuan Construction Corporation'
    # WC120 (contractors 2%) present, with a sales_name (company is a contractor)
    wc120 = WithholdingTax.query.filter_by(code='WC120').first()
    assert wc120 is not None and float(wc120.rate) == 2.0
    assert wc120.sales_name
    assert SalesVATCategory.query.filter_by(code='V12').first() is not None
    # 2025 Jan-Jun periods open
    for m in range(1, 7):
        p = AccountingPeriod.query.filter_by(year=2025, month=m).first()
        assert p is not None and p.status == 'open'
    # Idempotent
    seed_demo_baseline()
    assert WithholdingTax.query.filter_by(code='WC120').count() == 1


def test_seed_master_data(db_session):
    from app.seeds.demo_seed import seed_demo_baseline, seed_demo_customers, seed_demo_vendors
    from app.customers.models import Customer
    from app.vendors.models import Vendor
    refs = seed_demo_baseline()
    custs = seed_demo_customers(refs['admin'].id)
    vends = seed_demo_vendors()
    assert len(custs) == 7 and len(vends) == 10
    # WHT association resolved to real objects
    v_sub = Vendor.query.filter_by(name='Premier Electrical Subcontractor').first()
    assert [w.code for w in v_sub.withholding_taxes] == ['WC120']
    c1 = Customer.query.filter_by(code='C001').first()
    assert c1.default_vat_category == 'V12'
    assert [w.code for w in c1.withholding_taxes] == ['WC120']
    # Idempotent
    assert len(seed_demo_customers(refs['admin'].id)) == 7
    assert Customer.query.count() == 7


def test_resolve_refs_and_numbers(db_session):
    from app.seeds.demo_seed import seed_demo_baseline, resolve_refs, next_doc_number, si_number
    seed_demo_baseline()
    refs = resolve_refs()
    assert refs['ar'].code == '10201'
    assert refs['ap'].code == '20101'
    assert refs['cash_bank'].code == '10111'
    assert refs['revenue_contract'].code == '40101'
    counters = {}
    from datetime import date
    assert next_doc_number('AP', date(2025, 3, 4), counters) == 'AP-2025-03-0001'
    assert next_doc_number('AP', date(2025, 3, 4), counters) == 'AP-2025-03-0002'
    assert si_number(counters) == '00001'
    assert si_number(counters) == '00002'


def test_build_si_posts_balanced(db_session):
    from datetime import date
    from decimal import Decimal
    from app.seeds.demo_seed import (seed_demo_baseline, seed_demo_customers,
                                     resolve_refs, build_si)
    refs0 = seed_demo_baseline()
    custs = seed_demo_customers(refs0['admin'].id)
    refs = resolve_refs()
    counters = {}
    si = build_si(date(2025, 2, 10), custs[0], Decimal('560000.00'),
                  refs, refs0['admin'].id, refs0['branch'].id, counters)
    assert si.status == 'posted'
    assert si.journal_entry_id is not None
    je = si.journal_entry
    assert je.status == 'posted'
    d = sum((l.debit_amount for l in je.lines.all()), Decimal('0'))
    c = sum((l.credit_amount for l in je.lines.all()), Decimal('0'))
    assert d == c
    # VATable customer -> WHT applied
    assert si.withholding_tax_amount > 0
    assert si.invoice_number == '00001'


def test_build_apv_posts_balanced(db_session):
    from datetime import date
    from decimal import Decimal
    from app.seeds.demo_seed import (seed_demo_baseline, seed_demo_vendors,
                                     resolve_refs, build_apv, VENDORS)
    refs0 = seed_demo_baseline()
    vends = seed_demo_vendors()
    refs = resolve_refs()
    counters = {}
    ap = build_apv(date(2025, 3, 5), vends[0], VENDORS[0], Decimal('224000.00'),
                   refs, refs0['admin'].id, refs0['branch'].id, counters)
    assert ap.status == 'posted'
    je = ap.journal_entry
    assert je.status == 'posted'
    d = sum((l.debit_amount for l in je.lines.all()), Decimal('0'))
    c = sum((l.credit_amount for l in je.lines.all()), Decimal('0'))
    assert d == c
    assert ap.ap_number == 'AP-2025-03-0001'
    assert ap.vendor_invoice_number  # required when VAT/WHT > 0


def test_build_crv_collects_invoice(db_session):
    from datetime import date
    from decimal import Decimal
    from app.seeds.demo_seed import (seed_demo_baseline, seed_demo_customers,
                                     resolve_refs, build_si, build_crv_collecting)
    refs0 = seed_demo_baseline()
    custs = seed_demo_customers(refs0['admin'].id)
    refs = resolve_refs()
    counters = {}
    si = build_si(date(2025, 2, 10), custs[0], Decimal('560000.00'),
                  refs, refs0['admin'].id, refs0['branch'].id, counters)
    bal_before = Decimal(str(si.balance))
    assert bal_before > 0
    crv = build_crv_collecting(date(2025, 3, 12), si, refs,
                               refs0['admin'].id, refs0['branch'].id, counters)
    assert crv.status == 'posted'
    je = crv.journal_entry
    d = sum((l.debit_amount for l in je.lines.all()), Decimal('0'))
    c = sum((l.credit_amount for l in je.lines.all()), Decimal('0'))
    assert d == c
    # SI balance reduced / marked paid
    assert Decimal(str(si.balance)) < bal_before
    assert si.status in ('paid', 'partially_paid')


def test_build_cdv_pays_ap(db_session):
    from datetime import date
    from decimal import Decimal
    from app.seeds.demo_seed import (seed_demo_baseline, seed_demo_vendors,
                                     resolve_refs, build_apv, build_cdv_paying, VENDORS)
    refs0 = seed_demo_baseline()
    vends = seed_demo_vendors()
    refs = resolve_refs()
    counters = {}
    ap = build_apv(date(2025, 3, 5), vends[0], VENDORS[0], Decimal('224000.00'),
                   refs, refs0['admin'].id, refs0['branch'].id, counters)
    bal_before = Decimal(str(ap.balance))
    cdv = build_cdv_paying(date(2025, 4, 5), ap, refs,
                           refs0['admin'].id, refs0['branch'].id, counters)
    assert cdv.status == 'posted'
    je = cdv.journal_entry
    d = sum((l.debit_amount for l in je.lines.all()), Decimal('0'))
    c = sum((l.credit_amount for l in je.lines.all()), Decimal('0'))
    assert d == c
    assert Decimal(str(ap.balance)) < bal_before
    assert ap.status in ('paid', 'partially_paid')
    assert cdv.cdv_number == 'CD-2025-04-0001'


def test_jv_and_stockholder_investments(db_session):
    from datetime import date
    from decimal import Decimal
    from app.seeds.demo_seed import (seed_demo_baseline, resolve_refs, build_jv,
                                     seed_stockholder_investments)
    refs0 = seed_demo_baseline()
    refs = resolve_refs()
    jv = build_jv(date(2025, 1, 31),
                  [(refs['dep_expense'], Decimal('15000.00'), Decimal('0.00')),
                   (refs['accum_dep_equipment'], Decimal('0.00'), Decimal('15000.00'))],
                  refs, refs0['admin'].id, refs0['branch'].id,
                  entry_type='adjustment', description='Monthly depreciation Jan 2025')
    assert jv.status == 'posted' and jv.is_balanced is True
    assert jv.entry_number.startswith('JV-2025-01-')

    inv = seed_stockholder_investments(refs, refs0['admin'].id, refs0['branch'].id)
    assert len(inv) == 3
    for je in inv:
        d = sum((l.debit_amount for l in je.lines.all()), Decimal('0'))
        c = sum((l.credit_amount for l in je.lines.all()), Decimal('0'))
        assert d == c and je.status == 'posted'


def test_run_seed_demo_refuses_double_run(db_session):
    import pytest
    from app.seeds.demo_seed import run_seed_demo
    run_seed_demo(reset=False)
    with pytest.raises(RuntimeError):
        run_seed_demo(reset=False)


def test_build_jv_rejects_unbalanced(db_session):
    import pytest
    from decimal import Decimal
    from datetime import date
    from app.seeds.demo_seed import seed_demo_baseline, resolve_refs, build_jv
    r0 = seed_demo_baseline()
    refs = resolve_refs()
    with pytest.raises(ValueError):
        build_jv(date(2025, 3, 1),
                 [(refs['dep_expense'], Decimal('100.00'), Decimal('0.00')),
                  (refs['accum_dep_equipment'], Decimal('0.00'), Decimal('90.00'))],
                 refs, r0['admin'].id, r0['branch'].id,
                 entry_type='adjustment', description='Deliberately unbalanced')


def test_run_seed_demo_full_balances(db_session):
    from decimal import Decimal
    from app.seeds.demo_seed import run_seed_demo
    from app.journal_entries.models import JournalEntry
    from app.sales_invoices.models import SalesInvoice
    from app.accounts_payable.models import AccountsPayable
    from app.cash_receipts.models import CashReceiptVoucher
    from app.cash_disbursements.models import CashDisbursementVoucher

    summary = run_seed_demo(reset=False)
    assert summary['si'] >= 8 and summary['ap'] >= 8
    assert summary['crv'] >= 6 and summary['cdv'] >= 6 and summary['jv'] >= 5
    # Every posted document type exists (including paid/partially_paid after collection)
    assert SalesInvoice.query.count() >= 8
    assert AccountsPayable.query.count() >= 8
    assert CashReceiptVoucher.query.count() >= 6
    assert CashDisbursementVoucher.query.count() >= 6
    # Trial balance: total posted debits == total posted credits
    tot_d = tot_c = Decimal('0')
    for je in JournalEntry.query.filter_by(status='posted').all():
        tot_d += sum((l.debit_amount for l in je.lines.all()), Decimal('0'))
        tot_c += sum((l.credit_amount for l in je.lines.all()), Decimal('0'))
    assert tot_d == tot_c
    assert summary['unbalanced'] == 0
    # All transactions within Jan 1 - Jun 19 2025
    from datetime import date
    for si in SalesInvoice.query.all():
        assert date(2025, 1, 1) <= si.invoice_date <= date(2025, 6, 19)
