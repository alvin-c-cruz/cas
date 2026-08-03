"""P4 Task 4 -- closing a Production Run period.

Closing transfers the period's completed units out of WIP into finished goods at
the period's cost per equivalent unit, freezes that unit cost and the residual WIP
value, and marks the run closed.

THE LOAD-BEARING INVARIANT: after close, WIP must tie to the GL. What stays in the
WIP account is the pool minus what was transferred out -- the residual PLUG -- and
that same figure is what the successor run inherits. Valuing the leftover as
`ending units x cost/EU` instead would strand the difference in WIP forever,
because those units are only partially complete.

P4 does NOT call produce_finished_goods(), deliberately. Its JE shape fits, but for
a STANDARD-COSTED output post_movement values the receipt at Product.standard_cost
and ignores the unit_cost passed in, while produce_finished_goods reads its JE
amount from mv.unit_cost -- WIP would be relieved at standard with the difference
stranded. D4 hit this first and wrote its own JE; P4 does the same, adding an
inventory_variance leg. See the arc spec's 2026-08-02 correction (backlog 265).
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialLine
from app.journal_entries.models import JournalEntry
from app.manufacturing_departments.models import ManufacturingDepartment
from app.posting.control_accounts import get_control_account
from app.production_runs.models import ProductionRun
from app.production_runs.service import close_run, issue_material, snapshot_materials
from app.products.models import Product
from app.stock_adjustments.service import post_movement

pytestmark = [pytest.mark.integration, pytest.mark.production_runs]

_N = [0]


def _setup(branch, actor, suffix, out_method='moving_average', out_standard=None):
    comp = Product(code=f'CL-C-{suffix}', name='Fresh Mango', track_inventory=True,
                   costing_method='moving_average', standard_cost=Decimal('5.00'),
                   is_active=True)
    out = Product(code=f'CL-O-{suffix}', name='Dried Mango', track_inventory=True,
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
    dept = ManufacturingDepartment(branch_id=branch.id, code=f'D{suffix}', name='Dehydration')
    db.session.add(dept); db.session.commit()
    return bom, dept, out, comp


def _open_run(branch, bom, dept, **kw):
    _N[0] += 1
    run = ProductionRun(run_number='CL%04d' % _N[0], bom_id=bom.id, department_id=dept.id,
                        branch_id=branch.id, period_start=date(2026, 8, 1),
                        period_end=date(2026, 8, 31), units_started=Decimal('100'), **kw)
    db.session.add(run); db.session.commit()
    snapshot_materials(run); db.session.commit()
    return run


def _wip_balance():
    """Net Dr-Cr on the WIP control account across every posted JE line."""
    wip = get_control_account('wip')
    total = Decimal('0.00')
    for je in JournalEntry.query.all():
        for line in je.lines:
            if line.account_id == wip.id:
                total += (line.debit_amount or 0) - (line.credit_amount or 0)
    return total.quantize(Decimal('0.01'))


def _standard_run(branch, actor, suffix, **kw):
    """The canonical shape: 200 material + 450 conversion, 80 done / 20 half-done."""
    bom, dept, out, comp = _setup(branch, actor, suffix, **kw)
    run = _open_run(branch, bom, dept,
                    conversion_cost=Decimal('450.00'),
                    units_completed_and_transferred=Decimal('80'),
                    units_ending_wip=Decimal('20'),
                    ending_wip_pct_complete=Decimal('50'))
    issue_material(run.materials[0], Decimal('200'), actor)   # 200 x 5.00 = 1000.00
    db.session.commit()
    return run, out


class TestCloseArithmetic:
    def test_transfers_at_cost_per_equivalent_unit_and_freezes_it(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        run, out = _standard_run(main_branch, accountant_user, 'A')
        close_run(run, accountant_user)
        db.session.commit()
        # pool 1450.00 / EU 90 = 16.11; 80 units transferred = 1288.80
        assert run.transferred_unit_cost == Decimal('16.11')
        assert run.status == 'closed'
        assert run.closed_at is not None
        assert run.closed_by_id == accountant_user.id

    def test_ending_wip_cost_is_the_residual_plug_not_units_times_cost_per_eu(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """THE convention. 1450.00 pool - 1288.80 transferred = 161.20 left.
        NOT 20 x 16.11 = 322.20, which would strand 161.00 in WIP permanently."""
        run, out = _standard_run(main_branch, accountant_user, 'B')
        close_run(run, accountant_user)
        db.session.commit()
        assert run.ending_wip_cost == Decimal('161.20')
        assert run.ending_wip_cost != Decimal('322.20')

    def test_wip_ties_to_the_gl_after_close(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """The whole point: what the ledger says is left in WIP is exactly what the
        run says it carries forward. If these ever disagree, value is stranded.

        This test is what forced conversion cost to be POSTED at close. Only material
        reaches WIP during the period (P2's consumption JE); the manually-entered
        conversion cost had no journal entry at all, so relieving WIP at a cost/EU
        that INCLUDES conversion would drive the ledger's WIP negative -- here
        1000.00 in, 1288.80 out. Applying conversion to WIP at close closes the gap:
        1000.00 + 450.00 - 1288.80 = 161.20, exactly the carried figure.

        EXTENDED by P6 (Task 5), not replaced: WIP is now relieved by THREE legs
        rather than one, so the identity is `pool - transferred - abnormal charged`.
        This run's BOM sets no expected-loss percentage and loses nothing, so the
        third term is zero and every figure above is untouched -- which is precisely
        the claim worth keeping here. The non-zero case lives in
        test_close_abnormal_loss.py, and deleting this one would lose the guard that
        caught P4's missing conversion posting in the first place.
        """
        run, out = _standard_run(main_branch, accountant_user, 'C')
        assert _wip_balance() == Decimal('1000.00'), 'only material is in WIP before close'
        close_run(run, accountant_user)
        db.session.commit()
        assert _wip_balance() == Decimal('161.20')
        assert _wip_balance() == run.ending_wip_cost, 'ledger and carried figure must agree'

        from app.production_runs.costing import compute_run_costing
        data = compute_run_costing(run)
        assert data['abnormal_loss_cost'] == Decimal('0.00'), 'no expectation set'
        assert run.ending_wip_cost == (data['total_cost']
                                       - Decimal('1288.80')
                                       - data['abnormal_loss_cost']), \
            'the three-term identity, with its third term at zero'

    def test_conversion_cost_is_applied_to_wip_at_close(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """Conversion is entered manually on the run and reaches the books only here.
        Dr WIP / Cr Labor Applied, mirroring how D4 credits labor_applied on the
        discrete side rather than inventing a second applied-cost account."""
        run, out = _standard_run(main_branch, accountant_user, 'C2')
        close_run(run, accountant_user)
        db.session.commit()
        je = JournalEntry.query.filter_by(entry_type='manufacturing_conversion',
                                          reference=run.run_number).one()
        assert je.is_balanced
        wip = get_control_account('wip')
        labor = get_control_account('labor_applied')
        dr_wip = sum((l.debit_amount or 0) for l in je.lines if l.account_id == wip.id)
        cr_lab = sum((l.credit_amount or 0) for l in je.lines if l.account_id == labor.id)
        assert dr_wip == Decimal('450.00')
        assert cr_lab == Decimal('450.00')

    def test_no_conversion_je_when_conversion_cost_is_zero(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        bom, dept, out, comp = _setup(main_branch, accountant_user, 'C3')
        run = _open_run(main_branch, bom, dept,
                        units_completed_and_transferred=Decimal('100'))
        issue_material(run.materials[0], Decimal('200'), accountant_user)
        db.session.commit()
        close_run(run, accountant_user); db.session.commit()
        assert not JournalEntry.query.filter_by(entry_type='manufacturing_conversion',
                                                reference=run.run_number).all()
        assert _wip_balance() == Decimal('0.00'), 'everything transferred out'

    def test_the_transfer_je_balances_and_hits_inventory_and_wip(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        run, out = _standard_run(main_branch, accountant_user, 'D')
        close_run(run, accountant_user)
        db.session.commit()
        je = JournalEntry.query.filter_by(entry_type='manufacturing_production',
                                          reference=run.run_number).one()
        assert je.is_balanced
        inv = get_control_account('inventory')
        wip = get_control_account('wip')
        dr_inv = sum((l.debit_amount or 0) for l in je.lines if l.account_id == inv.id)
        cr_wip = sum((l.credit_amount or 0) for l in je.lines if l.account_id == wip.id)
        assert dr_inv == Decimal('1288.80')
        assert cr_wip == Decimal('1288.80')

    def test_finished_goods_stock_increases_by_the_transferred_units(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        from app.stock_adjustments.models import StockMovement
        run, out = _standard_run(main_branch, accountant_user, 'E')
        close_run(run, accountant_user)
        db.session.commit()
        mv = StockMovement.query.filter_by(source_document_type='production_run',
                                           movement_type='production').one()
        assert mv.quantity == Decimal('80.0000')
        assert mv.unit_cost == Decimal('16.11')


class TestStandardCostedOutput:
    def test_variance_leg_absorbs_the_gap_and_wip_is_still_fully_relieved(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """post_movement pins a standard-costed receipt to Product.standard_cost and
        ignores the cost/EU we pass. Inventory therefore lands at standard, WIP is
        still relieved at the real transferred amount, and inventory_variance takes
        the difference -- exactly what produce_finished_goods would have got wrong."""
        run, out = _standard_run(main_branch, accountant_user, 'F',
                                 out_method='standard', out_standard='15.00')
        close_run(run, accountant_user)
        db.session.commit()

        je = JournalEntry.query.filter_by(entry_type='manufacturing_production',
                                          reference=run.run_number).one()
        assert je.is_balanced, 'a variance leg must make it balance'
        inv = get_control_account('inventory')
        wip = get_control_account('wip')
        var = get_control_account('inventory_variance')
        dr_inv = sum((l.debit_amount or 0) for l in je.lines if l.account_id == inv.id)
        cr_wip = sum((l.credit_amount or 0) for l in je.lines if l.account_id == wip.id)
        dr_var = sum((l.debit_amount or 0) for l in je.lines if l.account_id == var.id)
        # inventory at standard: 80 x 15.00 = 1200.00; WIP relieved at 80 x 16.11 = 1288.80
        assert dr_inv == Decimal('1200.00')
        assert cr_wip == Decimal('1288.80'), 'WIP must be relieved at the REAL cost'
        assert dr_var == Decimal('88.80'), 'the gap is a variance, never stranded in WIP'

    def test_a_moving_average_output_posts_no_variance_leg(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        run, out = _standard_run(main_branch, accountant_user, 'G')
        close_run(run, accountant_user)
        db.session.commit()
        je = JournalEntry.query.filter_by(entry_type='manufacturing_production',
                                          reference=run.run_number).one()
        var = get_control_account('inventory_variance')
        assert not [l for l in je.lines if l.account_id == var.id]


class TestFrozenFigures:
    def test_a_later_standard_cost_edit_cannot_change_what_was_posted(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        run, out = _standard_run(main_branch, accountant_user, 'H')
        close_run(run, accountant_user)
        db.session.commit()
        frozen, wip_left = run.transferred_unit_cost, run.ending_wip_cost

        out.standard_cost = Decimal('999.00')
        db.session.commit()
        db.session.refresh(run)
        assert run.transferred_unit_cost == frozen
        assert run.ending_wip_cost == wip_left


class TestGuards:
    def test_refuses_a_run_that_is_not_open(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        run, out = _standard_run(main_branch, accountant_user, 'I')
        close_run(run, accountant_user); db.session.commit()
        with pytest.raises(ValueError, match='open'):
            close_run(run, accountant_user)

    def test_refuses_when_nothing_has_been_reported(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        bom, dept, out, comp = _setup(main_branch, accountant_user, 'J')
        run = _open_run(main_branch, bom, dept)
        with pytest.raises(ValueError, match='nothing to close|no period results'):
            close_run(run, accountant_user)

    def test_closes_with_ending_wip_only_and_transfers_nothing(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """A period where everything is still in process: no transfer, no JE, and the
        whole pool carries forward."""
        bom, dept, out, comp = _setup(main_branch, accountant_user, 'K')
        run = _open_run(main_branch, bom, dept,
                        units_ending_wip=Decimal('50'),
                        ending_wip_pct_complete=Decimal('40'))
        issue_material(run.materials[0], Decimal('100'), accountant_user)   # 500.00
        db.session.commit()
        close_run(run, accountant_user); db.session.commit()
        assert run.status == 'closed'
        assert run.ending_wip_cost == Decimal('500.00'), 'the whole pool carries'
        assert not JournalEntry.query.filter_by(entry_type='manufacturing_production',
                                                reference=run.run_number).all()

    def test_refuses_an_untracked_output_product(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """Transferring into finished goods requires an inventory-tracked output --
        otherwise WIP could be relieved with nothing receiving the value."""
        bom, dept, out, comp = _setup(main_branch, accountant_user, 'L')
        out.track_inventory = False
        db.session.commit()
        run = _open_run(main_branch, bom, dept,
                        units_completed_and_transferred=Decimal('80'),
                        ending_wip_pct_complete=Decimal('50'))
        issue_material(run.materials[0], Decimal('200'), accountant_user)
        db.session.commit()
        with pytest.raises(ValueError, match='inventory'):
            close_run(run, accountant_user)


class TestCarryChain:
    def test_the_successor_inherits_exactly_what_close_left_in_wip(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """End-to-end of the whole mechanism: close period 1, open period 2, and the
        carried figure is the closed run's frozen residual."""
        from app.production_runs.service import carry_beginning_wip
        run, out = _standard_run(main_branch, accountant_user, 'M')
        close_run(run, accountant_user); db.session.commit()

        successor = ProductionRun(run_number='CL-SUCC', bom_id=run.bom_id,
                                  department_id=run.department_id, branch_id=main_branch.id,
                                  period_start=date(2026, 9, 1), period_end=date(2026, 9, 30),
                                  units_started=Decimal('100'))
        carry_beginning_wip(successor)
        assert successor.beginning_wip_units == Decimal('20')
        assert successor.beginning_wip_cost == run.ending_wip_cost == Decimal('161.20')
