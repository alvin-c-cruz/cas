"""Integration tests for the area-based dynamic sidebar tree (Task 3, P-59).

Verifies that build_sidebar is exposed to templates and that the area → group → module
tree renders correctly in base.html for different user roles.
"""
import pytest

pytestmark = [pytest.mark.integration]


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def test_sidebar_renders_area_headers(client, db_session, admin_user, main_branch):
    """Admin sees the four core area headers in the dynamic sidebar.

    Inventory is intentionally absent — products and UOM are optional modules
    with default_enabled=False so they are disabled in a fresh test DB.
    """
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    html = client.get('/dashboard').data.decode()

    # Each core area renders a data-area attribute in the new markup
    for area in ('Sales', 'Purchases', 'Accounting', 'Compliance'):
        assert f'data-area="{area.lower()}"' in html, (
            f"Area '{area}' missing from sidebar (data-area attribute not found)"
        )

    # Representative module links within those areas
    assert 'Sales Orders' in html, 'Sales Orders link missing from Sales area'
    assert 'Chart of Accounts' in html, 'Chart of Accounts link missing from Accounting area'
    assert 'Books of Accounts' in html, 'Books of Accounts link missing from Compliance area'

    # Inventory area is absent — optional modules are default_enabled=False
    assert 'data-area="inventory"' not in html, (
        'Inventory area should not appear when products/UOM are disabled'
    )


def test_all_modules_enabled_dashboard_200(client, db_session, admin_user, main_branch):
    """Guard: enabling ALL optional modules must not cause a 500 on /dashboard.

    The _nav_ep/_nav_icon Jinja maps in base.html must cover every MODULE_REGISTRY key.
    A missing entry causes url_for(undefined) → UndefinedError → 500 on every page.
    All five areas (Sales, Purchases, Inventory, Accounting, Compliance) must render.
    """
    from app.settings import AppSettings
    from app.users.module_access import MODULE_REGISTRY
    from app.utils.cache_helpers import clear_module_config_cache

    for m in MODULE_REGISTRY:
        if m.get('optional'):
            AppSettings.set_setting(f'module_enabled:{m["key"]}', '1')
    clear_module_config_cache()

    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/dashboard')
    assert resp.status_code == 200, "Dashboard returned non-200 — check _nav_ep/_nav_icon maps in base.html"

    html = resp.data.decode()
    for area in ('sales', 'purchases', 'inventory', 'accounting', 'compliance'):
        assert f'data-area="{area}"' in html, f"Area '{area}' missing after enabling all modules"

    # Clear module config cache so optional-module state doesn't leak into later tests
    # that rely on the default (disabled) state of Inventory modules.
    clear_module_config_cache()


def test_sidebar_hides_area_with_no_access(client, db_session, accountant_user, main_branch):
    """An area with no accessible modules is completely absent from the sidebar.

    accountant_user has default_all_permissions (all non-optional modules granted).
    The Inventory area requires products + units_of_measure, both optional and
    default_enabled=False, so it should be absent.  The Sales area should be
    visible because accounts_receivable, collections, customers, and sales_orders
    are all non-optional and granted.
    """
    _login(client, accountant_user)
    _select_branch(client, main_branch.id)
    html = client.get('/dashboard').data.decode()

    # Positive: accountant can see Sales area (AR, collections, customers, SO all granted)
    assert 'data-area="sales"' in html, (
        'Sales area should be visible for accountant with default_all_permissions'
    )

    # Absence: Inventory area is entirely absent (disabled optional modules)
    assert 'data-area="inventory"' not in html, (
        'Inventory area must not render when UOM and Products are disabled'
    )
