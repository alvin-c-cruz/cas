from decimal import Decimal
from app import db
from app.accounts.models import Account
from app.utils.cache_helpers import get_sales_vat_categories, clear_sales_vat_cache
from app.sales_vat_categories.models import SalesVATCategory


def test_get_and_clear_sales_vat_cache(db_session):
    clear_sales_vat_cache()
    db_session.add(SalesVATCategory(code='SVAT-G', name='Goods', rate=Decimal('12.00'),
                                    transaction_nature='regular', is_active=True))
    db_session.commit()
    rows = get_sales_vat_categories()
    assert any(r.code == 'SVAT-G' for r in rows)
    clear_sales_vat_cache()  # must not raise


def test_cached_sales_vat_to_dict_safe_after_session_detach(db_session):
    """Regression: cached SalesVATCategory ORM objects outlive their session.
    to_dict() reads output_vat_account.code/name (a relationship); the cached
    helper must eager-load it so a detached read does not raise
    DetachedInstanceError -- the HTTP-500 that broke /sales-orders/create on
    every request after the 1-hour memoize cache warmed."""
    clear_sales_vat_cache()
    acct = Account(code='21050', name='Output VAT Payable', account_type='Liability',
                   normal_balance='Credit', is_active=True)
    db.session.add(acct)
    db.session.commit()
    db.session.add(SalesVATCategory(code='V12', name='Vatable 12%', rate=Decimal('12.00'),
                                    transaction_nature='regular',
                                    output_vat_account_id=acct.id, is_active=True))
    db.session.commit()
    clear_sales_vat_cache()

    get_sales_vat_categories()     # populate the cache with ORM objects
    db.session.expunge_all()       # detach them, as request/test teardown does

    # Reading the cached (now detached) objects must NOT raise DetachedInstanceError.
    dicts = {v.code: v.to_dict() for v in get_sales_vat_categories()}
    assert dicts['V12']['output_vat_account_code'] == '21050'
    assert dicts['V12']['output_vat_account_name'] == 'Output VAT Payable'
