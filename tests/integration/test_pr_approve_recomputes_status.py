"""Approving a requisition that was already pulled lands on its TRUE status.

The consequence of letting a `submitted` requisition be pulled (2026-08-26). It
stays `submitted` through the pull -- RECOMPUTABLE_PR deliberately excludes that
status, because approve() and reject() both require it exactly and recomputing
early would delete the approval step. So the requisition arrives at approve()
carrying a status that no longer describes it, and approve() has to settle it.

Two things are tested, and the second is the one that is easy to get wrong: the
LIVE status, and the status recorded in the Rev 0 snapshot. write_revision reads
SNAPSHOT_HEADER_FIELDS, which includes `status`, so recomputing after the
baseline is written leaves Rev 0 permanently claiming `approved` for a
requisition that was already fully ordered. Rev 0 is what every later amendment
is measured against, so that is not a cosmetic difference.
"""
import json
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.amendments.models import DocumentRevision
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem

pytestmark = [pytest.mark.integration, pytest.mark.purchase_requests]


@pytest.fixture(autouse=True)
def pr_enabled(db_session):
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


def _submitted_pr(db_session, branch, qty='10', number='PR-RECOMP-1'):
    pr = PurchaseRequest(branch_id=branch.id, pr_number=number,
                         request_date=date(2026, 8, 26), status='submitted',
                         reason='Site needs cement')
    pr.line_items.append(PurchaseRequestItem(
        line_number=1, description='Cement', quantity=Decimal(qty), uom_text='bag'))
    db_session.add(pr); db_session.commit()
    return pr


def _pull(db_session, branch, pr_item, qty, number='PO-RECOMP-1'):
    """A draft purchase order taking *qty* of the requisition line.

    Draft on purpose: COMMITTED_PO counts drafts, because a line pulled onto a
    draft is spoken for and two buyers must not both claim it.
    """
    po = PurchaseOrder(po_number=number, order_date=date(2026, 8, 26), status='draft',
                       branch_id=branch.id, vat_treatment='inclusive', notes='')
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description='Cement', quantity=Decimal(qty),
        unit_price=Decimal('10.00'), amount=Decimal(qty) * 10,
        source_pr_item_id=pr_item.id))
    db_session.add(po); db_session.commit()
    return po


def _rev0(pr):
    return (DocumentRevision.query
            .filter_by(document_type='purchase_requests', document_id=pr.id,
                       revision_number=0).one())


class TestTheLiveStatus:

    def test_an_untouched_requisition_lands_on_approved(
            self, client, accountant_user, main_branch, db_session):
        """CONTROL. Nothing was pulled, so approval must behave exactly as it
        did before this change -- this is the overwhelmingly common path."""
        _login(client, accountant_user, main_branch)
        pr = _submitted_pr(db_session, main_branch)

        client.post(f'/purchase-requests/{pr.id}/approve', follow_redirects=True)
        db_session.refresh(pr)
        assert pr.status == 'approved'

    def test_a_fully_ordered_requisition_lands_on_converted(
            self, client, accountant_user, main_branch, db_session):
        """Every line already on an order. Leaving it plain `approved` would
        offer a requisition with nothing left to order back to the picker."""
        _login(client, accountant_user, main_branch)
        pr = _submitted_pr(db_session, main_branch, qty='10')
        _pull(db_session, main_branch, pr.line_items[0], '10')

        client.post(f'/purchase-requests/{pr.id}/approve', follow_redirects=True)
        db_session.refresh(pr)
        assert pr.status == 'converted'

    def test_a_partly_ordered_requisition_lands_on_partially_converted(
            self, client, accountant_user, main_branch, db_session):
        _login(client, accountant_user, main_branch)
        pr = _submitted_pr(db_session, main_branch, qty='10')
        _pull(db_session, main_branch, pr.line_items[0], '4')

        client.post(f'/purchase-requests/{pr.id}/approve', follow_redirects=True)
        db_session.refresh(pr)
        assert pr.status == 'partially_converted'

    def test_a_cancelled_order_does_not_count_towards_the_recompute(
            self, client, accountant_user, main_branch, db_session):
        """The recompute reads the SAME derived allocation everything else does,
        so a cancelled order reopens the line with no restore step."""
        _login(client, accountant_user, main_branch)
        pr = _submitted_pr(db_session, main_branch, qty='10')
        po = _pull(db_session, main_branch, pr.line_items[0], '10')
        po.status = 'cancelled'
        db_session.commit()

        client.post(f'/purchase-requests/{pr.id}/approve', follow_redirects=True)
        db_session.refresh(pr)
        assert pr.status == 'approved'


