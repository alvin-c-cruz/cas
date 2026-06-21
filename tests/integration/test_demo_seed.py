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
        assert a.children.count() == 0, f'{code} must be a postable leaf'
    # Construction-specific accounts present
    assert Account.query.filter_by(code='40101').first().name == 'Construction Contract Revenue'
    assert Account.query.filter_by(code='10310').first() is not None  # CIP
    # Idempotent
    assert seed_construction_coa() == 0
