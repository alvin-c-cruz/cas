"""Legacy customer / vendor master import."""
import sqlite3

import pytest

from app import db
from app.customers.models import Customer
from app.vendors.models import Vendor
from scripts.legacy_import.masterdata import import_master_data, legacy_code

pytestmark = [pytest.mark.integration, pytest.mark.legacy_import]


@pytest.fixture()
def conn():
    c = sqlite3.connect(':memory:')
    c.executescript("""
        CREATE TABLE customers (id INTEGER PRIMARY KEY, customer_name TEXT, customer_tin TEXT);
        CREATE TABLE vendors (id INTEGER PRIMARY KEY, vendor_name TEXT, vendor_tin TEXT);
        INSERT INTO customers VALUES (1, 'MONDE MY SAN CORPORATION', '209-152-680-000');
        INSERT INTO customers VALUES (10, 'SYCWIN COATING AND WIRES INC', '000-370-641-00000 (VATABLE)');
        INSERT INTO customers VALUES (126, '  PADDED NAME  ', NULL);
        INSERT INTO vendors  VALUES (2, 'A VENDOR', '111-222-333');
        INSERT INTO vendors  VALUES (344, 'LAST VENDOR', NULL);
    """)
    return c


def test_code_encodes_the_legacy_id():
    assert legacy_code('C', 1) == 'C001'
    assert legacy_code('V', 344) == 'V344'


def test_imports_customers_and_vendors(db_session, conn, admin_user):
    stats = import_master_data(db.session, conn, admin_user.id)
    db.session.commit()

    assert (stats.customers_created, stats.vendors_created) == (3, 2)
    assert Customer.query.count() == 3
    assert Vendor.query.count() == 2

    monde = Customer.query.filter_by(code='C001').one()
    assert monde.name == 'MONDE MY SAN CORPORATION'
    assert monde.tin == '209-152-680-000'
    assert monde.is_active is True
    assert monde.created_by_id == admin_user.id

    assert Vendor.query.filter_by(code='V344').one().name == 'LAST VENDOR'


def test_annotated_tin_is_preserved_verbatim(db_session, conn, admin_user):
    """RIC typed '(VATABLE)' into TINs; the column is String(50) and must keep it."""
    import_master_data(db.session, conn, admin_user.id)
    db.session.commit()
    assert Customer.query.filter_by(code='C010').one().tin == '000-370-641-00000 (VATABLE)'


def test_names_are_trimmed(db_session, conn, admin_user):
    import_master_data(db.session, conn, admin_user.id)
    db.session.commit()
    assert Customer.query.filter_by(code='C126').one().name == 'PADDED NAME'


def test_blank_tin_becomes_null(db_session, conn, admin_user):
    import_master_data(db.session, conn, admin_user.id)
    db.session.commit()
    assert Customer.query.filter_by(code='C126').one().tin is None


def test_rerun_is_idempotent(db_session, conn, admin_user):
    import_master_data(db.session, conn, admin_user.id)
    db.session.commit()

    stats = import_master_data(db.session, conn, admin_user.id)
    db.session.commit()

    assert (stats.customers_created, stats.customers_existing) == (0, 3)
    assert (stats.vendors_created, stats.vendors_existing) == (0, 2)
    assert Customer.query.count() == 3
    assert Vendor.query.count() == 2
