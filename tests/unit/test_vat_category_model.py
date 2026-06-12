"""VATCategory.input_vat_account mapping (B-014)."""
from app.accounts.models import Account
from app.vat_categories.models import VATCategory


def make_account(db_session, code='10502', name='Input VAT - Domestic Goods'):
    a = Account(code=code, name=name, account_type='Asset',
                normal_balance='Debit', is_active=True)
    db_session.add(a)
    db_session.commit()
    return a


class TestInputVatAccountField:
    def test_field_and_relationship(self, db_session):
        acct = make_account(db_session)
        cat = VATCategory(code='V12T', name='Test 12%', rate=12.00,
                          is_active=True, input_vat_account_id=acct.id)
        db_session.add(cat)
        db_session.commit()
        assert cat.input_vat_account.code == '10502'

    def test_nullable_for_zero_rate(self, db_session):
        cat = VATCategory(code='V0T', name='Test 0%', rate=0.00, is_active=True)
        db_session.add(cat)
        db_session.commit()
        assert cat.input_vat_account_id is None

    def test_to_dict_includes_account(self, db_session):
        acct = make_account(db_session, code='10503', name='Input VAT - Services')
        cat = VATCategory(code='V12S', name='Svc 12%', rate=12.00,
                          is_active=True, input_vat_account_id=acct.id)
        db_session.add(cat)
        db_session.commit()
        d = cat.to_dict()
        assert d['input_vat_account_id'] == acct.id
        assert d['input_vat_account_code'] == '10503'
        assert d['input_vat_account_name'] == 'Input VAT - Services'

    def test_to_dict_unmapped(self, db_session):
        cat = VATCategory(code='V0U', name='Zero', rate=0.00, is_active=True)
        db_session.add(cat)
        db_session.commit()
        d = cat.to_dict()
        assert d['input_vat_account_id'] is None
        assert d['input_vat_account_code'] is None
        assert d['input_vat_account_name'] is None
