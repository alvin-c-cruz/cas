from app.users.module_access import MODULE_REGISTRY, all_permission_keys


def test_stock_adjustments_module_registered():
    entry = next((m for m in MODULE_REGISTRY if m['key'] == 'stock_adjustments'), None)
    assert entry is not None
    assert entry['optional'] and entry['default_enabled'] is False
    assert 'inventory' in entry['depends_on']
    assert entry['area'] == 'Inventory'


def test_stock_adjustments_is_per_user_grantable():
    """stock_adjustments must set per_user=True (like its Transactions/Documents-section
    siblings bank_accounts, petty_cash, bill_of_materials, etc.) so a plain accountant can
    be individually granted access via Company Settings -- an optional module without
    per_user is silently excluded from all_permission_keys()/default_all_permissions(),
    making it admin/chief-accountant-only in practice regardless of what an admin grants."""
    entry = next((m for m in MODULE_REGISTRY if m['key'] == 'stock_adjustments'), None)
    assert entry is not None
    assert entry.get('per_user') is True
    assert 'stock_adjustments' in all_permission_keys()


def test_index_blocked_when_module_disabled(client, admin_user, login_user):
    login_user(client, 'admin', 'admin123')
    # module default-off -> the list route should not be reachable (redirect/403/404)
    resp = client.get('/stock-adjustments/', follow_redirects=False)
    assert resp.status_code in (302, 403, 404)