class TestTheRevZeroSnapshot:
    """ORDERING. recompute_pr_status must run BEFORE write_revision.

    SNAPSHOT_HEADER_FIELDS includes `status`, so a recompute placed after the
    baseline leaves Rev 0 claiming `approved` forever -- for a requisition that
    was already fully ordered when it was approved. Rev 0 is the baseline every
    later amendment is measured against; it has to be true.
    """

    def test_rev_0_records_converted_not_approved(
            self, client, accountant_user, main_branch, db_session):
        _login(client, accountant_user, main_branch)
        pr = _submitted_pr(db_session, main_branch, qty='10')
        _pull(db_session, main_branch, pr.line_items[0], '10')

        client.post(f'/purchase-requests/{pr.id}/approve', follow_redirects=True)
        snap = json.loads(_rev0(pr).snapshot_json)
        assert snap['header']['status'] == 'converted'

    def test_rev_0_records_partially_converted(
            self, client, accountant_user, main_branch, db_session):
        _login(client, accountant_user, main_branch)
        pr = _submitted_pr(db_session, main_branch, qty='10')
        _pull(db_session, main_branch, pr.line_items[0], '4')

        client.post(f'/purchase-requests/{pr.id}/approve', follow_redirects=True)
        snap = json.loads(_rev0(pr).snapshot_json)
        assert snap['header']['status'] == 'partially_converted'

    def test_rev_0_for_an_untouched_requisition_still_records_approved(
            self, client, accountant_user, main_branch, db_session):
        """CONTROL on the ordering change: moving the recompute earlier must not
        disturb the snapshot of an ordinary approval."""
        _login(client, accountant_user, main_branch)
        pr = _submitted_pr(db_session, main_branch)

        client.post(f'/purchase-requests/{pr.id}/approve', follow_redirects=True)
        snap = json.loads(_rev0(pr).snapshot_json)
        assert snap['header']['status'] == 'approved'

    def test_exactly_one_baseline_is_written(
            self, client, accountant_user, main_branch, db_session):
        """CONTROL. The recompute sits between the status write and the
        baseline, so it is positioned to disturb Rev 0's uniqueness."""
        _login(client, accountant_user, main_branch)
        pr = _submitted_pr(db_session, main_branch, qty='10')
        _pull(db_session, main_branch, pr.line_items[0], '10')

        client.post(f'/purchase-requests/{pr.id}/approve', follow_redirects=True)
        revs = DocumentRevision.query.filter_by(
            document_type='purchase_requests', document_id=pr.id).all()
        assert len(revs) == 1
        assert revs[0].revision_number == 0
        assert revs[0].reason is None, 'Rev 0 is a baseline, not an amendment'


class TestTheFollowUpMessage:
    """The instruction has to match the status the recompute settled on.

    "Convert it to a Purchase Order" is wrong advice for a requisition that was
    already ordered against before approval: the picker has nothing left to
    offer and convert() would refuse it outright.
    """

    def test_an_untouched_requisition_is_told_to_convert(
            self, client, accountant_user, main_branch, db_session):
        """CONTROL -- the ordinary path keeps the message it has always had."""
        _login(client, accountant_user, main_branch)
        pr = _submitted_pr(db_session, main_branch)
        resp = client.post(f'/purchase-requests/{pr.id}/approve', follow_redirects=True)
        assert b'Convert it to a Purchase Order' in resp.data

    def test_a_fully_ordered_requisition_is_not_told_to_convert(
            self, client, accountant_user, main_branch, db_session):
        _login(client, accountant_user, main_branch)
        pr = _submitted_pr(db_session, main_branch, qty='10')
        _pull(db_session, main_branch, pr.line_items[0], '10')
        resp = client.post(f'/purchase-requests/{pr.id}/approve', follow_redirects=True)
        assert b'Convert it to a Purchase Order' not in resp.data
        assert b'already on a Purchase Order' in resp.data

    def test_a_partly_ordered_requisition_is_told_to_convert_the_rest(
            self, client, accountant_user, main_branch, db_session):
        _login(client, accountant_user, main_branch)
        pr = _submitted_pr(db_session, main_branch, qty='10')
        _pull(db_session, main_branch, pr.line_items[0], '4')
        resp = client.post(f'/purchase-requests/{pr.id}/approve', follow_redirects=True)
        assert b'convert the rest when ready' in resp.data
