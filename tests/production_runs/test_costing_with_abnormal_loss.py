"""P6 Task 3 -- abnormal loss enters the equivalent-units denominator.

    equivalent units = completed + (ending WIP x pct) + ABNORMAL loss
                       ^ NORMAL loss stays OUT, so the good units absorb it (as since P3)
                         ABNORMAL loss goes IN, so it CARRIES cost that can be relieved
    abnormal charge  = abnormal loss units x cost per equivalent unit

This is the third revision of a formula P3 shipped: P4 added beginning WIP to the
pool, P6 adds the abnormal term to the denominator. The two directions are separately
wrong in separately invisible ways, so both get pinned here:

  * put NORMAL loss into the denominator and the good units stop absorbing ordinary
    shrinkage -- cost/EU falls, and the shrinkage strands itself in WIP forever.
  * leave ABNORMAL loss out and it carries no cost, so there is nothing to charge to
    the P&L and the whole slice is a no-op that still looks green.

`normal_loss_pct` NULL is the backward-compatibility guarantee and is asserted
against P4's own worked example (1450.00 pool / 90 EU / 16.11), byte-identical.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialLine
from app.manufacturing_departments.models import ManufacturingDepartment
from app.production_runs.costing import compute_run_costing, equivalent_units
from app.production_runs.models import ProductionRun
from app.production_runs.service import issue_material, snapshot_materials
from app.products.models import Product
from app.stock_adjustments.service import post_movement

pytestmark = [pytest.mark.integration, pytest.mark.production_runs]


def _setup(branch, actor, suffix, normal_loss_pct=None):
    comp = Product(code=f'AL-C-{suffix}', name='Fresh Mango', track_inventory=True,
                   costing_method='moving_average', standard_cost=Decimal('5.00'),
                   is_active=True)
    out = Product(code=f'AL-O-{suffix}', name='Dried Mango', is_active=True)
    db.session.add_all([comp, out]); db.session.commit()
    post_movement(comp, branch.id, 'opening', Decimal('10000'), Decimal('5.00'),
                  'stock_adjustment', 0, 'seed', actor, movement_date=date(2026, 1, 1))
    db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='process',
                         normal_loss_pct=normal_loss_pct)
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id,
                                        quantity_per=Decimal('2')))
    db.session.add(bom); db.session.commit()
    dept = ManufacturingDepartment(branch_id=branch.id, code=f'A{suffix}', name='Dehydration')
    db.session.add(dept); db.session.commit()
    return bom, dept


def _run(branch, bom, dept, number, *, completed='70', ending='20', issue='200',
         actor=None, **kw):
    """100 started, 200 components issued at 5.00 = 1000.00 material, 450.00
    conversion -- P4's worked pool of 1450.00, so every figure below is comparable
    to the example that slice pinned."""
    run = ProductionRun(run_number=number, bom_id=bom.id, department_id=dept.id,
                        branch_id=branch.id, period_start=date(2026, 9, 1),
                        period_end=date(2026, 9, 30),
                        units_started=Decimal('100'),
                        conversion_cost=Decimal('450.00'),
                        units_completed_and_transferred=Decimal(completed),
                        units_ending_wip=Decimal(ending),
                        ending_wip_pct_complete=Decimal('50'), **kw)
    db.session.add(run); db.session.commit()
    snapshot_materials(run); db.session.commit()
    if issue:
        issue_material(run.materials[0], Decimal(issue), actor)
        db.session.commit()
    return run


class TestNoExpectationIsByteIdenticalToP5:
    def test_the_P4_worked_example_is_unchanged(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """The headline backward-compatibility guarantee. A run that ties (no loss at
        all) with no expectation set must still produce 1450.00 / 90 / 16.11."""
        bom, dept = _setup(main_branch, accountant_user, 'A')
        run = _run(main_branch, bom, dept, 'AL001', completed='80', ending='20',
                   actor=accountant_user)
        data = compute_run_costing(run)
        assert data['total_cost'] == Decimal('1450.00')
        assert data['equivalent_units'] == Decimal('90.0000')
        assert data['cost_per_equivalent_unit'] == Decimal('16.11')
        assert data['abnormal_loss_units'] == Decimal('0.0000')
        assert data['abnormal_loss_cost'] == Decimal('0.00')

    def test_a_LOSING_run_with_no_expectation_absorbs_all_of_it(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """10 units lost, no expectation set. Every one of them is normal, so none
        enter the denominator: EU = 70 + 10 = 80, and the good units carry the whole
        1450.00 pool at 18.13 apiece. This is exactly what P5 shipped."""
        bom, dept = _setup(main_branch, accountant_user, 'B')
        run = _run(main_branch, bom, dept, 'AL002', actor=accountant_user)
        data = compute_run_costing(run)
        assert data['total_loss_units'] == Decimal('10.0000')
        assert data['normal_loss_units'] == Decimal('10.0000')
        assert data['abnormal_loss_units'] == Decimal('0.0000')
        assert data['equivalent_units'] == Decimal('80.0000')
        assert data['cost_per_equivalent_unit'] == Decimal('18.13')
        assert data['abnormal_loss_cost'] == Decimal('0.00')


class TestAbnormalLossEntersTheDenominator:
    def test_only_the_ABNORMAL_units_join_the_denominator(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """3% of 100 started = 3 allowed, 10 lost -> 3 normal + 7 abnormal.

        EU = 70 completed + 10 ending-WIP equivalents + 7 abnormal = 87.

        This single assertion kills BOTH mutations the design calls for: adding the
        normal 3 as well reads 90, and leaving the abnormal 7 out reads 80."""
        bom, dept = _setup(main_branch, accountant_user, 'C', normal_loss_pct=Decimal('3.00'))
        run = _run(main_branch, bom, dept, 'AL003', actor=accountant_user)
        data = compute_run_costing(run)
        assert data['normal_loss_units'] == Decimal('3.0000')
        assert data['abnormal_loss_units'] == Decimal('7.0000')
        assert data['equivalent_units'] == Decimal('87.0000'), \
            'normal loss stays OUT of the denominator, abnormal loss goes IN'

    def test_the_good_units_get_CHEAPER_once_abnormal_loss_stops_being_absorbed(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """The economic point of the whole slice. Same run, same 1450.00 pool, same
        10 units lost -- but with an expectation set, 7 of them carry their own cost
        instead of being loaded onto the survivors: 18.13 -> 16.67."""
        bom, dept = _setup(main_branch, accountant_user, 'D', normal_loss_pct=Decimal('3.00'))
        run = _run(main_branch, bom, dept, 'AL004', actor=accountant_user)
        data = compute_run_costing(run)
        assert data['total_cost'] == Decimal('1450.00'), 'the pool itself does not move'
        assert data['cost_per_equivalent_unit'] == Decimal('16.67')

    def test_the_abnormal_charge_is_units_x_cost_per_EU(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """7 abnormal x 16.67 = 116.69 -- what Task 5 will post Dr Abnormal Loss /
        Cr WIP."""
        bom, dept = _setup(main_branch, accountant_user, 'E', normal_loss_pct=Decimal('3.00'))
        run = _run(main_branch, bom, dept, 'AL005', actor=accountant_user)
        data = compute_run_costing(run)
        assert data['abnormal_loss_cost'] == Decimal('116.69')

    def test_a_zero_percent_expectation_makes_every_lost_unit_carry_cost(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """0.00 is an explicit expectation of no loss -- the opposite of NULL. All 10
        lost units join the denominator: EU = 70 + 10 + 10 = 90 at 16.11."""
        bom, dept = _setup(main_branch, accountant_user, 'F', normal_loss_pct=Decimal('0.00'))
        run = _run(main_branch, bom, dept, 'AL006', actor=accountant_user)
        data = compute_run_costing(run)
        assert data['normal_loss_units'] == Decimal('0.0000')
        assert data['abnormal_loss_units'] == Decimal('10.0000')
        assert data['equivalent_units'] == Decimal('90.0000')
        assert data['cost_per_equivalent_unit'] == Decimal('16.11')
        assert data['abnormal_loss_cost'] == Decimal('161.10')

    def test_loss_within_the_allowance_leaves_the_denominator_alone(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """2 lost against a 3-unit allowance: nothing abnormal, so nothing joins the
        denominator and nothing gets charged out. EU = 78 + 10 = 88."""
        bom, dept = _setup(main_branch, accountant_user, 'G', normal_loss_pct=Decimal('3.00'))
        run = _run(main_branch, bom, dept, 'AL007', completed='78', actor=accountant_user)
        data = compute_run_costing(run)
        assert data['abnormal_loss_units'] == Decimal('0.0000')
        assert data['equivalent_units'] == Decimal('88.0000')
        assert data['abnormal_loss_cost'] == Decimal('0.00')


class TestDataErrorsAndEdges:
    def test_a_NEGATIVE_total_loss_never_shrinks_the_denominator(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """95 + 40 accounted for against 100 started is a DATA ERROR (P5 flags it).
        max(0, ...) must keep the abnormal term at zero -- a negative term would
        shrink EU, inflate cost/EU, and post a P&L credit for a typo."""
        bom, dept = _setup(main_branch, accountant_user, 'H', normal_loss_pct=Decimal('3.00'))
        run = _run(main_branch, bom, dept, 'AL008', completed='95', ending='40',
                   actor=accountant_user)
        data = compute_run_costing(run)
        assert data['total_loss_units'] == Decimal('-35.0000')
        assert data['abnormal_loss_units'] == Decimal('0.0000')
        assert data['equivalent_units'] == Decimal('115.0000'), '95 + (40 x 50%)'
        assert data['abnormal_loss_cost'] == Decimal('0.00')

    def test_zero_equivalent_units_still_returns_none_and_no_charge(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """P3's divide-by-zero guard survives its third revision. Nothing reported
        yet, so the whole 100 started reads as lost -- and with 0.00 expected, all of
        it is abnormal, which is precisely when a bad guard would divide by an EU of
        zero... except abnormal loss is now IN the denominator, so EU is 100."""
        bom, dept = _setup(main_branch, accountant_user, 'I', normal_loss_pct=Decimal('0.00'))
        run = _run(main_branch, bom, dept, 'AL009', completed='0', ending='0',
                   issue=None, actor=accountant_user)
        run.conversion_cost = Decimal('0.00')
        db.session.commit()
        data = compute_run_costing(run)
        assert data['equivalent_units'] == Decimal('100.0000')
        assert data['cost_per_equivalent_unit'] == Decimal('0.00')
        assert data['abnormal_loss_cost'] == Decimal('0.00')

    def test_a_run_with_no_reported_results_and_NO_expectation_still_guards(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """The same shape with NULL pct: all loss is normal, so EU really is zero and
        the guard must still return None rather than dividing."""
        bom, dept = _setup(main_branch, accountant_user, 'J')
        run = _run(main_branch, bom, dept, 'AL010', completed='0', ending='0',
                   issue=None, actor=accountant_user)
        data = compute_run_costing(run)
        assert data['equivalent_units'] == Decimal('0.0000')
        assert data['cost_per_equivalent_unit'] is None
        assert data['abnormal_loss_cost'] == Decimal('0.00')


    def test_no_denominator_implies_nothing_abnormal(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """The invariant behind an EQUIVALENT MUTANT, pinned deliberately.

        `abnormal_loss_cost` guards on `cost_per_equivalent_unit is None`, and no
        mutation of that guard changes any figure -- because abnormal loss is now IN
        the denominator, a non-zero abnormal figure guarantees a non-zero EU and so
        always has a cost/EU to be valued at. The guard therefore fires only when
        there is nothing to value, and returning zero is the only possible answer.

        Both sides are asserted so neither can pass vacuously: the NULL run really
        does reach the None arm, and the 0.00 run really does escape it.
        """
        bom_a, dept_a = _setup(main_branch, accountant_user, 'Y')
        nothing_expected = _run(main_branch, bom_a, dept_a, 'AL012', completed='0',
                                ending='0', issue=None, actor=accountant_user)
        absorbed = compute_run_costing(nothing_expected)
        assert absorbed['cost_per_equivalent_unit'] is None, 'this run must reach the guard'
        assert absorbed['abnormal_loss_units'] == Decimal('0.0000'), \
            'no denominator must imply nothing abnormal, or the guard would hide a real charge'

        bom_b, dept_b = _setup(main_branch, accountant_user, 'Z',
                               normal_loss_pct=Decimal('0.00'))
        all_abnormal = _run(main_branch, bom_b, dept_b, 'AL013', completed='0',
                            ending='0', issue=None, actor=accountant_user)
        charged = compute_run_costing(all_abnormal)
        assert charged['abnormal_loss_units'] == Decimal('100.0000')
        assert charged['cost_per_equivalent_unit'] is not None, \
            'abnormal units put themselves in the denominator, so a charge always has a rate'


class TestEquivalentUnitsIsSharedWithTheReport:
    def test_equivalent_units_alone_carries_the_abnormal_term(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """P5's report calls equivalent_units() directly rather than
        compute_run_costing() (it must tie to the GL, not to the run record). The
        abnormal term therefore has to live in the shared function, not in the
        costing wrapper, or the statement's denominator would disagree with the
        preview panel's."""
        bom, dept = _setup(main_branch, accountant_user, 'K', normal_loss_pct=Decimal('3.00'))
        run = _run(main_branch, bom, dept, 'AL011', actor=accountant_user)
        assert equivalent_units(run) == Decimal('87.0000')
