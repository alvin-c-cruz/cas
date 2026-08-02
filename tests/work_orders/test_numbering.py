"""WO number generation tests (R-07 D2) -- plain continuous 5-digit sequence,
mirroring generate_invoice_number's contract (no prefix, no reset)."""
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.work_orders]


def test_generate_wo_number_format(db_session):
    from app.work_orders.forms import generate_wo_number
    n = generate_wo_number()
    assert n == '00001'


def test_generate_wo_number_increments(db_session, main_branch):
    from app import db
    from app.work_orders.forms import generate_wo_number
    from app.work_orders.models import WorkOrder
    from app.bill_of_materials.models import BillOfMaterial
    from app.products.models import Product
    p = Product(code='WON-P1', name='Product', is_active=True)
    db.session.add(p); db.session.commit()
    bom = BillOfMaterial(product_id=p.id, manufacturing_mode='discrete')
    db.session.add(bom); db.session.commit()
    first = generate_wo_number()
    db.session.add(WorkOrder(wo_number=first, bom_id=bom.id, branch_id=main_branch.id,
                             qty_to_produce=1))
    db.session.commit()
    second = generate_wo_number()
    assert second == '00002'


def test_generate_wo_number_ignores_legacy_prefixed_numbers(db_session, main_branch):
    from app import db
    from app.work_orders.forms import generate_wo_number
    from app.work_orders.models import WorkOrder
    from app.bill_of_materials.models import BillOfMaterial
    from app.products.models import Product
    p = Product(code='WON-P2', name='Product', is_active=True)
    db.session.add(p); db.session.commit()
    bom = BillOfMaterial(product_id=p.id, manufacturing_mode='discrete')
    db.session.add(bom); db.session.commit()
    db.session.add(WorkOrder(wo_number='WO-2026-07-0030', bom_id=bom.id,
                             branch_id=main_branch.id, qty_to_produce=1))
    db.session.commit()
    assert generate_wo_number() == '00001'
