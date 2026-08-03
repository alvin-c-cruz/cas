"""Production Run lifecycle (R-07 Process Track slice P2).

Mirrors work_orders/service.py's shape. Opening a run snapshots the BOM's component
lines onto ProductionRunMaterial so a later BOM edit never disturbs a run already
under way -- the same rule release_work_order() applies on the Discrete side.
"""
from decimal import Decimal

from app import db
from app.bill_of_materials.service import consume_materials
from app.production_runs.models import ProductionRun, ProductionRunMaterial

ZERO = Decimal('0.00')
MONEY = Decimal('0.01')


def find_predecessor_run(bom_id, department_id, branch_id, period_start):
    """The most recent CLOSED run for the same cost pool ending before *period_start*.

    "Same cost pool" is (bom, department, branch): a different product line, a
    different department, or another branch accumulates its own WIP, so carrying
    across any of them would move value between pools that never touched.

    Only a CLOSED run qualifies. An OPEN one has not settled its ending WIP -- that
    figure is still moving, and is not even frozen yet. A CANCELLED one reversed its
    consumptions and therefore left nothing in WIP at all.

    period_end must be strictly BEFORE period_start; an overlapping run is not a
    predecessor, it is a double count.
    """
    return (ProductionRun.query
            .filter(ProductionRun.bom_id == bom_id,
                    ProductionRun.department_id == department_id,
                    ProductionRun.branch_id == branch_id,
                    ProductionRun.status == 'closed',
                    ProductionRun.period_end < period_start)
            .order_by(ProductionRun.period_end.desc(), ProductionRun.id.desc())
            .first())


def carry_beginning_wip(run):
    """Stamp *run*'s beginning WIP from its predecessor, or leave it at zero.

    PULLED here at create time rather than PUSHED at the predecessor's close: when a
    run closes, its successor usually does not exist yet, because the accountant
    closes the old period before opening the new one.

    What carries is the predecessor's units_ending_wip and its frozen
    ending_wip_cost -- the residual plug left sitting in the WIP account. A run
    closed before P4 shipped has no ending_wip_cost at all; that reads as zero, never
    NULL, since NULL would drop out of the cost pool's sum instead of adding nothing.
    """
    prior = find_predecessor_run(run.bom_id, run.department_id, run.branch_id,
                                 run.period_start)
    if prior is None:
        run.beginning_wip_units = Decimal('0')
        run.beginning_wip_cost = ZERO
        return None
    run.beginning_wip_units = Decimal(str(prior.units_ending_wip or 0))
    run.beginning_wip_cost = Decimal(str(prior.ending_wip_cost or 0)).quantize(ZERO)
    return prior


def update_period_results(run, units_completed_and_transferred=None, units_ending_wip=None,
                          ending_wip_pct_complete=None, conversion_cost=None):
    """Record the period's reported units and conversion cost. OPEN runs only.

    The status guard lives HERE rather than only in the view, copying
    issue_material() -- which is exactly why the material-issue route was safe all
    along while this one was not. P3 shipped the route with no status check at all;
    the template hid the form, so nothing surfaced it until a probe POSTed the URL
    directly against a CLOSED run and rewrote every figure
    (BUG-PERIOD-RESULTS-ROUTE-HAS-NO-STATUS-GUARD).

    The books survived that, because transferred_unit_cost/ending_wip_cost are frozen
    at close -- but the NEXT period did not: carry_beginning_wip() reads
    units_ending_wip LIVE beside that frozen cost, so a successor could inherit a
    fabricated unit count against a real cost.

    Does NOT commit -- the caller owns the transaction.
    """
    if run.status != 'open':
        raise ValueError('Period results can only be recorded on an open Production Run.')
    if units_completed_and_transferred is not None:
        run.units_completed_and_transferred = units_completed_and_transferred
    if units_ending_wip is not None:
        run.units_ending_wip = units_ending_wip
    if ending_wip_pct_complete is not None:
        run.ending_wip_pct_complete = ending_wip_pct_complete
    if conversion_cost is not None:
        run.conversion_cost = conversion_cost
    return run


