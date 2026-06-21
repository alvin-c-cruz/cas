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
