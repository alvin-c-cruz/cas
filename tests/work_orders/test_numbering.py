"""WO number generation tests (R-07 D2) -- mirrors generate_quotation_number's contract."""
import pytest

pytestmark = [pytest.mark.integration]


def test_generate_wo_number_format(db_session):
    from app.work_orders.forms import generate_wo_number
    from app.utils import ph_now
    n = generate_wo_number()
    today = ph_now().date()
    assert n == f'WO-{today.year:04d}-{today.month:02d}-0001'


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
    assert second != first
    assert second.endswith('0002')
