from decimal import Decimal
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
