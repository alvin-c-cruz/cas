import pytest

from app.common.vat_nature import resolve_sales_nature, resolve_purchase_nature
from app.vat_categories.models import VATCategory
from app.sales_vat_categories.models import SalesVATCategory
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
from tests.integration.test_accounts_payable_vat_buckets import setup_world, post_bill, login

pytestmark = [pytest.mark.accounts_payable, pytest.mark.integration]


class TestNatureResolvers:
    def test_sales_code_resolves(self, db_session):
        db_session.add(SalesVATCategory(code='V12', name='Vatable', rate=12,
                                        transaction_nature='regular', is_active=True))
        db_session.commit()
        assert resolve_sales_nature('V12') == 'regular'

    def test_purchase_code_resolves(self, db_session):
        db_session.add(VATCategory(code='V12SV', name='Services', rate=12,
                                   transaction_nature='domestic_services', is_active=True))
        db_session.commit()
        assert resolve_purchase_nature('V12SV') == 'domestic_services'

    def test_empty_code_is_none(self, db_session):
        assert resolve_sales_nature('') is None
        assert resolve_purchase_nature('') is None
        assert resolve_sales_nature(None) is None
        assert resolve_purchase_nature(None) is None

    def test_unmatched_code_is_none(self, db_session):
        assert resolve_purchase_nature('NOPE') is None

    def test_category_with_null_nature_yields_none(self, db_session):
        db_session.add(VATCategory(code='LEGACY', name='Legacy', rate=0,
                                   transaction_nature=None, is_active=True))
        db_session.commit()
        assert resolve_purchase_nature('LEGACY') is None


class TestVatNatureOnPost:
    """A freshly posted AP line snapshots vat_nature at build time (not just history)."""

    def test_ap_line_carries_resolved_nature(self, client, db_session,
                                             admin_user, main_branch):
        w = setup_world(db_session)
        # setup_world's V12SV category doesn't set a nature; give it one so the
        # resolver has something real to find.
        sv_cat = VATCategory.query.filter_by(code='V12SV').first()
        sv_cat.transaction_nature = 'domestic_services'
        db_session.commit()

        login(client)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        post_bill(client, w['vendor'], [
            {'description': 'services', 'amount': 560.0, 'vat_category': 'V12SV',
             'account_id': w['69903'].id, 'wt_id': None, 'wt_rate': None},
        ], number='AP-NATURE-0001')

        bill = AccountsPayable.query.order_by(AccountsPayable.id.desc()).first()
        assert bill is not None
        item = AccountsPayableItem.query.filter_by(ap_id=bill.id).first()
        assert item is not None
        assert item.vat_category == 'V12SV'
        assert item.vat_nature == 'domestic_services'
