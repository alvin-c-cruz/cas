"""P5 Task 2 -- the quantity schedule and its unaccounted-units line.

    units to account for  = beginning WIP + started
    units accounted for   = completed & transferred + ending WIP
    unaccounted           = to account for - accounted for

**These will routinely NOT be equal, and that is correct.** Dehydration loses mass;
any process with shrinkage or spoilage does. A design that forced them to tie would
be wrong, and one that showed a silent mismatch would be worse -- so the difference
is an explicit line.

The generator returns the SIGN raw and makes no rendering decision. Which sign gets
flagged is the template's job (Task 3): positive is ordinary loss and is shown
plainly; negative means more units were accounted for than ever existed, which is a
data error.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialLine
from app.manufacturing_departments.models import ManufacturingDepartment
from app.production_runs.models import ProductionRun
from app.production_runs.service import close_run, issue_material, snapshot_materials
from app.products.models import Product
from app.reports.production_run_costing import generate_production_run_cost_report
from app.stock_adjustments.service import post_movement

pytestmark = [pytest.mark.integration, pytest.mark.reports, pytest.mark.production_runs]

_N = [0]


def _closed_run(branch, actor, suffix, **run_kw):
    comp = Product(code=f'QS-C-{suffix}', name='Fresh Mango', track_inventory=True,
                   costing_method='moving_average', standard_cost=Decimal('5.00'),
                   is_active=True)
    out = Product(code=f'QS-O-{suffix}', name='Dried Mango', track_inventory=True,
                  costing_method='moving_average', is_active=True)
    db.session.add_all([comp, out]); db.session.commit()
    post_movement(comp, branch.id, 'opening', Decimal('10000'), Decimal('5.00'),
                  'stock_adjustment', 0, 'seed', actor, movement_date=date(2026, 1, 1))
    db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='process')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id,
                                        quantity_per=Decimal('2')))
    db.session.add(bom); db.session.commit()
    dept = ManufacturingDepartment(branch_id=branch.id, code=f'Q{suffix}', name='Dehydration')
    db.session.add(dept); db.session.commit()

    _N[0] += 1
    kw = dict(conversion_cost=Decimal('450.00'),
              units_completed_and_transferred=Decimal('80'),
              units_ending_wip=Decimal('20'),
              ending_wip_pct_complete=Decimal('50'))
    kw.update(run_kw)
    run = ProductionRun(run_number='QS%04d' % _N[0], bom_id=bom.id, department_id=dept.id,
                        branch_id=branch.id, period_start=date(2026, 8, 1),
                        period_end=date(2026, 8, 31), units_started=Decimal('100'), **kw)
    db.session.add(run); db.session.commit()
    snapshot_materials(run); db.session.commit()
    issue_material(run.materials[0], Decimal('200'), actor); db.session.commit()
    close_run(run, actor); db.session.commit()
    return run


class TestQuantitySchedule:
    def test_both_halves_of_the_schedule(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        run = _closed_run(main_branch, accountant_user, 'A',
                          beginning_wip_units=Decimal('20'),
                          beginning_wip_cost=Decimal('225.00'))
        rep = generate_production_run_cost_report(run.id, main_branch.id)
        assert rep['beginning_wip_units'] == Decimal('20.0000')
        assert rep['units_started'] == Decimal('100.0000')
        assert rep['units_to_account_for'] == Decimal('120.0000')
        assert rep['units_completed_and_transferred'] == Decimal('80.0000')
        assert rep['units_ending_wip'] == Decimal('20.0000')
        assert rep['units_accounted_for'] == Decimal('100.0000')

    def test_unaccounted_is_positive_for_ordinary_shrinkage(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """120 to account for, 100 accounted for -> 20 lost. Philgen's normal state."""
        run = _closed_run(main_branch, accountant_user, 'B',
                          beginning_wip_units=Decimal('20'),
                          beginning_wip_cost=Decimal('225.00'))
        rep = generate_production_run_cost_report(run.id, main_branch.id)
        assert rep['unaccounted_units'] == Decimal('20.0000')

    def test_unaccounted_is_zero_when_the_schedule_ties(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        run = _closed_run(main_branch, accountant_user, 'C',
                          units_completed_and_transferred=Decimal('80'),
                          units_ending_wip=Decimal('20'))
        rep = generate_production_run_cost_report(run.id, main_branch.id)
        assert rep['units_to_account_for'] == Decimal('100.0000')
        assert rep['units_accounted_for'] == Decimal('100.0000')
        assert rep['unaccounted_units'] == Decimal('0.0000')

    def test_unaccounted_goes_NEGATIVE_when_more_is_accounted_for_than_existed(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """The data-error case the template flags. 100 to account for, 135 accounted
        for -- units that never existed."""
        run = _closed_run(main_branch, accountant_user, 'D',
                          units_completed_and_transferred=Decimal('95'),
                          units_ending_wip=Decimal('40'))
        rep = generate_production_run_cost_report(run.id, main_branch.id)
        assert rep['units_accounted_for'] == Decimal('135.0000')
        assert rep['unaccounted_units'] == Decimal('-35.0000')

    def test_the_generator_makes_no_rendering_decision(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """Returns the signed number and nothing else -- no 'is_error' flag, no
        severity, no formatted string. Which sign is alarming belongs to the
        template, and baking it in here would make the figure harder to reuse."""
        run = _closed_run(main_branch, accountant_user, 'E')
        rep = generate_production_run_cost_report(run.id, main_branch.id)
        assert isinstance(rep['unaccounted_units'], Decimal)
        for forbidden in ('unaccounted_is_error', 'unaccounted_severity',
                          'unaccounted_class', 'unaccounted_label'):
            assert forbidden not in rep

    def test_the_pct_complete_is_carried_for_the_equivalent_units_line(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """The statement shows 'Ending WIP x 50% complete', so the percentage has to
        reach the template."""
        run = _closed_run(main_branch, accountant_user, 'F')
        rep = generate_production_run_cost_report(run.id, main_branch.id)
        assert rep['ending_wip_pct_complete'] == Decimal('50.00')
