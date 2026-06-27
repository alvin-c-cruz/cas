from app import db
from app.products.models import Product
from app.units_of_measure.models import UnitOfMeasure
from app.utils.cache_helpers import get_active_products, clear_product_cache


def test_get_active_products_excludes_inactive_and_caches(db_session):
    db.session.add(Product(code='A', name='Active', is_active=True))
    db.session.add(Product(code='B', name='Gone', is_active=False))
    db.session.commit()
    clear_product_cache()
    codes = [p.code for p in get_active_products()]
    assert 'A' in codes and 'B' not in codes


def test_cached_products_to_dict_safe_after_session_detach(db_session):
    """Regression: cached Product ORM objects outlive their session. to_dict()
    reads default_unit_of_measure.code (a relationship); get_active_products must
    eager-load it so a detached read does not raise DetachedInstanceError (the
    HTTP-500 that broke every document form render once products existed)."""
    uom = UnitOfMeasure(code='pcs', name='Pieces', is_active=True)
    db.session.add(uom)
    db.session.commit()
    db.session.add(Product(code='WID', name='Widget',
                           default_unit_of_measure_id=uom.id, is_active=True))
    db.session.commit()
    clear_product_cache()

    get_active_products()          # populate the cache with ORM objects
    db.session.expunge_all()       # detach them, as request/test teardown does

    # Reading the cached (now detached) objects must NOT raise DetachedInstanceError.
    dicts = [p.to_dict() for p in get_active_products()]
    assert dicts[0]['default_uom_code'] == 'pcs'
