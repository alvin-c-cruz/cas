"""The backfill must mark reconstructed rows honestly."""
import json
import pytest
from app.sales_orders.revision_models import SalesOrderRevision

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]

RECONSTRUCTED = 'Rev 0 - reconstructed at upgrade, not an original capture'


def test_backfilled_rev0_is_labelled_reconstructed(db_session):
    rev = SalesOrderRevision(sales_order_id=1, revision_number=0,
                             snapshot_json='{}', reason=RECONSTRUCTED, branch_id=1)
    db_session.add(rev)
    db_session.commit()
    got = SalesOrderRevision.query.filter_by(sales_order_id=1).one()
    assert got.reason == RECONSTRUCTED
