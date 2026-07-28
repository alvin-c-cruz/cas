"""Screen route for the Work Order Costing & Variance Report (R-07 D5)."""
from datetime import timedelta
from decimal import Decimal

import pytest

from app import db
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialLine, BillOfMaterialOperation
from app.products.models import Product
from app.stock_adjustments.service import post_movement
from app.utils import ph_now
from app.work_centers.models import WorkCenter
from app.work_orders.forms import generate_wo_number
from app.work_orders.models import WorkOrder
from app.work_orders.service import (release_work_order, issue_material, start_operation,
                                     complete_operation, complete_work_order_batch,
                                     force_close_work_order)

pytestmark = [pytest.mark.integration]


def _login(client, u):
    with client.session_transaction() as s:
        s['_user_id'] = str(u.id); s['_fresh'] = True


def _ready_wo(main_branch, accountant_user, qty_to_produce='10',
              costing_method='moving_average', standard_cost=None,
              hourly_rate='60.00', minutes='60', code_suffix='A'):
    """Mirrors tests/unit/test_work_order_costing_report.py's own helper -- builds a
    released, material-issued, operation-completed WO ready for completion/force-close."""
    out = Product(code=f'D5V-OUT-{code_suffix}', name='Out', track_inventory=True,
                  costing_method=costing_method, standard_cost=standard_cost, is_active=True)
    comp = Product(code=f'D5V-COMP-{code_suffix}', name='Comp', track_inventory=True,
                   costing_method='moving_average', is_active=True)
    db.session.add_all([out, comp]); db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='discrete')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id,
                                        quantity_per=Decimal('1')))
    db.session.add(bom); db.session.commit()
    wc = WorkCenter(branch_id=main_branch.id, code=f'D5V-WC-{code_suffix}', name='Line',
                    hourly_rate=Decimal(hourly_rate))
    db.session.add(wc); db.session.commit()
    bom.operations.append(BillOfMaterialOperation(sequence_no=1, work_center_id=wc.id,
                                                   operation_name='Cut'))
    db.session.commit()

    wo = WorkOrder(wo_number=generate_wo_number(), bom_id=bom.id, branch_id=main_branch.id,
                   qty_to_produce=Decimal(qty_to_produce))
    db.session.add(wo); db.session.commit()
    release_work_order(wo, None)
    db.session.commit()

    post_movement(comp, main_branch.id, 'opening', Decimal('1000'), Decimal('5.00'),
                 'stock_adjustment', 0, 'seed', accountant_user)
    db.session.commit()
    issue_material(wo.materials[0], Decimal(qty_to_produce), accountant_user)
    db.session.commit()

    op = wo.operations[0]
    start_operation(op, accountant_user)
    db.session.commit()
    op.actual_start_at = ph_now() - timedelta(minutes=int(minutes))
    db.session.commit()
    complete_operation(op, accountant_user)
    db.session.commit()
    return wo


def test_accountant_can_view_report(client, db_session, accountant_user, main_branch):
    _login(client, accountant_user)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    resp = client.get('/reports/work-order-costing-variance')
    assert resp.status_code == 200
    assert b'Work Order Costing' in resp.data


def test_staff_cannot_view_report(client, db_session, staff_user, main_branch):
    # staff_user (unlike accountant_user) has no branches assigned by the fixture --
    # without this, the before_request branch-validation hook redirects to /login
    # before the accountant_or_above_required gate ever runs, and the test would
    # fail for the wrong reason. See tests/integration/test_accounts_payable_views.py
    # TestAccess for the same pattern.
    staff_user.set_branches([main_branch])
    db_session.commit()
    _login(client, staff_user)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    resp = client.get('/reports/work-order-costing-variance', follow_redirects=True)
    assert b'do not have permission' in resp.data


def test_renders_standard_costed_moving_average_and_force_closed_rows(
        client, db_session, accountant_user, main_branch, wo_control_accounts):
    """Real-data render check: standard-costed variance row, moving-average
    muted-dash row, force-closed badge, and totals footer all appear in the
    actual rendered HTML -- not just asserted at the generator-function level."""
    wo_std = _ready_wo(main_branch, accountant_user, qty_to_produce='10',
                       costing_method='standard', standard_cost=Decimal('6.00'),
                       code_suffix='STD')
    complete_work_order_batch(wo_std, Decimal('10'), accountant_user)
    db.session.commit()

    wo_ma = _ready_wo(main_branch, accountant_user, code_suffix='MA')
    complete_work_order_batch(wo_ma, Decimal('10'), accountant_user)
    db.session.commit()

    wo_fc = _ready_wo(main_branch, accountant_user, qty_to_produce='10',
                      costing_method='standard', standard_cost=Decimal('6.00'),
                      code_suffix='FC')
    complete_work_order_batch(wo_fc, Decimal('4'), accountant_user)
    db.session.commit()
    force_close_work_order(wo_fc, 'Line breakdown, aborting remainder', accountant_user)
    db.session.commit()

    _login(client, accountant_user)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    resp = client.get('/reports/work-order-costing-variance')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')

    assert wo_std.wo_number in body
    assert wo_ma.wo_number in body
    assert wo_fc.wo_number in body
    # standard-costed WO: material 50.00 + labor 60.00 = 110.00 actual, baseline 60.00,
    # variance +50.00 (unfavorable -- shows the "+" prefix and the unfavorable class)
    assert '₱110.00' in body
    assert '+₱50.00' in body
    assert 'variance-unfavorable' in body
    # moving-average WO: no standard baseline -- muted dash, not a bare number
    assert 'text-muted">&mdash;' in body or 'text-muted">—' in body
    # force-closed WO: badge shown next to its WO #
    assert 'badge-force-closed' in body
    assert 'Force-Closed' in body
    # totals footer present
    assert 'TOTALS' in body
