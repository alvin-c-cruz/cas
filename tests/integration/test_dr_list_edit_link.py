"""The DR list should offer an Edit link for DRAFT rows (edit is draft-only; the route
existed but was only reachable from the detail page)."""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.customers.models import Customer
from app.products.models import Product
from app.sales_orders.models import SalesOrder, SalesOrderItem
from app.delivery_receipts.models import DeliveryReceipt

pytestmark = [pytest.mark.integration, pytest.mark.delivery_receipts]


@pytest.fixture(autouse=True)
def dr_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:delivery_receipts', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, u):
    with client.session_transaction() as s:
        s['_user_id'] = str(u.id); s['_fresh'] = True


def _dr(branch, admin_user, status='draft'):
    c = Customer(code='C1', name='Acme', is_active=True)
    p = Product(code='W', name='Widget', is_active=True)
    db.session.add_all([c, p]); db.session.commit()
    so = SalesOrder(so_number='SO-1', order_date=date(2026, 7, 9), customer_id=c.id,
                    customer_name='Acme', branch_id=branch.id, status='confirmed')
    so.line_items.append(SalesOrderItem(line_number=1, product_id=p.id, quantity=Decimal('10'),
                                        unit_price=Decimal('100'), amount=Decimal('1000')))
    db.session.add(so); db.session.commit()
    dr = DeliveryReceipt(dr_number='DR-1', branch_id=branch.id, delivery_date=date(2026, 7, 9),
                         sales_order_id=so.id, customer_id=c.id, customer_name='Acme',
                         status=status, created_by_id=admin_user.id)
    db.session.add(dr); db.session.commit()
    return dr


def test_list_shows_edit_link_for_draft(client, db_session, admin_user, main_branch):
    dr = _dr(main_branch, admin_user, status='draft')
    _login(client, admin_user)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    resp = client.get('/delivery-receipts')
    assert resp.status_code == 200
    assert f'/delivery-receipts/{dr.id}/edit'.encode() in resp.data


def test_list_hides_edit_link_for_non_draft(client, db_session, admin_user, main_branch):
    dr = _dr(main_branch, admin_user, status='approved')
    _login(client, admin_user)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    resp = client.get('/delivery-receipts')
    assert resp.status_code == 200
    assert f'/delivery-receipts/{dr.id}/edit'.encode() not in resp.data
