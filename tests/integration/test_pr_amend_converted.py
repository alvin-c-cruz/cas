"""A CONVERTED requisition can be amended.

Owner request 2026-09-06, reversing the note that adding demand to a fully
ordered requisition "belongs on a new requisition".

It is the only way to change one at all. return_to_draft() refuses a converted
requisition, and before this so did amend() -- so a requisition that turned out
to need one more item had no route except raising a second requisition, losing
the tie between the demand and the document that recorded it.

Amendment is also the RIGHT route, which is why this was widened rather than
letting a converted requisition go back to draft:

  * a DocumentRevision is written, so the pre-change state is on the record
  * validate_amendment still refuses shrinking or deleting a line below what has
    been ordered against it (consumed_qty)

So the only change permitted on a fully ordered requisition is ADDING demand or
growing a line -- which is exactly the case, and cannot strand an order.

Gated on the module's ordinary approver rule (_approve_gate), not narrowed to
admin.
"""
from datetime import date
from decimal import Decimal
import json
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.purchase_requests]


@pytest.fixture(autouse=True)
def modules_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'purchase_requests'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _converted_pr(db_session, branch, number='AMC-PR-1'):
    """Fully ordered: requested 100, ordered 100, status converted."""
    from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    from app.vendors.models import Vendor
    v = Vendor.query.filter_by(code='AMC-V').first()
    if v is None:
        v = Vendor(code='AMC-V', name='Amend Converted Vendor')
        db_session.add(v); db_session.commit()

    pr = PurchaseRequest(branch_id=branch.id, pr_number=number,
                         request_date=date(2026, 9, 6), status='converted',
                         approved_by_id=1, reason='Site needs cement')
    pr.line_items.append(PurchaseRequestItem(line_number=1, description='Cement',
                                             quantity=Decimal('100')))
    db_session.add(pr); db_session.commit()

    po = PurchaseOrder(branch_id=branch.id, po_number=f'PO-{number}',
                       order_date=date(2026, 9, 6), status='approved',
                       vendor_id=v.id, vendor_name=v.name)
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description='Cement', quantity=Decimal('100'),
        source_pr_item_id=pr.line_items[0].id))
    db_session.add(po); db_session.commit()
    return pr


def _amend(client, pr, lines, reason='One more pallet needed on site.'):
    return client.post(f'/purchase-requests/{pr.id}/amend', data={
        'request_date': '2026-09-06',
        'reason': 'Site needs cement',
        'amend_reason': reason,
        'row_version': pr.row_version,
        'line_items': json.dumps(lines),
    }, follow_redirects=True)


class TestItIsReachable:

    def test_converted_is_in_amend_statuses(self):
        from app.purchase_requests.models import PurchaseRequest
        assert 'converted' in PurchaseRequest.AMEND_STATUSES

    def test_the_amend_page_opens(self, client, accountant_user, main_branch,
                                  db_session):
        """Before this it redirected with "already converted ... amend that
        order instead", leaving no way to change the requisition."""
        pr = _converted_pr(db_session, main_branch, number='AMC-PR-OPEN')
        _login(client, accountant_user, main_branch)
        assert client.get(f'/purchase-requests/{pr.id}/amend').status_code == 200

    def test_the_button_is_offered(self, client, accountant_user, main_branch,
                                   db_session):
        """The template carried its own is_converted() test; keeping it would
        have hidden the only control that can change a converted requisition."""
        pr = _converted_pr(db_session, main_branch, number='AMC-PR-BTN')
        _login(client, accountant_user, main_branch)
        body = client.get(f'/purchase-requests/{pr.id}').data.decode()
        assert f'/purchase-requests/{pr.id}/amend' in body


class TestWhatItPermits:

    def test_a_line_can_be_added(self, client, accountant_user, main_branch,
                                 db_session):
        """The case: fully ordered, and one more item is needed."""
        pr = _converted_pr(db_session, main_branch, number='AMC-PR-ADD')
        keep = pr.line_items[0].id
        _login(client, accountant_user, main_branch)
        _amend(client, pr, [{'pr_item_id': keep, 'description': 'Cement',
                             'quantity': 100},
                            {'description': 'Sand', 'quantity': 20}])
        db_session.refresh(pr)
        assert len(pr.line_items) == 2

    def test_a_line_can_be_grown(self, client, accountant_user, main_branch,
                                 db_session):
        pr = _converted_pr(db_session, main_branch, number='AMC-PR-GROW')
        keep = pr.line_items[0].id
        _login(client, accountant_user, main_branch)
        _amend(client, pr, [{'pr_item_id': keep, 'description': 'Cement',
                             'quantity': 150}])
        db_session.refresh(pr)
        assert pr.line_items[0].quantity == Decimal('150')


class TestWhatItStillRefuses:

    def test_shrinking_below_the_ordered_quantity(self, client, accountant_user,
                                                  main_branch, db_session):
        """consumed_qty is unchanged by this widening -- it is what makes
        amending a fully ordered requisition safe at all."""
        pr = _converted_pr(db_session, main_branch, number='AMC-PR-SHRINK')
        keep = pr.line_items[0].id
        _login(client, accountant_user, main_branch)
        _amend(client, pr, [{'pr_item_id': keep, 'description': 'Cement',
                             'quantity': 10}])
        db_session.refresh(pr)
        assert pr.line_items[0].quantity == Decimal('100')

    def test_staff_may_not_amend(self, client, staff_user, main_branch, db_session):
        """_approve_gate, unchanged: amendment rewrites an approved document."""
        pr = _converted_pr(db_session, main_branch, number='AMC-PR-STAFF')
        keep = pr.line_items[0].id
        _login(client, staff_user, main_branch)
        _amend(client, pr, [{'pr_item_id': keep, 'description': 'Cement',
                             'quantity': 150}])
        db_session.refresh(pr)
        assert pr.line_items[0].quantity == Decimal('100')


class TestTheChangeIsOnTheRecord:

    def test_a_revision_is_written(self, client, accountant_user, main_branch,
                                   db_session):
        """THE reason this went through amend rather than return-to-draft: the
        edit path writes no DocumentRevision, so a converted requisition changed
        that way would leave no snapshot of what it was before."""
        from app.amendments.models import DocumentRevision
        pr = _converted_pr(db_session, main_branch, number='AMC-PR-REV')
        keep = pr.line_items[0].id
        _login(client, accountant_user, main_branch)
        _amend(client, pr, [{'pr_item_id': keep, 'description': 'Cement',
                             'quantity': 150}])
        revs = DocumentRevision.query.filter_by(
            document_type='purchase_requests', document_id=pr.id).all()
        assert revs, 'amending a converted requisition wrote no revision'

    def test_the_line_keeps_its_identity(self, client, accountant_user, main_branch,
                                         db_session):
        """The order points at this row; the amend path updates in place."""
        pr = _converted_pr(db_session, main_branch, number='AMC-PR-ID')
        keep = pr.line_items[0].id
        _login(client, accountant_user, main_branch)
        _amend(client, pr, [{'pr_item_id': keep, 'description': 'Cement',
                             'quantity': 150},
                            {'description': 'Sand', 'quantity': 5}])
        db_session.refresh(pr)
        assert keep in [li.id for li in pr.line_items]
