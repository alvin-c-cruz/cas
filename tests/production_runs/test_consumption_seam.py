"""consume_materials() must accept a ProductionRun (R-07 Process Track slice P2).

Its docstring already CLAIMED a ProductionRun "will call this unchanged (dispatch is
by isinstance, not a hardcoded WorkOrder assumption)". That was not true:
`_source_document_type()` raised ValueError for any non-WorkOrder, and the JE
description was hardcoded `f'Work Order {reference} material consumption'`. A
docstring promising future compatibility is not evidence of it.

This is a SHARED posting path -- the Discrete track calls it too -- so the WorkOrder
side is asserted unchanged alongside the new ProductionRun support.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialLine
from app.bill_of_materials.service import consume_materials
from app.journal_entries.models import JournalEntry
from app.manufacturing_departments.models import ManufacturingDepartment
from app.production_runs.models import ProductionRun, ProductionRunMaterial
from app.products.models import Product
from app.stock_adjustments.service import post_movement

pytestmark = [pytest.mark.integration, pytest.mark.production_runs]


def _component(branch, actor, code='SEAM-C', qty='1000', cost='5.00'):
    comp = Product(code=code, name='Fresh Mango', track_inventory=True,
                   costing_method='moving_average', standard_cost=Decimal(cost), is_active=True)
    db.session.add(comp); db.session.commit()
    post_movement(comp, branch.id, 'opening', Decimal(qty), Decimal(cost),
                  'stock_adjustment', 0, 'seed', actor, movement_date=date(2026, 1, 1))
    db.session.commit()
    return comp


def _run(branch, actor, comp, code='SEAM-OUT', run_number='00001'):
    out = Product(code=code, name='Dried Mango', is_active=True)
    db.session.add(out); db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='process')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id,
                                        quantity_per=Decimal('2')))
    db.session.add(bom); db.session.commit()
    dept = ManufacturingDepartment(branch_id=branch.id, code='DRY', name='Dehydration')
    db.session.add(dept); db.session.commit()
    run = ProductionRun(run_number=run_number, bom_id=bom.id, department_id=dept.id,
                        branch_id=branch.id, period_start=date(2026, 8, 1),
                        period_end=date(2026, 8, 31), units_started=Decimal('50'))
    db.session.add(run); db.session.commit()
    run.materials.append(ProductionRunMaterial(
        line_number=1, component_product_id=comp.id, quantity_required=Decimal('100')))
    db.session.commit()
    return run


def test_production_run_consumption_posts_its_own_je(
        db_session, main_branch, accountant_user, wo_control_accounts):
    comp = _component(main_branch, accountant_user)
    run = _run(main_branch, accountant_user, comp)

    consume_materials(run, [(run.materials[0], Decimal('100'))], accountant_user)
    db.session.commit()

    jes = JournalEntry.query.filter_by(entry_type='manufacturing_consumption',
                                       reference=run.run_number).all()
    assert len(jes) == 1, 'exactly one consumption JE for the run'
    je = jes[0]
    assert 'Production Run' in je.description, (
        'the JE description must name a Production Run, not a Work Order -- it was '
        'hardcoded to "Work Order" before P2')
    assert run.run_number in je.description

    # 100 units x 5.00 moving-average = 500.00, Dr WIP / Cr Inventory
    assert je.total_debit == Decimal('500.00')
    assert je.total_credit == Decimal('500.00')
    assert je.is_balanced


def test_movement_is_tagged_as_a_production_run_not_a_work_order(
        db_session, main_branch, accountant_user, wo_control_accounts):
    """source_document_type also feeds post_movement, so a wrong dispatch would
    file the stock movement under 'work_order' and point its id at a WO that does
    not exist."""
    from app.stock_adjustments.models import StockMovement
    comp = _component(main_branch, accountant_user, code='SEAM-C2')
    run = _run(main_branch, accountant_user, comp, code='SEAM-OUT2', run_number='00002')

    consume_materials(run, [(run.materials[0], Decimal('20'))], accountant_user)
    db.session.commit()

    mv = (StockMovement.query
          .filter_by(source_document_type='production_run', source_document_id=run.id)
          .first())
    assert mv is not None, "the movement must be filed under 'production_run'"
    assert mv.quantity == Decimal('-20')


def test_work_order_description_is_unchanged(
        db_session, main_branch, accountant_user, wo_control_accounts):
    """Regression guard on the shared path: the Discrete track's wording and
    dispatch must be byte-identical after P2's edit."""
    from app.work_orders.models import WorkOrder
    from app.work_orders.forms import generate_wo_number
    from app.work_orders.service import release_work_order, issue_material

    comp = _component(main_branch, accountant_user, code='SEAM-C3')
    out = Product(code='SEAM-WO', name='Widget', is_active=True)
    db.session.add(out); db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='discrete')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id,
                                        quantity_per=Decimal('1')))
    db.session.add(bom); db.session.commit()
    wo = WorkOrder(wo_number=generate_wo_number(), bom_id=bom.id,
                   branch_id=main_branch.id, qty_to_produce=Decimal('10'))
    db.session.add(wo); db.session.commit()
    release_work_order(wo, None); db.session.commit()
    issue_material(wo.materials[0], Decimal('10'), accountant_user)
    db.session.commit()

    je = JournalEntry.query.filter_by(entry_type='manufacturing_consumption',
                                      reference=wo.wo_number).first()
    assert je is not None
    assert je.description == f'Work Order {wo.wo_number} material consumption'


def test_unsupported_source_document_still_fails_closed(
        db_session, main_branch, accountant_user, wo_control_accounts):
    """Extending the dispatch must not turn it into a catch-all."""
    from app.bill_of_materials.service import _source_document_type
    with pytest.raises(ValueError, match='unsupported source_document type'):
        _source_document_type(object())
