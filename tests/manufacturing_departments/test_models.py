"""ManufacturingDepartment model (R-07 Process Track slice P1).

Process mode's cost-pool counterpart to WorkCenter. Deliberately has NO hourly_rate:
conversion cost is allocated to the department for a period via R-03a's
ExpenseAllocationRule driver, not an hourly rate -- see the arc design's Process Track
section and docs/superpowers/plans/2026-08-02-r07-p1-manufacturing-departments.md.
"""
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app import db
from app.manufacturing_departments.models import ManufacturingDepartment

pytestmark = [pytest.mark.unit]


def _dept(main_branch, code='DEPT-1', name='Dehydration', **kw):
    d = ManufacturingDepartment(branch_id=main_branch.id, code=code, name=name, **kw)
    db.session.add(d)
    db.session.commit()
    return d


def test_persists_and_defaults_active(db_session, main_branch):
    d = _dept(main_branch)
    assert d.id is not None
    assert d.branch_id == main_branch.id
    assert d.code == 'DEPT-1'
    assert d.name == 'Dehydration'
    assert d.is_active is True, 'is_active must default to True'
    assert d.created_at is not None
    assert d.updated_at is not None


def test_to_dict_shape(db_session, main_branch):
    d = _dept(main_branch, code='DEPT-2', name='Packing')
    assert d.to_dict() == {
        'id': d.id, 'branch_id': main_branch.id, 'code': 'DEPT-2',
        'name': 'Packing', 'is_active': True,
    }


def test_has_no_hourly_rate(db_session, main_branch):
    """Guards the one deliberate divergence from WorkCenter. If someone mirrors
    WorkCenter too literally later, this fails and points at the design decision."""
    d = _dept(main_branch, code='DEPT-3')
    assert not hasattr(d, 'hourly_rate'), (
        'ManufacturingDepartment must NOT carry hourly_rate -- process mode allocates '
        'conversion cost via ExpenseAllocationRule, not an hourly rate')


def test_branch_id_is_required(db_session, main_branch):
    d = ManufacturingDepartment(code='DEPT-4', name='No Branch')
    db.session.add(d)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_name_is_required(db_session, main_branch):
    d = ManufacturingDepartment(branch_id=main_branch.id, code='DEPT-5')
    db.session.add(d)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_repr_carries_code_and_name(db_session, main_branch):
    d = _dept(main_branch, code='DEPT-6', name='Blanching')
    assert 'DEPT-6' in repr(d) and 'Blanching' in repr(d)
