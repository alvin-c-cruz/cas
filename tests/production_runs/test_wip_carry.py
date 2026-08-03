"""P4 Task 2 -- beginning WIP is PULLED from the predecessor when a run is created.

Pull-on-create, not push-on-close (owner decision 2026-08-02): at close time the
successor run usually does not exist yet, because the accountant closes the old
period before opening the new one.

A predecessor is the MOST RECENT run that is:
  - CLOSED (an open run has not settled its ending WIP; a cancelled one never will)
  - the same (bom_id, department_id, branch_id) -- a different product line, a
    different department, or another branch is a different cost pool entirely
  - whose period_end is strictly BEFORE this run's period_start

What is carried is the predecessor's units_ending_wip and its frozen
ending_wip_cost -- the residual plug it left in the WIP account.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialLine
from app.manufacturing_departments.models import ManufacturingDepartment
from app.production_runs.models import ProductionRun
from app.production_runs.service import find_predecessor_run, carry_beginning_wip
from app.products.models import Product

pytestmark = [pytest.mark.integration, pytest.mark.production_runs]


@pytest.fixture
def bom(db_session):
    # Output must be inventory-tracked -- the create form only offers such BOMs.
    out = Product(code='W-OUT', name='Dried Mango', track_inventory=True,
                  costing_method='moving_average', is_active=True)
    comp = Product(code='W-COMP', name='Fresh Mango', track_inventory=True,
                   costing_method='moving_average', standard_cost=Decimal('5.00'),
                   is_active=True)
    db.session.add_all([out, comp]); db.session.commit()
    b = BillOfMaterial(product_id=out.id, manufacturing_mode='process')
    b.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id,
                                      quantity_per=Decimal('2')))
    db.session.add(b); db.session.commit()
    return b


@pytest.fixture
def other_bom(db_session):
    out = Product(code='W-OUT2', name='Dried Banana', track_inventory=True,
                  costing_method='moving_average', is_active=True)
    comp = Product(code='W-COMP2', name='Fresh Banana', track_inventory=True,
                   costing_method='moving_average', standard_cost=Decimal('4.00'),
                   is_active=True)
    db.session.add_all([out, comp]); db.session.commit()
    b = BillOfMaterial(product_id=out.id, manufacturing_mode='process')
    b.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id,
                                      quantity_per=Decimal('1')))
    db.session.add(b); db.session.commit()
    return b


@pytest.fixture
def dept(db_session, main_branch):
    d = ManufacturingDepartment(branch_id=main_branch.id, code='DRY', name='Dehydration')
    db.session.add(d); db.session.commit()
    return d


@pytest.fixture
def other_dept(db_session, main_branch):
    d = ManufacturingDepartment(branch_id=main_branch.id, code='PCK', name='Packing')
    db.session.add(d); db.session.commit()
    return d


_N = [0]


def _run(branch, bom, dept, start, end, status='closed',
         ending_units='20', ending_cost='161.20', **kw):
    _N[0] += 1
    run = ProductionRun(
        run_number='W%04d' % _N[0], bom_id=bom.id, department_id=dept.id,
        branch_id=branch.id, period_start=start, period_end=end, status=status,
        units_started=Decimal('100'),
        units_ending_wip=Decimal(ending_units),
        ending_wip_cost=Decimal(ending_cost) if ending_cost is not None else None, **kw)
    db.session.add(run); db.session.commit()
    return run


AUG = (date(2026, 8, 1), date(2026, 8, 31))
SEP = (date(2026, 9, 1), date(2026, 9, 30))
OCT = (date(2026, 10, 1), date(2026, 10, 31))


class TestFindPredecessor:
    def test_none_when_no_prior_run_exists(self, db_session, main_branch, bom, dept):
        assert find_predecessor_run(bom.id, dept.id, main_branch.id, SEP[0]) is None

    def test_finds_the_closed_prior_run(self, db_session, main_branch, bom, dept):
        prior = _run(main_branch, bom, dept, *AUG)
        found = find_predecessor_run(bom.id, dept.id, main_branch.id, SEP[0])
        assert found is not None and found.id == prior.id

    def test_ignores_an_open_prior_run(self, db_session, main_branch, bom, dept):
        """An open run has not settled its ending WIP -- carrying from it would
        move a figure that is still changing."""
        _run(main_branch, bom, dept, *AUG, status='open')
        assert find_predecessor_run(bom.id, dept.id, main_branch.id, SEP[0]) is None

    def test_ignores_a_cancelled_prior_run(self, db_session, main_branch, bom, dept):
        """A cancelled run reversed its consumptions -- it left nothing in WIP."""
        _run(main_branch, bom, dept, *AUG, status='cancelled')
        assert find_predecessor_run(bom.id, dept.id, main_branch.id, SEP[0]) is None

    def test_ignores_a_different_bom(self, db_session, main_branch, bom, other_bom, dept):
        _run(main_branch, other_bom, dept, *AUG)
        assert find_predecessor_run(bom.id, dept.id, main_branch.id, SEP[0]) is None

    def test_ignores_a_different_department(self, db_session, main_branch, bom, dept, other_dept):
        _run(main_branch, bom, other_dept, *AUG)
        assert find_predecessor_run(bom.id, dept.id, main_branch.id, SEP[0]) is None

    def test_ignores_another_branch(self, db_session, main_branch, branch_manila, bom, dept):
        other = ManufacturingDepartment(branch_id=branch_manila.id, code='DRY2', name='Dehydration 2')
        db.session.add(other); db.session.commit()
        _run(branch_manila, bom, other, *AUG)
        assert find_predecessor_run(bom.id, dept.id, main_branch.id, SEP[0]) is None

    def test_ignores_a_run_that_ends_after_this_period_start(
            self, db_session, main_branch, bom, dept):
        _run(main_branch, bom, dept, SEP[0], SEP[1])
        assert find_predecessor_run(bom.id, dept.id, main_branch.id, SEP[0]) is None

    def test_ignores_a_run_ending_exactly_ON_this_period_start(
            self, db_session, main_branch, bom, dept):
        """The strict-inequality boundary. Periods are inclusive of both ends, so a
        run ending Sep 1 and a run starting Sep 1 OVERLAP by a day -- carrying
        between them would count that day's WIP twice.

        This case exists because mutation testing caught its absence: flipping
        `period_end < period_start` to `<=` left the whole suite green, since the
        only "overlapping" fixture ended Sep 30 against a Sep 1 start and failed
        both comparisons identically. A boundary is not tested by a value far from it.
        """
        _run(main_branch, bom, dept, date(2026, 8, 1), SEP[0])
        assert find_predecessor_run(bom.id, dept.id, main_branch.id, SEP[0]) is None

    def test_accepts_a_run_ending_the_day_BEFORE_this_period_start(
            self, db_session, main_branch, bom, dept):
        """The other side of the same boundary -- the normal month-to-month case,
        which must still be found."""
        prior = _run(main_branch, bom, dept, *AUG)          # ends Aug 31
        found = find_predecessor_run(bom.id, dept.id, main_branch.id, SEP[0])
        assert found is not None and found.id == prior.id

    def test_picks_the_most_recent_of_several(self, db_session, main_branch, bom, dept):
        _run(main_branch, bom, dept, date(2026, 7, 1), date(2026, 7, 31), ending_cost='99.00')
        august = _run(main_branch, bom, dept, *AUG, ending_cost='161.20')
        found = find_predecessor_run(bom.id, dept.id, main_branch.id, OCT[0])
        assert found.id == august.id
        assert found.ending_wip_cost == Decimal('161.20')


class TestCarryBeginningWip:
    def test_carries_units_and_cost_from_the_predecessor(
            self, db_session, main_branch, bom, dept):
        _run(main_branch, bom, dept, *AUG, ending_units='20', ending_cost='161.20')
        successor = ProductionRun(run_number='W-SUCC', bom_id=bom.id, department_id=dept.id,
                                  branch_id=main_branch.id, period_start=SEP[0],
                                  period_end=SEP[1], units_started=Decimal('100'))
        carry_beginning_wip(successor)
        assert successor.beginning_wip_units == Decimal('20')
        assert successor.beginning_wip_cost == Decimal('161.20')

    def test_leaves_zeros_when_there_is_no_predecessor(
            self, db_session, main_branch, bom, dept):
        first = ProductionRun(run_number='W-FIRST', bom_id=bom.id, department_id=dept.id,
                              branch_id=main_branch.id, period_start=AUG[0],
                              period_end=AUG[1], units_started=Decimal('100'))
        carry_beginning_wip(first)
        assert first.beginning_wip_units == Decimal('0')
        assert first.beginning_wip_cost == Decimal('0')

    def test_treats_a_null_ending_wip_cost_as_zero(self, db_session, main_branch, bom, dept):
        """A run closed before P4 existed has no frozen ending_wip_cost. Carry zero
        rather than crashing -- and never NULL, which would break the pool's sum."""
        _run(main_branch, bom, dept, *AUG, ending_units='20', ending_cost=None)
        successor = ProductionRun(run_number='W-NULL', bom_id=bom.id, department_id=dept.id,
                                  branch_id=main_branch.id, period_start=SEP[0],
                                  period_end=SEP[1], units_started=Decimal('100'))
        carry_beginning_wip(successor)
        assert successor.beginning_wip_cost == Decimal('0')
        assert successor.beginning_wip_units == Decimal('20')


