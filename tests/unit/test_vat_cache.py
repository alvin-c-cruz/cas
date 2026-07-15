from decimal import Decimal
from app import db
from app.accounts.models import Account
from app.utils.cache_helpers import get_vat_categories, clear_vat_cache
from app.vat_categories.models import VATCategory


def test_get_and_clear_vat_cache(db_session):
    clear_vat_cache()
    db_session.add(VATCategory(code='VC-G', name='Goods', rate=Decimal('12.00'),
                                transaction_nature='domestic_goods', is_active=True))
    db_session.commit()
    rows = get_vat_categories()
    assert any(r.code == 'VC-G' for r in rows)
    clear_vat_cache()  # must not raise


def test_cached_vat_to_dict_safe_after_session_detach(db_session):
    """Regression: cached VATCategory ORM objects outlive their session. to_dict()
    reads input_vat_account.code/name (a relationship); the cached helper must
    eager-load it so a detached read does not raise DetachedInstanceError -- the
    HTTP-500 that broke /purchase-orders/create and /purchase-orders/<id>/edit
    on every request after the 1-hour memoize cache warmed and an accountant
    assigned a real input_vat_account to a VAT category. Sibling of the already-
    fixed get_sales_vat_categories() (test_sales_vat_cache.py)."""
    clear_vat_cache()
    acct = Account(code='21040', name='Input VAT', account_type='Asset',
                   normal_balance='Debit', is_active=True)
    db.session.add(acct)
    db.session.commit()
    db.session.add(VATCategory(code='V12', name='Vatable 12%', rate=Decimal('12.00'),
                                transaction_nature='domestic_goods',
                                input_vat_account_id=acct.id, is_active=True))
    db.session.commit()
    clear_vat_cache()

    get_vat_categories()       # populate the cache with ORM objects
    db.session.expunge_all()   # detach them, as request/test teardown does

    # Reading the cached (now detached) objects must NOT raise DetachedInstanceError.
    dicts = {v.code: v.to_dict() for v in get_vat_categories()}
    assert dicts['V12']['input_vat_account_code'] == '21040'
    assert dicts['V12']['input_vat_account_name'] == 'Input VAT'
