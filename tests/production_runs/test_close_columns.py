"""P4 Task 1 -- the period-close columns on ProductionRun.

Six additive columns (owner-approved 2026-08-02). The two beginning-WIP fields
are NOT NULL with a 0 default because every run has a beginning WIP even when it
is zero, and a NULL there would silently drop out of the cost pool's arithmetic.
The four close fields are nullable: an open run has not been closed.

The migration itself is verified separately against a REAL migrated database --
a conftest create_all() builds today's model, not the migration history, so it
structurally cannot catch a batch_alter_table that drops an index. See
scripts/verify_prodclose_migration.py and memory migration-verify-on-real-db-copy.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialLine
from app.manufacturing_departments.models import ManufacturingDepartment
from app.production_runs.models import ProductionRun
from app.products.models import Product

pytestmark = [pytest.mark.unit, pytest.mark.production_runs]


@pytest.fixture
def process_bom(db_session):
    out = Product(code='P4-OUT', name='Dried Mango', is_active=True)
    comp = Product(code='P4-COMP', name='Fresh Mango', track_inventory=True,
                   costing_method='moving_average', standard_cost=Decimal('5.00'),
                   is_active=True)
    db.session.add_all([out, comp]); db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='process')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id,
                                        quantity_per=Decimal('2')))
    db.session.add(bom); db.session.commit()
    return bom


@pytest.fixture
def dehydration_dept(db_session, main_branch):
    d = ManufacturingDepartment(branch_id=main_branch.id, code='DRY', name='Dehydration')
    db.session.add(d); db.session.commit()
    return d


def _run(branch, bom, dept, number='C0001', **kw):
    run = ProductionRun(run_number=number, bom_id=bom.id, department_id=dept.id,
                        branch_id=branch.id, period_start=date(2026, 8, 1),
                        period_end=date(2026, 8, 31), units_started=Decimal('100'), **kw)
    db.session.add(run)
    db.session.commit()
    return run


class TestBeginningWipDefaults:
    def test_beginning_wip_defaults_to_zero_not_null(
            self, db_session, main_branch, process_bom, dehydration_dept):
        """A run with no predecessor still carries a real zero, never NULL --
        NULL would drop out of the cost-pool sum instead of adding nothing."""
        run = _run(main_branch, process_bom, dehydration_dept)
        assert run.beginning_wip_units == Decimal('0')
        assert run.beginning_wip_cost == Decimal('0')

    def test_beginning_wip_round_trips(
            self, db_session, main_branch, process_bom, dehydration_dept):
        run = _run(main_branch, process_bom, dehydration_dept, number='C0002',
                   beginning_wip_units=Decimal('20'), beginning_wip_cost=Decimal('161.20'))
        db.session.expire(run)
        assert run.beginning_wip_units == Decimal('20.0000')
        assert run.beginning_wip_cost == Decimal('161.20')


class TestCloseFields:
    def test_close_fields_start_empty_on_an_open_run(
            self, db_session, main_branch, process_bom, dehydration_dept):
        run = _run(main_branch, process_bom, dehydration_dept, number='C0003')
        assert run.status == 'open'
        assert run.ending_wip_cost is None
        assert run.transferred_unit_cost is None
        assert run.closed_at is None
        assert run.closed_by_id is None

    def test_frozen_figures_round_trip(
            self, db_session, main_branch, process_bom, dehydration_dept, accountant_user):
        """Re-fetches from a CLEARED identity map, not just expire(), so the values
        must have gone through SQL. With expire() alone this test passed VACUOUSLY
        against a model that had no such columns at all -- the assignments were just
        Python attributes, which expire() does not touch."""
        from app.utils import ph_now
        run = _run(main_branch, process_bom, dehydration_dept, number='C0004')
        # Read every id BEFORE expunging -- expunge_all() detaches the fixtures too,
        # and touching accountant_user.id afterwards raises DetachedInstanceError.
        run_id, actor_id = run.id, accountant_user.id
        run.transferred_unit_cost = Decimal('16.11')
        run.ending_wip_cost = Decimal('161.20')
        run.closed_at = ph_now()
        run.closed_by_id = actor_id
        run.status = 'closed'
        db.session.commit()
        db.session.expunge_all()

        fresh = db.session.get(ProductionRun, run_id)
        assert fresh is not run, 'identity map was not cleared -- test proves nothing'
        assert fresh.transferred_unit_cost == Decimal('16.11')
        assert fresh.ending_wip_cost == Decimal('161.20')
        assert fresh.closed_by_id == actor_id
        assert fresh.closed_at is not None
        assert fresh.status == 'closed'


class TestToDict:
    def test_to_dict_exposes_the_new_figures(
            self, db_session, main_branch, process_bom, dehydration_dept):
        """to_dict feeds the audit log's old/new snapshot -- a close that did not
        appear in it would leave the audit trail unable to show what changed."""
        run = _run(main_branch, process_bom, dehydration_dept, number='C0005',
                   beginning_wip_units=Decimal('20'), beginning_wip_cost=Decimal('161.20'))
        run.transferred_unit_cost = Decimal('16.11')
        run.ending_wip_cost = Decimal('55.00')
        db.session.commit()
        d = run.to_dict()
        assert d['beginning_wip_units'] == 20.0
        assert d['beginning_wip_cost'] == 161.20
        assert d['transferred_unit_cost'] == 16.11
        assert d['ending_wip_cost'] == 55.00

    def test_to_dict_keeps_none_as_none_for_an_open_run(
            self, db_session, main_branch, process_bom, dehydration_dept):
        run = _run(main_branch, process_bom, dehydration_dept, number='C0006')
        d = run.to_dict()
        assert d['transferred_unit_cost'] is None
        assert d['ending_wip_cost'] is None
        assert d['beginning_wip_cost'] == 0.0
