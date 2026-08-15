"""The ceiling rule and the picker payload."""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.purchase_requests.allocation import (
    assert_within_open_qty, open_lines_for_branch)
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem

pytestmark = [pytest.mark.unit]


@pytest.fixture
def pr(db_session, main_branch, admin_user):
    p = PurchaseRequest(pr_number='RULE-1', request_date=date(2026, 8, 15),
                        date_needed=date(2026, 9, 1), branch_id=main_branch.id,
                        status='approved', created_by_id=admin_user.id)
    p.line_items.append(PurchaseRequestItem(
        line_number=1, description='Carbide', quantity=20))
    db_session.add(p)
    db_session.commit()
    return p


def _order(db_session, main_branch, admin_user, pr_item, qty, status='draft',
           number='RULE-PO-1'):
    po = PurchaseOrder(po_number=number, order_date=date(2026, 8, 15),
                       branch_id=main_branch.id, status=status,
                       vat_treatment='inclusive', created_by_id=admin_user.id)
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description='Carbide', quantity=qty, unit_price=10,
        amount=Decimal(str(qty)) * 10, source_pr_item_id=pr_item.id))
    db_session.add(po)
    db_session.commit()
    return po


class TestTheCeiling:

    def test_within_the_open_qty_is_allowed(self, pr):
        assert assert_within_open_qty(pr.line_items[0], Decimal('20'), 1) is None

    def test_over_the_open_qty_raises(self, pr):
        with pytest.raises(ValueError) as e:
            assert_within_open_qty(pr.line_items[0], Decimal('21'), 3)
        assert 'Line 3' in str(e.value)
        assert '20' in str(e.value)

    def test_the_ceiling_shrinks_as_lines_are_ordered(self, db_session, main_branch,
                                                      admin_user, pr):
        _order(db_session, main_branch, admin_user, pr.line_items[0], 8)
        assert_within_open_qty(pr.line_items[0], Decimal('12'), 1)
        with pytest.raises(ValueError):
            assert_within_open_qty(pr.line_items[0], Decimal('13'), 1)

    def test_exclude_po_id_restores_the_ceiling(self, db_session, main_branch,
                                                admin_user, pr):
        """Editing a draft PO that already took 8 must still allow 8."""
        po = _order(db_session, main_branch, admin_user, pr.line_items[0], 8)
        assert_within_open_qty(pr.line_items[0], Decimal('8'), 1, exclude_po_id=po.id)

    def test_an_unquantified_line_has_no_ceiling(self, db_session, main_branch,
                                                 admin_user):
        p = PurchaseRequest(pr_number='RULE-2', request_date=date(2026, 8, 15),
                            branch_id=main_branch.id, status='approved',
                            created_by_id=admin_user.id)
        p.line_items.append(PurchaseRequestItem(
            line_number=1, description='Cement, qty to follow'))
        db_session.add(p)
        db_session.commit()
        assert assert_within_open_qty(p.line_items[0], Decimal('999'), 1) is None


class TestThePickerPayload:

    def test_it_lists_an_open_line(self, main_branch, pr):
        rows = open_lines_for_branch(main_branch.id)
        assert len(rows) == 1
        assert rows[0]['pr_number'] == 'RULE-1'
        assert rows[0]['requested'] == '20'
        assert rows[0]['ordered'] == '0'
        assert rows[0]['open'] == '20'

    def test_it_carries_date_needed_for_prioritisation(self, main_branch, pr):
        assert open_lines_for_branch(main_branch.id)[0]['date_needed'] == '2026-09-01'

    def test_a_fully_ordered_line_drops_out(self, db_session, main_branch,
                                            admin_user, pr):
        _order(db_session, main_branch, admin_user, pr.line_items[0], 20)
        assert open_lines_for_branch(main_branch.id) == []

    def test_a_partly_ordered_line_stays_with_the_remainder(self, db_session,
                                                            main_branch, admin_user, pr):
        _order(db_session, main_branch, admin_user, pr.line_items[0], 8)
        rows = open_lines_for_branch(main_branch.id)
        assert rows[0]['ordered'] == '8'
        assert rows[0]['open'] == '12'

    def test_another_branch_is_not_listed(self, db_session, branch_manila,
                                          admin_user, pr):
        assert open_lines_for_branch(branch_manila.id) == []

    def test_a_draft_requisition_is_not_offered(self, db_session, main_branch, pr):
        """Only approved and partially_converted requisitions may be pulled."""
        pr.status = 'draft'
        db_session.commit()
        assert open_lines_for_branch(main_branch.id) == []
