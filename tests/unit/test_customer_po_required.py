import pytest
from app import db
from app.customers.models import Customer

pytestmark = [pytest.mark.integration, pytest.mark.customers]


def test_customer_po_required_defaults_false_and_in_to_dict(db_session):
    c = Customer(code='C-PO1', name='NoPO Corp', is_active=True)
    db.session.add(c); db.session.commit()
    assert c.po_required is False
    assert c.to_dict()['po_required'] is False
    c2 = Customer(code='C-PO2', name='PO Corp', is_active=True, po_required=True)
    db.session.add(c2); db.session.commit()
    assert c2.to_dict()['po_required'] is True
