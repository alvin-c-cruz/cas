# tests/bill_of_materials/test_stock_posting.py
from decimal import Decimal
import pytest
from app import db
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialLine
from app.bill_of_materials.service import consume_materials
from app.work_orders.models import WorkOrder
from app.work_orders.service import release_work_order
from app.work_orders.forms import generate_wo_number
from app.products.models import Product
from app.stock_adjustments.models import StockMovement, StockBalance
from app.stock_adjustments.service import post_movement
from app.posting.control_accounts import ControlAccountError
from app.settings import AppSettings

pytestmark = [pytest.mark.integration]


def _assign(code_setting, code, account_factory):
    account_factory(code)
    AppSettings.set_setting(code_setting, code, updated_by='test')


def _released_wo(main_branch, out_code, comp_code, qty_per='2', track_comp=True, qty_to_produce='5'):
    out = Product(code=out_code, name='Out', is_active=True)
    comp = Product(code=comp_code, name='Comp', is_active=True, track_inventory=track_comp,
                  costing_method='moving_average' if track_comp else None)
    db.session.add_all([out, comp]); db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='discrete')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id,
                                        quantity_per=Decimal(qty_per)))
    db.session.add(bom); db.session.commit()
    wo = WorkOrder(wo_number=generate_wo_number(), bom_id=bom.id, branch_id=main_branch.id,
                   qty_to_produce=Decimal(qty_to_produce))
    db.session.add(wo); db.session.commit()
    release_work_order(wo, None)
    db.session.commit()
    return wo


def test_tracked_component_posts_movement_and_wip_je(db_session, main_branch, admin_user, make_account):
    _assign('inventory_account_code', '1401', make_account)
    _assign('wip_account_code', '1402', make_account)
    wo = _released_wo(main_branch, 'CM-OUT1', 'CM-COMP1')
    comp = wo.materials[0].component_product
    post_movement(comp, main_branch.id, 'receipt', Decimal('50'), Decimal('4.00'),
                  'seed', None, 'seed stock', admin_user)
    db.session.commit()

    consume_materials(wo, [(wo.materials[0], Decimal('6'))], admin_user)
    db.session.commit()

    mv = StockMovement.query.filter_by(source_document_type='work_order', source_document_id=wo.id).one()
    assert mv.quantity == Decimal('-6.0000')
    assert mv.unit_cost == Decimal('4.00')   # current average, UNCHANGED by the issue
    je = mv.journal_entry
    assert je is not None and je.is_balanced and je.entry_type == 'manufacturing_consumption'
    wip_line = next(l for l in je.lines if l.account.code == '1402')
    inv_line = next(l for l in je.lines if l.account.code == '1401')
    assert wip_line.debit_amount == Decimal('24.00') and inv_line.credit_amount == Decimal('24.00')
    bal = StockBalance.query.filter_by(product_id=comp.id, branch_id=main_branch.id).one()
    assert bal.quantity_on_hand == Decimal('44.0000')
    assert bal.average_unit_cost == Decimal('4.00')


def test_untracked_component_posts_nothing(db_session, main_branch, admin_user, make_account):
    wo = _released_wo(main_branch, 'CM-OUT2', 'CM-COMP2', track_comp=False)
    consume_materials(wo, [(wo.materials[0], Decimal('3'))], admin_user)  # no accounts assigned -- must not raise
    db.session.commit()
    assert StockMovement.query.count() == 0


def test_fails_closed_before_any_write_when_wip_unassigned(db_session, main_branch, admin_user, make_account):
    _assign('inventory_account_code', '1401', make_account)  # wip left unassigned
    wo = _released_wo(main_branch, 'CM-OUT3', 'CM-COMP3')
    with pytest.raises(ControlAccountError):
        consume_materials(wo, [(wo.materials[0], Decimal('1'))], admin_user)
    assert StockMovement.query.filter_by(source_document_type='work_order').count() == 0


def test_multi_line_consumption_accumulates_balanced_je(db_session, main_branch, admin_user, make_account):
    _assign('inventory_account_code', '1401', make_account)
    _assign('wip_account_code', '1402', make_account)
    out = Product(code='CM-OUT4', name='Out', is_active=True)
    comp1 = Product(code='CM-COMP4A', name='Comp A', is_active=True, track_inventory=True, costing_method='moving_average')
    comp2 = Product(code='CM-COMP4B', name='Comp B', is_active=True, track_inventory=True, costing_method='moving_average')
    db.session.add_all([out, comp1, comp2]); db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='discrete')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp1.id, quantity_per=Decimal('1')))
    bom.lines.append(BillOfMaterialLine(line_number=2, component_product_id=comp2.id, quantity_per=Decimal('1')))
    db.session.add(bom); db.session.commit()
    wo = WorkOrder(wo_number=generate_wo_number(), bom_id=bom.id, branch_id=main_branch.id, qty_to_produce=Decimal('5'))
    db.session.add(wo); db.session.commit()
    release_work_order(wo, None); db.session.commit()
    post_movement(comp1, main_branch.id, 'receipt', Decimal('20'), Decimal('2.00'), 'seed', None, 's', admin_user)
    post_movement(comp2, main_branch.id, 'receipt', Decimal('20'), Decimal('3.00'), 'seed', None, 's', admin_user)
    db.session.commit()
    mat1 = next(m for m in wo.materials if m.component_product_id == comp1.id)
    mat2 = next(m for m in wo.materials if m.component_product_id == comp2.id)

    consume_materials(wo, [(mat1, Decimal('4')), (mat2, Decimal('2'))], admin_user)
    db.session.commit()

    je = StockMovement.query.filter_by(source_document_type='work_order', source_document_id=wo.id).first().journal_entry
    assert je.is_balanced
    assert je.total_debit == Decimal('14.00')   # 4*2.00 + 2*3.00
    assert je.lines.count() == 4


def test_negative_on_hand_consumption_surfaces_warning(db_session, main_branch, admin_user, make_account):
    _assign('inventory_account_code', '1401', make_account)
    _assign('wip_account_code', '1402', make_account)
    wo = _released_wo(main_branch, 'CM-OUT5', 'CM-COMP5')  # no prior receipt -- zero on-hand
    consume_materials(wo, [(wo.materials[0], Decimal('3'))], admin_user)
    db.session.commit()
    assert wo._negative_warnings == [wo.materials[0].component_product.code]
