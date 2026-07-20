from decimal import Decimal
from app.accounts.models import Account
from app.sales_vat_categories.models import (
    SalesVATCategory, SalesVATCategoryChangeRequest,
    SALES_NATURES, SALES_NATURE_LABELS, format_sales_nature,
)


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


class TestSalesNatures:
    def test_five_natures_defined(self):
        assert SALES_NATURES == (
            'regular', 'zero_export', 'zero_other', 'exempt', 'government',
        )

    def test_labels_have_exactly_one_entry_per_nature(self):
        """SALES_NATURE_LABELS must never drift from SALES_NATURES -- exactly
        one label per defined nature, no more, no fewer."""
        assert set(SALES_NATURE_LABELS.keys()) == set(SALES_NATURES)
        assert len(SALES_NATURE_LABELS) == len(SALES_NATURES)


class TestFormatSalesNature:
    """BUG-SALES-VAT-NATURE-RAW-VALUE: the list page rendered the bare DB
    token ('regular') instead of a friendly label. format_sales_nature is the
    fix's formatting function -- mirrors format_purchase_nature's None vs.
    unrecognized-token distinction."""

    def test_none_renders_unclassified(self):
        assert format_sales_nature(None) == '(unclassified)'

    def test_recognized_value_renders_its_label(self):
        assert format_sales_nature('regular') == 'Regular VATable'
        assert format_sales_nature('zero_export') == SALES_NATURE_LABELS['zero_export']

    def test_unrecognized_value_renders_distinctly_from_unclassified(self):
        result = format_sales_nature('some_stale_token')
        assert result != '(unclassified)'
        assert 'some_stale_token' in result
