"""Editing a draft requisition must not orphan the orders already on it.

FOUND 2026-09-06 by simulation, and REACHABLE ONLY because of a change made the
same day. edit() rebuilds a requisition's lines from scratch --
`pr.line_items.clear()` then re-parse -- which assigns fresh ids. models.py says
that strands nothing "because PR has no such child", and that WAS true: edit() is
draft-only and PULLABLE_PR excludes `draft`, so a draft could never have a
purchase order pointing at its lines.

Return to Draft broke that invariant. A `submitted` requisition may be pulled
onto an order (PULLABLE_PR, 2026-08-26) and may now be sent back to draft, so a
draft CAN carry PurchaseOrderItem.source_pr_item_id references. Rebuilding then
deletes the rows those columns point at:

    line id=7, ordered 100 across 2 PO lines
    return to draft -> edit
    -> line ids [12]; row 7 gone; 2 PO lines orphaned; ordered reads 0

The requisition then reports nothing ordered, so the same quantity can be
ordered a second time, and two order lines tie back to nothing.

Two guarantees are needed and both are asserted here: line identity SURVIVES an
edit, and an edit may not shrink a line below what is already ordered against it
-- the guard the amend path has always had via validate_amendment/consumed_qty.
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


def _pulled_pr(db_session, branch, requested='100', ordered='100',
               number='EDITID-PR-1'):
    """A DRAFT requisition that a purchase order already points at -- the state
    Return to Draft makes reachable."""
    from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    from app.vendors.models import Vendor
    v = Vendor.query.filter_by(code='EDITID-V').first()
    if v is None:
        v = Vendor(code='EDITID-V', name='Edit Identity Vendor')
        db_session.add(v); db_session.commit()

    pr = PurchaseRequest(branch_id=branch.id, pr_number=number,
                         request_date=date(2026, 9, 6), status='draft',
                         reason='Site needs cement')
    pr.line_items.append(PurchaseRequestItem(line_number=1, description='Cement',
                                             quantity=Decimal(requested)))
    db_session.add(pr); db_session.commit()

    po = PurchaseOrder(branch_id=branch.id, po_number=f'PO-{number}',
                       order_date=date(2026, 9, 6), status='approved',
                       vendor_id=v.id, vendor_name=v.name)
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description='Cement', quantity=Decimal(ordered),
        source_pr_item_id=pr.line_items[0].id))
    db_session.add(po); db_session.commit()
    return pr


def _edit(client, pr, lines, number=None):
    return client.post(f'/purchase-requests/{pr.id}/edit', data={
        'request_date': '2026-09-06',
        'reason': 'Re-specified',
        'pr_number': number or pr.pr_number,
        'row_version': pr.row_version,
        'line_items': json.dumps(lines),
    }, follow_redirects=True)


class TestLineIdentitySurvives:

    def test_editing_keeps_the_line_id(self, client, accountant_user, main_branch,
                                       db_session):
        """THE regression. A rebuild would renumber it and orphan the order."""
        pr = _pulled_pr(db_session, main_branch)
        old_id = pr.line_items[0].id
        _login(client, accountant_user, main_branch)
        _edit(client, pr, [{'pr_item_id': old_id, 'description': 'Cement',
                            'quantity': 100}])
        db_session.refresh(pr)
        assert [li.id for li in pr.line_items] == [old_id]

    def test_the_order_still_ties_back(self, client, accountant_user, main_branch,
                                       db_session):
        """What the id is FOR: allocation must still see the 100 as ordered."""
        from app.purchase_requests.allocation import pr_line_ordered_qty
        pr = _pulled_pr(db_session, main_branch, number='EDITID-PR-TIE')
        old_id = pr.line_items[0].id
        _login(client, accountant_user, main_branch)
        _edit(client, pr, [{'pr_item_id': old_id, 'description': 'Cement',
                            'quantity': 100}])
        db_session.refresh(pr)
        assert pr_line_ordered_qty(pr.line_items[0]) == Decimal('100')

    def test_no_purchase_order_line_is_orphaned(self, client, accountant_user,
                                                main_branch, db_session):
        from app.purchase_orders.models import PurchaseOrderItem
        from app.purchase_requests.models import PurchaseRequestItem
        pr = _pulled_pr(db_session, main_branch, number='EDITID-PR-ORPH')
        old_id = pr.line_items[0].id
        _login(client, accountant_user, main_branch)
        _edit(client, pr, [{'pr_item_id': old_id, 'description': 'Cement',
                            'quantity': 100}])
        for po_line in PurchaseOrderItem.query.filter_by(
                source_pr_item_id=old_id).all():
            assert db_session.get(PurchaseRequestItem,
                                  po_line.source_pr_item_id) is not None


class TestAnEditMayNotUndercutWhatIsOrdered:

    def test_shrinking_below_the_ordered_quantity_is_refused(
            self, client, accountant_user, main_branch, db_session):
        """The guard the amend path has always had. Without it, preserving ids
        merely moves the defect: the order still points at a line, but at one
        claiming less than was ordered against it."""
        pr = _pulled_pr(db_session, main_branch, requested='100', ordered='100',
                        number='EDITID-PR-SHRINK')
        old_id = pr.line_items[0].id
        _login(client, accountant_user, main_branch)
        _edit(client, pr, [{'pr_item_id': old_id, 'description': 'Cement',
                            'quantity': 10}])
        db_session.refresh(pr)
        assert pr.line_items[0].quantity == Decimal('100')     # unchanged

    def test_deleting_an_ordered_line_is_refused(self, client, accountant_user,
                                                 main_branch, db_session):
        """A SECOND line is added first: a requisition must keep at least one
        item, so posting an empty list would be refused by that rule instead and
        prove nothing about the consumed-quantity guard."""
        from app.purchase_requests.models import PurchaseRequestItem
        pr = _pulled_pr(db_session, main_branch, number='EDITID-PR-DEL')
        ordered_id = pr.line_items[0].id
        pr.line_items.append(PurchaseRequestItem(line_number=2, description='Sand',
                                                 quantity=Decimal('4')))
        db_session.commit()
        spare_id = [li.id for li in pr.line_items if li.id != ordered_id][0]
        _login(client, accountant_user, main_branch)
        # keep only the SPARE -- i.e. drop the line an order points at
        _edit(client, pr, [{'pr_item_id': spare_id, 'description': 'Sand',
                            'quantity': 4}])
        db_session.refresh(pr)
        assert ordered_id in [li.id for li in pr.line_items]

    def test_growing_is_allowed(self, client, accountant_user, main_branch,
                                db_session):
        """CONTROL -- the guard must refuse only what undercuts the order."""
        pr = _pulled_pr(db_session, main_branch, requested='100', ordered='50',
                        number='EDITID-PR-GROW')
        old_id = pr.line_items[0].id
        _login(client, accountant_user, main_branch)
        _edit(client, pr, [{'pr_item_id': old_id, 'description': 'Cement',
                            'quantity': 120}])
        db_session.refresh(pr)
        assert pr.line_items[0].quantity == Decimal('120')


class TestAnUntouchedDraftStillEditsFreely:
    """CONTROL. The ordinary case -- a draft nothing has ordered against -- must
    keep working exactly as before, including adding and removing lines."""

    def _plain_draft(self, db_session, branch, number='EDITID-PR-PLAIN'):
        from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
        pr = PurchaseRequest(branch_id=branch.id, pr_number=number,
                             request_date=date(2026, 9, 6), status='draft',
                             reason='Site needs cement')
        pr.line_items.append(PurchaseRequestItem(line_number=1, description='Cement',
                                                 quantity=Decimal('10')))
        db_session.add(pr); db_session.commit()
        return pr

    def test_a_line_can_still_be_added(self, client, accountant_user, main_branch,
                                       db_session):
        pr = self._plain_draft(db_session, main_branch)
        old_id = pr.line_items[0].id
        _login(client, accountant_user, main_branch)
        _edit(client, pr, [{'pr_item_id': old_id, 'description': 'Cement',
                            'quantity': 10},
                           {'description': 'Sand', 'quantity': 4}])
        db_session.refresh(pr)
        assert len(pr.line_items) == 2

    def test_a_line_can_still_be_removed(self, client, accountant_user, main_branch,
                                         db_session):
        """One of TWO lines -- a requisition must keep at least one item, so
        emptying it is refused by that rule and is not what this asserts."""
        from app.purchase_requests.models import PurchaseRequestItem
        pr = self._plain_draft(db_session, main_branch, number='EDITID-PR-RM')
        keep_id = pr.line_items[0].id
        pr.line_items.append(PurchaseRequestItem(line_number=2, description='Sand',
                                                 quantity=Decimal('4')))
        db_session.commit()
        _login(client, accountant_user, main_branch)
        _edit(client, pr, [{'pr_item_id': keep_id, 'description': 'Cement',
                            'quantity': 10}])
        db_session.refresh(pr)
        assert [li.id for li in pr.line_items] == [keep_id]
