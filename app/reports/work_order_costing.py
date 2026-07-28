"""Work Order Costing & Variance Report (R-07 Discrete Track slice D5). Reads
material/labor/variance figures back off the posted manufacturing_production
JEs for each completed Work Order -- never recomputes them or stores a
parallel copy. See
docs/superpowers/specs/2026-07-28-r07-d5-wo-costing-variance-report-design.md.
"""
from datetime import date
from decimal import Decimal

from app.journal_entries.models import JournalEntry
from app.posting.control_accounts import get_control_account
from app.work_orders.models import WorkOrder

ZERO = Decimal('0.00')


def _completion_date(wo):
    """force_closed_at's date if force-closed, else the latest completion
    batch's date. None if the WO somehow has neither (shouldn't happen for a
    status='completed' WO)."""
    if wo.force_closed_at:
        return wo.force_closed_at.date()
    dates = [c.completed_at.date() for c in wo.completions if c.completed_at]
    return max(dates) if dates else None


def _cost_breakdown(wo):
    """(material_cost, labor_cost, variance_amount) summed across every
    manufacturing_production JE this WO posted -- every completion batch's
    JE plus any force-close write-off JE, since both share the same
    entry_type/reference (mirrors reverse_consumption's own query shape)."""
    jes = JournalEntry.query.filter_by(
        entry_type='manufacturing_production', reference=wo.wo_number).all()
    wip = get_control_account('wip', required=False)
    labor = get_control_account('labor_applied', required=False)
    variance_acct = get_control_account('inventory_variance', required=False)

    material_cost = ZERO
    labor_cost = ZERO
    variance_amount = ZERO
    for je in jes:
        for line in je.lines:
            if wip and line.account_id == wip.id:
                material_cost += line.credit_amount
            elif labor and line.account_id == labor.id:
                labor_cost += line.credit_amount
            elif variance_acct and line.account_id == variance_acct.id:
                variance_amount += line.debit_amount - line.credit_amount
    return material_cost, labor_cost, variance_amount


def _variance_pct(variance, baseline):
    """Mirrors budget_variance.py's own _variance_pct convention exactly."""
    if baseline == ZERO:
        return None
    return round(float(variance / baseline * 100), 2)


def generate_work_order_costing_variance_report(branch_id, status='completed',
                                                 date_from=None, date_to=None):
    """List of Work Orders (default: status='completed', which covers both
    normal completions and force-closed WOs) with their material/labor/total
    actual cost, standard-cost baseline, and variance, scoped to branch_id."""
    query = WorkOrder.query.filter(WorkOrder.branch_id == branch_id)
    if status == 'force_closed':
        # Force-closed is a SUBSET of completed -- force_close_work_order() sets
        # status='completed' too, only force_closed_at distinguishes it (there is
        # no separate 'force_closed' value in WO_STATUSES).
        query = query.filter(WorkOrder.status == 'completed', WorkOrder.force_closed_at.isnot(None))
    elif status == 'all':
        pass  # no status restriction at all -- 'all' is not a real WorkOrder.status value
    else:
        query = query.filter(WorkOrder.status == status)
    wos = query.all()

    rows = []
    total_material = ZERO
    total_labor = ZERO
    total_actual = ZERO
    total_variance = ZERO

    for wo in wos:
        completion_date = _completion_date(wo)
        if date_from and (completion_date is None or completion_date < date_from):
            continue
        if date_to and (completion_date is None or completion_date > date_to):
            continue

        material_cost, labor_cost, variance_amount = _cost_breakdown(wo)
        actual_total = material_cost + labor_cost

        product = wo.bom.product
        is_standard = product.costing_method == 'standard'
        # Derive the baseline from the POSTED figures (actual_total - variance), not a fresh
        # product.standard_cost lookup -- guarantees actual_total - standard_baseline ==
        # variance_amount always holds, even if standard_cost is edited after this WO completed.
        standard_baseline = (
            (actual_total - variance_amount).quantize(Decimal('0.01')) if is_standard else None)
        row_variance = variance_amount if is_standard else None
        variance_pct = (_variance_pct(row_variance, standard_baseline)
                        if is_standard else None)

        rows.append({
            'wo_number': wo.wo_number,
            'product_code': product.code,
            'product_name': product.name,
            'qty_completed': wo.qty_completed_to_date,
            'material_cost': material_cost,
            'labor_cost': labor_cost,
            'actual_total': actual_total,
            'standard_baseline': standard_baseline,
            'variance_amount': row_variance,
            'variance_pct': variance_pct,
            'is_force_closed': wo.force_closed_at is not None,
            'completion_date': completion_date,
        })
        total_material += material_cost
        total_labor += labor_cost
        total_actual += actual_total
        if standard_baseline is not None:
            total_variance += variance_amount

    rows.sort(key=lambda r: (r['completion_date'] or date.min, r['wo_number']))

    return {
        'rows': rows,
        'total_material': total_material,
        'total_labor': total_labor,
        'total_actual': total_actual,
        'total_variance': total_variance,
        'date_from': date_from,
        'date_to': date_to,
    }
