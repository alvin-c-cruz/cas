"""ProductionRun / ProductionRunMaterial models (R-07 Process Track slice P2).

The period-based process-costing counterpart to the Discrete track's WorkOrder.
Deliberately carries NO product_id: BillOfMaterial is strictly 1:1 with Product
since Wave 0, so the output product is derived via bom.product. Owner decision
2026-08-02, a knowing divergence from the arc spec's field list.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app import db
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialLine
from app.manufacturing_departments.models import ManufacturingDepartment
from app.production_runs.models import ProductionRun, ProductionRunMaterial
from app.products.models import Product

pytestmark = [pytest.mark.unit, pytest.mark.production_runs]


def _bom(code='P2-OUT'):
    out = Product(code=code, name='Dried Mango', is_active=True)
    comp = Product(code=code + '-C', name='Fresh Mango', track_inventory=True,
                   costing_method='moving_average', standard_cost=Decimal('5.00'),
                   is_active=True)
    db.session.add_all([out, comp]); db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='process')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id,
                                        quantity_per=Decimal('2')))
    db.session.add(bom); db.session.commit()
    return bom, out, comp


def _dept(branch, code='DRY'):
    d = ManufacturingDepartment(branch_id=branch.id, code=code, name='Dehydration')
    db.session.add(d); db.session.commit()
    return d


def _run(branch, bom, dept, **kw):
    kw.setdefault('run_number', '00001')
    kw.setdefault('period_start', date(2026, 8, 1))
    kw.setdefault('period_end', date(2026, 8, 31))
    run = ProductionRun(bom_id=bom.id, department_id=dept.id, branch_id=branch.id, **kw)
    db.session.add(run); db.session.commit()
    return run


def test_persists_with_expected_defaults(db_session, main_branch):
    bom, out, comp = _bom()
    run = _run(main_branch, bom, _dept(main_branch))
    assert run.id is not None
    assert run.status == 'open', "a new run defaults to 'open'"
    assert run.units_started == Decimal('0')
    assert run.units_completed_and_transferred == Decimal('0')
    assert run.units_ending_wip == Decimal('0')
    assert run.ending_wip_pct_complete is None
    assert run.row_version == 1, 'ProductionRun is RowVersioned'


def test_output_product_is_derived_not_stored(db_session, main_branch):
    """The divergence from the spec: no product_id column; derive through the BOM."""
    bom, out, comp = _bom(code='P2-DERIVE')
    run = _run(main_branch, bom, _dept(main_branch, code='D2'))
    assert not hasattr(run, 'product_id'), (
        'ProductionRun must NOT store product_id -- BOM is 1:1 with Product, so a stored '
        'copy is a second source of truth that can drift')
    assert run.output_product.id == out.id
    assert run.output_product.code == 'P2-DERIVE'


def test_to_dict_shape(db_session, main_branch):
    bom, out, comp = _bom(code='P2-DICT')
    dept = _dept(main_branch, code='D3')
    run = _run(main_branch, bom, dept, units_started=Decimal('100'))
    d = run.to_dict()
    assert d['run_number'] == '00001'
    assert d['status'] == 'open'
    assert d['department_id'] == dept.id
    assert d['units_started'] == 100.0
    assert d['output_product_code'] == 'P2-DICT'


@pytest.mark.parametrize('missing', ['bom_id', 'department_id', 'branch_id',
                                     'period_start', 'period_end'])
def test_required_columns(db_session, main_branch, missing):
    bom, out, comp = _bom(code='P2-REQ-' + missing[:4])
    dept = _dept(main_branch, code='R' + missing[:3])
    kwargs = dict(run_number='X1', bom_id=bom.id, department_id=dept.id,
                  branch_id=main_branch.id,
                  period_start=date(2026, 8, 1), period_end=date(2026, 8, 31))
    kwargs.pop(missing)
    db.session.add(ProductionRun(**kwargs))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_run_number_is_unique(db_session, main_branch):
    bom, out, comp = _bom(code='P2-UNIQ')
    dept = _dept(main_branch, code='D4')
    _run(main_branch, bom, dept, run_number='00007')
    db.session.add(ProductionRun(run_number='00007', bom_id=bom.id, department_id=dept.id,
                                 branch_id=main_branch.id, period_start=date(2026, 8, 1),
                                 period_end=date(2026, 8, 31)))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_material_snapshot_child(db_session, main_branch):
    bom, out, comp = _bom(code='P2-MAT')
    run = _run(main_branch, bom, _dept(main_branch, code='D5'))
    run.materials.append(ProductionRunMaterial(
        line_number=1, component_product_id=comp.id, quantity_required=Decimal('200')))
    db.session.commit()
    assert len(run.materials) == 1
    m = run.materials[0]
    assert m.quantity_required == Decimal('200')
    assert m.quantity_issued == Decimal('0'), 'nothing issued yet'
    assert m.to_dict()['component_code'] == 'P2-MAT-C'
