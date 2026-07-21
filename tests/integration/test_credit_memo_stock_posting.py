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


# --- Task 5: Credit Memo posts real stock movements for chain-verified lines ---
from app.sales_memos.je import post_memo_je
from app.stock_adjustments.models import StockMovement, StockBalance
from app.stock_adjustments.service import post_movement
from app.posting.control_accounts import ControlAccountError
from app.settings import AppSettings
from app.accounts.models import Account


def _assign(code_setting, code, name='Acct'):
    acc = Account.query.filter_by(code=code).first()
    if acc is None:
        acc = Account(code=code, name=name, account_type='Asset', normal_balance='Debit')
        db.session.add(acc); db.session.commit()
    AppSettings.set_setting(code_setting, code, updated_by='test')
    return acc


def _full_cm_coa():
    from tests.conftest import assign_control_accounts
    from app.sales_memos import service
    ar = _assign('ar_trade_account_code', '10201', 'AR-Trade')
    assign_control_accounts(db.session, ar='10201', creditable_wht='10212')
    sr = _assign(service.SALES_RETURNS_KEY, '40103', 'Sales Returns and Allowances')
    inv = _assign('inventory_account_code', '1401', 'Inventory')
    cogs = _assign('cogs_account_code', '61060', 'COGS')
    from app.sales_vat_categories.models import SalesVATCategory
    outvat = _assign('output_vat_account_code', '20211', 'Output VAT')
    db.session.add(SalesVATCategory(code='V12', name='VATABLE', rate=Decimal('12'),
                                    output_vat_account_id=outvat.id, is_active=True))
    db.session.commit()
    return {'ar': ar, 'sr': sr, 'inv': inv, 'cogs': cogs}


def test_chain_verified_line_posts_movement_and_adds_inventory_cogs(
        db_session, main_branch, admin_user):
    coa = _full_cm_coa()
    product = Product(code='CMC-PROD4', name='CM Chain Product 4', is_active=True,
                      track_inventory=True, costing_method='moving_average')
    db.session.add(product); db.session.commit()
    post_movement(product, main_branch.id, 'receipt', Decimal('20'), Decimal('4.00'),
                  'seed', None, 'seed stock', admin_user)
    db.session.commit()
    si, si_item = _si_with_item(main_branch, product)
    so, soi = _so_item(main_branch, si.customer, product, 'SO-CMC-0004')
    dr = DeliveryReceipt(branch_id=main_branch.id, dr_number='DR-CMC-0004',
                         delivery_date=date(2026, 2, 8), sales_order_id=so.id,
                         customer_id=si.customer_id,
                         customer_name=si.customer.name, sales_invoice_id=si.id, status='delivered')
    dr.line_items.append(DeliveryReceiptItem(line_number=1, sales_order_item_id=soi.id,
                                             product_id=product.id,
                                             delivered_quantity=Decimal('5')))
    db.session.add(dr); db.session.commit()
    mitem = _cm_item_for(si_item)
    memo = mitem.memo
    memo.subtotal = Decimal('22.40'); memo.vat_amount = Decimal('2.40')
    memo.total_amount = Decimal('22.40')
    db.session.commit()

    je = post_memo_je(memo, admin_user.id, actor=admin_user)
    db.session.commit()

    mv = StockMovement.query.filter_by(source_document_type='sales_memo',
                                       source_document_id=memo.id).one()
    assert mv.quantity == Decimal('2.0000') and mv.unit_cost == Decimal('4.00')
    inv_line = next(l for l in je.lines if l.account_id == coa['inv'].id)
    cogs_line = next(l for l in je.lines if l.account_id == coa['cogs'].id)
    assert inv_line.debit_amount == Decimal('8.00') and cogs_line.credit_amount == Decimal('8.00')
    bal = StockBalance.query.filter_by(product_id=product.id, branch_id=main_branch.id).one()
    assert bal.quantity_on_hand == Decimal('22.0000')


def test_non_chain_verified_line_posts_nothing(db_session, main_branch, admin_user):
    coa = _full_cm_coa()
    product = Product(code='CMC-PROD5', name='CM Chain Product 5', is_active=True,
                      track_inventory=True, costing_method='moving_average')
    db.session.add(product); db.session.commit()
    si, si_item = _si_with_item(main_branch, product)   # no DR
    mitem = _cm_item_for(si_item)
    memo = mitem.memo
    memo.subtotal = Decimal('22.40'); memo.vat_amount = Decimal('2.40')
    memo.total_amount = Decimal('22.40')
    db.session.commit()

    post_memo_je(memo, admin_user.id, actor=admin_user)  # not chain-verified -- must not raise
    db.session.commit()
    assert StockMovement.query.filter_by(source_document_type='sales_memo').count() == 0


