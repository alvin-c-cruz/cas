from app.fixed_assets.models import AssetCategory
from app.audit.models import AuditLog


def test_create_asset_category(client, db_session, accountant_user, login_user):
    login_user(client, 'accountant', 'accountant123')
    resp = client.post('/fixed-assets/categories/create', data={
        'name': 'Office Equipment',
        'default_useful_life_months': '60',
        'default_depreciation_method': 'straight_line',
        'is_active': '1',
    }, follow_redirects=True)
    assert resp.status_code == 200
    cat = AssetCategory.query.filter_by(name='Office Equipment').first()
    assert cat is not None
    assert cat.default_useful_life_months == 60
    log = AuditLog.query.filter_by(module='asset_categories', action='create',
                                    record_id=cat.id).first()
    assert log is not None


def test_staff_cannot_create_asset_category(client, db_session, staff_user, main_branch,
                                             login_user):
    staff_user.set_branches([main_branch])
    db_session.commit()
    login_user(client, 'staff', 'staff123')
    resp = client.post('/fixed-assets/categories/create', data={
        'name': 'Furniture', 'is_active': '1',
    }, follow_redirects=True)
    assert AssetCategory.query.filter_by(name='Furniture').first() is None
    assert b'permission' in resp.data.lower()


def test_edit_asset_category(client, db_session, accountant_user, login_user):
    cat = AssetCategory(name='Vehicles', default_useful_life_months=60)
    db_session.add(cat)
    db_session.commit()
    login_user(client, 'accountant', 'accountant123')
    resp = client.post(f'/fixed-assets/categories/{cat.id}/edit', data={
        'name': 'Transportation Equipment',
        'default_useful_life_months': '84',
        'default_depreciation_method': 'straight_line',
        'is_active': '1',
    }, follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(cat)
    assert cat.name == 'Transportation Equipment'
    assert cat.default_useful_life_months == 84
