"""Convert to Purchase Order: take every OPEN line at its full open quantity.

Kept as a shortcut for the common case -- one requisition, one supplier, take
everything. It shares the allocation tail with the picker so the two can never
disagree about what "open" means.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def modules_on(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_requests', 'purchase_orders'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


@pytest.fixture
def pr(db_session, main_branch, admin_user):
    p = PurchaseRequest(pr_number='SC-1', request_date=date(2026, 8, 15),
                        branch_id=main_branch.id, status='approved',
                        created_by_id=admin_user.id)
    p.line_items.append(PurchaseRequestItem(line_number=1, description='A', quantity=10))
    p.line_items.append(PurchaseRequestItem(line_number=2, description='B', quantity=5))
    db_session.add(p)
    db_session.commit()
    return p


class TestTheShortcut:

    def test_it_pulls_every_line_with_its_source_set(self, client, db_session,
                                                     admin_user, main_branch, pr):
        _login(client, admin_user, main_branch)
        client.post(f'/purchase-requests/{pr.id}/convert', follow_redirects=True)
        po = PurchaseOrder.query.filter_by(purchase_request_id=pr.id).first()
        assert po is not None
        assert len(po.line_items) == 2
        assert all(li.source_pr_item_id is not None for li in po.line_items)

    def test_it_leaves_the_requisition_converted(self, client, db_session,
                                                 admin_user, main_branch, pr):
        _login(client, admin_user, main_branch)
        client.post(f'/purchase-requests/{pr.id}/convert', follow_redirects=True)
        assert db.session.get(PurchaseRequest, pr.id).status == 'converted'

    def test_it_takes_only_what_remains_open(self, client, db_session, admin_user,
                                             main_branch, pr):
        """After a partial pick, the shortcut must order the remainder -- not
        the original quantity, which would double-order."""
        po = PurchaseOrder(po_number='SC-PO-PRE', order_date=date(2026, 8, 15),
                           branch_id=main_branch.id, status='draft',
                           vat_treatment='inclusive', created_by_id=admin_user.id)
        po.line_items.append(PurchaseOrderItem(
            line_number=1, description='A', quantity=4, unit_price=1,
            amount=Decimal('4'), source_pr_item_id=pr.line_items[0].id))
        db_session.add(po)
        db_session.commit()

        _login(client, admin_user, main_branch)
        client.post(f'/purchase-requests/{pr.id}/convert', follow_redirects=True)
        new_po = (PurchaseOrder.query.filter_by(purchase_request_id=pr.id)
                  .filter(PurchaseOrder.id != po.id).first())
        by_src = {li.source_pr_item_id: li.quantity for li in new_po.line_items}
        assert by_src[pr.line_items[0].id] == 6
        assert by_src[pr.line_items[1].id] == 5

    def test_a_partially_converted_requisition_can_still_use_it(self, client,
                                                                db_session, admin_user,
                                                                main_branch, pr):
        """The guard used to read status != 'approved', which killed the
        shortcut after the first partial pull."""
        pr.status = 'partially_converted'
        db_session.commit()
        _login(client, admin_user, main_branch)
        client.post(f'/purchase-requests/{pr.id}/convert', follow_redirects=True)
        assert PurchaseOrder.query.filter_by(purchase_request_id=pr.id).first() is not None

    def test_a_fully_converted_requisition_cannot(self, client, db_session,
                                                  admin_user, main_branch, pr):
        """Control: nothing is open, so there is nothing to convert."""
        pr.status = 'converted'
        db_session.commit()
        _login(client, admin_user, main_branch)
        client.post(f'/purchase-requests/{pr.id}/convert', follow_redirects=True)
        assert PurchaseOrder.query.filter_by(purchase_request_id=pr.id).first() is None
