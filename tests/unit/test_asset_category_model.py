from app.fixed_assets.models import AssetCategory


def test_asset_category_to_dict(db_session):
    cat = AssetCategory(name='Office Equipment', default_useful_life_months=60,
                        default_depreciation_method='straight_line')
    db_session.add(cat)
    db_session.commit()

    d = cat.to_dict()
    assert d['name'] == 'Office Equipment'
    assert d['default_useful_life_months'] == 60
    assert d['default_depreciation_method'] == 'straight_line'
    assert d['is_active'] is True


def test_asset_category_name_unique(db_session):
    db_session.add(AssetCategory(name='Furniture'))
    db_session.commit()
    db_session.add(AssetCategory(name='Furniture'))
    import pytest
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        db_session.commit()
