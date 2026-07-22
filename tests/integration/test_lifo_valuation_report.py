from datetime import datetime
from decimal import Decimal
from app import db
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache

D = Decimal


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _enable_stock_adjustments():
    # stock_adjustments is an optional module, default-off in the test DB (see
    # tests/integration/test_fifo_layers_report.py's own _enable_stock_adjustments) --
    # the brief's test snippet omitted this (and login) and would 302 without it.
    AppSettings.set_setting('module_enabled:inventory', '1', updated_by='t')
    AppSettings.set_setting('module_enabled:stock_adjustments', '1', updated_by='t')
    clear_module_config_cache()


def test_lifo_valuation_report_shows_current_tab_layers(client, db_session, admin_user, branch_main):
    from app.products.models import Product
    from app.stock_adjustments.models import StockMovement
    _enable_stock_adjustments()
    product = Product(code='LIFO-RPT-1', name='LIFO Report Item', track_inventory=True,
                      costing_method='lifo', standard_cost=None, is_active=True)
    db.session.add(product); db.session.commit()
    mv = StockMovement(product_id=product.id, branch_id=branch_main.id, movement_type='receipt',
                       quantity=D('5'), unit_cost=D('7.50'), balance_qty_after=D('5'),
                       balance_avg_cost_after=D('7.50'), balance_value_after=D('37.50'),
                       created_at=datetime(2026, 1, 1), created_by_id=admin_user.id)
    db.session.add(mv); db.session.commit()

    _login(client, admin_user, branch_main)
    resp = client.get(f'/reports/lifo-valuation?product_id={product.id}&branch_id={branch_main.id}')
    assert resp.status_code == 200
    assert b'7.50' in resp.data
    assert b'Internal management view only' in resp.data


def test_lifo_valuation_report_cogs_tab_shows_variance(client, db_session, admin_user, branch_main):
    from app.products.models import Product
    from app.stock_adjustments.models import StockMovement
    _enable_stock_adjustments()
    product = Product(code='LIFO-RPT-2', name='LIFO Report COGS Item', track_inventory=True,
                      costing_method='lifo', standard_cost=None, is_active=True)
    db.session.add(product); db.session.commit()
    receipt = StockMovement(product_id=product.id, branch_id=branch_main.id, movement_type='receipt',
                            quantity=D('5'), unit_cost=D('4.00'), balance_qty_after=D('5'),
                            balance_avg_cost_after=D('4.00'), balance_value_after=D('20.00'),
                            created_at=datetime(2026, 1, 1), created_by_id=admin_user.id)
    db.session.add(receipt); db.session.commit()
    issue = StockMovement(product_id=product.id, branch_id=branch_main.id, movement_type='issue',
                          quantity=D('-2'), unit_cost=D('4.00'), balance_qty_after=D('3'),
                          balance_avg_cost_after=D('4.00'), balance_value_after=D('12.00'),
                          created_at=datetime(2026, 2, 1), created_by_id=admin_user.id)
    db.session.add(issue); db.session.commit()

    _login(client, admin_user, branch_main)
    resp = client.get(f'/reports/lifo-valuation/cogs?product_id={product.id}&branch_id={branch_main.id}'
                      f'&start_date=2026-02-01&end_date=2026-02-28')
    assert resp.status_code == 200
    assert b'8.00' in resp.data  # LIFO cost: 2 @ 4.00


def test_lifo_valuation_report_export_excel(client, db_session, admin_user, branch_main):
    from app.products.models import Product
    from app.stock_adjustments.models import StockMovement
    _enable_stock_adjustments()
    product = Product(code='LIFO-RPT-3', name='LIFO Report Excel Item', track_inventory=True,
                      costing_method='lifo', standard_cost=None, is_active=True)
    db.session.add(product); db.session.commit()
    mv = StockMovement(product_id=product.id, branch_id=branch_main.id, movement_type='receipt',
                       quantity=D('5'), unit_cost=D('4.00'), balance_qty_after=D('5'),
                       balance_avg_cost_after=D('4.00'), balance_value_after=D('20.00'),
                       created_at=datetime(2026, 1, 1), created_by_id=admin_user.id)
    db.session.add(mv); db.session.commit()

    _login(client, admin_user, branch_main)
    resp = client.get(f'/reports/lifo-valuation/export/excel?product_id={product.id}&branch_id={branch_main.id}')
    assert resp.status_code == 200
    assert resp.mimetype == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def test_lifo_valuation_report_cogs_export_excel(client, db_session, admin_user, branch_main):
    # The approved Task 3 mockup shows "Export to Excel" on BOTH tabs (plan line 444), but
    # Task 4's own build spec (plan line 688) only wired up Tab 1 -- a genuine plan-authoring
    # gap, not an implementer shortcut. Fixed by the controller before final review: the COGS
    # tab gets its own export route mirroring the Tab 1 one exactly.
    from app.products.models import Product
    from app.stock_adjustments.models import StockMovement
    _enable_stock_adjustments()
    product = Product(code='LIFO-RPT-4', name='LIFO Report COGS Excel Item', track_inventory=True,
                      costing_method='lifo', standard_cost=None, is_active=True)
    db.session.add(product); db.session.commit()
    receipt = StockMovement(product_id=product.id, branch_id=branch_main.id, movement_type='receipt',
                            quantity=D('5'), unit_cost=D('4.00'), balance_qty_after=D('5'),
                            balance_avg_cost_after=D('4.00'), balance_value_after=D('20.00'),
                            created_at=datetime(2026, 1, 1), created_by_id=admin_user.id)
    db.session.add(receipt); db.session.commit()
    issue = StockMovement(product_id=product.id, branch_id=branch_main.id, movement_type='issue',
                          quantity=D('-2'), unit_cost=D('4.00'), balance_qty_after=D('3'),
                          balance_avg_cost_after=D('4.00'), balance_value_after=D('12.00'),
                          created_at=datetime(2026, 2, 1), created_by_id=admin_user.id)
    db.session.add(issue); db.session.commit()

    _login(client, admin_user, branch_main)
    resp = client.get(f'/reports/lifo-valuation/cogs/export/excel?product_id={product.id}'
                      f'&branch_id={branch_main.id}&start_date=2026-02-01&end_date=2026-02-28')
    assert resp.status_code == 200
    assert resp.mimetype == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
