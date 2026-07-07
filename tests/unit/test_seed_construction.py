import pytest


def test_seed_construction_builds_clean_instance(db_session, capsys):
    from app.seeds.seed_data import seed_construction
    seed_construction()
    from app.accounts.models import Account
    from app.settings import AppSettings
    from app.vat_categories.models import VATCategory
    # generic identity, not a client name
    assert AppSettings.get_setting('company_name') == 'Construction Company'
    # magic codes present with correct type
    a = Account.query.filter_by(code='10212').first()
    assert a is not None and a.account_type == 'Asset'
    assert Account.query.filter_by(code='30301').first() is not None
    # VAT category V12SV links to Input VAT - Services (10503), NOT to CWT
    v = VATCategory.query.filter_by(code='V12SV').first()
    svc = Account.query.filter_by(code='10503').first()
    assert v.input_vat_account_id == svc.id
    # prints the target DB filename
    assert 'DB:' in capsys.readouterr().out


def test_seed_construction_refuses_nonempty_coa(db_session):
    from app.seeds.seed_data import seed_construction
    seed_construction()                    # first run seeds
    with pytest.raises(RuntimeError):
        seed_construction()                # second run must refuse (COA non-empty)
