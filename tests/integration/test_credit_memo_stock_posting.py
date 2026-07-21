"""Credit Memo document-level chain-verification helper (R-03 slice 2a-v, Task 4).

_cm_line_chain_verified(li) is a document-level (not line-level) check: does the
Sales Invoice referenced by this Credit Memo line have at least one billed
Delivery Receipt (DeliveryReceipt.sales_invoice_id pointing at that SI) that
shipped the SAME product? A Sales Invoice can be created fully standalone with
zero DR involvement (SalesInvoiceItem has no FK back to any DeliveryReceiptItem),
so there is no reliable line-level trace the way VDM has -- this heuristic exists
to avoid reversing COGS that was never expensed.
"""
from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.sales_memos.je import _cm_line_chain_verified
from app.sales_memos.models import SalesMemo, SalesMemoItem, generate_memo_number
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.sales_orders.models import SalesOrder, SalesOrderItem
from app.delivery_receipts.models import DeliveryReceipt, DeliveryReceiptItem
from app.products.models import Product
from app.customers.models import Customer

pytestmark = [pytest.mark.integration]


def _customer(code='CMC-CUST'):
    c = Customer(code=code, name='CM Chain Customer')
    db.session.add(c); db.session.commit()
    return c


def _si_with_item(main_branch, product, qty='5'):
    customer = _customer()
    si = SalesInvoice(branch_id=main_branch.id, invoice_number='SI-CMC-0001',
                      invoice_date=date(2026, 2, 10), due_date=date(2026, 3, 12),
                      customer_id=customer.id, customer_name=customer.name,
                      payment_terms='30', status='posted')
    db.session.add(si); db.session.flush()
    item = SalesInvoiceItem(invoice_id=si.id, line_number=1, description=product.name,
                            amount=Decimal('56.00'), quantity=Decimal(qty), unit_price=Decimal('11.20'),
                            product_id=product.id)
    db.session.add(item); db.session.commit()
    return si, item


def _so_item(main_branch, customer, product, so_number, qty='5'):
    """Minimal SalesOrder+SalesOrderItem chain -- DeliveryReceipt/DeliveryReceiptItem
    require sales_order_id / sales_order_item_id (both NOT NULL)."""
    so = SalesOrder(so_number=so_number, order_date=date(2026, 2, 5), customer_id=customer.id,
                    customer_name=customer.name, branch_id=main_branch.id, status='confirmed')
    soi = SalesOrderItem(line_number=1, product_id=product.id, quantity=Decimal(qty),
                         unit_price=Decimal('11.20'), vat_category='V12', vat_rate=Decimal('12'))
    soi.calculate_amounts(); so.line_items.append(soi)
    db.session.add(so); db.session.commit()
    return so, soi


def _cm_item_for(si_item, qty='2'):
    memo = SalesMemo(memo_type='credit', memo_number=generate_memo_number('credit'),
                     customer_id=si_item.invoice.customer_id, sales_invoice_id=si_item.invoice_id,
                     original_invoice_number=si_item.invoice.invoice_number,
                     customer_name=si_item.invoice.customer.name, branch_id=si_item.invoice.branch_id,
                     memo_date=date(2026, 2, 15), destination='ar', reason='return', status='draft')
    db.session.add(memo); db.session.flush()
    mitem = SalesMemoItem(sales_memo_id=memo.id, sales_invoice_item_id=si_item.id, line_number=1,
                          product_id=si_item.product_id, quantity=Decimal(qty),
                          amount=Decimal('22.40'), line_total=Decimal('22.40'),
                          vat_category='V12', vat_rate=Decimal('12.00'), vat_amount=Decimal('2.40'))
    memo.line_items.append(mitem)
    db.session.add(memo); db.session.commit()
    return mitem


def test_chain_verified_when_billed_dr_shipped_same_product(db_session, main_branch, admin_user):
    product = Product(code='CMC-PROD', name='CM Chain Product', is_active=True,
                      track_inventory=True, costing_method='moving_average')
    db.session.add(product); db.session.commit()
    si, si_item = _si_with_item(main_branch, product)
    so, soi = _so_item(main_branch, si.customer, product, 'SO-CMC-0001')
    dr = DeliveryReceipt(branch_id=main_branch.id, dr_number='DR-CMC-0001',
                         delivery_date=date(2026, 2, 8), sales_order_id=so.id,
                         customer_id=si.customer_id, customer_name=si.customer.name,
                         sales_invoice_id=si.id, status='delivered')
    dr.line_items.append(DeliveryReceiptItem(line_number=1, sales_order_item_id=soi.id,
                                             product_id=product.id, delivered_quantity=Decimal('5')))
    db.session.add(dr); db.session.commit()

    mitem = _cm_item_for(si_item)
    assert _cm_line_chain_verified(mitem) is True


def test_not_chain_verified_when_no_billed_dr(db_session, main_branch):
    product = Product(code='CMC-PROD2', name='CM Chain Product 2', is_active=True,
                      track_inventory=True, costing_method='moving_average')
    db.session.add(product); db.session.commit()
    si, si_item = _si_with_item(main_branch, product)   # NO DeliveryReceipt at all

    mitem = _cm_item_for(si_item)
    assert _cm_line_chain_verified(mitem) is False


def test_not_chain_verified_when_billed_dr_is_for_a_different_product(db_session, main_branch):
    product = Product(code='CMC-PROD3', name='CM Chain Product 3', is_active=True,
                      track_inventory=True, costing_method='moving_average')
    other = Product(code='CMC-OTHER', name='Other Product', is_active=True,
                    track_inventory=True, costing_method='moving_average')
    db.session.add_all([product, other]); db.session.commit()
    si, si_item = _si_with_item(main_branch, product)
    so, soi = _so_item(main_branch, si.customer, other, 'SO-CMC-0003')
    dr = DeliveryReceipt(branch_id=main_branch.id, dr_number='DR-CMC-0003',
                         delivery_date=date(2026, 2, 8), sales_order_id=so.id,
                         customer_id=si.customer_id, customer_name=si.customer.name,
                         sales_invoice_id=si.id, status='delivered')
    dr.line_items.append(DeliveryReceiptItem(line_number=1, sales_order_item_id=soi.id,
                                             product_id=other.id, delivered_quantity=Decimal('5')))
    db.session.add(dr); db.session.commit()

    mitem = _cm_item_for(si_item)
    assert _cm_line_chain_verified(mitem) is False
