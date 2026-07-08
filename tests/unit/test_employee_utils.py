from app import db
from app.employees.models import Employee
from app.employees.utils import generate_next_employee_no
from app.branches.models import Branch


def _mk(no):
    b = Branch(code='MAIN', name='HO'); db.session.add(b); db.session.flush()
    db.session.add(Employee(employee_no=no, first_name='X', last_name='Y', branch_id=b.id))
    db.session.commit()


def test_first_code(db_session):
    assert generate_next_employee_no() == 'EMP-0001'


def test_sequences_by_numeric_suffix_past_9999(db_session):
    _mk('EMP-9999')
    assert generate_next_employee_no() == 'EMP-10000'


def test_ignores_non_conforming(db_session):
    _mk('LEGACY-1')
    assert generate_next_employee_no() == 'EMP-0001'