def test_fails_closed_before_any_write_when_cogs_unassigned(db_session, main_branch, admin_user):
    coa = _full_cm_coa()
    AppSettings.set_setting('cogs_account_code', '', updated_by='test')   # unassign
    product = Product(code='CMC-PROD6', name='CM Chain Product 6', is_active=True,
                      track_inventory=True, costing_method='moving_average')
    db.session.add(product); db.session.commit()
    post_movement(product, main_branch.id, 'receipt', Decimal('20'), Decimal('4.00'),
                  'seed', None, 'seed stock', admin_user)
    db.session.commit()
    si, si_item = _si_with_item(main_branch, product)
    so, soi = _so_item(main_branch, si.customer, product, 'SO-CMC-0006')
    dr = DeliveryReceipt(branch_id=main_branch.id, dr_number='DR-CMC-0006',
                         delivery_date=date(2026, 2, 8), sales_order_id=so.id,
                         customer_id=si.customer_id,
                         customer_name=si.customer.name, sales_invoice_id=si.id, status='delivered')
    dr.line_items.append(DeliveryReceiptItem(line_number=1, sales_order_item_id=soi.id,
                                             product_id=product.id,
                                             delivered_quantity=Decimal('5')))
    db.session.add(dr); db.session.commit()
    mitem = _cm_item_for(si_item)
    memo = mitem.memo
    memo.subtotal = Decimal('22.40'); memo.vat_amount = Decimal('2.40')
    memo.total_amount = Decimal('22.40')
    db.session.commit()

    with pytest.raises(ControlAccountError):
        post_memo_je(memo, admin_user.id, actor=admin_user)
    assert StockMovement.query.filter_by(source_document_type='sales_memo').count() == 0


# --- Task 6: void reverses whatever stock movement a Credit Memo posted ---
from app.sales_memos.je import reverse_memo_je


def test_void_reverses_chain_verified_movement(db_session, main_branch, admin_user):
    coa = _full_cm_coa()
    product = Product(code='CMC-PROD7', name='CM Chain Product 7', is_active=True,
                      track_inventory=True, costing_method='moving_average')
    db.session.add(product); db.session.commit()
    post_movement(product, main_branch.id, 'receipt', Decimal('20'), Decimal('4.00'),
                  'seed', None, 'seed stock', admin_user)
    db.session.commit()
    si, si_item = _si_with_item(main_branch, product)
    so, soi = _so_item(main_branch, si.customer, product, 'SO-CMC-0007')
    dr = DeliveryReceipt(branch_id=main_branch.id, dr_number='DR-CMC-0007',
                         delivery_date=date(2026, 2, 8), sales_order_id=so.id,
                         customer_id=si.customer_id, customer_name=si.customer.name,
                         sales_invoice_id=si.id, status='delivered')
    dr.line_items.append(DeliveryReceiptItem(line_number=1, sales_order_item_id=soi.id,
                                             product_id=product.id, delivered_quantity=Decimal('5')))
    db.session.add(dr); db.session.commit()
    mitem = _cm_item_for(si_item)
    memo = mitem.memo
    memo.subtotal = Decimal('22.40'); memo.vat_amount = Decimal('2.40')
    memo.total_amount = Decimal('22.40')
    memo.status = 'posted'
    db.session.commit()
    je = post_memo_je(memo, admin_user.id, actor=admin_user)
    memo.journal_entry_id = je.id
    db.session.commit()

    reverse_memo_je(memo, admin_user.id, actor=admin_user)
    db.session.commit()

    bal = StockBalance.query.filter_by(product_id=product.id, branch_id=main_branch.id).one()
    assert bal.quantity_on_hand == Decimal('20.0000')   # back to the seeded 20


def test_void_noop_when_no_movement_posted(db_session, main_branch, admin_user):
    coa = _full_cm_coa()
    product = Product(code='CMC-PROD8', name='CM Chain Product 8', is_active=True,
                      track_inventory=True, costing_method='moving_average')
    db.session.add(product); db.session.commit()
    si, si_item = _si_with_item(main_branch, product)   # no DR
    mitem = _cm_item_for(si_item)
    memo = mitem.memo
    memo.subtotal = Decimal('22.40'); memo.vat_amount = Decimal('2.40')
    memo.total_amount = Decimal('22.40')
    memo.status = 'posted'
    db.session.commit()
    je = post_memo_je(memo, admin_user.id, actor=admin_user)
    memo.journal_entry_id = je.id
    db.session.commit()

    reverse_memo_je(memo, admin_user.id, actor=admin_user)   # must not raise
    db.session.commit()
    assert StockMovement.query.filter_by(source_document_type='sales_memo').count() == 0
