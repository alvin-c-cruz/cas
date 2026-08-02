"""Production Run module registration, open lifecycle and material issue
(R-07 Process Track slice P2, Tasks 3-4).
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialLine
from app.journal_entries.models import JournalEntry
from app.manufacturing_departments.models import ManufacturingDepartment
from app.production_runs.models import ProductionRun
from app.production_runs.service import issue_material, snapshot_materials
from app.products.models import Product
from app.settings import AppSettings
from app.stock_adjustments.service import post_movement
from app.utils.cache_helpers import clear_module_config_cache

pytestmark = [pytest.mark.integration, pytest.mark.production_runs]


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _enable(db_session, on=True):
    for key in ('bill_of_materials', 'production_runs'):
        AppSettings.set_setting(f'module_enabled:{key}', '1' if on else '0')
    db_session.commit()
    clear_module_config_cache()


def _bom(comp, code='PR-OUT', with_lines=True):
    out = Product(code=code, name='Dried Mango', is_active=True)
    db.session.add(out); db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='process')
    if with_lines:
        bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id,
                                            quantity_per=Decimal('2')))
    db.session.add(bom); db.session.commit()
    return bom


def _component(branch, actor, code='PR-C', qty='1000', cost='5.00'):
    comp = Product(code=code, name='Fresh Mango', track_inventory=True,
                   costing_method='moving_average', standard_cost=Decimal(cost), is_active=True)
    db.session.add(comp); db.session.commit()
    post_movement(comp, branch.id, 'opening', Decimal(qty), Decimal(cost),
                  'stock_adjustment', 0, 'seed', actor)
    db.session.commit()
    return comp


def _dept(branch, code='DRY'):
    d = ManufacturingDepartment(branch_id=branch.id, code=code, name='Dehydration')
    db.session.add(d); db.session.commit()
    return d


def _run(branch, bom, dept, units='50', number='00001', status='open'):
    run = ProductionRun(run_number=number, bom_id=bom.id, department_id=dept.id,
                        branch_id=branch.id, period_start=date(2026, 8, 1),
                        period_end=date(2026, 8, 31), units_started=Decimal(units),
                        status=status)
    db.session.add(run); db.session.commit()
    return run


class TestModuleRegistry:
    def test_registered_with_the_expected_shape(self):
        from app.users.module_access import MODULE_REGISTRY
        entry = next((m for m in MODULE_REGISTRY if m['key'] == 'production_runs'), None)
        assert entry is not None
        assert entry['optional'] is True
        assert entry['default_enabled'] is False
        assert entry['per_user'] is True
        assert entry['area'] == 'Manufacturing'
        assert entry['depends_on'] == ['bill_of_materials'], \
            'a run needs a BOM to snapshot'

    def test_endpoint_prefix_resolves_to_this_module(self):
        from app.users.module_access import module_key_for_endpoint
        assert module_key_for_endpoint('production_runs.list') == 'production_runs'


class TestModuleGating:
    def test_routes_404_when_disabled(self, client, db_session, accountant_user, main_branch):
        _enable(db_session, False)
        _login(client, accountant_user, main_branch)
        assert client.get('/production-runs').status_code == 404
        assert client.get('/production-runs/create').status_code == 404
        assert client.get('/production-runs/1').status_code == 404

    def test_list_reachable_when_enabled(self, client, db_session, accountant_user, main_branch):
        _enable(db_session)
        _login(client, accountant_user, main_branch)
        assert client.get('/production-runs').status_code == 200

    def test_sidebar_links_when_enabled(self, client, db_session, accountant_user, main_branch):
        _enable(db_session)
        _login(client, accountant_user, main_branch)
        assert b'href="/production-runs"' in client.get('/production-runs').data

    def test_sidebar_hidden_when_disabled(self, client, db_session, accountant_user, main_branch):
        _enable(db_session, False)
        _login(client, accountant_user, main_branch)
        assert b'href="/production-runs"' not in client.get('/dashboard').data


class TestOpenLifecycle:
    def test_snapshot_scales_by_units_started(self, db_session, main_branch, accountant_user):
        comp = _component(main_branch, accountant_user)
        run = _run(main_branch, _bom(comp), _dept(main_branch), units='50')
        snapshot_materials(run)
        db.session.commit()
        assert len(run.materials) == 1
        # 2 per unit x 50 units started
        assert run.materials[0].quantity_required == Decimal('100')
        assert run.materials[0].quantity_issued == Decimal('0')

    def test_open_is_blocked_when_the_bom_has_no_lines(self, db_session, main_branch, accountant_user):
        comp = _component(main_branch, accountant_user, code='PR-C2')
        run = _run(main_branch, _bom(comp, code='PR-EMPTY', with_lines=False),
                   _dept(main_branch, code='D2'))
        with pytest.raises(ValueError, match='no component lines'):
            snapshot_materials(run)

    def test_create_via_the_route_persists_and_audits(self, client, db_session, accountant_user,
                                                      main_branch):
        _enable(db_session)
        comp = _component(main_branch, accountant_user, code='PR-C3')
        bom = _bom(comp, code='PR-ROUTE')
        dept = _dept(main_branch, code='D3')
        _login(client, accountant_user, main_branch)
        resp = client.post('/production-runs/create', data={
            'bom_id': bom.id, 'department_id': dept.id, 'units_started': '50',
            'period_start': '2026-08-01', 'period_end': '2026-08-31',
        }, follow_redirects=True)
        assert resp.status_code == 200
        run = ProductionRun.query.filter_by(bom_id=bom.id).first()
        assert run is not None
        assert run.status == 'open'
        assert run.branch_id == main_branch.id, 'branch comes from the session'
        assert len(run.materials) == 1, 'BOM lines snapshotted at open'

        from app.audit.models import AuditLog
        assert AuditLog.query.filter_by(module='production_runs', record_id=run.id).first() \
            is not None

    def test_detail_rejects_another_branchs_run(self, client, db_session, accountant_user,
                                                main_branch, branch_manila):
        """Same branch-scope discipline as P1 -- do not reproduce
        BUG-BRANCH-SCOPED-MASTERS-EDIT-NOT-BRANCH-FILTERED."""
        _enable(db_session)
        comp = _component(main_branch, accountant_user, code='PR-C4')
        other = _run(branch_manila, _bom(comp, code='PR-OTHER'),
                     _dept(branch_manila, code='D4'), number='00099')
        _login(client, accountant_user, main_branch)
        assert client.get(f'/production-runs/{other.id}').status_code == 404


class TestMaterialIssue:
    def test_issue_posts_dr_wip_cr_inventory_and_tracks_issued(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        comp = _component(main_branch, accountant_user, code='PR-C5')
        run = _run(main_branch, _bom(comp, code='PR-ISSUE'), _dept(main_branch, code='D5'))
        snapshot_materials(run); db.session.commit()

        issue_material(run.materials[0], Decimal('100'), accountant_user)
        db.session.commit()

        assert run.materials[0].quantity_issued == Decimal('100')
        je = JournalEntry.query.filter_by(entry_type='manufacturing_consumption',
                                          reference=run.run_number).first()
        assert je is not None
        # 100 x 5.00 moving-average. Assert the LEGS against the document, not just
        # that it balances -- a residual leg would absorb a per-leg error silently.
        wip_code = AppSettings.get_setting('wip_account_code')
        inv_code = AppSettings.get_setting('inventory_account_code')
        legs = {(l.account.code, 'D' if l.debit_amount else 'C'):
                (l.debit_amount or l.credit_amount) for l in je.lines}
        assert legs[(wip_code, 'D')] == Decimal('500.00')
        assert legs[(inv_code, 'C')] == Decimal('500.00')

    def test_over_issue_is_refused(self, db_session, main_branch, accountant_user,
                                   wo_control_accounts):
        comp = _component(main_branch, accountant_user, code='PR-C6')
        run = _run(main_branch, _bom(comp, code='PR-OVER'), _dept(main_branch, code='D6'))
        snapshot_materials(run); db.session.commit()
        with pytest.raises(ValueError, match='only'):
            issue_material(run.materials[0], Decimal('101'), accountant_user)

    def test_issue_to_a_closed_run_is_refused(self, db_session, main_branch, accountant_user,
                                              wo_control_accounts):
        comp = _component(main_branch, accountant_user, code='PR-C7')
        run = _run(main_branch, _bom(comp, code='PR-CLOSED'), _dept(main_branch, code='D7'))
        snapshot_materials(run); db.session.commit()
        run.status = 'closed'; db.session.commit()
        with pytest.raises(ValueError, match='open Production Run'):
            issue_material(run.materials[0], Decimal('10'), accountant_user)

    def test_zero_or_negative_issue_is_refused(self, db_session, main_branch, accountant_user,
                                               wo_control_accounts):
        comp = _component(main_branch, accountant_user, code='PR-C8')
        run = _run(main_branch, _bom(comp, code='PR-ZERO'), _dept(main_branch, code='D8'))
        snapshot_materials(run); db.session.commit()
        with pytest.raises(ValueError, match='greater than zero'):
            issue_material(run.materials[0], Decimal('0'), accountant_user)


class TestRoleGuardIsReachable:
    """`_can_manage()` (app/production_runs/views.py:23) had NO coverage until
    2026-08-02 -- the P1 lesson was not carried into P2 hours later.

    The module gate masks the role guard: a staff user without the per-user grant is
    stopped by enforce_module_access before the view runs. Grant the module first,
    then assert the role guard still refuses. Covers BOTH guarded routes (create at
    :56, issue at :101). See memory feedback-outer-gate-masks-inner-guard.
    """

    def _staff_with_module(self, db_session, staff_user, main_branch):
        staff_user.set_branches([main_branch])
        staff_user.set_book_permissions({'production_runs': True})
        db_session.commit()

    def test_staff_without_the_grant_is_stopped_by_the_outer_module_gate(
            self, client, db_session, staff_user, main_branch):
        _enable(db_session)
        staff_user.set_branches([main_branch]); db_session.commit()
        _login(client, staff_user, main_branch)
        resp = client.post('/production-runs/create', data={}, follow_redirects=True)
        assert b'do not have access to this module' in resp.data

    def test_staff_with_the_grant_is_still_refused_at_create(
            self, client, db_session, staff_user, accountant_user, main_branch):
        _enable(db_session)
        comp = _component(main_branch, accountant_user, code='RG-C1')
        bom = _bom(comp, code='RG-B1'); dept = _dept(main_branch, code='RG1')
        self._staff_with_module(db_session, staff_user, main_branch)
        _login(client, staff_user, main_branch)
        resp = client.post('/production-runs/create', data={
            'bom_id': bom.id, 'department_id': dept.id, 'units_started': '10',
            'period_start': '2026-08-01', 'period_end': '2026-08-31',
        }, follow_redirects=True)
        assert b'do not have permission to manage' in resp.data
        assert ProductionRun.query.filter_by(bom_id=bom.id).first() is None

    def test_staff_with_the_grant_is_still_refused_at_material_issue(
            self, client, db_session, staff_user, accountant_user, main_branch,
            wo_control_accounts):
        """The second guarded route -- a fix that only covered create would leave
        material issue (which POSTS TO THE GL) unprotected and still green."""
        _enable(db_session)
        comp = _component(main_branch, accountant_user, code='RG-C2')
        run = _run(main_branch, _bom(comp, code='RG-B2'), _dept(main_branch, code='RG2'),
                   number='00900')
        snapshot_materials(run); db.session.commit()
        self._staff_with_module(db_session, staff_user, main_branch)
        _login(client, staff_user, main_branch)
        resp = client.post(
            f'/production-runs/{run.id}/materials/{run.materials[0].id}/issue',
            data={'quantity': '5'}, follow_redirects=True)
        assert b'do not have permission to manage' in resp.data
        db.session.refresh(run)
        assert run.materials[0].quantity_issued == Decimal('0'), 'nothing may post'
