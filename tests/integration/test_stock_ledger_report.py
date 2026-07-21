from decimal import Decimal
from app import db
from app.stock_adjustments.service import post_movement
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache


def _enable_stock_adjustments():
    AppSettings.set_setting('module_enabled:inventory', '1', updated_by='t')
    AppSettings.set_setting('module_enabled:stock_adjustments', '1', updated_by='t')
    clear_module_config_cache()


def test_stock_ledger_lists_movements_with_running_balance(
        client, admin_user, login_user, db_session, product_tracked, branch_main):
    _enable_stock_adjustments()
    post_movement(product_tracked, branch_main.id, 'adjustment', Decimal('10'), Decimal('5.00'),
                  'stock_adjustment', 1, 'seed', admin_user)
    db.session.commit()
    login_user(client, 'admin', 'admin123')
    resp = client.get(f'/reports/stock-ledger?product_id={product_tracked.id}')
    assert resp.status_code == 200
    assert b'10.0000' in resp.data or b'10.00' in resp.data   # qty appears
    assert b'50.00' in resp.data                               # running value 10*5


def test_stock_ledger_module_gated(client, admin_user, login_user, db_session, branch_main):
    """branch_main is required so admin (full-access) has an accessible branch to
    auto-select -- with zero branches in the DB the before_request branch gate
    force-logs the user out before this view is even reached.

    The app-wide enforce_module_access before_request hook (app/__init__.py) already
    404s any request whose endpoint maps to a module disabled at the instance level --
    for EVERY role, including admin -- before this view's own module_enabled() check
    ever runs, so a disabled 'stock_adjustments' module means 404 here, not the view's
    in-view flash/redirect (that in-view check is defense-in-depth for the same rule,
    e.g. an endpoint reachable without matching module_key_for_endpoint())."""
    AppSettings.set_setting('module_enabled:stock_adjustments', '0', updated_by='t')
    clear_module_config_cache()
    login_user(client, 'admin', 'admin123')
    resp = client.get('/reports/stock-ledger')
    assert resp.status_code == 404


def test_stock_ledger_print_and_export(
        client, admin_user, login_user, db_session, product_tracked, branch_main):
    _enable_stock_adjustments()
    post_movement(product_tracked, branch_main.id, 'adjustment', Decimal('10'), Decimal('5.00'),
                  'stock_adjustment', 1, 'seed', admin_user)
    db.session.commit()
    login_user(client, 'admin', 'admin123')
    print_resp = client.get(f'/reports/stock-ledger/print?product_id={product_tracked.id}')
    assert print_resp.status_code == 200
    assert b'50.00' in print_resp.data

    excel_resp = client.get(f'/reports/stock-ledger/export/excel?product_id={product_tracked.id}')
    assert excel_resp.status_code == 200
    assert excel_resp.headers['Content-Type'].startswith(
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


def test_stock_ledger_branch_scoped(
        client, admin_user, login_user, db_session, product_tracked, branch_main, accountant_user):
    """A branch-scoped accountant with no access to branch_main sees no movements for it.
    stock_adjustments is an optional, non-per_user module -- default_all_permissions()
    excludes it, so it must be explicitly granted here (independent of branch access) for
    the accountant to reach the report at all."""
    _enable_stock_adjustments()
    perms = accountant_user.get_book_permissions()
    perms['stock_adjustments'] = True
    accountant_user.set_book_permissions(perms)
    db.session.commit()
    post_movement(product_tracked, branch_main.id, 'adjustment', Decimal('10'), Decimal('5.00'),
                  'stock_adjustment', 1, 'seed', admin_user)
    db.session.commit()
    login_user(client, 'accountant', 'accountant123')
    resp = client.get(f'/reports/stock-ledger?product_id={product_tracked.id}')
    assert resp.status_code == 200
    assert b'50.00' not in resp.data


def test_stock_ledger_branch_filter_narrows_to_selected_branch(
        client, admin_user, login_user, db_session, product_tracked,
        branch_main, branch_manila):
    """Review finding: the spec says the report is 'optionally filtered by
    branch' -- it previously only showed a Branch column with zero query-
    string filter. Post movements for the same product in two branches;
    filtering by branch_id must narrow to just that branch's rows, and
    omitting the param must show both (the existing default, unchanged)."""
    _enable_stock_adjustments()
    post_movement(product_tracked, branch_main.id, 'adjustment', Decimal('10'), Decimal('5.00'),
                  'stock_adjustment', 1, 'seed main', admin_user)
    post_movement(product_tracked, branch_manila.id, 'adjustment', Decimal('20'), Decimal('7.00'),
                  'stock_adjustment', 2, 'seed manila', admin_user)
    db.session.commit()
    login_user(client, 'admin', 'admin123')
    client.post('/select-branch', data={'branch_id': branch_main.id})

    # No branch_id -- both branches' movements appear (unchanged default).
    all_resp = client.get(f'/reports/stock-ledger?product_id={product_tracked.id}')
    assert all_resp.status_code == 200
    assert branch_main.name.encode() in all_resp.data
    assert branch_manila.name.encode() in all_resp.data

    # branch_id=branch_main.id -- only that branch's movement/value appears.
    main_resp = client.get(
        f'/reports/stock-ledger?product_id={product_tracked.id}&branch_id={branch_main.id}')
    assert main_resp.status_code == 200
    assert b'50.00' in main_resp.data      # 10 * 5.00, main branch
    assert b'140.00' not in main_resp.data  # 20 * 7.00, manila branch -- must NOT appear

    # branch_id=branch_manila.id -- only Manila's movement/value appears.
    manila_resp = client.get(
        f'/reports/stock-ledger?product_id={product_tracked.id}&branch_id={branch_manila.id}')
    assert manila_resp.status_code == 200
    assert b'140.00' in manila_resp.data
    assert b'50.00' not in manila_resp.data
