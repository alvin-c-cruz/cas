from app.fixed_assets.models import AssetCategory
from app.audit.models import AuditLog


def _enable_fixed_assets_for(user, db_session):
    """Task 12 gated fixed_assets (optional, default_enabled=False, not per_user in the
    registry). These Tasks 1-11 tests predate that gate. Turn the module on at the
    instance level AND grant this user the book permission directly -- module_enabled
    alone isn't enough: can_access_module still checks book_permissions for a
    non-full-access role (mirrors _fixed_assets_module_enabled in
    test_fixed_assets_views.py)."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:fixed_assets', '1')
    db_session.commit()
    clear_module_config_cache()
    perms = user.get_book_permissions()
    perms['fixed_assets'] = True
    user.set_book_permissions(perms)
    db_session.commit()


def test_create_asset_category(client, db_session, accountant_user, login_user):
    _enable_fixed_assets_for(accountant_user, db_session)
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
    # Module access granted (so the module gate lets staff through) -- this test targets
    # the view's OWN role decorator (accountant_or_admin_required), not the module gate.
    _enable_fixed_assets_for(staff_user, db_session)
    staff_user.set_branches([main_branch])
    db_session.commit()
    login_user(client, 'staff', 'staff123')
    resp = client.post('/fixed-assets/categories/create', data={
        'name': 'Furniture', 'is_active': '1',
    }, follow_redirects=True)
    assert AssetCategory.query.filter_by(name='Furniture').first() is None
    assert b'permission' in resp.data.lower()


def test_edit_asset_category(client, db_session, accountant_user, login_user):
    _enable_fixed_assets_for(accountant_user, db_session)
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
    log = AuditLog.query.filter_by(module='asset_categories', action='update',
                                    record_id=cat.id).first()
    assert log is not None
