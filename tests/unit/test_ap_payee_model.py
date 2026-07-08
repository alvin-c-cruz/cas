from datetime import date
from decimal import Decimal
from app import db
from app.accounts_payable.models import AccountsPayable


def _ap(**over):
    base = dict(ap_number='AP-X-1', ap_date=date(2026, 6, 30), due_date=date(2026, 7, 30),
                vendor_name='X', notes='n', payee_type='vendor', payee_id=1, vendor_id=1)
    base.update(over)
    return AccountsPayable(**base)


def test_employee_payee_has_null_vendor_id(db_session):
    ap = _ap(ap_number='AP-X-2', payee_type='employee', payee_id=5, vendor_id=None)
    db.session.add(ap); db.session.commit()
    assert ap.vendor_id is None
    assert ap.payee_type == 'employee' and ap.payee_id == 5


def test_payee_type_default_vendor(db_session):
    ap = AccountsPayable(ap_number='AP-X-3', ap_date=date(2026, 6, 30), due_date=date(2026, 7, 30),
                         vendor_name='X', notes='n', payee_id=1, vendor_id=1)
    db.session.add(ap); db.session.commit()
    assert ap.payee_type == 'vendor'
