"""An amendment may not shrink or delete a line that is already on order.

Nothing in app/amendments/ changes. The shared validator has always called
PurchaseRequest.consumed_qty() and has_any_child_reference(); they returned 0
and False above a comment reading "no table carries a purchase_request_item_id".
Now one does.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem

pytestmark = [pytest.mark.integration, pytest.mark.purchase_requests]


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
    p = PurchaseRequest(pr_number='GUARD-1', request_date=date(2026, 8, 15),
                        branch_id=main_branch.id, status='approved',
                        created_by_id=admin_user.id)
    p.line_items.append(PurchaseRequestItem(line_number=1, description='Ordered', quantity=10))
    p.line_items.append(PurchaseRequestItem(line_number=2, description='Untouched', quantity=5))
    db_session.add(p)
    db_session.commit()
    return p


@pytest.fixture
def ordered(db_session, main_branch, admin_user, pr):
    po = PurchaseOrder(po_number='GUARD-PO-1', order_date=date(2026, 8, 15),
                       branch_id=main_branch.id, status='approved',
                       vat_treatment='inclusive', created_by_id=admin_user.id)
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description='Ordered', quantity=6, unit_price=1,
        amount=Decimal('6'), source_pr_item_id=pr.line_items[0].id))
    db_session.add(po)
    db_session.commit()
    return po


class TestTheHooksAreReal:

    def test_consumed_qty_reports_the_ordered_amount(self, pr, ordered):
        assert pr.consumed_qty(pr.line_items[0]) == Decimal('6')

    def test_consumed_qty_is_zero_for_an_untouched_line(self, pr, ordered):
        assert pr.consumed_qty(pr.line_items[1]) == Decimal('0')

    def test_has_any_child_reference_is_true_for_an_ordered_line(self, pr, ordered):
        assert pr.has_any_child_reference(pr.line_items[0]) is True

    def test_has_any_child_reference_is_false_for_an_untouched_line(self, pr, ordered):
        """Control: the guard must be per-line, not a blanket freeze."""
        assert pr.has_any_child_reference(pr.line_items[1]) is False

    def test_a_cancelled_po_releases_the_line(self, db_session, pr, ordered):
        ordered.status = 'cancelled'
        db_session.commit()
        assert pr.consumed_qty(pr.line_items[0]) == Decimal('0')
        assert pr.has_any_child_reference(pr.line_items[0]) is False


class TestTheValidatorUsesThem:

    def _amend(self, client, pr, lines):
        import json
        return client.post(f'/purchase-requests/{pr.id}/amend', data={
            'pr_number': pr.pr_number, 'request_date': '2026-08-15',
            'amend_reason': 'Adjusting the requisition after review',
            'row_version': pr.row_version,
            'line_items': json.dumps(lines),
        }, follow_redirects=True)

    def test_shrinking_an_ordered_line_below_what_is_ordered_is_refused(
            self, client, db_session, admin_user, main_branch, pr, ordered):
        _login(client, admin_user, main_branch)
        self._amend(client, pr, [
            {'pr_item_id': pr.line_items[0].id, 'description': 'Ordered', 'quantity': '2'},
            {'pr_item_id': pr.line_items[1].id, 'description': 'Untouched', 'quantity': '5'},
        ])
        assert db.session.get(PurchaseRequestItem, pr.line_items[0].id).quantity == 10

    def test_an_untouched_line_may_still_be_changed(
            self, client, db_session, admin_user, main_branch, pr, ordered):
        """The control that proves the guard is conditional."""
        _login(client, admin_user, main_branch)
        self._amend(client, pr, [
            {'pr_item_id': pr.line_items[0].id, 'description': 'Ordered', 'quantity': '10'},
            {'pr_item_id': pr.line_items[1].id, 'description': 'Untouched', 'quantity': '9'},
        ])
        assert db.session.get(PurchaseRequestItem, pr.line_items[1].id).quantity == 9
