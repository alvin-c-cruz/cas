"""BUG-SI-DETAIL-MISSING-DR-SO-PO: the SI detail page must show every source
Delivery Receipt (and its Sales Order) that was billed into this invoice."""
import pytest
from decimal import Decimal
from datetime import date
from app import db

pytestmark = [pytest.mark.integration]


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _invoice_with_dr(db_session, main_branch, customer):
    from app.sales_orders.models import SalesOrder, SalesOrderItem
    from app.delivery_receipts.models import DeliveryReceipt, DeliveryReceiptItem
    from app.sales_invoices.models import SalesInvoice

    so = SalesOrder(so_number='SO-DET-0001', order_date=date(2026, 7, 1), customer_id=customer.id,
                    customer_name=customer.name, branch_id=main_branch.id, status='confirmed')
    li = SalesOrderItem(line_number=1, quantity=Decimal('10'), unit_price=Decimal('5.00'),
                        amount=Decimal('50.00'))
    so.line_items.append(li)
    db.session.add(so); db.session.commit()

    invoice = SalesInvoice(invoice_number='SI-DET-0001', invoice_date=date(2026, 7, 15),
                           due_date=date(2026, 8, 14), customer_id=customer.id,
                           customer_name=customer.name, branch_id=main_branch.id, status='draft')
    db.session.add(invoice); db.session.commit()

    dr = DeliveryReceipt(dr_number='DR-DET-0001', delivery_date=date(2026, 7, 10),
                         sales_order_id=so.id, customer_id=customer.id, customer_name=customer.name,
                         status='billed', branch_id=main_branch.id, sales_invoice_id=invoice.id)
    db.session.add(dr); db.session.commit()
    dr.line_items.append(DeliveryReceiptItem(line_number=1, sales_order_item_id=li.id,
                                             delivered_quantity=Decimal('10')))
    db.session.commit()
    return invoice, dr, so


def test_detail_page_shows_source_dr_and_so(client, db_session, staff_user, main_branch, customer):
    from app.settings import AppSettings
    AppSettings.set_setting('module_enabled:sales_invoices', '1')
    db_session.commit()
    invoice, dr, so = _invoice_with_dr(db_session, main_branch, customer)
    staff_user.branches.append(main_branch)
    db_session.commit()
    _login(client, staff_user)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    resp = client.get(f'/sales-invoices/{invoice.id}')
    body = resp.get_data(as_text=True)
    assert dr.dr_number in body
    assert so.so_number in body


def test_detail_page_omits_dr_section_when_invoice_has_no_source_dr(client, db_session, staff_user, main_branch, customer):
    from app.settings import AppSettings
    from app.sales_invoices.models import SalesInvoice
    AppSettings.set_setting('module_enabled:sales_invoices', '1')
    db_session.commit()
    invoice = SalesInvoice(invoice_number='SI-DET-0002', invoice_date=date(2026, 7, 15),
                           due_date=date(2026, 8, 14), customer_id=customer.id,
                           customer_name=customer.name, branch_id=main_branch.id, status='draft')
    db.session.add(invoice); db.session.commit()
    staff_user.branches.append(main_branch)
    db_session.commit()
    _login(client, staff_user)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    resp = client.get(f'/sales-invoices/{invoice.id}')
    body = resp.get_data(as_text=True)
    assert 'Source Delivery Receipt' not in body
