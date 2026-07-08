import pytest
from app import db
from app.employees.models import Employee
from app.branches.models import Branch


def _branch():
    b = Branch(code='MAIN', name='Head Office')
    db.session.add(b); db.session.commit()
    return b


def test_employee_minimal_create(db_session):
    b = _branch()
    e = Employee(employee_no='EMP-0001', first_name='Alvin', last_name='Cruz', branch_id=b.id)
    db.session.add(e); db.session.commit()
    assert e.id is not None
    assert e.is_active is True                 # default
    assert e.qualified_dependents == 0         # default
    assert e.is_minimum_wage is False          # default


def test_full_name_collapses_blank_middle(db_session):
    b = _branch()
    e = Employee(employee_no='EMP-0002', first_name='Maria', middle_name=None,
                 last_name='Santos', branch_id=b.id)
    db.session.add(e); db.session.commit()
    assert e.full_name == 'Maria Santos'


def test_employee_no_unique(db_session):
    b = _branch()
    db.session.add(Employee(employee_no='EMP-0003', first_name='A', last_name='B', branch_id=b.id))
    db.session.commit()
    db.session.add(Employee(employee_no='EMP-0003', first_name='C', last_name='D', branch_id=b.id))
    with pytest.raises(Exception):
        db.session.commit()
    db.session.rollback()


def test_to_dict_is_columns_only(db_session):
    b = _branch()
    e = Employee(employee_no='EMP-0004', first_name='A', last_name='B', branch_id=b.id, user_id=None)
    db.session.add(e); db.session.commit()
    d = e.to_dict()
    assert d['employee_no'] == 'EMP-0004'
    assert d['user_id'] is None
    assert 'branch' not in d                    # no relationship reads
