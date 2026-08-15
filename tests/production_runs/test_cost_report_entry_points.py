"""P5 Task 6 -- the report must be REACHABLE from both entry points.

RENDER assertions on the GET, not route checks. Every route in
tests/reports/test_production_run_cost_report_routes.py reaches the report by URL
and stays green even if no link to it is ever rendered -- which is exactly how
BUG-D5-REPORT-PRINT-EXPORT-BUTTONS-MISSING shipped two whole deliverables that no
user could reach, with the suite green. P4 re-confirmed the same by mutation.

The list link is gated on `status == 'closed'`: the report refuses an open run, so
a link on an open row would point at a guaranteed redirect. A control that is
always going to fail is worse than no control.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialLine
from app.manufacturing_departments.models import ManufacturingDepartment
from app.production_runs.models import ProductionRun
from app.production_runs.service import cancel_run, close_run, issue_material, snapshot_materials
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


def _run(branch, actor, suffix, state='closed'):
    comp = Product(code=f'EP-C-{suffix}', name='Fresh Mango', track_inventory=True,
                   costing_method='moving_average', standard_cost=Decimal('5.00'),
                   is_active=True)
    out = Product(code=f'EP-O-{suffix}', name='Dried Mango', track_inventory=True,
                  costing_method='moving_average', is_active=True)
    db.session.add_all([comp, out]); db.session.commit()
    post_movement(comp, branch.id, 'opening', Decimal('10000'), Decimal('5.00'),
                  'stock_adjustment', 0, 'seed', actor, movement_date=date(2026, 1, 1))
    db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='process')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id,
                                        quantity_per=Decimal('2')))
    db.session.add(bom); db.session.commit()
    dept = ManufacturingDepartment(branch_id=branch.id, code=f'E{suffix}', name='Dehydration')
    db.session.add(dept); db.session.commit()
    _N[0] += 1
    run = ProductionRun(run_number='EP%04d' % _N[0], bom_id=bom.id, department_id=dept.id,
                        branch_id=branch.id, period_start=date(2026, 8, 1),
                        period_end=date(2026, 8, 31), units_started=Decimal('100'),
                        conversion_cost=Decimal('450.00'),
                        units_completed_and_transferred=Decimal('80'),
                        units_ending_wip=Decimal('20'),
                        ending_wip_pct_complete=Decimal('50'))
    db.session.add(run); db.session.commit()
    snapshot_materials(run); db.session.commit()
    issue_material(run.materials[0], Decimal('200'), actor); db.session.commit()
    if state == 'closed':
        close_run(run, actor); db.session.commit()
    elif state == 'cancelled':
        cancel_run(run, 'Spoiled', actor); db.session.commit()
    return run


def _report_href(run):
    return f'/reports/production-run-cost/{run.id}'


class TestFromTheRunDetail:
    def test_a_closed_run_links_to_its_report(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        _enable(db_session)
        run = _run(main_branch, accountant_user, 'A')
        _login(client, accountant_user, main_branch)
        body = client.get(f'/production-runs/{run.id}').data.decode('utf-8')
        assert _report_href(run) in body, 'no link from the run to its own cost report'

    def test_an_OPEN_run_does_not(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        """The report refuses an open run, so a link here would be a dead end."""
        _enable(db_session)
        run = _run(main_branch, accountant_user, 'B', state='open')
        _login(client, accountant_user, main_branch)
        body = client.get(f'/production-runs/{run.id}').data.decode('utf-8')
        assert _report_href(run) not in body

    def test_a_CANCELLED_run_does_not(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        _enable(db_session)
        run = _run(main_branch, accountant_user, 'C', state='cancelled')
        _login(client, accountant_user, main_branch)
        body = client.get(f'/production-runs/{run.id}').data.decode('utf-8')
        assert _report_href(run) not in body


class TestFromTheRunList:
    def test_a_closed_row_links_to_its_report(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        _enable(db_session)
        run = _run(main_branch, accountant_user, 'D')
        _login(client, accountant_user, main_branch)
        body = client.get('/production-runs').data.decode('utf-8')
        assert _report_href(run) in body, 'no per-row link on the list'

    def test_an_open_row_does_not(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        _enable(db_session)
        run = _run(main_branch, accountant_user, 'E', state='open')
        _login(client, accountant_user, main_branch)
        body = client.get('/production-runs').data.decode('utf-8')
        assert _report_href(run) not in body

    def test_the_row_still_has_its_View_link(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        """Adding the report link must not displace the existing one."""
        _enable(db_session)
        run = _run(main_branch, accountant_user, 'F')
        _login(client, accountant_user, main_branch)
        body = client.get('/production-runs').data.decode('utf-8')
        assert f'/production-runs/{run.id}"' in body


class TestStaffSeesNeither:
    def test_a_granted_staff_user_gets_no_report_link_on_either_surface(
            self, client, db_session, main_branch, staff_user, accountant_user,
            wo_control_accounts):
        """The report is accountant-or-above, so the template guard must match the
        route's -- otherwise the link 403s, or the route has no UI path at all."""
        _enable(db_session)
        run = _run(main_branch, accountant_user, 'G')
        staff_user.set_branches([main_branch])
        staff_user.set_book_permissions({'production_runs': True, 'bill_of_materials': True})
        db_session.commit()
        _login(client, staff_user, main_branch)
        assert _report_href(run) not in client.get('/production-runs').data.decode('utf-8')
        assert _report_href(run) not in client.get(
            f'/production-runs/{run.id}').data.decode('utf-8')
