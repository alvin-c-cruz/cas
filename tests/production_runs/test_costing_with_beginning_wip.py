"""P4 Task 3 -- beginning WIP enters the cost pool (revises P3's shipped formula).

Weighted-average process costing values the period against
    pool = beginning WIP cost brought forward + costs added this period
    cost per EU = pool / equivalent units

P3 shipped with the pool reading only this run's OWN posted journal entries, which
is correct for a first period and understates every period after it by exactly what
the predecessor left behind -- while that value sits stranded in the WIP control
account with nothing ever relieving it. This module pins the corrected pool.

Equivalent units are deliberately NOT changed: EU counts completed + ending-WIP
equivalents regardless of which period the cost came from.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialLine
from app.manufacturing_departments.models import ManufacturingDepartment
from app.production_runs.costing import compute_run_costing
from app.production_runs.models import ProductionRun
from app.production_runs.service import issue_material, snapshot_materials
from app.products.models import Product
from app.stock_adjustments.service import post_movement

pytestmark = [pytest.mark.integration, pytest.mark.production_runs]


def _setup(branch, actor, suffix, unit_cost='5.00', qty_per='2'):
    comp = Product(code=f'BW-C-{suffix}', name='Fresh Mango', track_inventory=True,
                   costing_method='moving_average', standard_cost=Decimal(unit_cost),
                   is_active=True)
    out = Product(code=f'BW-O-{suffix}', name='Dried Mango', is_active=True)
    db.session.add_all([comp, out]); db.session.commit()
    post_movement(comp, branch.id, 'opening', Decimal('10000'), Decimal(unit_cost),
                  'stock_adjustment', 0, 'seed', actor)
    db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='process')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id,
                                        quantity_per=Decimal(qty_per)))
    db.session.add(bom); db.session.commit()
    dept = ManufacturingDepartment(branch_id=branch.id, code=f'D{suffix}', name='Dehydration')
    db.session.add(dept); db.session.commit()
    return bom, dept


def _run(branch, bom, dept, number, units_started='100', **kw):
    run = ProductionRun(run_number=number, bom_id=bom.id, department_id=dept.id,
                        branch_id=branch.id, period_start=date(2026, 9, 1),
                        period_end=date(2026, 9, 30),
                        units_started=Decimal(units_started), **kw)
    db.session.add(run); db.session.commit()
    snapshot_materials(run); db.session.commit()
    return run


class TestPoolIncludesBeginningWip:
    def test_beginning_wip_cost_is_reported(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        bom, dept = _setup(main_branch, accountant_user, 'A')
        run = _run(main_branch, bom, dept, 'BW001',
                   beginning_wip_cost=Decimal('225.00'),
                   beginning_wip_units=Decimal('20'))
        data = compute_run_costing(run)
        assert data['beginning_wip_cost'] == Decimal('225.00')

    def test_beginning_wip_is_added_to_the_pool(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """The mockup's own second-period figures: 225.00 carried + 1200.00 material
        + 500.00 conversion = 1925.00 over 110 EU = 17.50."""
        bom, dept = _setup(main_branch, accountant_user, 'B')
        run = _run(main_branch, bom, dept, 'BW002', units_started='120',
                   beginning_wip_cost=Decimal('225.00'),
                   beginning_wip_units=Decimal('20'),
                   conversion_cost=Decimal('500.00'),
                   units_completed_and_transferred=Decimal('100'),
                   units_ending_wip=Decimal('20'),
                   ending_wip_pct_complete=Decimal('50'))
        issue_material(run.materials[0], Decimal('240'), accountant_user)  # 240 x 5.00 = 1200
        db.session.commit()

        data = compute_run_costing(run)
        assert data['material_cost'] == Decimal('1200.00')
        assert data['conversion_cost'] == Decimal('500.00')
        assert data['beginning_wip_cost'] == Decimal('225.00')
        assert data['total_cost'] == Decimal('1925.00'), 'pool must include beginning WIP'
        assert data['equivalent_units'] == Decimal('110.0000')
        assert data['cost_per_equivalent_unit'] == Decimal('17.50')

    def test_a_first_period_is_unchanged_from_P3(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """Regression guard on the revision itself: with no beginning WIP the answer
        must still be exactly what P3 shipped (1450.00 / 90 = 16.11)."""
        bom, dept = _setup(main_branch, accountant_user, 'C')
        run = _run(main_branch, bom, dept, 'BW003',
                   conversion_cost=Decimal('450.00'),
                   units_completed_and_transferred=Decimal('80'),
                   units_ending_wip=Decimal('20'),
                   ending_wip_pct_complete=Decimal('50'))
        issue_material(run.materials[0], Decimal('200'), accountant_user)
        db.session.commit()
        data = compute_run_costing(run)
        assert data['beginning_wip_cost'] == Decimal('0.00')
        assert data['total_cost'] == Decimal('1450.00')
        assert data['cost_per_equivalent_unit'] == Decimal('16.11')

    def test_beginning_wip_units_do_NOT_change_equivalent_units(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """Under weighted average, EU counts what this period completed plus its
        ending-WIP equivalents. Beginning-WIP UNITS are already inside
        units_completed_and_transferred when they finish -- adding them again would
        double-count. Only the beginning-WIP COST joins the pool."""
        bom, dept = _setup(main_branch, accountant_user, 'D')
        run = _run(main_branch, bom, dept, 'BW004',
                   beginning_wip_units=Decimal('20'),
                   beginning_wip_cost=Decimal('225.00'),
                   units_completed_and_transferred=Decimal('80'),
                   units_ending_wip=Decimal('20'),
                   ending_wip_pct_complete=Decimal('50'))
        assert compute_run_costing(run)['equivalent_units'] == Decimal('90.0000')

    def test_beginning_wip_alone_still_costs_out(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """A period that adds nothing but finishes what it inherited."""
        bom, dept = _setup(main_branch, accountant_user, 'E')
        run = _run(main_branch, bom, dept, 'BW005',
                   beginning_wip_cost=Decimal('225.00'),
                   beginning_wip_units=Decimal('20'),
                   units_completed_and_transferred=Decimal('20'))
        data = compute_run_costing(run)
        assert data['material_cost'] == Decimal('0.00')
        assert data['total_cost'] == Decimal('225.00')
        assert data['equivalent_units'] == Decimal('20.0000')
        assert data['cost_per_equivalent_unit'] == Decimal('11.25')

    def test_zero_equivalent_units_still_returns_none(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """P3's divide-by-zero guard must survive the revision -- a run that carried
        cost forward but has reported nothing yet is the normal start-of-period state,
        and now it has a NON-zero pool, which is exactly when a bad guard would divide."""
        bom, dept = _setup(main_branch, accountant_user, 'F')
        run = _run(main_branch, bom, dept, 'BW006',
                   beginning_wip_cost=Decimal('225.00'),
                   beginning_wip_units=Decimal('20'))
        data = compute_run_costing(run)
        assert data['equivalent_units'] == Decimal('0.0000')
        assert data['cost_per_equivalent_unit'] is None
        assert data['total_cost'] == Decimal('225.00'), 'the pool is still reported'
