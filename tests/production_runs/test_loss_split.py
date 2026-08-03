"""P6 Task 2 -- splitting a run's loss into normal and abnormal.

    total loss       = (beginning WIP + started) - (completed + ending WIP)
    normal allowance = normal_loss_pct% x units STARTED
    abnormal loss    = max(0, total loss - allowance)
    normal loss      = total loss - abnormal loss

Pure arithmetic over the run and its BOM -- no posting, no cost, no rendering
decision. The percentage base is units STARTED, not units to account for: basing it
on the latter would make the allowance depend on how much unfinished work happened
to be carried in, so the same physical process would show a different allowance
month to month.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialLine
from app.manufacturing_departments.models import ManufacturingDepartment
from app.production_runs.costing import loss_split
from app.production_runs.models import ProductionRun
from app.products.models import Product

pytestmark = [pytest.mark.unit, pytest.mark.production_runs]

_N = [0]


def _run(branch, suffix, *, normal_loss_pct=None, started='100', beginning='0',
         completed='80', ending='20'):
    comp = Product(code=f'LS-C-{suffix}', name='Fresh', track_inventory=True,
                   costing_method='moving_average', is_active=True)
    out = Product(code=f'LS-O-{suffix}', name='Dried', track_inventory=True,
                  costing_method='moving_average', is_active=True)
    db.session.add_all([comp, out]); db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='process',
                         normal_loss_pct=normal_loss_pct)
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id,
                                        quantity_per=Decimal('2')))
    db.session.add(bom); db.session.commit()
    dept = ManufacturingDepartment(branch_id=branch.id, code=f'L{suffix}', name='Dehydration')
    db.session.add(dept); db.session.commit()
    _N[0] += 1
    run = ProductionRun(run_number='LS%04d' % _N[0], bom_id=bom.id, department_id=dept.id,
                        branch_id=branch.id, period_start=date(2026, 8, 1),
                        period_end=date(2026, 8, 31),
                        units_started=Decimal(started),
                        beginning_wip_units=Decimal(beginning),
                        units_completed_and_transferred=Decimal(completed),
                        units_ending_wip=Decimal(ending))
    db.session.add(run); db.session.commit()
    return run


class TestNoExpectationSet:
    def test_null_pct_makes_every_lost_unit_NORMAL(self, db_session, main_branch):
        """The backward-compatibility guarantee, at the arithmetic level. 100 started,
        80 + 20 accounted for... no loss here; use a run that does lose."""
        run = _run(main_branch, 'A', normal_loss_pct=None, completed='70', ending='20')
        total, normal, abnormal = loss_split(run)
        assert total == Decimal('10.0000')
        assert normal == Decimal('10.0000')
        assert abnormal == Decimal('0.0000'), 'no expectation means nothing can be abnormal'

    def test_null_pct_absorbs_even_an_enormous_loss(self, db_session, main_branch):
        """Today's behaviour, preserved: without an expectation there is no threshold
        to exceed, however bad the batch was."""
        run = _run(main_branch, 'B', normal_loss_pct=None, completed='10', ending='0')
        total, normal, abnormal = loss_split(run)
        assert total == Decimal('90.0000')
        assert abnormal == Decimal('0.0000')


class TestWithAnExpectation:
    def test_loss_within_the_allowance_is_all_normal(self, db_session, main_branch):
        """3% of 100 started = 3.0 allowed; 2 lost is under it."""
        run = _run(main_branch, 'C', normal_loss_pct=Decimal('3.00'),
                   completed='78', ending='20')
        total, normal, abnormal = loss_split(run)
        assert total == Decimal('2.0000')
        assert normal == Decimal('2.0000')
        assert abnormal == Decimal('0.0000')

    def test_only_the_EXCESS_is_abnormal(self, db_session, main_branch):
        """3% of 100 = 3.0 allowed, 10 lost -> 3 normal, 7 abnormal."""
        run = _run(main_branch, 'D', normal_loss_pct=Decimal('3.00'),
                   completed='70', ending='20')
        total, normal, abnormal = loss_split(run)
        assert total == Decimal('10.0000')
        assert normal == Decimal('3.0000')
        assert abnormal == Decimal('7.0000')
        assert normal + abnormal == total, 'the split must be exhaustive'

    def test_loss_exactly_at_the_allowance_is_all_normal(self, db_session, main_branch):
        """The boundary. 3% of 100 = 3.0 allowed, exactly 3 lost -> nothing abnormal.
        A `>` vs `>=` slip lives here, and a test far from the boundary cannot see it."""
        run = _run(main_branch, 'E', normal_loss_pct=Decimal('3.00'),
                   completed='77', ending='20')
        total, normal, abnormal = loss_split(run)
        assert total == Decimal('3.0000')
        assert abnormal == Decimal('0.0000')

    def test_zero_pct_makes_ALL_loss_abnormal(self, db_session, main_branch):
        """0.00 is an explicit expectation of no loss -- the opposite of NULL."""
        run = _run(main_branch, 'F', normal_loss_pct=Decimal('0.00'),
                   completed='70', ending='20')
        total, normal, abnormal = loss_split(run)
        assert total == Decimal('10.0000')
        assert normal == Decimal('0.0000')
        assert abnormal == Decimal('10.0000')

    def test_the_allowance_is_a_percentage_of_units_STARTED(self, db_session, main_branch):
        """Not of units to account for. With 20 carried in, an allowance based on 120
        would be 3.6 and this test would read 6.4 abnormal instead of 7.0."""
        run = _run(main_branch, 'G', normal_loss_pct=Decimal('3.00'),
                   started='100', beginning='20', completed='90', ending='20')
        total, normal, abnormal = loss_split(run)
        assert total == Decimal('10.0000')
        assert normal == Decimal('3.0000'), '3% of 100 started, not of 120 to account for'
        assert abnormal == Decimal('7.0000')

    def test_a_fractional_percentage_is_honoured(self, db_session, main_branch):
        run = _run(main_branch, 'H', normal_loss_pct=Decimal('2.50'),
                   completed='70', ending='20')
        total, normal, abnormal = loss_split(run)
        assert normal == Decimal('2.5000')
        assert abnormal == Decimal('7.5000')


class TestNoLossAndNegativeLoss:
    def test_a_schedule_that_ties_produces_no_loss_at_all(self, db_session, main_branch):
        run = _run(main_branch, 'I', normal_loss_pct=Decimal('3.00'),
                   completed='80', ending='20')
        total, normal, abnormal = loss_split(run)
        assert total == Decimal('0.0000')
        assert normal == Decimal('0.0000')
        assert abnormal == Decimal('0.0000')

    def test_a_NEGATIVE_total_loss_never_becomes_a_negative_abnormal_charge(
            self, db_session, main_branch):
        """P5 flags a negative unaccounted figure as a DATA ERROR -- more units
        accounted for than existed. P6 must not turn that into a negative loss
        charge, which would CREDIT the P&L for a mistake. This is what max(0, ...)
        is for."""
        run = _run(main_branch, 'J', normal_loss_pct=Decimal('3.00'),
                   completed='95', ending='40')
        total, normal, abnormal = loss_split(run)
        assert total == Decimal('-35.0000')
        assert abnormal == Decimal('0.0000'), 'a data error must never post a negative charge'

    def test_a_negative_total_loss_with_NO_expectation_also_stays_zero(
            self, db_session, main_branch):
        run = _run(main_branch, 'K', normal_loss_pct=None, completed='95', ending='40')
        total, normal, abnormal = loss_split(run)
        assert total == Decimal('-35.0000')
        assert abnormal == Decimal('0.0000')
