from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.purchase_memos.je import _vdm_line_chain_verified
from app.purchase_memos.models import PurchaseMemo, PurchaseMemoItem, generate_purchase_memo_number
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from app.products.models import Product
from app.vendors.models import Vendor
from app.stock_adjustments.service import post_movement

pytestmark = [pytest.mark.integration]


def _vendor(code='CV-VEND'):
    v = Vendor(code=code, name='Chain Vendor', tin='111-000-000')
    db.session.add(v); db.session.commit()
    return v


def _ap_item_from_rr(db_session, main_branch, admin_user, tracked=True):
    """Build a real PO -> RR -> AP chain. When tracked=True, seeds a real
    StockMovement (via post_movement) and sets RR item's stock_movement_id,
    exactly as 2a-ii's own RR-approval posting would -- then bills an AP item
    FROM that RR item (source_rr_item_id set), mirroring how AP billing
    actually stamps this field today."""
    vendor = _vendor()
    product = Product(code='CV-PROD', name='Chain Product', is_active=True,
                      track_inventory=tracked, costing_method='moving_average' if tracked else None)
    db.session.add(product); db.session.commit()
    po = PurchaseOrder(po_number='PO-CV-0001', order_date=date(2026, 2, 1), vendor_id=vendor.id,
                       vendor_name=vendor.name, branch_id=main_branch.id, status='approved')
    po.line_items.append(PurchaseOrderItem(line_number=1, product_id=product.id,
                                           quantity=Decimal('10'), unit_price=Decimal('5.00'),
                                           amount=Decimal('50.00')))
    db.session.add(po); db.session.commit()
    rr = ReceivingReport(rr_number='RR-CV-0001', receipt_date=date(2026, 2, 5),
                         purchase_order_id=po.id, branch_id=main_branch.id, status='approved',
                         vendor_id=vendor.id, vendor_name=vendor.name)
    rr_item = ReceivingReportItem(line_number=1, purchase_order_item_id=po.line_items[0].id,
                                  product_id=product.id, received_quantity=Decimal('10'))
    rr.line_items.append(rr_item)
    db.session.add(rr); db.session.commit()
    if tracked:
        mv, _ = post_movement(product, main_branch.id, 'receipt', Decimal('10'), Decimal('5.00'),
                              'receiving_report', rr.id, 'seed receipt', admin_user)
        db.session.commit()
        rr_item.stock_movement_id = mv.id
        db.session.commit()
    ap = AccountsPayable(branch_id=main_branch.id, ap_number='AP-CV-0001',
                         ap_date=date(2026, 2, 6), due_date=date(2026, 3, 8),
                         payee_type='vendor', payee_id=vendor.id, vendor_id=vendor.id,
                         vendor_name=vendor.name, vendor_tin=vendor.tin, status='posted',
                         subtotal=Decimal('56.00'), total_amount=Decimal('56.00'),
                         amount_paid=Decimal('0.00'), balance=Decimal('56.00'))
    ap_item = AccountsPayableItem(line_number=1, description='Chain Product', amount=Decimal('56.00'),
                                  quantity=Decimal('10'), unit_price=Decimal('5.60'),
                                  vat_rate=Decimal('12.00'), vat_category='V12', vat_nature='regular',
                                  line_total=Decimal('56.00'), vat_amount=Decimal('6.00'),
                                  source_rr_item_id=rr_item.id)
    ap.line_items.append(ap_item)
    db.session.add(ap); db.session.commit()
    return ap_item, product


def _memo_item_for(ap_item):
    memo = PurchaseMemo(memo_type='debit', memo_number=generate_purchase_memo_number('debit'),
                        vendor_id=ap_item.ap.payee_id, accounts_payable_id=ap_item.ap_id,
                        original_ap_number=ap_item.ap.ap_number, vendor_name=ap_item.ap.vendor_name,
                        branch_id=ap_item.ap.branch_id, memo_date=date(2026, 2, 10),
                        destination='ap', reason='return', status='draft')
    db.session.add(memo); db.session.flush()
    mitem = PurchaseMemoItem(purchase_memo_id=memo.id, accounts_payable_item_id=ap_item.id,
                             line_number=1, product_id=None,
                             quantity=Decimal('2'), amount=Decimal('11.20'), line_total=Decimal('11.20'),
                             vat_category='V12', vat_rate=Decimal('12.00'), vat_amount=Decimal('1.20'))
    memo.line_items.append(mitem)
    db.session.add(memo); db.session.commit()
    return mitem


def test_chain_verified_when_rr_sourced_and_tracked(db_session, main_branch, admin_user):
    ap_item, product = _ap_item_from_rr(db_session, main_branch, admin_user, tracked=True)
    mitem = _memo_item_for(ap_item)
    mitem.product_id = product.id
    db.session.commit()
    assert _vdm_line_chain_verified(mitem) is True


def test_not_chain_verified_when_untracked(db_session, main_branch, admin_user):
    ap_item, product = _ap_item_from_rr(db_session, main_branch, admin_user, tracked=False)
    mitem = _memo_item_for(ap_item)
    mitem.product_id = product.id
    db.session.commit()
    assert _vdm_line_chain_verified(mitem) is False


def test_not_chain_verified_when_ap_entered_directly_no_rr(db_session, main_branch):
    vendor = _vendor('CV-VEND2')
    ap = AccountsPayable(branch_id=main_branch.id, ap_number='AP-CV-0002', ap_date=date(2026, 2, 6),
                         due_date=date(2026, 3, 8), payee_type='vendor', payee_id=vendor.id,
                         vendor_id=vendor.id, vendor_name=vendor.name, vendor_tin=vendor.tin,
                         status='posted', subtotal=Decimal('56.00'), total_amount=Decimal('56.00'),
                         amount_paid=Decimal('0.00'), balance=Decimal('56.00'))
    ap_item = AccountsPayableItem(line_number=1, description='Direct entry', amount=Decimal('56.00'),
                                  vat_rate=Decimal('12.00'), vat_category='V12', vat_nature='regular',
                                  line_total=Decimal('56.00'), vat_amount=Decimal('6.00'))
    ap.line_items.append(ap_item)
    db.session.add(ap); db.session.commit()
    mitem = _memo_item_for(ap_item)
    assert _vdm_line_chain_verified(mitem) is False
