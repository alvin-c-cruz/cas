"""P5 Task 7 -- the two defects P4's post-merge review confirmed by probe.

Both were found by probing the merged code, not by reading it, and both live just
outside the boundary of P4's own tests: one is a sibling route P4 did not add, the
other a branch P4's fixtures never produce. A slice's suite is scoped to the slice.

1. BUG-PERIOD-RESULTS-ROUTE-HAS-NO-STATUS-GUARD -- POST .../period mutated a
   CLOSED run. The template hid the form; the route never checked status. The books
   survived (the frozen figures are right) but the NEXT period did not:
   carry_beginning_wip() reads units_ending_wip LIVE beside a FROZEN
   ending_wip_cost, so a successor could inherit fabricated units against real cost.

2. BUG-CLOSE-WITH-ZERO-COST-POOL-CREATES-FREE-INVENTORY -- completed units with an
   empty pool received finished goods at 0.00 and posted a zero-value JE that
   balances, so is_balanced could not catch it.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialLine
from app.journal_entries.models import JournalEntry
from app.manufacturing_departments.models import ManufacturingDepartment
from app.production_runs.models import ProductionRun
from app.production_runs.service import (carry_beginning_wip, close_run, issue_material,
                                         snapshot_materials, update_period_results)
from app.products.models import Product
from app.stock_adjustments.models import StockBalance, StockMovement
from app.stock_adjustments.service import post_movement

pytestmark = [pytest.mark.integration, pytest.mark.production_runs]

_N = [0]


def _enable(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('bill_of_materials', 'production_runs'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id); s['_fresh'] = True
        s['selected_branch_id'] = branch.id


def _parts(branch, actor, suffix, seed_stock=True):
    comp = Product(code=f'DG-C-{suffix}', name='Fresh Mango', track_inventory=True,
                   costing_method='moving_average', standard_cost=Decimal('5.00'),
                   is_active=True)
    out = Product(code=f'DG-O-{suffix}', name='Dried Mango', track_inventory=True,
                  costing_method='moving_average', is_active=True)
    db.session.add_all([comp, out]); db.session.commit()
    if seed_stock:
        post_movement(comp, branch.id, 'opening', Decimal('10000'), Decimal('5.00'),
                      'stock_adjustment', 0, 'seed', actor, movement_date=date(2026, 1, 1))
        db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='process')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id,
                                        quantity_per=Decimal('2')))
    db.session.add(bom); db.session.commit()
    dept = ManufacturingDepartment(branch_id=branch.id, code=f'G{suffix}', name='Dehydration')
    db.session.add(dept); db.session.commit()
    return bom, dept, out


def _run(branch, bom, dept, **kw):
    _N[0] += 1
    base = dict(conversion_cost=Decimal('450.00'),
                units_completed_and_transferred=Decimal('80'),
                units_ending_wip=Decimal('20'),
                ending_wip_pct_complete=Decimal('50'))
    base.update(kw)
    run = ProductionRun(run_number='DG%04d' % _N[0], bom_id=bom.id, department_id=dept.id,
                        branch_id=branch.id, period_start=date(2026, 8, 1),
                        period_end=date(2026, 8, 31), units_started=Decimal('100'), **base)
    db.session.add(run); db.session.commit()
    snapshot_materials(run); db.session.commit()
    return run


class TestPeriodResultsRefusesANonOpenRun:
    """Guarded at the SERVICE layer, copying issue_material() -- which is why the
    issue route was safe all along despite looking equally exposed."""

    def test_service_refuses_a_closed_run(self, db_session, main_branch, accountant_user,
                                          wo_control_accounts):
        bom, dept, out = _parts(main_branch, accountant_user, 'A')
        run = _run(main_branch, bom, dept)
        issue_material(run.materials[0], Decimal('200'), accountant_user); db.session.commit()
        close_run(run, accountant_user); db.session.commit()
        with pytest.raises(ValueError, match='open'):
            update_period_results(run, units_completed_and_transferred=Decimal('999'))

    def test_service_refuses_a_cancelled_run(self, db_session, main_branch, accountant_user,
                                             wo_control_accounts):
        from app.production_runs.service import cancel_run
        bom, dept, out = _parts(main_branch, accountant_user, 'B')
        run = _run(main_branch, bom, dept)
        cancel_run(run, 'Spoiled', accountant_user); db.session.commit()
        with pytest.raises(ValueError, match='open'):
            update_period_results(run, units_ending_wip=Decimal('5'))

    def test_the_ROUTE_refuses_and_changes_nothing(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        """The original probe, now an assertion. Before the fix this returned 200 and
        rewrote every figure on a closed run."""
        _enable(db_session)
        bom, dept, out = _parts(main_branch, accountant_user, 'C')
        run = _run(main_branch, bom, dept)
        issue_material(run.materials[0], Decimal('200'), accountant_user); db.session.commit()
        close_run(run, accountant_user); db.session.commit()
        _login(client, accountant_user, main_branch)

        resp = client.post(f'/production-runs/{run.id}/period', data={
            'units_completed_and_transferred': '999', 'units_ending_wip': '888',
            'ending_wip_pct_complete': '100', 'conversion_cost': '99999.00',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(run)
        assert run.units_completed_and_transferred == Decimal('80'), 'a closed run was mutated'
        assert run.units_ending_wip == Decimal('20')
        assert run.conversion_cost == Decimal('450.00')

    def test_the_successor_cannot_inherit_fabricated_units(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        """The consequence that made this MEDIUM-HIGH rather than cosmetic:
        carry_beginning_wip() reads units_ending_wip LIVE beside a FROZEN
        ending_wip_cost, so tampering desynced the next period's opening position."""
        _enable(db_session)
        bom, dept, out = _parts(main_branch, accountant_user, 'D')
        run = _run(main_branch, bom, dept)
        issue_material(run.materials[0], Decimal('200'), accountant_user); db.session.commit()
        close_run(run, accountant_user); db.session.commit()
        _login(client, accountant_user, main_branch)
        client.post(f'/production-runs/{run.id}/period',
                    data={'units_ending_wip': '888'}, follow_redirects=True)

        successor = ProductionRun(run_number='DG-SUCC', bom_id=bom.id, department_id=dept.id,
                                  branch_id=main_branch.id, period_start=date(2026, 9, 1),
                                  period_end=date(2026, 9, 30), units_started=Decimal('100'))
        carry_beginning_wip(successor)
        assert successor.beginning_wip_units == Decimal('20'), 'inherited a fabricated unit count'
        assert successor.beginning_wip_cost == Decimal('161.20')

    def test_an_OPEN_run_still_accepts_period_results(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        """The guard must not break the normal path."""
        _enable(db_session)
        bom, dept, out = _parts(main_branch, accountant_user, 'E')
        run = _run(main_branch, bom, dept, units_completed_and_transferred=Decimal('0'))
        _login(client, accountant_user, main_branch)
        client.post(f'/production-runs/{run.id}/period',
                    data={'units_completed_and_transferred': '70'}, follow_redirects=True)
        db.session.refresh(run)
        assert run.units_completed_and_transferred == Decimal('70')


class TestCloseRefusesAZeroCostPool:
    def test_refuses_when_units_transfer_but_the_pool_is_empty(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """80 units completed, nothing issued, no conversion. Before the fix this
        received 80 units of finished goods at 0.00 and posted a zero-value JE."""
        bom, dept, out = _parts(main_branch, accountant_user, 'F')
        run = _run(main_branch, bom, dept, conversion_cost=None,
                   units_ending_wip=Decimal('0'), ending_wip_pct_complete=Decimal('0'))
        with pytest.raises(ValueError, match='no cost|material|conversion'):
            close_run(run, accountant_user)

    def test_nothing_is_posted_and_no_free_stock_is_created(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        bom, dept, out = _parts(main_branch, accountant_user, 'G')
        run = _run(main_branch, bom, dept, conversion_cost=None,
                   units_ending_wip=Decimal('0'), ending_wip_pct_complete=Decimal('0'))
        before = JournalEntry.query.count()
        with pytest.raises(ValueError):
            close_run(run, accountant_user)
        db.session.rollback()
        assert JournalEntry.query.count() == before
        assert StockMovement.query.filter_by(source_document_type='production_run',
                                             movement_type='production').first() is None
        bal = StockBalance.query.filter_by(product_id=out.id, branch_id=main_branch.id).first()
        assert bal is None or bal.quantity_on_hand == Decimal('0')

    def test_a_zero_pool_with_NOTHING_transferred_still_closes(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """Only the TRANSFER needs a cost. A period that started nothing and finished
        nothing is legitimately empty and must still be closable."""
        bom, dept, out = _parts(main_branch, accountant_user, 'H')
        run = _run(main_branch, bom, dept, conversion_cost=None,
                   units_completed_and_transferred=Decimal('0'),
                   units_ending_wip=Decimal('20'), ending_wip_pct_complete=Decimal('50'))
        close_run(run, accountant_user); db.session.commit()
        assert run.status == 'closed'
        assert run.ending_wip_cost == Decimal('0.00')

    def test_a_normal_close_is_unaffected(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        bom, dept, out = _parts(main_branch, accountant_user, 'I')
        run = _run(main_branch, bom, dept)
        issue_material(run.materials[0], Decimal('200'), accountant_user); db.session.commit()
        close_run(run, accountant_user); db.session.commit()
        assert run.status == 'closed'
        assert run.transferred_unit_cost == Decimal('16.11')
