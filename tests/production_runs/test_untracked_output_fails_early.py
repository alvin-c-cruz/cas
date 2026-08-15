"""P5 Task 8 -- an untracked output product must fail at run CREATION, not at close.

BUG-PRODUCTION-RUN-UNTRACKED-OUTPUT-FAILS-ONLY-AT-CLOSE. Closing correctly refuses
to transfer completed units into a product that has nowhere to receive them, but
that refusal arrived after a whole period of work -- material issued, real
consumption JEs posted into WIP that then could not be relieved through the normal
path. The guard was right; the failure POINT was wrong.

Fixed by filtering the create form's BOM picker: an unselectable option cannot be
chosen by mistake. The POST is validated too, since a stale form or a hand-made
request would otherwise slip past a client-side-only narrowing.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialLine
from app.manufacturing_departments.models import ManufacturingDepartment
from app.production_runs.models import ProductionRun
from app.products.models import Product

pytestmark = [pytest.mark.integration, pytest.mark.production_runs]


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


def _bom(suffix, tracked_output):
    comp = Product(code=f'UT-C-{suffix}', name='Fresh Mango', track_inventory=True,
                   costing_method='moving_average', standard_cost=Decimal('5.00'),
                   is_active=True)
    out = Product(code=f'UT-O-{suffix}', name='Dried Mango',
                  track_inventory=tracked_output,
                  costing_method='moving_average' if tracked_output else None,
                  is_active=True)
    db.session.add_all([comp, out]); db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='process')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id,
                                        quantity_per=Decimal('2')))
    db.session.add(bom); db.session.commit()
    return bom


def _dept(branch, code):
    d = ManufacturingDepartment(branch_id=branch.id, code=code, name='Dehydration')
    db.session.add(d); db.session.commit()
    return d


class TestThePickerHidesIt:
    def test_a_bom_with_an_untracked_output_is_not_offered(
            self, client, db_session, main_branch, accountant_user):
        _enable(db_session)
        good = _bom('A1', tracked_output=True)
        bad = _bom('A2', tracked_output=False)
        _dept(main_branch, 'UA')
        _login(client, accountant_user, main_branch)
        body = client.get('/production-runs/create').data.decode('utf-8')
        assert 'UT-O-A1' in body, 'the valid BOM must still be offered'
        assert 'UT-O-A2' not in body, 'an untracked output must not be selectable'


class TestThePostIsValidatedToo:
    def test_posting_an_untracked_output_is_refused(
            self, client, db_session, main_branch, accountant_user):
        """A narrowed picker is not a guard on its own -- a stale form or a
        hand-made request would otherwise slip straight past it."""
        _enable(db_session)
        bad = _bom('B1', tracked_output=False)
        dept = _dept(main_branch, 'UB')
        _login(client, accountant_user, main_branch)
        resp = client.post('/production-runs/create', data={
            'bom_id': str(bad.id), 'department_id': str(dept.id), 'units_started': '100',
            'period_start': '2026-08-01', 'period_end': '2026-08-31',
        }, follow_redirects=True)
        # Asserts the SECURITY property (no run exists), not a particular message.
        # Narrowing the picker means WTForms' own choice validation rejects this id
        # first, so the view's explicit check is defence in depth rather than the
        # primary guard -- and pinning its wording here would test the wrong layer.
        assert resp.status_code == 200
        assert ProductionRun.query.filter_by(bom_id=bad.id).first() is None, \
            'a run was created against an untracked output product'

    def test_a_tracked_output_still_creates_normally(
            self, client, db_session, main_branch, accountant_user):
        _enable(db_session)
        good = _bom('C1', tracked_output=True)
        dept = _dept(main_branch, 'UC')
        _login(client, accountant_user, main_branch)
        resp = client.post('/production-runs/create', data={
            'bom_id': str(good.id), 'department_id': str(dept.id), 'units_started': '100',
            'period_start': '2026-08-01', 'period_end': '2026-08-31',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert ProductionRun.query.filter_by(bom_id=good.id).first() is not None


class TestTheClosePreviewSharesOneCalculation:
    """The close confirm screen used to recompute the transfer amount independently
    of close_run(). Both were pinned to the same constants by separate tests, but
    nothing asserted the PREVIEW equals what is POSTED -- so a formula change could
    make the screen promise one number and the ledger record another."""

    def test_the_preview_matches_what_close_actually_posts(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts):
        from app.production_runs.service import (close_run, issue_material,
                                                 snapshot_materials)
        from app.stock_adjustments.service import post_movement
        _enable(db_session)
        bom = _bom('D1', tracked_output=True)
        # Seed the COMPONENT's stock. Without it the moving average is 0.00, the pool
        # is conversion-only, and the worked figures below never arise -- the test
        # would be measuring an empty warehouse rather than the shared calculation.
        post_movement(bom.lines[0].component_product, main_branch.id, 'opening',
                      Decimal('10000'), Decimal('5.00'), 'stock_adjustment', 0,
                      'seed', accountant_user, movement_date=date(2026, 1, 1))
        db.session.commit()
        dept = _dept(main_branch, 'UD')
        run = ProductionRun(run_number='UT0001', bom_id=bom.id, department_id=dept.id,
                            branch_id=main_branch.id, period_start=date(2026, 8, 1),
                            period_end=date(2026, 8, 31), units_started=Decimal('100'),
                            conversion_cost=Decimal('450.00'),
                            units_completed_and_transferred=Decimal('80'),
                            units_ending_wip=Decimal('20'),
                            ending_wip_pct_complete=Decimal('50'))
        db.session.add(run); db.session.commit()
        snapshot_materials(run); db.session.commit()
        issue_material(run.materials[0], Decimal('200'), accountant_user); db.session.commit()

        _login(client, accountant_user, main_branch)
        preview = client.get(f'/production-runs/{run.id}/close').data.decode('utf-8')
        assert '1288.80' in preview and '161.20' in preview

        close_run(run, accountant_user); db.session.commit()
        posted = (run.units_completed_and_transferred * run.transferred_unit_cost).quantize(
            Decimal('0.01'))
        assert posted == Decimal('1288.80'), 'the preview promised a different number'
        assert run.ending_wip_cost == Decimal('161.20')
