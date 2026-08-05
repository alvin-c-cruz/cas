"""CustomerDeliverySite model — Task 1 of the SO delivery-date-site feature.

Covers: create Customer + 2 delivery sites, ordering-by-name, cascade-delete,
and to_dict() keys.
"""
import pytest
from app import db

pytestmark = [pytest.mark.unit, pytest.mark.models, pytest.mark.customers]


def _make_customer(code='CUST-DS-0001', name='Test Co'):
    from app.customers.models import Customer
    c = Customer(code=code, name=name)
    db.session.add(c)
    db.session.commit()
    return c


def test_create_delivery_site_defaults(db_session):
    from app.customers.models import CustomerDeliverySite
    customer = _make_customer()
    site = CustomerDeliverySite(customer_id=customer.id, name='MY SAN CAINTA')
    db.session.add(site)
    db.session.commit()

    assert site.id is not None
    assert site.customer_id == customer.id
    assert site.name == 'MY SAN CAINTA'
    assert site.is_active is True
    assert site.created_at is not None
    assert site.updated_at is not None


def test_customer_delivery_sites_ordered_by_name(db_session):
    """Customer.delivery_sites comes back ordered by name, regardless of insert order."""
    from app.customers.models import CustomerDeliverySite
    customer = _make_customer(code='CUST-DS-0002')

    site_b = CustomerDeliverySite(customer_id=customer.id, name='MY SAN CALAMBA')
    site_a = CustomerDeliverySite(customer_id=customer.id, name='MY SAN CAINTA')
    db.session.add_all([site_b, site_a])
    db.session.commit()
    db.session.refresh(customer)

    assert [s.name for s in customer.delivery_sites] == ['MY SAN CAINTA', 'MY SAN CALAMBA']


def test_delivery_site_backref_to_customer(db_session):
    from app.customers.models import CustomerDeliverySite
    customer = _make_customer(code='CUST-DS-0003')
    site = CustomerDeliverySite(customer_id=customer.id, name='MY SAN CAINTA')
    db.session.add(site)
    db.session.commit()

    assert site.customer.id == customer.id
    assert site.customer.code == 'CUST-DS-0003'


def test_deleting_customer_cascades_to_delivery_sites(db_session):
    from app.customers.models import Customer, CustomerDeliverySite
    customer = _make_customer(code='CUST-DS-0004')
    site1 = CustomerDeliverySite(customer_id=customer.id, name='MY SAN CAINTA')
    site2 = CustomerDeliverySite(customer_id=customer.id, name='MY SAN CALAMBA')
    db.session.add_all([site1, site2])
    db.session.commit()
    site1_id, site2_id = site1.id, site2.id

    db.session.delete(customer)
    db.session.commit()

    assert db.session.get(CustomerDeliverySite, site1_id) is None
    assert db.session.get(CustomerDeliverySite, site2_id) is None


def test_delivery_site_to_dict_keys(db_session):
    from app.customers.models import CustomerDeliverySite
    customer = _make_customer(code='CUST-DS-0005')
    site = CustomerDeliverySite(customer_id=customer.id, name='MY SAN CAINTA')
    db.session.add(site)
    db.session.commit()

    d = site.to_dict()
    assert d == {
        'id': site.id,
        'customer_id': customer.id,
        'name': 'MY SAN CAINTA',
        'is_active': True,
    }