def close_run(run, actor):
    """Close the period: apply conversion cost, transfer completed units to finished
    goods at the period's cost per equivalent unit, and freeze what stays in WIP.

    Two postings, both keyed on the run number:

    1. **Conversion applied** (`manufacturing_conversion`) -- Dr WIP / Cr Labor
       Applied. Conversion cost is entered MANUALLY on the run (P3, owner decision)
       and reaches the books nowhere else. Without this leg the cost pool would
       include value that never entered WIP, and relieving WIP at a cost/EU that
       includes conversion would drive the ledger's WIP balance NEGATIVE. Skipped
       entirely when conversion is zero.
    2. **Transfer** (`manufacturing_production`) -- Dr Inventory / Cr WIP at
       `units_transferred x cost_per_EU`, plus an `inventory_variance` leg when the
       output product is standard-costed.

    Why this does NOT call produce_finished_goods(): for a standard-costed output,
    post_movement values the receipt at Product.standard_cost and IGNORES the
    unit_cost passed to it, while produce_finished_goods reads its JE amount back
    from mv.unit_cost -- so WIP would be relieved at standard and the difference
    stranded. D4 hit this first and wrote its own JE for the same reason.

    What remains in WIP is the residual PLUG (pool - transferred), NOT
    `ending units x cost/EU`: the ending-WIP units are only partially complete, so
    valuing them at a full equivalent-unit cost would strand the difference in WIP
    permanently. The plug is what ties WIP to the GL, and it is what the successor
    run inherits as its beginning WIP.

    Does NOT commit -- the caller owns the transaction.
    """
    from app.bill_of_materials.service import _add_line, _new_je
    from app.journal_entries.utils import generate_entry_number
    from app.posting.control_accounts import get_control_account
    from app.production_runs.costing import compute_run_costing
    from app.stock_adjustments.service import post_movement
    from app.utils import ph_now

    if run.status != 'open':
        raise ValueError('Only an open Production Run can be closed.')

    data = compute_run_costing(run)
    transferred_units = Decimal(str(run.units_completed_and_transferred or 0))
    ending_units = Decimal(str(run.units_ending_wip or 0))
    if transferred_units <= 0 and ending_units <= 0:
        raise ValueError('There is nothing to close -- no period results have been '
                         'reported for this run.')

    product = run.output_product
    if transferred_units > 0 and (product is None or not product.track_inventory):
        raise ValueError('The output product is not inventory-tracked, so completed '
                         'units cannot be transferred to finished goods.')

    pool = data['total_cost']
    # Transferring units out of an EMPTY pool would receive finished goods at 0.00 and
    # post a zero-value JE -- which balances (0 = 0), so is_balanced cannot catch it,
    # and the free stock then relieves COGS at zero when it is sold
    # (BUG-CLOSE-WITH-ZERO-COST-POOL-CREATES-FREE-INVENTORY). Refuse rather than skip
    # the posting: skipping would mark the run closed while stranding the units.
    # Note this guards the TRANSFER only -- a period that finished nothing is
    # legitimately empty and still closes.
    if transferred_units > 0 and pool <= ZERO:
        raise ValueError('This period has no cost to transfer -- no material has been '
                         'issued and no conversion cost entered. Record them before '
                         'closing, or the finished goods would be received at zero cost.')
    per_eu = data['cost_per_equivalent_unit'] or ZERO
    conversion = data['conversion_cost']

    wip_account = get_control_account('wip')

    # 1. apply conversion cost to WIP so the pool and the ledger agree
    if conversion > ZERO:
        labor_account = get_control_account('labor_applied')
        je = _new_je(generate_entry_number(run.branch_id), ph_now().date(),
                     f'Production Run {run.run_number} conversion applied',
                     run.run_number, 'manufacturing_conversion', run.branch_id, actor)
        _add_line(je, 1, wip_account.id, 'Conversion cost applied', conversion, ZERO)
        _add_line(je, 2, labor_account.id, 'Conversion cost applied', ZERO, conversion)
        db.session.flush()
        je.calculate_totals()
        if not je.is_balanced:
            raise ValueError(f'{run.run_number} conversion JE does not balance.')

    # 2. transfer the completed units out of WIP
    transferred_amount = ZERO
    if transferred_units > 0:
        inv_account = get_control_account('inventory')
        transferred_amount = (transferred_units * per_eu).quantize(MONEY)
        je = _new_je(generate_entry_number(run.branch_id), ph_now().date(),
                     f'Production Run {run.run_number} transferred to finished goods',
                     run.run_number, 'manufacturing_production', run.branch_id, actor)
        mv, _went_negative = post_movement(
            product, run.branch_id, 'production', transferred_units, per_eu,
            'production_run', run.id, f'{run.run_number} transferred to finished goods',
            actor, journal_entry_id=je.id)
        # The movement's OWN unit_cost, not per_eu -- they differ for a standard-costed
        # product, and the stock ledger's figure is what Inventory must be debited.
        inventory_amount = (transferred_units * Decimal(str(mv.unit_cost))).quantize(MONEY)
        n = 1
        _add_line(je, n, inv_account.id, f'{product.code} transferred in',
                  inventory_amount, ZERO); n += 1
        _add_line(je, n, wip_account.id, f'{product.code} relieved from WIP',
                  ZERO, transferred_amount); n += 1
        variance = (transferred_amount - inventory_amount).quantize(MONEY)
        if variance != ZERO:
            variance_account = get_control_account('inventory_variance')
            if variance > ZERO:
                _add_line(je, n, variance_account.id,
                          f'{product.code} standard cost variance', variance, ZERO)
            else:
                _add_line(je, n, variance_account.id,
                          f'{product.code} standard cost variance', ZERO, -variance)
        db.session.flush()
        je.calculate_totals()
        if not je.is_balanced:
            raise ValueError(f'{run.run_number} transfer JE does not balance '
                             f'(debit={je.total_debit}, credit={je.total_credit}).')

    run.transferred_unit_cost = per_eu
    run.ending_wip_cost = (pool - transferred_amount).quantize(MONEY)
    run.status = 'closed'
    run.closed_at = ph_now()
    run.closed_by_id = actor.id
    return run


