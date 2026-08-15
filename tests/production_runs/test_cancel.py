"""P4 Task 6 -- cancelling a Production Run.

P2 migrated cancel_reason / cancelled_by_id / cancelled_at onto ProductionRun but
never wired a route or a service; the columns have been dead since. The arc spec's
Cross-cutting concerns describe cancellation as reversing the run's consumptions
(returning component stock and reversing the GL posting), mirroring how SO/PO
cancellation reverses commitments elsewhere in CAS.

Reversal goes through the existing reverse_document_movements() primitive, the same
one delivery_receipts / receiving_reports / sales_memos / purchase_memos use -- it
posts an opposite movement per original at the SAME cost basis, so the append-only
ledger stays consistent.
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
from app.production_runs.service import (cancel_run, close_run, find_predecessor_run,
                                         issue_material, snapshot_materials)
from app.products.models import Product
from app.stock_adjustments.models import StockBalance
from app.stock_adjustments.service import post_movement

pytestmark = [pytest.mark.integration, pytest.mark.production_runs]

_N = [0]


def _setup(branch, actor, suffix):
    comp = Product(code=f'CN-C-{suffix}', name='Fresh Mango', track_inventory=True,
                   costing_method='moving_average', standard_cost=Decimal('5.00'),
                   is_active=True)
    out = Product(code=f'CN-O-{suffix}', name='Dried Mango', track_inventory=True,
                  costing_method='moving_average', is_active=True)
    db.session.add_all([comp, out]); db.session.commit()
    post_movement(comp, branch.id, 'opening', Decimal('10000'), Decimal('5.00'),
                  'stock_adjustment', 0, 'seed', actor, movement_date=date(2026, 1, 1))
    db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='process')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id,
                                        quantity_per=Decimal('2')))
    db.session.add(bom); db.session.commit()
    dept = ManufacturingDepartment(branch_id=branch.id, code=f'C{suffix}', name='Dehydration')
    db.session.add(dept); db.session.commit()
    return bom, dept, comp


def _run(branch, bom, dept, **kw):
    _N[0] += 1
    run = ProductionRun(run_number='CN%04d' % _N[0], bom_id=bom.id, department_id=dept.id,
                        branch_id=branch.id, period_start=date(2026, 8, 1),
                        period_end=date(2026, 8, 31), units_started=Decimal('100'), **kw)
    db.session.add(run); db.session.commit()
    snapshot_materials(run); db.session.commit()
    return run


def _on_hand(product, branch):
    bal = StockBalance.query.filter_by(product_id=product.id, branch_id=branch.id).first()
    return Decimal(bal.quantity_on_hand) if bal else Decimal('0')


def _wip_balance():
    wip = get_control_account('wip')
    total = Decimal('0.00')
    for je in JournalEntry.query.all():
        for line in je.lines:
            if line.account_id == wip.id:
                total += (line.debit_amount or 0) - (line.credit_amount or 0)
    return total.quantize(Decimal('0.01'))


class TestCancelReversesConsumption:
    def test_component_stock_returns_to_its_pre_issue_level(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        bom, dept, comp = _setup(main_branch, accountant_user, 'A')
        run = _run(main_branch, bom, dept)
        before = _on_hand(comp, main_branch)
        issue_material(run.materials[0], Decimal('200'), accountant_user)
        db.session.commit()
        assert _on_hand(comp, main_branch) == before - Decimal('200')

        cancel_run(run, 'Batch spoiled', accountant_user)
        db.session.commit()
        assert _on_hand(comp, main_branch) == before

    def test_wip_returns_to_zero(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """A cancelled run must leave nothing behind in WIP -- that is precisely why
        find_predecessor_run() refuses to carry from one."""
        bom, dept, comp = _setup(main_branch, accountant_user, 'B')
        run = _run(main_branch, bom, dept)
        issue_material(run.materials[0], Decimal('200'), accountant_user)
        db.session.commit()
        assert _wip_balance() == Decimal('1000.00')

        cancel_run(run, 'Batch spoiled', accountant_user)
        db.session.commit()
        assert _wip_balance() == Decimal('0.00')

    def test_the_reversing_je_balances(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        bom, dept, comp = _setup(main_branch, accountant_user, 'C')
        run = _run(main_branch, bom, dept)
        issue_material(run.materials[0], Decimal('200'), accountant_user)
        db.session.commit()
        cancel_run(run, 'Batch spoiled', accountant_user)
        db.session.commit()
        je = JournalEntry.query.filter_by(entry_type='manufacturing_consumption',
                                          reference=run.run_number).all()[-1]
        assert je.is_balanced

    def test_records_who_cancelled_it_and_why(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        bom, dept, comp = _setup(main_branch, accountant_user, 'D')
        run = _run(main_branch, bom, dept)
        cancel_run(run, 'Ordered in error', accountant_user)
        db.session.commit()
        assert run.status == 'cancelled'
        assert run.cancel_reason == 'Ordered in error'
        assert run.cancelled_by_id == accountant_user.id
        assert run.cancelled_at is not None

    def test_cancelling_a_run_with_no_issues_is_a_clean_no_op_posting(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """Nothing was consumed, so there is nothing to reverse and no JE to write."""
        bom, dept, comp = _setup(main_branch, accountant_user, 'E')
        run = _run(main_branch, bom, dept)
        before = JournalEntry.query.count()
        cancel_run(run, 'Never started', accountant_user)
        db.session.commit()
        assert run.status == 'cancelled'
        assert JournalEntry.query.count() == before


class TestGuards:
    def test_refuses_a_closed_run(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """A closed period has already transferred value into finished goods --
        unwinding it is a different operation, not a cancel."""
        bom, dept, comp = _setup(main_branch, accountant_user, 'F')
        run = _run(main_branch, bom, dept,
                   units_completed_and_transferred=Decimal('80'),
                   units_ending_wip=Decimal('20'),
                   ending_wip_pct_complete=Decimal('50'))
        issue_material(run.materials[0], Decimal('200'), accountant_user)
        db.session.commit()
        close_run(run, accountant_user); db.session.commit()
        with pytest.raises(ValueError, match='closed'):
            cancel_run(run, 'Too late', accountant_user)

    def test_refuses_an_already_cancelled_run(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        bom, dept, comp = _setup(main_branch, accountant_user, 'G')
        run = _run(main_branch, bom, dept)
        cancel_run(run, 'First', accountant_user); db.session.commit()
        with pytest.raises(ValueError):
            cancel_run(run, 'Second', accountant_user)

    def test_requires_a_reason(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        bom, dept, comp = _setup(main_branch, accountant_user, 'H')
        run = _run(main_branch, bom, dept)
        with pytest.raises(ValueError, match='[Rr]eason'):
            cancel_run(run, '   ', accountant_user)


class TestCancelledRunIsNotAPredecessor:
    def test_a_cancelled_run_is_never_carried_from(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """Belt and braces with Task 2's own test: cancel reverses everything, so a
        cancelled run has no WIP to hand on. Proven here against a REAL cancel rather
        than a hand-set status."""
        bom, dept, comp = _setup(main_branch, accountant_user, 'I')
        run = _run(main_branch, bom, dept)
        issue_material(run.materials[0], Decimal('200'), accountant_user)
        db.session.commit()
        cancel_run(run, 'Spoiled', accountant_user); db.session.commit()
        assert find_predecessor_run(run.bom_id, run.department_id, main_branch.id,
                                    date(2026, 9, 1)) is None


class TestCancelRoute:
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

    def test_cancels_via_the_route_and_audits_it(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        from app.audit.models import AuditLog
        self._enable(db_session)
        bom, dept, comp = _setup(main_branch, accountant_user, 'J')
        run = _run(main_branch, bom, dept)
        self._login(client, accountant_user, main_branch)
        resp = client.post(f'/production-runs/{run.id}/cancel',
                           data={'cancel_reason': 'Batch spoiled'}, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(run)
        assert run.status == 'cancelled'
        assert AuditLog.query.filter_by(module='production_runs', action='cancel',
                                        record_identifier=run.run_number).first() is not None

    def test_a_missing_reason_is_refused_by_the_route(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        self._enable(db_session)
        bom, dept, comp = _setup(main_branch, accountant_user, 'K')
        run = _run(main_branch, bom, dept)
        self._login(client, accountant_user, main_branch)
        resp = client.post(f'/production-runs/{run.id}/cancel',
                           data={'cancel_reason': ''}, follow_redirects=True)
        assert b'reason' in resp.data.lower()
        db.session.refresh(run)
        assert run.status == 'open'

    def test_granted_staff_is_still_refused_by_the_views_own_guard(
            self, client, db_session, main_branch, staff_user, accountant_user,
            wo_control_accounts):
        self._enable(db_session)
        bom, dept, comp = _setup(main_branch, accountant_user, 'L')
        run = _run(main_branch, bom, dept)
        staff_user.set_branches([main_branch])
        staff_user.set_book_permissions({'production_runs': True, 'bill_of_materials': True})
        db_session.commit()
        self._login(client, staff_user, main_branch)
        resp = client.post(f'/production-runs/{run.id}/cancel',
                           data={'cancel_reason': 'nope'}, follow_redirects=True)
        assert b'do not have permission to manage' in resp.data
        db.session.refresh(run)
        assert run.status == 'open'
