"""Unit tests for the ProductCategory master model."""
import pytest
from app import db
from app.product_categories.models import ProductCategory


@pytest.mark.unit
@pytest.mark.models
class TestProductCategoryModel:
    def test_create_and_to_dict(self, db_session):
        c = ProductCategory(code='BEV', name='Beverages', is_active=True)
        db.session.add(c)
        db.session.commit()
        d = c.to_dict()
        assert d['code'] == 'BEV'
        assert d['name'] == 'Beverages'
        assert d['is_active'] is True
        assert 'id' in d and d['id'] == c.id

    def test_code_is_unique(self, db_session):
        db.session.add(ProductCategory(code='SNK', name='Snacks'))
        db.session.commit()
        db.session.add(ProductCategory(code='SNK', name='Snacks 2'))
        with pytest.raises(Exception):
            db.session.commit()
        db.session.rollback()

    def test_cache_helper_returns_active_only(self, db_session):
        from app.utils.cache_helpers import (get_active_product_categories,
                                             clear_product_category_cache)
        db.session.add(ProductCategory(code='AAA', name='Active One', is_active=True))
        db.session.add(ProductCategory(code='BBB', name='Inactive One', is_active=False))
        db.session.commit()
        clear_product_category_cache()
        codes = [c.code for c in get_active_product_categories()]
        assert 'AAA' in codes
        assert 'BBB' not in codes