class TestCreateRouteCarries:
    def _enable(self, db_session):
        from app.settings import AppSettings
        from app.utils.cache_helpers import clear_module_config_cache
        for k in ('bill_of_materials', 'production_runs'):
            AppSettings.set_setting(f'module_enabled:{k}', '1')
        db_session.commit(); clear_module_config_cache()

    def _login(self, client, user, branch):
        with client.session_transaction() as s:
            s['_user_id'] = str(user.id); s['_fresh'] = True
            s['selected_branch_id'] = branch.id

    def test_creating_a_run_pulls_the_predecessors_ending_wip(
            self, client, db_session, main_branch, accountant_user, bom, dept):
        self._enable(db_session)
        _run(main_branch, bom, dept, *AUG, ending_units='20', ending_cost='161.20')
        self._login(client, accountant_user, main_branch)

        resp = client.post('/production-runs/create', data={
            'bom_id': str(bom.id), 'department_id': str(dept.id),
            'units_started': '100', 'period_start': '2026-09-01', 'period_end': '2026-09-30',
        }, follow_redirects=True)
        assert resp.status_code == 200

        created = ProductionRun.query.filter_by(period_start=SEP[0]).one()
        assert created.beginning_wip_units == Decimal('20.0000')
        assert created.beginning_wip_cost == Decimal('161.20')

    def test_first_ever_run_is_created_with_zero_beginning_wip(
            self, client, db_session, main_branch, accountant_user, bom, dept):
        self._enable(db_session)
        self._login(client, accountant_user, main_branch)
        resp = client.post('/production-runs/create', data={
            'bom_id': str(bom.id), 'department_id': str(dept.id),
            'units_started': '100', 'period_start': '2026-08-01', 'period_end': '2026-08-31',
        }, follow_redirects=True)
        assert resp.status_code == 200
        created = ProductionRun.query.filter_by(period_start=AUG[0]).one()
        assert created.beginning_wip_units == Decimal('0.0000')
        assert created.beginning_wip_cost == Decimal('0.00')
