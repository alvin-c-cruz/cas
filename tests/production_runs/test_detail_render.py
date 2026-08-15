"""P4 Task 7 -- the detail page renders the close/cancel surface.

RENDER assertions on the GET, not route-reachability checks. A route GET proves a
page works; it does not prove a real user can REACH it. Every P4 route is already
covered by its own test posting to the URL directly -- those stay green even if the
button that leads there is never rendered, which is exactly how
BUG-D5-REPORT-PRINT-EXPORT-BUTTONS-MISSING shipped: the whole deliverable was
unreachable and the suite was green.
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


def _run_with_results(branch, actor, suffix, **run_kw):
    _N[0] += 1
    comp = Product(code=f'DR-C-{suffix}', name='Fresh Mango', track_inventory=True,
                   costing_method='moving_average', standard_cost=Decimal('5.00'),
                   is_active=True)
    out = Product(code=f'DR-O-{suffix}', name='Dried Mango', track_inventory=True,
                  costing_method='moving_average', is_active=True)
    db.session.add_all([comp, out]); db.session.commit()
    post_movement(comp, branch.id, 'opening', Decimal('10000'), Decimal('5.00'),
                  'stock_adjustment', 0, 'seed', actor, movement_date=date(2026, 1, 1))
    db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='process')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id,
                                        quantity_per=Decimal('2')))
    db.session.add(bom); db.session.commit()
    dept = ManufacturingDepartment(branch_id=branch.id, code=f'R{suffix}', name='Dehydration')
    db.session.add(dept); db.session.commit()
    kw = dict(conversion_cost=Decimal('450.00'),
              units_completed_and_transferred=Decimal('80'),
              units_ending_wip=Decimal('20'),
              ending_wip_pct_complete=Decimal('50'))
    kw.update(run_kw)
    run = ProductionRun(run_number='DR%04d' % _N[0], bom_id=bom.id, department_id=dept.id,
                        branch_id=branch.id, period_start=date(2026, 8, 1),
                        period_end=date(2026, 8, 31), units_started=Decimal('100'), **kw)
    db.session.add(run); db.session.commit()
    snapshot_materials(run); db.session.commit()
    issue_material(run.materials[0], Decimal('200'), actor); db.session.commit()
    return run


class TestOpenRunControls:
    def test_close_and_cancel_are_REACHABLE_from_the_page(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        _enable(db_session)
        run = _run_with_results(main_branch, accountant_user, 'A')
        _login(client, accountant_user, main_branch)
        body = client.get(f'/production-runs/{run.id}').data.decode('utf-8')
        assert f'/production-runs/{run.id}/close' in body, 'no link to the close screen'
        assert f'/production-runs/{run.id}/cancel' in body, 'no cancel control'

    def test_beginning_wip_rows_render(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        _enable(db_session)
        run = _run_with_results(main_branch, accountant_user, 'B',
                                beginning_wip_units=Decimal('20'),
                                beginning_wip_cost=Decimal('225.00'))
        _login(client, accountant_user, main_branch)
        body = client.get(f'/production-runs/{run.id}').data.decode('utf-8')
        assert 'Beginning WIP' in body
        assert '225.00' in body
        assert 'Total Cost Pool' in body, 'the total is a POOL now, not just this period'

    def test_cancel_uses_an_html_form_with_a_reason_not_a_js_confirm(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        _enable(db_session)
        run = _run_with_results(main_branch, accountant_user, 'C')
        _login(client, accountant_user, main_branch)
        body = client.get(f'/production-runs/{run.id}').data.decode('utf-8')
        assert 'confirm(' not in body
        assert 'name="cancel_reason"' in body


class TestClosedRunIsReadOnly:
    def test_no_issue_control_once_closed(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        _enable(db_session)
        run = _run_with_results(main_branch, accountant_user, 'D')
        close_run(run, accountant_user); db.session.commit()
        _login(client, accountant_user, main_branch)
        body = client.get(f'/production-runs/{run.id}').data.decode('utf-8')
        assert '/materials/' not in body, 'a closed run must accept no further material'

    def test_no_close_or_cancel_control_once_closed(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        _enable(db_session)
        run = _run_with_results(main_branch, accountant_user, 'E')
        close_run(run, accountant_user); db.session.commit()
        _login(client, accountant_user, main_branch)
        body = client.get(f'/production-runs/{run.id}').data.decode('utf-8')
        assert f'/production-runs/{run.id}/close' not in body
        assert f'/production-runs/{run.id}/cancel' not in body

    def test_no_period_results_form_once_closed(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        _enable(db_session)
        run = _run_with_results(main_branch, accountant_user, 'F')
        close_run(run, accountant_user); db.session.commit()
        _login(client, accountant_user, main_branch)
        body = client.get(f'/production-runs/{run.id}').data.decode('utf-8')
        assert f'/production-runs/{run.id}/period' not in body

    def test_shows_the_frozen_close_summary(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        _enable(db_session)
        run = _run_with_results(main_branch, accountant_user, 'G')
        close_run(run, accountant_user); db.session.commit()
        _login(client, accountant_user, main_branch)
        body = client.get(f'/production-runs/{run.id}').data.decode('utf-8')
        assert '16.11' in body, 'the frozen transferred unit cost'
        assert '1288.80' in body, 'the amount posted to finished goods'
        assert '161.20' in body, 'what carried forward'


class TestCancelledRun:
    def test_shows_the_reason_and_offers_no_actions(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        from app.production_runs.service import cancel_run
        _enable(db_session)
        run = _run_with_results(main_branch, accountant_user, 'H')
        cancel_run(run, 'Batch spoiled in the dryer', accountant_user)
        db.session.commit()
        _login(client, accountant_user, main_branch)
        body = client.get(f'/production-runs/{run.id}').data.decode('utf-8')
        assert 'Batch spoiled in the dryer' in body
        assert f'/production-runs/{run.id}/close' not in body
        assert f'/production-runs/{run.id}/cancel' not in body


class TestStaffCannotSeeWriteControls:
    def test_a_granted_staff_user_sees_no_close_or_cancel_control(
            self, client, db_session, main_branch, staff_user, accountant_user,
            wo_control_accounts):
        """The template's guard must match the view's. Loosening or tightening one
        without the other leaves a control that 403s, or a route with no UI path."""
        _enable(db_session)
        run = _run_with_results(main_branch, accountant_user, 'I')
        staff_user.set_branches([main_branch])
        staff_user.set_book_permissions({'production_runs': True, 'bill_of_materials': True})
        db_session.commit()
        _login(client, staff_user, main_branch)
        body = client.get(f'/production-runs/{run.id}').data.decode('utf-8')
        assert f'/production-runs/{run.id}/close' not in body
        assert f'/production-runs/{run.id}/cancel' not in body
