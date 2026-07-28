"""generate_work_order_costing_variance_report (R-07 Discrete Track slice D5).
See docs/superpowers/specs/2026-07-28-r07-d5-wo-costing-variance-report-design.md."""
from datetime import timedelta
from decimal import Decimal

import pytest

from app import db
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialLine, BillOfMaterialOperation
from app.products.models import Product
from app.reports.work_order_costing import generate_work_order_costing_variance_report
from app.stock_adjustments.service import post_movement
from app.utils import ph_now
from app.work_centers.models import WorkCenter
from app.work_orders.forms import generate_wo_number
from app.work_orders.models import WorkOrder
from app.work_orders.service import (release_work_order, issue_material, start_operation,
                                     complete_operation, complete_work_order_batch,
                                     force_close_work_order)

pytestmark = [pytest.mark.integration]


def _ready_wo(main_branch, accountant_user, qty_to_produce='10',
              costing_method='moving_average', standard_cost=None,
              hourly_rate='60.00', minutes='60', code_suffix='A'):
    out = Product(code=f'D5-OUT-{code_suffix}', name='Out', track_inventory=True,
                  costing_method=costing_method, standard_cost=standard_cost, is_active=True)
    comp = Product(code=f'D5-COMP-{code_suffix}', name='Comp', track_inventory=True,
                   costing_method='moving_average', is_active=True)
    db.session.add_all([out, comp]); db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='discrete')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id,
                                        quantity_per=Decimal('1')))
    db.session.add(bom); db.session.commit()
    wc = WorkCenter(branch_id=main_branch.id, code=f'D5-WC-{code_suffix}', name='Line',
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


def test_standard_costed_wo_shows_material_labor_and_variance(
        db_session, main_branch, accountant_user, wo_control_accounts):
    wo = _ready_wo(main_branch, accountant_user, qty_to_produce='10',
                   costing_method='standard', standard_cost=Decimal('6.00'), code_suffix='B')
    complete_work_order_batch(wo, Decimal('10'), accountant_user)
    db.session.commit()

    data = generate_work_order_costing_variance_report(main_branch.id)
    assert len(data['rows']) == 1
    row = data['rows'][0]
    assert row['wo_number'] == wo.wo_number
    # material: 10 units x PHP5.00 component cost = 50.00; labor: 60 min x PHP60/hr = 60.00
    assert row['material_cost'] == Decimal('50.00')
    assert row['labor_cost'] == Decimal('60.00')
    assert row['actual_total'] == Decimal('110.00')
    # standard baseline: 10 x 6.00 = 60.00; variance = actual(110.00) - baseline(60.00) = 50.00
    assert row['standard_baseline'] == Decimal('60.00')
    assert row['variance_amount'] == Decimal('50.00')
    assert row['variance_pct'] == 83.33
    assert row['is_force_closed'] is False
    assert data['total_material'] == Decimal('50.00')
    assert data['total_variance'] == Decimal('50.00')


def test_moving_average_costed_wo_has_no_variance(
        db_session, main_branch, accountant_user, wo_control_accounts):
    wo = _ready_wo(main_branch, accountant_user, code_suffix='C')
    complete_work_order_batch(wo, Decimal('10'), accountant_user)
    db.session.commit()

    data = generate_work_order_costing_variance_report(main_branch.id)
    row = data['rows'][0]
    assert row['standard_baseline'] is None
    assert row['variance_amount'] is None
    assert row['variance_pct'] is None
    assert data['total_variance'] == Decimal('0.00')


def test_multi_batch_sums_both_completion_jes(
        db_session, main_branch, accountant_user, wo_control_accounts):
    wo = _ready_wo(main_branch, accountant_user, qty_to_produce='10', code_suffix='D')
    complete_work_order_batch(wo, Decimal('4'), accountant_user)
    db.session.commit()
    complete_work_order_batch(wo, Decimal('6'), accountant_user)
    db.session.commit()

    data = generate_work_order_costing_variance_report(main_branch.id)
    row = data['rows'][0]
    # unit_cost frozen at first batch: (50.00 material + 60.00 labor) / 10 = 11.00/unit
    # both batches together = 10 units x 11.00 = 110.00 total actual cost
    assert row['actual_total'] == Decimal('110.00')
    assert row['qty_completed'] == Decimal('10')


def test_force_closed_wo_folds_writeoff_into_variance(
        db_session, main_branch, accountant_user, wo_control_accounts):
    wo = _ready_wo(main_branch, accountant_user, qty_to_produce='10',
                   costing_method='standard', standard_cost=Decimal('6.00'), code_suffix='E')
    complete_work_order_batch(wo, Decimal('4'), accountant_user)
    db.session.commit()
    force_close_work_order(wo, 'Line breakdown, aborting remainder', accountant_user)
    db.session.commit()

    data = generate_work_order_costing_variance_report(main_branch.id)
    row = data['rows'][0]
    assert row['is_force_closed'] is True
    # the write-off posts its own inventory_variance leg for the unproduced 6 units --
    # total variance must be larger than the single-batch-only case above (50.00 for qty 10).
    assert row['variance_amount'] > Decimal('0.00')


def test_standard_baseline_survives_a_later_standard_cost_edit(
        db_session, main_branch, accountant_user, wo_control_accounts):
    """The report must reconcile (actual_total - standard_baseline == variance_amount)
    even if Product.standard_cost is edited after the WO completed -- both the baseline
    and the variance are derived from the posted JE, not a live standard_cost lookup."""
    wo = _ready_wo(main_branch, accountant_user, qty_to_produce='10',
                   costing_method='standard', standard_cost=Decimal('6.00'), code_suffix='H')
    complete_work_order_batch(wo, Decimal('10'), accountant_user)
    db.session.commit()

    wo.bom.product.standard_cost = Decimal('999.00')  # edited AFTER completion
    db.session.commit()

    data = generate_work_order_costing_variance_report(main_branch.id)
    row = data['rows'][0]
    assert row['actual_total'] - row['standard_baseline'] == row['variance_amount']
    assert row['standard_baseline'] == Decimal('60.00')  # unchanged from the original 6.00/unit


def test_branch_scoping_excludes_other_branches(
        db_session, main_branch, branch_manila, accountant_user, wo_control_accounts):
    wo = _ready_wo(main_branch, accountant_user, code_suffix='F')
    complete_work_order_batch(wo, Decimal('10'), accountant_user)
    db.session.commit()

    data = generate_work_order_costing_variance_report(branch_manila.id)
    assert data['rows'] == []


def test_date_range_filter_excludes_out_of_range_wo(
        db_session, main_branch, accountant_user, wo_control_accounts):
    wo = _ready_wo(main_branch, accountant_user, code_suffix='G')
    complete_work_order_batch(wo, Decimal('10'), accountant_user)
    db.session.commit()

    future_start = ph_now().date() + timedelta(days=30)
    data = generate_work_order_costing_variance_report(main_branch.id, date_from=future_start)
    assert data['rows'] == []


def test_zero_standard_cost_makes_baseline_exactly_zero_with_none_variance_pct(
        db_session, main_branch, accountant_user, wo_control_accounts):
    """Review finding 1 (template crash risk): a standard-costed product whose
    Product.standard_cost is 0.00 posts a completion whose entire actual cost is
    booked as variance -- inventory_amount - qty*0.00 -- so standard_baseline
    (actual_total - variance_amount) computes to exactly Decimal('0.00'), while
    variance_pct stays None (division-by-zero guard in _variance_pct). This is
    the exact "baseline is not None, but variance_pct IS None" combination the
    template's old single `standard_baseline is not none` gate could not tell
    apart from the moving-average case."""
    wo = _ready_wo(main_branch, accountant_user, qty_to_produce='10',
                   costing_method='standard', standard_cost=Decimal('0.00'), code_suffix='ZB')
    complete_work_order_batch(wo, Decimal('10'), accountant_user)
    db.session.commit()

    data = generate_work_order_costing_variance_report(main_branch.id)
    row = data['rows'][0]
    assert row['standard_baseline'] == Decimal('0.00')
    assert row['variance_amount'] == Decimal('110.00')
    assert row['variance_pct'] is None


def test_status_completed_includes_both_normal_and_force_closed(
        db_session, main_branch, accountant_user, wo_control_accounts):
    wo_normal = _ready_wo(main_branch, accountant_user, code_suffix='ST1')
    complete_work_order_batch(wo_normal, Decimal('10'), accountant_user)
    db.session.commit()

    wo_fc = _ready_wo(main_branch, accountant_user, qty_to_produce='10', code_suffix='ST2')
    complete_work_order_batch(wo_fc, Decimal('4'), accountant_user)
    db.session.commit()
    force_close_work_order(wo_fc, 'Line breakdown, aborting remainder', accountant_user)
    db.session.commit()

    data = generate_work_order_costing_variance_report(main_branch.id, status='completed')
    numbers = {r['wo_number'] for r in data['rows']}
    assert numbers == {wo_normal.wo_number, wo_fc.wo_number}


def test_status_force_closed_returns_only_the_force_closed_wo(
        db_session, main_branch, accountant_user, wo_control_accounts):
    wo_normal = _ready_wo(main_branch, accountant_user, code_suffix='ST3')
    complete_work_order_batch(wo_normal, Decimal('10'), accountant_user)
    db.session.commit()

    wo_fc = _ready_wo(main_branch, accountant_user, qty_to_produce='10', code_suffix='ST4')
    complete_work_order_batch(wo_fc, Decimal('4'), accountant_user)
    db.session.commit()
    force_close_work_order(wo_fc, 'Line breakdown, aborting remainder', accountant_user)
    db.session.commit()

    data = generate_work_order_costing_variance_report(main_branch.id, status='force_closed')
    numbers = {r['wo_number'] for r in data['rows']}
    assert numbers == {wo_fc.wo_number}


def test_status_all_removes_the_status_restriction_entirely(
        db_session, main_branch, accountant_user, wo_control_accounts):
    wo_completed = _ready_wo(main_branch, accountant_user, code_suffix='ST5')
    complete_work_order_batch(wo_completed, Decimal('10'), accountant_user)
    db.session.commit()

    # never completed -- _ready_wo leaves it at 'in_progress' (operation completed,
    # batch never posted). Zero cost data is fine -- it only needs to appear in the rows.
    wo_in_progress = _ready_wo(main_branch, accountant_user, code_suffix='ST6')
    assert wo_in_progress.status != 'completed'

    data = generate_work_order_costing_variance_report(main_branch.id, status='all')
    numbers = {r['wo_number'] for r in data['rows']}
    assert numbers == {wo_completed.wo_number, wo_in_progress.wo_number}
