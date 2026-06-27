from app import db
from app.products.models import Product
from app.utils.cache_helpers import get_active_products, clear_product_cache


def test_get_active_products_excludes_inactive_and_caches(db_session):
    db.session.add(Product(code='A', name='Active', is_active=True))
    db.session.add(Product(code='B', name='Gone', is_active=False))
    db.session.commit()
    clear_product_cache()
    codes = [p.code for p in get_active_products()]
    assert 'A' in codes and 'B' not in codes
