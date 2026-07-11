import pytest

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def po_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _make_draft_po(db_session, branch, vendor):
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    from datetime import date
    po = PurchaseOrder(branch_id=branch.id, po_number='PO-2026-07-0200', order_date=date(2026, 7, 11),
                       vendor_id=vendor.id, vendor_name=vendor.name, status='draft',
                       vat_treatment='inclusive')
    po.line_items.append(PurchaseOrderItem(line_number=1, description='Cement',
                                           quantity=1, unit_price=100, amount=100))
    po.calculate_totals()
    db_session.add(po); db_session.commit()
    return po


def test_sidebar_shows_po_link_when_enabled(client, accountant_user, main_branch, db_session):
    _login(client, accountant_user, main_branch)
    body = client.get('/dashboard').data
    assert b'/purchase-orders' in body
    assert b'Purchase Orders' in body


def test_sidebar_hides_po_link_when_disabled(client, accountant_user, main_branch, db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:purchase_orders', '0')
    db_session.commit(); clear_module_config_cache()
    _login(client, accountant_user, main_branch)
    body = client.get('/dashboard').data
    assert b'/purchase-orders' not in body


def test_print_renders(client, accountant_user, main_branch, vl_vendor, db_session):
    _login(client, accountant_user, main_branch)
    po = _make_draft_po(db_session, main_branch, vl_vendor)
    resp = client.get(f'/purchase-orders/{po.id}/print')
    assert resp.status_code == 200
    assert b'PURCHASE ORDER' in resp.data and b'PO-2026-07-0200' in resp.data
