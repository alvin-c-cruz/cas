from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.purchase_memos.je import _vdm_line_chain_verified, post_purchase_memo_je
from app.purchase_memos.models import PurchaseMemo, PurchaseMemoItem, generate_purchase_memo_number
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from app.products.models import Product
from app.vendors.models import Vendor
from app.stock_adjustments.service import post_movement
from app.stock_adjustments.models import StockMovement, StockBalance
from app.posting.control_accounts import ControlAccountError
from app.settings import AppSettings
from app.accounts.models import Account

pytestmark = [pytest.mark.integration]


def _vendor(code='CV-VEND'):
    v = Vendor(code=code, name='Chain Vendor', tin='111-000-000')
    db.session.add(v); db.session.commit()
    return v


def _ap_item_from_rr(db_session, main_branch, admin_user, tracked=True, suffix='CV',
                     receipt_qty=Decimal('10'), receipt_cost=Decimal('5.00')):
    """Build a real PO -> RR -> AP chain. When tracked=True, seeds a real
    StockMovement (via post_movement) and sets RR item's stock_movement_id,
    exactly as 2a-ii's own RR-approval posting would -- then bills an AP item
    FROM that RR item (source_rr_item_id set), mirroring how AP billing
    actually stamps this field today.

    `suffix` and `receipt_qty`/`receipt_cost` default to the original hardcoded
    values (backward-compatible with every pre-existing caller) but let a test
    build TWO independent chains (different product/vendor/PO/RR/AP codes,
    different receipt quantity/cost -> different moving-average cost) attached
    as two separate PurchaseMemoItem rows on the SAME PurchaseMemo."""
    vendor = _vendor(f'{suffix}-VEND')
    product = Product(code=f'{suffix}-PROD', name='Chain Product', is_active=True,
                      track_inventory=tracked, costing_method='moving_average' if tracked else None)
    db.session.add(product); db.session.commit()
    po = PurchaseOrder(po_number=f'PO-{suffix}-0001', order_date=date(2026, 2, 1), vendor_id=vendor.id,
                       vendor_name=vendor.name, branch_id=main_branch.id, status='approved')
    po.line_items.append(PurchaseOrderItem(line_number=1, product_id=product.id,
                                           quantity=receipt_qty, unit_price=receipt_cost,
                                           amount=receipt_qty * receipt_cost))
    db.session.add(po); db.session.commit()
    rr = ReceivingReport(rr_number=f'RR-{suffix}-0001', receipt_date=date(2026, 2, 5),
                         purchase_order_id=po.id, branch_id=main_branch.id, status='approved',
                         vendor_id=vendor.id, vendor_name=vendor.name)
    rr_item = ReceivingReportItem(line_number=1, purchase_order_item_id=po.line_items[0].id,
                                  product_id=product.id, received_quantity=receipt_qty)
    rr.line_items.append(rr_item)
    db.session.add(rr); db.session.commit()
    if tracked:
        mv, _ = post_movement(product, main_branch.id, 'receipt', receipt_qty, receipt_cost,
                              'receiving_report', rr.id, 'seed receipt', admin_user)
        db.session.commit()
        rr_item.stock_movement_id = mv.id
        db.session.commit()
    gross = (receipt_qty * receipt_cost * Decimal('1.12')).quantize(Decimal('0.01'))
    ap = AccountsPayable(branch_id=main_branch.id, ap_number=f'AP-{suffix}-0001',
                         ap_date=date(2026, 2, 6), due_date=date(2026, 3, 8),
                         payee_type='vendor', payee_id=vendor.id, vendor_id=vendor.id,
                         vendor_name=vendor.name, vendor_tin=vendor.tin, status='posted',
                         subtotal=gross, total_amount=gross,
                         amount_paid=Decimal('0.00'), balance=gross)
    ap_item = AccountsPayableItem(line_number=1, description='Chain Product', amount=gross,
                                  quantity=receipt_qty, unit_price=(gross / receipt_qty),
                                  vat_rate=Decimal('12.00'), vat_category='V12', vat_nature='regular',
                                  line_total=gross, vat_amount=(gross - receipt_qty * receipt_cost),
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


def _assign(code, name='Acct'):
    # Ensure an Account with this code+name exists. The posting engine resolves
    # ap_trade / wht_payable / inventory / purchase-returns by CODE via the
    # settings the callers set explicitly below, so the account codes must match
    # those setting values (20101, 1401, 50103, ...). (Corrected from the brief's
    # inverted (code_setting, code) form, which created code='AP-Trade'/name='Acct'
    # -- wrong code AND a duplicate-name UNIQUE collision on accounts.name.)
    acc = Account.query.filter_by(code=code).first()
    if acc is None:
        acc = Account(code=code, name=name, account_type='Asset', normal_balance='Debit')
        db.session.add(acc); db.session.commit()
    return acc


def _full_vdm_coa():
    from tests.conftest import assign_control_accounts
    ap = _assign('20101', 'AP-Trade')
    assign_control_accounts(db.session, ap='20101', wht_payable='20301')
    pr = _assign('50103', 'Purchase Returns and Allowances')
    inv = _assign('1401', 'Inventory')
    AppSettings.set_setting('inventory_account_code', '1401', updated_by='test')
    from app.vat_categories.models import VATCategory
    invat = _assign('10213', 'Input VAT')
    db.session.add(VATCategory(code='V12', name='VATABLE', rate=Decimal('12'),
                               input_vat_account_id=invat.id, is_active=True))
    db.session.commit()
    from app.purchase_memos import service
    AppSettings.set_setting(service.PURCHASE_RETURNS_KEY, '50103', updated_by='test')
    return {'ap': ap, 'pr': pr, 'inv': inv}


def test_chain_verified_line_posts_movement_and_credits_inventory(
        db_session, main_branch, admin_user):
    coa = _full_vdm_coa()
    ap_item, product = _ap_item_from_rr(db_session, main_branch, admin_user, tracked=True)
    mitem = _memo_item_for(ap_item)
    mitem.product_id = product.id
    mitem.quantity = Decimal('2')
    mitem.amount = Decimal('11.20'); mitem.line_total = Decimal('11.20')
    mitem.vat_amount = Decimal('1.20')
    memo = mitem.memo
    memo.subtotal = Decimal('11.20'); memo.vat_amount = Decimal('1.20')
    memo.total_amount = Decimal('11.20')
    db.session.commit()

    je = post_purchase_memo_je(memo, admin_user.id, actor=admin_user)
    db.session.commit()

    mv = StockMovement.query.filter_by(source_document_type='purchase_memo',
                                       source_document_id=memo.id).one()
    assert mv.quantity == Decimal('-2.0000')
    assert mv.unit_cost == Decimal('5.00')   # current average, unchanged by the return
    inv_line = next(l for l in je.lines if l.account_id == coa['inv'].id)
    assert inv_line.credit_amount == Decimal('10.00')   # 2 * 5.00, current average
    pr_lines = [l for l in je.lines if l.account_id == coa['pr'].id]
    assert pr_lines == []   # fully redirected -- nothing left for Purchase Returns
    bal = StockBalance.query.filter_by(product_id=product.id, branch_id=main_branch.id).one()
    assert bal.quantity_on_hand == Decimal('8.0000')


def test_non_chain_verified_line_unchanged(db_session, main_branch, admin_user):
    coa = _full_vdm_coa()
    ap_item, product = _ap_item_from_rr(db_session, main_branch, admin_user, tracked=False)
    mitem = _memo_item_for(ap_item)
    mitem.product_id = product.id
    memo = mitem.memo
    memo.subtotal = Decimal('11.20'); memo.vat_amount = Decimal('1.20')
    memo.total_amount = Decimal('11.20')
    db.session.commit()

    je = post_purchase_memo_je(memo, admin_user.id, actor=admin_user)
    db.session.commit()

    assert StockMovement.query.filter_by(source_document_type='purchase_memo').count() == 0
    pr_line = next(l for l in je.lines if l.account_id == coa['pr'].id)
    assert pr_line.credit_amount == Decimal('10.00')   # unchanged, exactly as pre-2a-v


def test_fails_closed_before_any_write_when_inventory_unassigned(
        db_session, main_branch, admin_user):
    coa = _full_vdm_coa()
    AppSettings.set_setting('inventory_account_code', '', updated_by='test')   # unassign
    ap_item, product = _ap_item_from_rr(db_session, main_branch, admin_user, tracked=True)
    mitem = _memo_item_for(ap_item)
    mitem.product_id = product.id
    memo = mitem.memo
    memo.subtotal = Decimal('11.20'); memo.vat_amount = Decimal('1.20')
    memo.total_amount = Decimal('11.20')
    db.session.commit()

    with pytest.raises(ControlAccountError):
        post_purchase_memo_je(memo, admin_user.id, actor=admin_user)
    assert StockMovement.query.filter_by(source_document_type='purchase_memo').count() == 0


def test_negative_on_hand_return_surfaces_warning(db_session, main_branch, admin_user):
    coa = _full_vdm_coa()
    vendor = _vendor('CV-VEND3')
    product = Product(code='CV-PROD3', name='Chain Product 3', is_active=True,
                      track_inventory=True, costing_method='moving_average')
    db.session.add(product); db.session.commit()
    po = PurchaseOrder(po_number='PO-CV-0003', order_date=date(2026, 2, 1), vendor_id=vendor.id,
                       vendor_name=vendor.name, branch_id=main_branch.id, status='approved')
    po.line_items.append(PurchaseOrderItem(line_number=1, product_id=product.id,
                                           quantity=Decimal('1'), unit_price=Decimal('5.00'),
                                           amount=Decimal('5.00')))
    db.session.add(po); db.session.commit()
    rr = ReceivingReport(rr_number='RR-CV-0003', receipt_date=date(2026, 2, 5),
                         purchase_order_id=po.id, branch_id=main_branch.id, status='approved',
                         vendor_id=vendor.id, vendor_name=vendor.name)
    rr_item = ReceivingReportItem(line_number=1, purchase_order_item_id=po.line_items[0].id,
                                  product_id=product.id, received_quantity=Decimal('1'))
    rr.line_items.append(rr_item)
    db.session.add(rr); db.session.commit()
    mv, _ = post_movement(product, main_branch.id, 'receipt', Decimal('1'), Decimal('5.00'),
                          'receiving_report', rr.id, 'seed', admin_user)
    db.session.commit()
    rr_item.stock_movement_id = mv.id
    db.session.commit()
    ap = AccountsPayable(branch_id=main_branch.id, ap_number='AP-CV-0003', ap_date=date(2026, 2, 6),
                         due_date=date(2026, 3, 8), payee_type='vendor', payee_id=vendor.id,
                         vendor_id=vendor.id, vendor_name=vendor.name, vendor_tin=vendor.tin,
                         status='posted', subtotal=Decimal('5.60'), total_amount=Decimal('5.60'),
                         amount_paid=Decimal('0.00'), balance=Decimal('5.60'))
    ap_item = AccountsPayableItem(line_number=1, description='Chain Product 3', amount=Decimal('5.60'),
                                  quantity=Decimal('1'), unit_price=Decimal('5.60'),
                                  vat_rate=Decimal('12.00'), vat_category='V12', vat_nature='regular',
                                  line_total=Decimal('5.60'), vat_amount=Decimal('0.60'),
                                  source_rr_item_id=rr_item.id)
    ap.line_items.append(ap_item)
    db.session.add(ap); db.session.commit()
    mitem = _memo_item_for(ap_item)
    mitem.product_id = product.id
    mitem.quantity = Decimal('3')   # return MORE than the 1 on hand
    mitem.amount = Decimal('16.80'); mitem.line_total = Decimal('16.80')
    mitem.vat_amount = Decimal('1.80')
    memo = mitem.memo
    memo.subtotal = Decimal('16.80'); memo.vat_amount = Decimal('1.80')
    memo.total_amount = Decimal('16.80')
    db.session.commit()

    post_purchase_memo_je(memo, admin_user.id, actor=admin_user)
    db.session.commit()

    assert memo._negative_warnings == [product.code]


def _memo_with_two_lines(ap_item_a, ap_item_b):
    """Build ONE PurchaseMemo with two PurchaseMemoItem lines, one attached to
    each AP item -- mirrors _memo_item_for but for the multi-line/mixed-line
    gaps (Task 2 review items 1 and 2), where two separate PO->RR->AP chains
    must land as two lines on the SAME memo."""
    memo = PurchaseMemo(memo_type='debit', memo_number=generate_purchase_memo_number('debit'),
                        vendor_id=ap_item_a.ap.payee_id, accounts_payable_id=ap_item_a.ap_id,
                        original_ap_number=ap_item_a.ap.ap_number, vendor_name=ap_item_a.ap.vendor_name,
                        branch_id=ap_item_a.ap.branch_id, memo_date=date(2026, 2, 10),
                        destination='ap', reason='return', status='draft')
    db.session.add(memo); db.session.flush()
    item_a = PurchaseMemoItem(purchase_memo_id=memo.id, accounts_payable_item_id=ap_item_a.id,
                              line_number=1, product_id=None,
                              quantity=Decimal('2'), amount=Decimal('11.20'),
                              line_total=Decimal('11.20'),
                              vat_category='V12', vat_rate=Decimal('12.00'), vat_amount=Decimal('1.20'))
    item_b = PurchaseMemoItem(purchase_memo_id=memo.id, accounts_payable_item_id=ap_item_b.id,
                              line_number=2, product_id=None,
                              quantity=Decimal('3'), amount=Decimal('26.88'),
                              line_total=Decimal('26.88'),
                              vat_category='V12', vat_rate=Decimal('12.00'), vat_amount=Decimal('2.88'))
    memo.line_items.append(item_a)
    memo.line_items.append(item_b)
    db.session.add(memo); db.session.commit()
    return memo, item_a, item_b


def test_multi_chain_verified_lines_accumulate_correctly(db_session, main_branch, admin_user):
    """Gap 1 (Task 2 review): two chain-verified lines, DIFFERENT products,
    quantities and receipt costs -- proves the loop accumulates inv_net across
    lines (not a reused-variable bug), posts ONE post_movement per line, and
    the resulting Cr inventory JE line equals the SUM of both nets."""
    coa = _full_vdm_coa()
    ap_item_a, product_a = _ap_item_from_rr(db_session, main_branch, admin_user, tracked=True,
                                            suffix='CVA', receipt_qty=Decimal('10'),
                                            receipt_cost=Decimal('5.00'))
    ap_item_b, product_b = _ap_item_from_rr(db_session, main_branch, admin_user, tracked=True,
                                            suffix='CVB', receipt_qty=Decimal('20'),
                                            receipt_cost=Decimal('8.00'))
    memo, item_a, item_b = _memo_with_two_lines(ap_item_a, ap_item_b)
    item_a.product_id = product_a.id
    item_b.product_id = product_b.id
    memo.subtotal = Decimal('38.08'); memo.vat_amount = Decimal('4.08')
    memo.total_amount = Decimal('38.08')
    db.session.commit()

    je = post_purchase_memo_je(memo, admin_user.id, actor=admin_user)
    db.session.commit()

    movements = StockMovement.query.filter_by(source_document_type='purchase_memo',
                                              source_document_id=memo.id).all()
    assert len(movements) == 2
    mv_a = next(m for m in movements if m.product_id == product_a.id)
    mv_b = next(m for m in movements if m.product_id == product_b.id)
    assert mv_a.quantity == Decimal('-2.0000')
    assert mv_a.unit_cost == Decimal('5.00')
    assert mv_b.quantity == Decimal('-3.0000')
    assert mv_b.unit_cost == Decimal('8.00')

    inv_lines = [l for l in je.lines if l.account_id == coa['inv'].id]
    assert len(inv_lines) == 1   # one accumulated Cr inventory leg, not one per line
    assert inv_lines[0].credit_amount == Decimal('34.00')   # 10.00 (line A net) + 24.00 (line B net)

    pr_lines = [l for l in je.lines if l.account_id == coa['pr'].id]
    assert pr_lines == []   # both lines fully redirected -- nothing left for Purchase Returns

    bal_a = StockBalance.query.filter_by(product_id=product_a.id, branch_id=main_branch.id).one()
    bal_b = StockBalance.query.filter_by(product_id=product_b.id, branch_id=main_branch.id).one()
    assert bal_a.quantity_on_hand == Decimal('8.0000')    # 10 - 2
    assert bal_b.quantity_on_hand == Decimal('17.0000')   # 20 - 3


def test_mixed_chain_verified_and_non_verified_lines_split_correctly(
        db_session, main_branch, admin_user):
    """Gap 2 (Task 2 review): one chain-verified line + one non-chain-verified
    line on the SAME memo -- proves the JE ends up with BOTH a Cr inventory
    leg (chain-verified line's net) AND a Cr Purchase Returns leg (the other
    line's net), and the two sum back to net_purchase. This is the core new
    arithmetic split none of the pre-existing tests (fully-redirects /
    nothing-redirects) actually exercise."""
    coa = _full_vdm_coa()
    ap_item_a, product_a = _ap_item_from_rr(db_session, main_branch, admin_user, tracked=True,
                                            suffix='MXA', receipt_qty=Decimal('10'),
                                            receipt_cost=Decimal('5.00'))
    ap_item_b, product_b = _ap_item_from_rr(db_session, main_branch, admin_user, tracked=False,
                                            suffix='MXB', receipt_qty=Decimal('20'),
                                            receipt_cost=Decimal('8.00'))
    memo, item_a, item_b = _memo_with_two_lines(ap_item_a, ap_item_b)
    item_a.product_id = product_a.id
    item_b.product_id = product_b.id
    memo.subtotal = Decimal('38.08'); memo.vat_amount = Decimal('4.08')
    memo.total_amount = Decimal('38.08')
    db.session.commit()

    je = post_purchase_memo_je(memo, admin_user.id, actor=admin_user)
    db.session.commit()

    movements = StockMovement.query.filter_by(source_document_type='purchase_memo',
                                              source_document_id=memo.id).all()
    assert len(movements) == 1   # only the chain-verified line (product_a) posts a movement
    assert movements[0].product_id == product_a.id

    inv_lines = [l for l in je.lines if l.account_id == coa['inv'].id]
    pr_lines = [l for l in je.lines if l.account_id == coa['pr'].id]
    assert len(inv_lines) == 1
    assert len(pr_lines) == 1
    assert inv_lines[0].credit_amount == Decimal('10.00')   # line A net (chain-verified)
    assert pr_lines[0].credit_amount == Decimal('24.00')    # line B net (non-verified)

    net_purchase = memo.subtotal - memo.vat_amount
    assert inv_lines[0].credit_amount + pr_lines[0].credit_amount == net_purchase


def test_actor_none_with_chain_verified_line_raises_value_error(
        db_session, main_branch, admin_user):
    """Gap 3 (Task 2 review): calling post_purchase_memo_je with NO actor kwarg
    on a memo carrying a chain-verified line must raise ValueError (not
    AttributeError from post_movement receiving actor=None), and must do so
    before any StockMovement row is written."""
    _full_vdm_coa()
    ap_item, product = _ap_item_from_rr(db_session, main_branch, admin_user, tracked=True)
    mitem = _memo_item_for(ap_item)
    mitem.product_id = product.id
    memo = mitem.memo
    memo.subtotal = Decimal('11.20'); memo.vat_amount = Decimal('1.20')
    memo.total_amount = Decimal('11.20')
    db.session.commit()

    with pytest.raises(ValueError, match='actor is required'):
        post_purchase_memo_je(memo, admin_user.id)   # no actor kwarg

    assert StockMovement.query.filter_by(source_document_type='purchase_memo',
                                         source_document_id=memo.id).count() == 0
