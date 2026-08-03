"""P5 Task 1 -- the Cost of Production Report's cost schedules.

The report reads material / conversion / transferred-out back off the POSTED
journal entries and takes beginning/ending WIP from the run's own frozen columns.
Three of those five figures therefore come straight off the ledger, which is what
makes "costs accounted for == costs to account for" a real reconciliation of the
WIP control account rather than the report agreeing with itself.

It deliberately does NOT call compute_run_costing(): that is the live PREVIEW
engine for open runs and reads stored values, so using it here would make the
statement agree with the run record instead of the GL -- see the design's
non-negotiable rule.

The last class is the point of the whole slice: a tie-out that cannot go red
proves nothing, so there is a test that makes it go red.
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


def _setup(branch, actor, suffix, out_method='moving_average', out_standard=None):
    comp = Product(code=f'R5-C-{suffix}', name='Fresh Mango', track_inventory=True,
                   costing_method='moving_average', standard_cost=Decimal('5.00'),
                   is_active=True)
    out = Product(code=f'R5-O-{suffix}', name='Dried Mango', track_inventory=True,
                  costing_method=out_method,
                  standard_cost=Decimal(out_standard) if out_standard else None,
                  is_active=True)
    db.session.add_all([comp, out]); db.session.commit()
    post_movement(comp, branch.id, 'opening', Decimal('10000'), Decimal('5.00'),
                  'stock_adjustment', 0, 'seed', actor)
    db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='process')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id,
                                        quantity_per=Decimal('2')))
    db.session.add(bom); db.session.commit()
    dept = ManufacturingDepartment(branch_id=branch.id, code=f'R{suffix}', name='Dehydration')
    db.session.add(dept); db.session.commit()
    return bom, dept, out


def _closed_run(branch, actor, suffix, issue_qty='200', **run_kw):
    """The canonical shape: 200 material @ 5.00 + 450 conversion, 80 done / 20 half."""
    bom, dept, out = _setup(branch, actor, suffix, **{k: v for k, v in run_kw.items()
                                                      if k in ('out_method', 'out_standard')})
    _N[0] += 1
    kw = dict(conversion_cost=Decimal('450.00'),
              units_completed_and_transferred=Decimal('80'),
              units_ending_wip=Decimal('20'),
              ending_wip_pct_complete=Decimal('50'))
    kw.update({k: v for k, v in run_kw.items()
               if k not in ('out_method', 'out_standard')})
    run = ProductionRun(run_number='R5%04d' % _N[0], bom_id=bom.id, department_id=dept.id,
                        branch_id=branch.id, period_start=date(2026, 8, 1),
                        period_end=date(2026, 8, 31), units_started=Decimal('100'), **kw)
    db.session.add(run); db.session.commit()
    snapshot_materials(run); db.session.commit()
    if issue_qty:
        issue_material(run.materials[0], Decimal(issue_qty), actor); db.session.commit()
    close_run(run, actor); db.session.commit()
    return run, out


class TestCostSchedules:
    def test_every_cost_figure_and_the_tie_out(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        run, out = _closed_run(main_branch, accountant_user, 'A')
        rep = generate_production_run_cost_report(run.id, main_branch.id)

        assert rep['beginning_wip_cost'] == Decimal('0.00')
        assert rep['material_added'] == Decimal('1000.00')
        assert rep['conversion_applied'] == Decimal('450.00')
        assert rep['total_to_account_for'] == Decimal('1450.00')
        assert rep['transferred_out'] == Decimal('1288.80')
        assert rep['ending_wip_cost'] == Decimal('161.20')
        assert rep['total_accounted_for'] == Decimal('1450.00')
        assert rep['difference'] == Decimal('0.00')
        assert rep['reconciles'] is True

    def test_cost_per_equivalent_unit_and_equivalent_units(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        run, out = _closed_run(main_branch, accountant_user, 'B')
        rep = generate_production_run_cost_report(run.id, main_branch.id)
        assert rep['equivalent_units'] == Decimal('90.0000')
        assert rep['cost_per_equivalent_unit'] == Decimal('16.11')

    def test_reconciles_with_a_beginning_wip_carried_in(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """Beginning WIP has NO journal entry -- it is carried, not posted -- so this
        is the case where the ledger alone would not add up."""
        run, out = _closed_run(main_branch, accountant_user, 'C',
                               beginning_wip_units=Decimal('20'),
                               beginning_wip_cost=Decimal('225.00'))
        rep = generate_production_run_cost_report(run.id, main_branch.id)
        assert rep['beginning_wip_cost'] == Decimal('225.00')
        assert rep['total_to_account_for'] == Decimal('1675.00')
        assert rep['reconciles'] is True, 'carried-in WIP must be part of the tie-out'

    def test_reconciles_with_zero_ending_wip(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        run, out = _closed_run(main_branch, accountant_user, 'D',
                               units_completed_and_transferred=Decimal('100'),
                               units_ending_wip=Decimal('0'),
                               ending_wip_pct_complete=Decimal('0'))
        rep = generate_production_run_cost_report(run.id, main_branch.id)
        assert rep['ending_wip_cost'] == Decimal('0.00')
        assert rep['reconciles'] is True

    def test_reconciles_for_a_standard_costed_output_with_a_variance_leg(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """The transfer JE carries an inventory_variance leg here. The report reads
        the WIP CREDIT, so the variance must not leak into transferred_out."""
        run, out = _closed_run(main_branch, accountant_user, 'E',
                               out_method='standard', out_standard='15.00')
        rep = generate_production_run_cost_report(run.id, main_branch.id)
        assert rep['transferred_out'] == Decimal('1288.80'), 'WIP relieved at the REAL cost'
        assert rep['reconciles'] is True


class TestItReadsTheLedgerNotTheRunRecord:
    def test_material_comes_from_the_posted_je_not_quantity_issued(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        run, out = _closed_run(main_branch, accountant_user, 'F')
        run.materials[0].quantity_issued = Decimal('999999')
        db.session.commit()
        rep = generate_production_run_cost_report(run.id, main_branch.id)
        assert rep['material_added'] == Decimal('1000.00')

    def test_conversion_comes_from_the_posted_je_not_the_stored_column(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """This is the difference between a tie-out and a restatement: tampering with
        run.conversion_cost must NOT move the reported figure, because the ledger is
        the source. compute_run_costing() would have moved."""
        run, out = _closed_run(main_branch, accountant_user, 'G')
        run.conversion_cost = Decimal('99999.00')
        db.session.commit()
        rep = generate_production_run_cost_report(run.id, main_branch.id)
        assert rep['conversion_applied'] == Decimal('450.00')


class TestTheTieOutCanFail:
    """A reconciliation that cannot go red proves nothing. These make it go red."""

    def test_a_tampered_ending_wip_breaks_the_tie_out(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        run, out = _closed_run(main_branch, accountant_user, 'H')
        run.ending_wip_cost = Decimal('150.00')      # was 161.20
        db.session.commit()
        rep = generate_production_run_cost_report(run.id, main_branch.id)
        assert rep['reconciles'] is False
        assert rep['difference'] == Decimal('11.20')

    def test_a_tampered_beginning_wip_breaks_the_tie_out(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        run, out = _closed_run(main_branch, accountant_user, 'I')
        run.beginning_wip_cost = Decimal('500.00')
        db.session.commit()
        rep = generate_production_run_cost_report(run.id, main_branch.id)
        assert rep['reconciles'] is False
        assert rep['difference'] == Decimal('500.00')

    def test_the_difference_is_signed_so_the_direction_is_visible(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """difference = to_account_for - accounted_for. A reader must be able to tell
        which side is short."""
        run, out = _closed_run(main_branch, accountant_user, 'J')
        run.ending_wip_cost = Decimal('200.00')      # accounted-for now EXCEEDS the pool
        db.session.commit()
        rep = generate_production_run_cost_report(run.id, main_branch.id)
        assert rep['reconciles'] is False
        assert rep['difference'] == Decimal('-38.80')


class TestGuards:
    def test_refuses_an_open_run(self, db_session, main_branch, accountant_user,
                                 wo_control_accounts):
        bom, dept, out = _setup(main_branch, accountant_user, 'K')
        run = ProductionRun(run_number='R5-OPEN', bom_id=bom.id, department_id=dept.id,
                            branch_id=main_branch.id, period_start=date(2026, 8, 1),
                            period_end=date(2026, 8, 31), units_started=Decimal('100'))
        db.session.add(run); db.session.commit()
        with pytest.raises(ValueError, match='closed'):
            generate_production_run_cost_report(run.id, main_branch.id)

    def test_refuses_another_branchs_run(self, db_session, main_branch, branch_manila,
                                         accountant_user, wo_control_accounts):
        run, out = _closed_run(main_branch, accountant_user, 'L')
        with pytest.raises(ValueError):
            generate_production_run_cost_report(run.id, branch_manila.id)

    def test_missing_control_accounts_report_zeros_rather_than_raising(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """D5's convention -- a half-configured install sees zeros, not a 500."""
        from app.settings import AppSettings
        run, out = _closed_run(main_branch, accountant_user, 'M')
        AppSettings.set_setting('wip_account_code', '')
        db.session.commit()
        rep = generate_production_run_cost_report(run.id, main_branch.id)
        assert rep['material_added'] == Decimal('0.00')
        assert rep['transferred_out'] == Decimal('0.00')
