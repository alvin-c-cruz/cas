"""Regression tests for BUG-SO-MONITORING-NOT-IN-SIDEBAR: the Order Monitoring report must
have its own sidebar link, gated by the same `sales_orders` module permission as the Sales
Orders link itself (no separate grantable permission)."""
from app.users.module_access import MODULE_REGISTRY
from app.settings import AppSettings


def test_order_monitoring_not_a_new_module_registry_key():
    keys = {m['key'] for m in MODULE_REGISTRY}
    assert 'so_monitoring' not in keys and 'order_monitoring' not in keys, (
        'Order Monitoring must reuse the existing sales_orders module key, not register '
        'as its own independently-grantable module')


def test_sidebar_shows_order_monitoring_link_for_user_with_sales_orders_access(
        client, admin_user, main_branch):
    AppSettings.set_setting('module_enabled:sales_orders', '1')
    with client:
        client.post('/login', data={'username': admin_user.username,
                                    'password': 'admin123'}, follow_redirects=True)
        resp = client.get('/dashboard')
        assert resp.status_code == 200
        body = resp.data.decode('utf-8')
        assert 'sales_orders.monitor' in body or 'sales-orders/monitor' in body, (
            'Order Monitoring link must appear in the sidebar for a user with Sales Orders access')
        assert 'Order Monitoring' in body
