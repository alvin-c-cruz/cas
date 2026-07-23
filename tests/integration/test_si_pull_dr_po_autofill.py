"""BUG-SI-PULL-DR-NO-PO-AUTOFILL: billable_drs() must include each DR's
source SO's customer_po_number so the frontend Pull handler can autofill it."""
import pytest
from decimal import Decimal
from datetime import date
from app import db

pytestmark = [pytest.mark.integration]


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def test_billable_drs_includes_customer_po_number(client, db_session, staff_user, main_branch, customer):
    from app.settings import AppSettings
    from app.sales_orders.models import SalesOrder, SalesOrderItem
    from app.delivery_receipts.models import DeliveryReceipt, DeliveryReceiptItem
    AppSettings.set_setting('module_enabled:sales_invoices', '1')
    db_session.commit()

    so = SalesOrder(so_number='SO-PO-0001', order_date=date(2026, 7, 1), customer_id=customer.id,
                    customer_name=customer.name, branch_id=main_branch.id, status='confirmed',
                    customer_po_number='PO-12345')
    li = SalesOrderItem(line_number=1, quantity=Decimal('10'), unit_price=Decimal('5.00'),
                        amount=Decimal('50.00'))
    so.line_items.append(li)
    db_session.add(so); db_session.commit()

    dr = DeliveryReceipt(dr_number='DR-PO-0001', delivery_date=date(2026, 7, 10),
                         sales_order_id=so.id, customer_id=customer.id, customer_name=customer.name,
                         status='delivered', branch_id=main_branch.id)
    db_session.add(dr); db_session.commit()
    dr.line_items.append(DeliveryReceiptItem(line_number=1, sales_order_item_id=li.id,
                                             delivered_quantity=Decimal('10')))
    db_session.commit()

    staff_user.branches.append(main_branch)
    db_session.commit()

    _login(client, staff_user)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    resp = client.get(f'/sales-invoices/billable-drs?customer_id={customer.id}')
    data = resp.get_json()
    assert len(data['drs']) == 1
    assert data['drs'][0]['customer_po_number'] == 'PO-12345'


def test_billable_drs_customer_po_number_null_when_so_has_none(client, db_session, staff_user, main_branch, customer):
    from app.settings import AppSettings
    from app.sales_orders.models import SalesOrder, SalesOrderItem
    from app.delivery_receipts.models import DeliveryReceipt, DeliveryReceiptItem
    AppSettings.set_setting('module_enabled:sales_invoices', '1')
    db_session.commit()

    so = SalesOrder(so_number='SO-PO-0002', order_date=date(2026, 7, 1), customer_id=customer.id,
                    customer_name=customer.name, branch_id=main_branch.id, status='confirmed')
    li = SalesOrderItem(line_number=1, quantity=Decimal('5'), unit_price=Decimal('2.00'),
                        amount=Decimal('10.00'))
    so.line_items.append(li)
    db_session.add(so); db_session.commit()

    dr = DeliveryReceipt(dr_number='DR-PO-0002', delivery_date=date(2026, 7, 10),
                         sales_order_id=so.id, customer_id=customer.id, customer_name=customer.name,
                         status='delivered', branch_id=main_branch.id)
    db_session.add(dr); db_session.commit()
    dr.line_items.append(DeliveryReceiptItem(line_number=1, sales_order_item_id=li.id,
                                             delivered_quantity=Decimal('5')))
    db_session.commit()

    staff_user.branches.append(main_branch)
    db_session.commit()

    _login(client, staff_user)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    resp = client.get(f'/sales-invoices/billable-drs?customer_id={customer.id}')
    data = resp.get_json()
    assert data['drs'][0]['customer_po_number'] is None
