"""Equivalent-units costing for a Production Run (R-07 Process Track slice P3).

Weighted-average process costing:
    equivalent units = units_completed_and_transferred
                     + (units_ending_wip x ending_wip_pct_complete / 100)
    cost per EU      = (material cost + conversion cost) / equivalent units

Material cost is READ BACK off the run's posted manufacturing_consumption journal
entries -- never recomputed from the materials table -- matching the house rule that
a report reconciles to the GL (the same convention D5's WO costing report follows).

Conversion cost is entered manually per run (owner decision 2026-08-02; the arc
spec's "reuse ExpenseAllocationRule" is impossible -- that driver is product-line
scoped with no department or period dimension. See the spec's dated correction).
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


def _setup(branch, actor, suffix='A', unit_cost='5.00', qty_per='2'):
    comp = Product(code=f'P3-C-{suffix}', name='Fresh Mango', track_inventory=True,
                   costing_method='moving_average', standard_cost=Decimal(unit_cost),
                   is_active=True)
    out = Product(code=f'P3-O-{suffix}', name='Dried Mango', is_active=True)
    db.session.add_all([comp, out]); db.session.commit()
    post_movement(comp, branch.id, 'opening', Decimal('10000'), Decimal(unit_cost),
                  'stock_adjustment', 0, 'seed', actor, movement_date=date(2026, 1, 1))
    db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='process')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id,
                                        quantity_per=Decimal(qty_per)))
    db.session.add(bom); db.session.commit()
    dept = ManufacturingDepartment(branch_id=branch.id, code=f'D{suffix}', name='Dehydration')
    db.session.add(dept); db.session.commit()
    return bom, dept


def _run(branch, bom, dept, units_started='100', number=None, **kw):
    run = ProductionRun(run_number=number or f'{abs(hash((bom.id, dept.id))) % 99999:05d}',
                        bom_id=bom.id, department_id=dept.id, branch_id=branch.id,
                        period_start=date(2026, 8, 1), period_end=date(2026, 8, 31),
                        units_started=Decimal(units_started), **kw)
    db.session.add(run); db.session.commit()
    snapshot_materials(run); db.session.commit()
    return run


def test_equivalent_units_include_partially_complete_ending_wip(
        db_session, main_branch, accountant_user, wo_control_accounts):
    bom, dept = _setup(main_branch, accountant_user, 'A')
    run = _run(main_branch, bom, dept, units_started='100', number='00001',
               units_completed_and_transferred=Decimal('80'),
               units_ending_wip=Decimal('20'),
               ending_wip_pct_complete=Decimal('50'))
    data = compute_run_costing(run)
    # 80 completed + (20 x 50%) = 90
    assert data['equivalent_units'] == Decimal('90.0000')


def test_cost_per_equivalent_unit(db_session, main_branch, accountant_user, wo_control_accounts):
    bom, dept = _setup(main_branch, accountant_user, 'B')
    run = _run(main_branch, bom, dept, units_started='100', number='00002',
               units_completed_and_transferred=Decimal('80'),
               units_ending_wip=Decimal('20'),
               ending_wip_pct_complete=Decimal('50'),
               conversion_cost=Decimal('450.00'))
    issue_material(run.materials[0], Decimal('200'), accountant_user)   # 200 x 5.00 = 1000.00
    db.session.commit()

    data = compute_run_costing(run)
    assert data['material_cost'] == Decimal('1000.00')
    assert data['conversion_cost'] == Decimal('450.00')
    assert data['total_cost'] == Decimal('1450.00')
    assert data['equivalent_units'] == Decimal('90.0000')
    # 1450.00 / 90 = 16.1111...
    assert data['cost_per_equivalent_unit'] == Decimal('16.11')


def test_material_cost_is_read_off_the_posted_je_not_the_materials_table(
        db_session, main_branch, accountant_user, wo_control_accounts):
    """House rule: the figure reconciles to the GL. If quantity_issued were trusted
    instead, tampering with it would silently change the reported cost."""
    bom, dept = _setup(main_branch, accountant_user, 'C')
    run = _run(main_branch, bom, dept, units_started='100', number='00003')
    issue_material(run.materials[0], Decimal('100'), accountant_user)
    db.session.commit()
    assert compute_run_costing(run)['material_cost'] == Decimal('500.00')

    run.materials[0].quantity_issued = Decimal('999999')   # tamper
    db.session.commit()
    assert compute_run_costing(run)['material_cost'] == Decimal('500.00'), \
        'material cost must come from the posted JE, not quantity_issued'


def test_multiple_issues_accumulate(db_session, main_branch, accountant_user, wo_control_accounts):
    bom, dept = _setup(main_branch, accountant_user, 'D')
    run = _run(main_branch, bom, dept, units_started='100', number='00004')
    issue_material(run.materials[0], Decimal('60'), accountant_user); db.session.commit()
    issue_material(run.materials[0], Decimal('40'), accountant_user); db.session.commit()
    assert compute_run_costing(run)['material_cost'] == Decimal('500.00')


def test_zero_equivalent_units_does_not_divide_by_zero(
        db_session, main_branch, accountant_user, wo_control_accounts):
    """A run opened but with nothing reported yet -- must return None, not raise."""
    bom, dept = _setup(main_branch, accountant_user, 'E')
    run = _run(main_branch, bom, dept, units_started='100', number='00005')
    issue_material(run.materials[0], Decimal('100'), accountant_user); db.session.commit()
    data = compute_run_costing(run)
    assert data['equivalent_units'] == Decimal('0.0000')
    assert data['cost_per_equivalent_unit'] is None
    assert data['material_cost'] == Decimal('500.00'), 'cost still reported'


def test_missing_conversion_cost_is_treated_as_zero(
        db_session, main_branch, accountant_user, wo_control_accounts):
    bom, dept = _setup(main_branch, accountant_user, 'F')
    run = _run(main_branch, bom, dept, units_started='100', number='00006',
               units_completed_and_transferred=Decimal('100'))
    issue_material(run.materials[0], Decimal('200'), accountant_user); db.session.commit()
    data = compute_run_costing(run)
    assert data['conversion_cost'] == Decimal('0.00')
    assert data['total_cost'] == Decimal('1000.00')
    assert data['cost_per_equivalent_unit'] == Decimal('10.00')


def test_ending_wip_fully_complete_counts_in_full(
        db_session, main_branch, accountant_user, wo_control_accounts):
    bom, dept = _setup(main_branch, accountant_user, 'G')
    run = _run(main_branch, bom, dept, units_started='100', number='00007',
               units_completed_and_transferred=Decimal('0'),
               units_ending_wip=Decimal('40'),
               ending_wip_pct_complete=Decimal('100'))
    assert compute_run_costing(run)['equivalent_units'] == Decimal('40.0000')


class TestPeriodResultsUi:
    """Entering period results and seeing the costing panel (R-07 P3 UI)."""

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

    def test_posting_period_results_persists_and_shows_cost_per_eu(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        self._enable(db_session)
        bom, dept = _setup(main_branch, accountant_user, 'UI')
        run = _run(main_branch, bom, dept, units_started='100', number='00050')
        issue_material(run.materials[0], Decimal('200'), accountant_user); db.session.commit()

        self._login(client, accountant_user, main_branch)
        resp = client.post(f'/production-runs/{run.id}/period', data={
            'units_completed_and_transferred': '80', 'units_ending_wip': '20',
            'ending_wip_pct_complete': '50', 'conversion_cost': '450.00',
        }, follow_redirects=True)
        assert resp.status_code == 200

        db.session.refresh(run)
        assert run.units_completed_and_transferred == Decimal('80')
        assert run.conversion_cost == Decimal('450.00')

        body = resp.data.decode('utf-8')
        assert '16.11' in body, 'cost per equivalent unit must be shown'
        assert '90.0000' in body, 'equivalent units must be shown'

    def test_costing_panel_renders_before_any_results_are_entered(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        """A freshly opened run must not 500 on a zero-EU division."""
        self._enable(db_session)
        bom, dept = _setup(main_branch, accountant_user, 'UI2')
        run = _run(main_branch, bom, dept, units_started='100', number='00051')
        self._login(client, accountant_user, main_branch)
        resp = client.get(f'/production-runs/{run.id}')
        assert resp.status_code == 200
        assert b'Equivalent Units' in resp.data

    def test_staff_cannot_post_period_results(
            self, client, db_session, main_branch, staff_user, accountant_user,
            wo_control_accounts):
        self._enable(db_session)
        bom, dept = _setup(main_branch, accountant_user, 'UI3')
        run = _run(main_branch, bom, dept, units_started='100', number='00052')
        staff_user.set_branches([main_branch])
        staff_user.set_book_permissions({'production_runs': True})
        db_session.commit()
        self._login(client, staff_user, main_branch)
        resp = client.post(f'/production-runs/{run.id}/period',
                           data={'units_completed_and_transferred': '10'},
                           follow_redirects=True)
        assert b'do not have permission' in resp.data
        db.session.refresh(run)
        assert run.units_completed_and_transferred == Decimal('0')