def cancel_run(run, reason, actor):
    """Cancel an open run, reversing every material consumption it posted.

    Component stock returns to its pre-issue level and the WIP debits are reversed,
    so a cancelled run leaves NOTHING behind in WIP -- which is exactly why
    find_predecessor_run() refuses to carry a beginning WIP from one.

    Reversal goes through the shared reverse_document_movements() primitive (the
    same one delivery_receipts / receiving_reports / sales_memos use), which posts
    an opposite movement per original at the SAME cost basis, keeping the
    append-only ledger consistent. It does not create a JE, so one is created here
    and passed in -- and it is skipped entirely when the run consumed nothing.

    A CLOSED run cannot be cancelled: it has already transferred value into finished
    goods, and unwinding that is a different operation.

    Does NOT commit -- the caller owns the transaction.
    """
    from app.bill_of_materials.service import _add_line, _new_je
    from app.journal_entries.utils import generate_entry_number
    from app.posting.control_accounts import get_control_account
    from app.stock_adjustments.models import StockMovement
    from app.stock_adjustments.service import post_movement, reverse_document_movements
    from app.utils import ph_now

    if run.status == 'closed':
        raise ValueError('A closed Production Run cannot be cancelled.')
    if run.status != 'open':
        raise ValueError('Only an open Production Run can be cancelled.')
    reason = (reason or '').strip()
    if not reason:
        raise ValueError('A reason is required to cancel a Production Run.')

    originals = StockMovement.query.filter_by(
        source_document_type='production_run', source_document_id=run.id).all()
    if originals:
        wip_account = get_control_account('wip')
        inv_account = get_control_account('inventory')
        je = _new_je(generate_entry_number(run.branch_id), ph_now().date(),
                     f'Production Run {run.run_number} cancelled -- consumption reversed',
                     run.run_number, 'manufacturing_consumption', run.branch_id, actor)
        reversals = reverse_document_movements('production_run', run.id, actor,
                                               journal_entry_id=je.id)
        n = 1
        for mv in reversals:
            amount = (abs(Decimal(str(mv.quantity))) * Decimal(str(mv.unit_cost))).quantize(MONEY)
            if amount == ZERO:
                continue
            # The original was Dr WIP / Cr Inventory; the reversal is the mirror.
            _add_line(je, n, inv_account.id, 'Component returned to stock',
                      amount, ZERO); n += 1
            _add_line(je, n, wip_account.id, 'WIP reversed on cancellation',
                      ZERO, amount); n += 1
        db.session.flush()
        je.calculate_totals()
        if not je.is_balanced:
            raise ValueError(f'{run.run_number} cancellation JE does not balance '
                             f'(debit={je.total_debit}, credit={je.total_credit}).')

    run.status = 'cancelled'
    run.cancel_reason = reason
    run.cancelled_by_id = actor.id
    run.cancelled_at = ph_now()
    return run


def snapshot_materials(run):
    """Copy the BOM's component lines onto the run, scaled by units_started."""
    if not run.bom.lines:
        raise ValueError('This Bill of Materials has no component lines -- nothing to produce.')
    for line in run.bom.lines:
        run.materials.append(ProductionRunMaterial(
            line_number=line.line_number,
            component_product_id=line.component_product_id,
            quantity_required=line.quantity_per * run.units_started,
            uom_id=line.uom_id,
        ))


def issue_material(material, quantity, actor):
    """Consume `quantity` of one snapshotted component into WIP.

    Posts Dr wip / Cr inventory through the shared consume_materials() seam (which
    accepts a ProductionRun since P2 Task 2). Does NOT commit -- the caller owns the
    transaction, same contract as the Discrete track's issue_material.
    """
    run = material.run
    if run.status != 'open':
        raise ValueError('Materials can only be issued to an open Production Run.')
    quantity = Decimal(str(quantity))
    if quantity <= 0:
        raise ValueError('Issue quantity must be greater than zero.')
    remaining = Decimal(str(material.quantity_required)) - Decimal(str(material.quantity_issued or 0))
    if quantity > remaining:
        raise ValueError(
            f'Cannot issue {quantity} -- only {remaining} of '
            f'{material.component_product.code} remains required for this run.')

    consume_materials(run, [(material, quantity)], actor)
    material.quantity_issued = Decimal(str(material.quantity_issued or 0)) + quantity
