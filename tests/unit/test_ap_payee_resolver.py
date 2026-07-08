from datetime import date
from app import db
from app.accounts_payable.models import AccountsPayable
from app.employees.models import Employee
from app.vendors.models import Vendor
from app.branches.models import Branch


def test_payee_resolves_vendor(db_session):
    v = Vendor(code='V001', name='Anthropic'); db.session.add(v); db.session.commit()
    ap = AccountsPayable(ap_number='AP-R-1', ap_date=date(2026, 6, 1), due_date=date(2026, 7, 1),
                         vendor_name='Anthropic', notes='n', payee_type='vendor', payee_id=v.id, vendor_id=v.id)
    db.session.add(ap); db.session.commit()
    assert ap.payee.id == v.id
    assert ap.to_dict()['payee_name'] == 'Anthropic'


def test_payee_resolves_employee(db_session):
    b = Branch(code='MAIN', name='HO'); db.session.add(b); db.session.commit()
    e = Employee(employee_no='EMP-0001', first_name='Alvin', last_name='Cruz', branch_id=b.id)
    db.session.add(e); db.session.commit()
    ap = AccountsPayable(ap_number='AP-R-2', ap_date=date(2026, 6, 1), due_date=date(2026, 7, 1),
                         vendor_name='Alvin Cruz', notes='n', payee_type='employee', payee_id=e.id, vendor_id=None)
    db.session.add(ap); db.session.commit()
    assert ap.payee.id == e.id
    assert ap.to_dict()['payee_name'] == 'Alvin Cruz'
    assert ap.vendor is None
