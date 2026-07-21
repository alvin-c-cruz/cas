"""issue_material() tests (R-07 D3). consume_materials() is still a Wave-0
NotImplementedError stub (R-03 slice 2 not yet built) -- these tests prove
issue_material's own validation/accounting logic by monkeypatching
consume_materials to a no-op, AND separately confirm the real current stub
still raises, so a future R-03 landing that silently changes the contract
gets caught here."""
from decimal import Decimal
import pytest
from app import db
from app.work_orders.models import WorkOrder
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialLine
from app.products.models import Product

pytestmark = [pytest.mark.integration]


def _released_wo_with_material(main_branch, qty_per='2'):
    out = Product(code='ISS-OUT', name='Out', is_active=True)
    comp = Product(code='ISS-COMP', name='Comp', is_active=True)
    db.session.add_all([out, comp]); db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='discrete')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id,
                                        quantity_per=Decimal(qty_per)))
    db.session.add(bom); db.session.commit()
    from app.work_orders.service import release_work_order
    from app.work_orders.forms import generate_wo_number
    wo = WorkOrder(wo_number=generate_wo_number(), bom_id=bom.id, branch_id=main_branch.id,
                   qty_to_produce=Decimal('5'))
    db.session.add(wo); db.session.commit()
    release_work_order(wo, None)
    db.session.commit()
    return wo


def test_issue_material_calls_real_consume_materials_without_control_accounts_when_untracked(
        db_session, main_branch, accountant_user):
    """consume_materials is no longer a Wave-0 stub as of R-03 slice 2a-iv --
    this replaces the old test that pinned the propagating NotImplementedError.
    ISS-COMP (from _released_wo_with_material) is untracked by default, so
    this exercises the real seam end-to-end via the untracked no-op path,
    with zero control accounts assigned."""
    from app.work_orders.service import issue_material
    wo = _released_wo_with_material(main_branch)
    mat = wo.materials[0]
    issue_material(mat, Decimal('3'), accountant_user)   # must not raise
    db.session.commit()
    assert mat.quantity_issued == Decimal('3')


def test_issue_material_updates_quantity_and_transitions_wo_when_consume_succeeds(db_session, main_branch, accountant_user, monkeypatch):
    from app.work_orders import service as wo_service
    monkeypatch.setattr(wo_service, 'consume_materials', lambda source_document, lines, actor: None)
    wo = _released_wo_with_material(main_branch)
    mat = wo.materials[0]
    assert wo.status == 'released'
    wo_service.issue_material(mat, Decimal('4'), accountant_user)
    db.session.commit()
    assert mat.quantity_issued == Decimal('4')
    assert wo.status == 'in_progress'


def test_issue_material_blocks_over_issue(db_session, main_branch, accountant_user, monkeypatch):
    from app.work_orders import service as wo_service
    monkeypatch.setattr(wo_service, 'consume_materials', lambda source_document, lines: None)
    wo = _released_wo_with_material(main_branch)  # quantity_required = 2 * 5 = 10
    mat = wo.materials[0]
    with pytest.raises(ValueError, match='remaining'):
        wo_service.issue_material(mat, Decimal('11'), accountant_user)


def test_issue_material_blocks_non_positive_quantity(db_session, main_branch, accountant_user, monkeypatch):
    from app.work_orders import service as wo_service
    monkeypatch.setattr(wo_service, 'consume_materials', lambda source_document, lines: None)
    wo = _released_wo_with_material(main_branch)
    mat = wo.materials[0]
    with pytest.raises(ValueError, match='greater than zero'):
        wo_service.issue_material(mat, Decimal('0'), accountant_user)


def test_issue_material_blocked_when_wo_draft(db_session, main_branch, accountant_user, monkeypatch):
    from app.work_orders import service as wo_service
    monkeypatch.setattr(wo_service, 'consume_materials', lambda source_document, lines: None)
    out = Product(code='ISD-OUT', name='Out', is_active=True)
    comp = Product(code='ISD-COMP', name='Comp', is_active=True)
    db.session.add_all([out, comp]); db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='discrete')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id, quantity_per=Decimal('1')))
    db.session.add(bom); db.session.commit()
    from app.work_orders.forms import generate_wo_number
    wo = WorkOrder(wo_number=generate_wo_number(), bom_id=bom.id, branch_id=main_branch.id,
                   qty_to_produce=Decimal('1'))
    db.session.add(wo); db.session.commit()
    # wo.materials is empty -- draft WOs have no snapshot yet -- so build a
    # detached-style check against a released sibling instead is unnecessary;
    # this test only needs a WorkOrderMaterial row to call issue_material on,
    # so release then force status back to draft to isolate the guard:
    from app.work_orders.service import release_work_order
    release_work_order(wo, None)
    db.session.commit()
    mat = wo.materials[0]
    wo.status = 'draft'
    db.session.commit()
    with pytest.raises(ValueError, match='released or in-progress'):
        wo_service.issue_material(mat, Decimal('1'), accountant_user)
