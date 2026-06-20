from decimal import Decimal
from app.accounts.models import Account
from app.sales_vat_categories.models import SalesVATCategory, SalesVATCategoryChangeRequest


class TestSalesVATCategoryModel:
    def test_create_and_to_dict(self, db_session):
        cat = SalesVATCategory(code='SVAT-G', name='Sale of Goods (12%)',
                               rate=Decimal('12.00'), transaction_nature='regular',
                               is_active=True)
        db_session.add(cat)
        db_session.commit()
        d = cat.to_dict()
        assert d['code'] == 'SVAT-G'
        assert d['rate'] == 12.0
        assert d['transaction_nature'] == 'regular'
        assert d['is_active'] is True

    def test_transaction_nature_defaults_regular(self, db_session):
        cat = SalesVATCategory(code='SVAT-X', name='X', rate=Decimal('12.00'))
        db_session.add(cat)
        db_session.commit()
        assert cat.transaction_nature == 'regular'

    def test_change_request_persists(self, db_session, admin_user):
        cr = SalesVATCategoryChangeRequest(action='create', status='pending',
                                           proposed_data='{"code": "SVAT-G"}',
                                           requested_by_id=admin_user.id)
        db_session.add(cr)
        db_session.commit()
        assert cr.id is not None
        assert cr.status == 'pending'

    def test_output_vat_account_relationship_resolves(self, db_session):
        acct = Account(code='2100', name='Output Tax', account_type='Liability',
                       classification='Current', normal_balance='credit', is_active=True)
        db_session.add(acct)
        db_session.flush()
        cat = SalesVATCategory(code='SVAT-G', name='Goods', rate=Decimal('12.00'),
                               transaction_nature='regular',
                               output_vat_account_id=acct.id)
        db_session.add(cat)
        db_session.commit()
        assert cat.output_vat_account is not None
        assert cat.output_vat_account.code == '2100'

    def test_to_dict_emits_output_account_fields(self, db_session):
        acct = Account(code='2100', name='Output Tax', account_type='Liability',
                       classification='Current', normal_balance='credit', is_active=True)
        db_session.add(acct)
        db_session.flush()
        cat = SalesVATCategory(code='SVAT-G', name='Goods', rate=Decimal('12.00'),
                               transaction_nature='regular',
                               output_vat_account_id=acct.id)
        db_session.add(cat)
        db_session.commit()
        d = cat.to_dict()
        assert d['output_vat_account_id'] == acct.id
        assert d['output_vat_account_code'] == '2100'
        assert d['output_vat_account_name'] == 'Output Tax'

        cat_no_acct = SalesVATCategory(code='SVAT-Z', name='Zero-rated',
                                       rate=Decimal('0.00'),
                                       transaction_nature='zero_export')
        db_session.add(cat_no_acct)
        db_session.commit()
        d2 = cat_no_acct.to_dict()
        assert 'output_vat_account_id' in d2
        assert d2['output_vat_account_id'] is None
        assert 'output_vat_account_code' in d2
        assert d2['output_vat_account_code'] is None
        assert 'output_vat_account_name' in d2
        assert d2['output_vat_account_name'] is None
