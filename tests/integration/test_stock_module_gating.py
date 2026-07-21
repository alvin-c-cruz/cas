from app.users.module_access import MODULE_REGISTRY


def test_stock_adjustments_module_registered():
    entry = next((m for m in MODULE_REGISTRY if m['key'] == 'stock_adjustments'), None)
    assert entry is not None
    assert entry['optional'] and entry['default_enabled'] is False
    assert 'inventory' in entry['depends_on']
    assert entry['area'] == 'Inventory'


def test_index_blocked_when_module_disabled(client, admin_user, login_user):
    login_user(client, 'admin', 'admin123')
    # module default-off -> the list route should not be reachable (redirect/403/404)
    resp = client.get('/stock-adjustments/', follow_redirects=False)
    assert resp.status_code in (302, 403, 404)
