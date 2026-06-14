"""VATCategory.input_vat_account mapping (B-014)."""
from app.accounts.models import Account
from app.vat_categories.models import VATCategory
import pytest
pytestmark = [pytest.mark.vat_categories, pytest.mark.unit]




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


def test_vat_category_has_output_vat_account_id(db_session):
    from app.vat_categories.models import VATCategory
    cat = VATCategory(code='TEST', name='Test', rate=12.0)
    db_session.add(cat)
    db_session.commit()
    assert hasattr(cat, 'output_vat_account_id')
    assert cat.output_vat_account_id is None
    d = cat.to_dict()
    assert 'output_vat_account_id' in d
    assert 'output_vat_account_code' in d


def test_output_vat_account_relationship_and_to_dict(db_session):
    from app.vat_categories.models import VATCategory
    from app.accounts.models import Account
    # Create a leaf account to assign
    acct = Account(code='20201', name='Output VAT - Sales', account_type='Liability',
                   normal_balance='credit', is_active=True)
    db_session.add(acct)
    db_session.flush()

    cat = VATCategory(code='V12', name='VAT 12%', rate=12.0,
                      output_vat_account_id=acct.id)
    db_session.add(cat)
    db_session.commit()

    assert cat.output_vat_account is not None
    assert cat.output_vat_account.code == '20201'
    d = cat.to_dict()
    assert d['output_vat_account_id'] == acct.id
    assert d['output_vat_account_code'] == '20201'
    assert d['output_vat_account_name'] == 'Output VAT - Sales'
