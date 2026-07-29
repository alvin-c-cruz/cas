import pytest
from app import db
from app.customers.models import Customer

pytestmark = [pytest.mark.integration, pytest.mark.customers]


def test_vendor_code_defaults_none_and_round_trips_in_to_dict(db_session):
    c1 = Customer(code='C-VC1', name='No Vendor Code Corp', is_active=True)
    db.session.add(c1); db.session.commit()
    assert c1.vendor_code is None
    assert c1.to_dict()['vendor_code'] is None

    c2 = Customer(code='C-VC2', name='Vendor Code Corp', is_active=True, vendor_code='200100')
    db.session.add(c2); db.session.commit()
    assert c2.vendor_code == '200100'
    assert c2.to_dict()['vendor_code'] == '200100'
