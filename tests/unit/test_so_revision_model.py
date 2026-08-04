"""Unit tests -- SalesOrderRevision model."""
import pytest
from sqlalchemy.exc import IntegrityError
from app import db
from app.sales_orders.revision_models import SalesOrderRevision

pytestmark = [pytest.mark.unit, pytest.mark.sales_orders]


def test_revision_row_persists_all_fields(db_session):
    rev = SalesOrderRevision(
        sales_order_id=1,
        revision_number=0,
        snapshot_json='{"header": {}, "lines": []}',
        change_summary=None,
        reason=None,
        authorizing_po_number=None,
        amended_by_id=None,
        branch_id=1,
    )
    db_session.add(rev)
    db_session.commit()

    got = SalesOrderRevision.query.filter_by(sales_order_id=1, revision_number=0).one()
    assert got.snapshot_json == '{"header": {}, "lines": []}'
    assert got.amended_at is not None


def test_revision_number_is_unique_per_sales_order(db_session):
    for n in (0, 0):
        db_session.add(SalesOrderRevision(
            sales_order_id=7, revision_number=n,
            snapshot_json='{}', branch_id=1))
    with pytest.raises(IntegrityError) as excinfo:
        db_session.commit()
    error_msg = str(excinfo.value)
    assert 'sales_order_id' in error_msg and 'revision_number' in error_msg
    db_session.rollback()


def test_same_revision_number_allowed_on_different_orders(db_session):
    db_session.add(SalesOrderRevision(sales_order_id=8, revision_number=0,
                                      snapshot_json='{}', branch_id=1))
    db_session.add(SalesOrderRevision(sales_order_id=9, revision_number=0,
                                      snapshot_json='{}', branch_id=1))
    db_session.commit()
    assert SalesOrderRevision.query.filter_by(revision_number=0).count() == 2
