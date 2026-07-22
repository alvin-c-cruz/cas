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
    # tests/integration/test_stock_ledger_report.py's own _enable_stock_adjustments) --
    # the brief's test snippet omitted this and would 302 to the dashboard without it.
    AppSettings.set_setting('module_enabled:inventory', '1', updated_by='t')
    AppSettings.set_setting('module_enabled:stock_adjustments', '1', updated_by='t')
    clear_module_config_cache()


def test_fifo_layers_report_shows_open_and_deficit_layers(client, db_session, admin_user, branch_main):
    from app.products.models import Product
    from app.stock_adjustments.service import post_movement
    _enable_stock_adjustments()
    product = Product(code='FIFOLR-1', name='FIFO Layers Report Item', track_inventory=True,
                      costing_method='fifo', standard_cost=None, is_active=True)
    db.session.add(product); db.session.commit()
    post_movement(product, branch_main.id, 'receipt', D('5'), D('4.00'),
                  'test_doc', 1, 'r1', admin_user)
    db.session.commit()
    post_movement(product, branch_main.id, 'issue', D('-8'), None,
                  'test_doc', 2, 'issue', admin_user)   # drains it + deficits
    db.session.commit()

    _login(client, admin_user, branch_main)
    resp = client.get(f'/reports/fifo-layers?product_id={product.id}')
    assert resp.status_code == 200
    assert b'4.00' in resp.data          # the layer's unit cost
    assert b'-3.0000' in resp.data or b'-3' in resp.data   # the deficit remaining_qty is shown


def test_fifo_layers_report_excel_export(client, db_session, admin_user, branch_main):
    from app.products.models import Product
    from app.stock_adjustments.service import post_movement
    _enable_stock_adjustments()
    product = Product(code='FIFOLR-2', name='FIFO Layers Report Excel Item', track_inventory=True,
                      costing_method='fifo', standard_cost=None, is_active=True)
    db.session.add(product); db.session.commit()
    post_movement(product, branch_main.id, 'receipt', D('5'), D('4.00'),
                  'test_doc', 1, 'r1', admin_user)
    db.session.commit()

    _login(client, admin_user, branch_main)
    resp = client.get(f'/reports/fifo-layers/export/excel?product_id={product.id}')
    assert resp.status_code == 200
    assert resp.mimetype == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
