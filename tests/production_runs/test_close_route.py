"""P4 Task 5 -- the close route and its confirm screen.

Two guarded routes, GET (confirm) and POST (do it). Both authorization layers are
tested on each: `enforce_module_access` stops an ungranted user FIRST, so a test
that only exercises the outer gate leaves the view's own `_can_manage()` with zero
coverage -- the P1 lesson (memory feedback-outer-gate-masks-inner-guard).

The confirm screen is an HTML page, never a JS confirm() (project convention).
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialLine
from app.manufacturing_departments.models import ManufacturingDepartment
from app.production_runs.models import ProductionRun
from app.production_runs.service import issue_material, snapshot_materials
from app.products.models import Product
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


def _ready_run(branch, actor, suffix):
    """An open run with 200 material issued, 450 conversion, 80 done / 20 half."""
    _N[0] += 1
    comp = Product(code=f'CR-C-{suffix}', name='Fresh Mango', track_inventory=True,
                   costing_method='moving_average', standard_cost=Decimal('5.00'),
                   is_active=True)
    out = Product(code=f'CR-O-{suffix}', name='Dried Mango', track_inventory=True,
                  costing_method='moving_average', is_active=True)
    db.session.add_all([comp, out]); db.session.commit()
    post_movement(comp, branch.id, 'opening', Decimal('10000'), Decimal('5.00'),
                  'stock_adjustment', 0, 'seed', actor)
    db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='process')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id,
                                        quantity_per=Decimal('2')))
    db.session.add(bom); db.session.commit()
    dept = ManufacturingDepartment(branch_id=branch.id, code=f'X{suffix}', name='Dehydration')
    db.session.add(dept); db.session.commit()
    run = ProductionRun(run_number='CR%04d' % _N[0], bom_id=bom.id, department_id=dept.id,
                        branch_id=branch.id, period_start=date(2026, 8, 1),
                        period_end=date(2026, 8, 31), units_started=Decimal('100'),
                        conversion_cost=Decimal('450.00'),
                        units_completed_and_transferred=Decimal('80'),
                        units_ending_wip=Decimal('20'),
                        ending_wip_pct_complete=Decimal('50'))
    db.session.add(run); db.session.commit()
    snapshot_materials(run); db.session.commit()
    issue_material(run.materials[0], Decimal('200'), actor); db.session.commit()
    return run


class TestConfirmScreen:
    def test_shows_what_will_be_posted_before_committing_to_it(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        _enable(db_session)
        run = _ready_run(main_branch, accountant_user, 'A')
        _login(client, accountant_user, main_branch)
        resp = client.get(f'/production-runs/{run.id}/close')
        assert resp.status_code == 200
        body = resp.data.decode('utf-8')
        assert '80.0000' in body, 'units to transfer'
        assert '16.11' in body, 'cost per equivalent unit'
        assert '1288.80' in body, 'amount posted to finished goods'
        assert '161.20' in body, 'what stays in WIP'

    def test_the_confirm_screen_does_not_itself_close_the_run(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        """A GET must never mutate -- otherwise a crawler or a prefetch closes a period."""
        _enable(db_session)
        run = _ready_run(main_branch, accountant_user, 'B')
        _login(client, accountant_user, main_branch)
        client.get(f'/production-runs/{run.id}/close')
        db.session.refresh(run)
        assert run.status == 'open'

    def test_uses_an_html_form_not_a_js_confirm(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        _enable(db_session)
        run = _ready_run(main_branch, accountant_user, 'C')
        _login(client, accountant_user, main_branch)
        body = client.get(f'/production-runs/{run.id}/close').data.decode('utf-8')
        assert 'confirm(' not in body
        assert f'action="/production-runs/{run.id}/close"' in body
        assert 'name="csrf_token"' in body

    def test_a_closed_run_cannot_reach_the_confirm_screen(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        _enable(db_session)
        run = _ready_run(main_branch, accountant_user, 'D')
        _login(client, accountant_user, main_branch)
        client.post(f'/production-runs/{run.id}/close', follow_redirects=True)
        resp = client.get(f'/production-runs/{run.id}/close', follow_redirects=True)
        assert b'Only an open Production Run can be closed' in resp.data


class TestClosePost:
    def test_closes_and_redirects_to_the_detail(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        _enable(db_session)
        run = _ready_run(main_branch, accountant_user, 'E')
        _login(client, accountant_user, main_branch)
        resp = client.post(f'/production-runs/{run.id}/close', follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(run)
        assert run.status == 'closed'
        assert run.transferred_unit_cost == Decimal('16.11')
        assert run.ending_wip_cost == Decimal('161.20')

    def test_records_an_audit_entry(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        from app.audit.models import AuditLog
        _enable(db_session)
        run = _ready_run(main_branch, accountant_user, 'F')
        _login(client, accountant_user, main_branch)
        client.post(f'/production-runs/{run.id}/close', follow_redirects=True)
        entry = AuditLog.query.filter_by(module='production_runs', action='close',
                                         record_identifier=run.run_number).first()
        assert entry is not None, 'closing a period must be auditable'
        assert entry.user_id == accountant_user.id

    def test_a_refused_close_leaves_nothing_behind(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        """Nothing reported -> the service raises -> no JE, no partial state."""
        from app.journal_entries.models import JournalEntry
        _enable(db_session)
        run = _ready_run(main_branch, accountant_user, 'G')
        run.units_completed_and_transferred = Decimal('0')
        run.units_ending_wip = Decimal('0')
        db.session.commit()
        before = JournalEntry.query.count()
        _login(client, accountant_user, main_branch)
        resp = client.post(f'/production-runs/{run.id}/close', follow_redirects=True)
        assert b'nothing to close' in resp.data
        db.session.refresh(run)
        assert run.status == 'open'
        assert JournalEntry.query.count() == before


class TestAuthorization:
    """Both layers, on both routes."""

    def _staff_with_module(self, db_session, staff_user, branch):
        staff_user.set_branches([branch])
        staff_user.set_book_permissions({'production_runs': True, 'bill_of_materials': True})
        db_session.commit()

    def test_ungranted_staff_stopped_by_the_outer_module_gate_on_get(
            self, client, db_session, main_branch, staff_user, accountant_user,
            wo_control_accounts):
        _enable(db_session)
        run = _ready_run(main_branch, accountant_user, 'H')
        staff_user.set_branches([main_branch]); db_session.commit()
        _login(client, staff_user, main_branch)
        resp = client.get(f'/production-runs/{run.id}/close', follow_redirects=True)
        assert b'do not have access to this module' in resp.data

    def test_granted_staff_still_refused_by_the_views_own_guard_on_get(
            self, client, db_session, main_branch, staff_user, accountant_user,
            wo_control_accounts):
        """Past the outer gate, so this is the ONLY test that can see _can_manage()."""
        _enable(db_session)
        run = _ready_run(main_branch, accountant_user, 'I')
        self._staff_with_module(db_session, staff_user, main_branch)
        _login(client, staff_user, main_branch)
        resp = client.get(f'/production-runs/{run.id}/close', follow_redirects=True)
        assert b'do not have permission to manage' in resp.data

    def test_granted_staff_still_refused_on_post_and_the_run_stays_open(
            self, client, db_session, main_branch, staff_user, accountant_user,
            wo_control_accounts):
        """The route that POSTS TO THE GL -- a fix covering only GET would leave this
        one open and still green."""
        _enable(db_session)
        run = _ready_run(main_branch, accountant_user, 'J')
        self._staff_with_module(db_session, staff_user, main_branch)
        _login(client, staff_user, main_branch)
        resp = client.post(f'/production-runs/{run.id}/close', follow_redirects=True)
        assert b'do not have permission to manage' in resp.data
        db.session.refresh(run)
        assert run.status == 'open'

    def test_another_branchs_run_is_not_closable(
            self, client, db_session, main_branch, branch_manila, accountant_user,
            wo_control_accounts):
        _enable(db_session)
        run = _ready_run(main_branch, accountant_user, 'K')
        accountant_user.set_branches([main_branch, branch_manila]); db_session.commit()
        _login(client, accountant_user, branch_manila)
        resp = client.post(f'/production-runs/{run.id}/close')
        assert resp.status_code == 404
        db.session.refresh(run)
        assert run.status == 'open'
