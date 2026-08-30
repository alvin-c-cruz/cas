"""A requisition's purchase orders are derived from its LINE links.

BUG-PR-PO-COLUMN-READS-HEADER-FK-NOT-LINE-LINKS, owner 2026-08-29 reading the
live list: "isn't PR 00006 already pulled in a PO?" It was -- fully ordered on
PO 00004, and the picker correctly no longer offered it -- but the column showed
an em dash.

Both templates read `PurchaseRequest.purchase_order_id`, a header FK that only
`convert()` ever sets. A requisition pulled through the PO form's picker records
its link on the LINE (`PurchaseOrderItem.source_pr_item_id`) and never touches
the header.

The 2026-08-26 arc made that the NORMAL case: `PULLABLE_PR` gained `submitted`,
while `convert()` still refuses anything not approved -- so for a submitted
requisition the header FK cannot be set at all, and the column is blank by
construction.

RENDER assertions: the fix is what a page DISPLAYS, and a query-level test would
pass while both templates still read the old FK.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache

pytestmark = [pytest.mark.integration, pytest.mark.purchase_requests]


@pytest.fixture(autouse=True)
def _modules_on(app, db_session):
    with app.app_context():
        clear_module_config_cache()
    for key in ('purchase_requests', 'purchase_orders'):
        AppSettings.set_setting('module_enabled:%s' % key, '1')
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _pr(db_session, branch, user, number, qty='1000', status='submitted'):
    pr = PurchaseRequest(pr_number=number, request_date=date(2026, 8, 29),
                         branch_id=branch.id, status=status,
                         created_by_id=user.id)
    pr.line_items.append(PurchaseRequestItem(
        line_number=1, description='For production use',
        quantity=Decimal(qty)))
    db_session.add(pr)
    db_session.commit()
    return pr


def _row_for(data, pr_number):
    """The single <tr> of the list that belongs to `pr_number`.

    Row-scoped because both requisitions render on the SAME page: a bare
    `b'PO-LNK-3' not in data` would fail on the sibling's legitimate link, and
    dropping the sibling is what made this control vacuous to begin with.
    """
    html = data.decode('utf-8')
    rows = [r for r in html.split('<tr') if '>%s<' % pr_number in r]
    assert len(rows) == 1, (
        'expected exactly one row for %s, found %d' % (pr_number, len(rows)))
    return rows[0]


def _po_pulling(db_session, branch, user, number, pr_item, qty, status='submitted'):
    """A purchase order built the way the PICKER builds one: the link lives on
    the line, and the requisition's header FK is deliberately left alone."""
    po = PurchaseOrder(po_number=number, order_date=date(2026, 8, 29),
                       branch_id=branch.id, status=status,
                       vat_treatment='inclusive', created_by_id=user.id)
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description='For production use',
        quantity=Decimal(qty), unit_price=Decimal('50'),
        amount=Decimal(qty) * 50, source_pr_item_id=pr_item.id))
    db_session.add(po)
    db_session.commit()
    return po


class TestTheListColumn:

    def test_a_pulled_requisition_names_its_purchase_order(
            self, client, db_session, admin_user, main_branch):
        """THE REPRODUCTION. Header FK is None throughout -- exactly PR 00006."""
        pr = _pr(db_session, main_branch, admin_user, 'PR-LNK-1')
        _po_pulling(db_session, main_branch, admin_user, 'PO-LNK-1',
                    pr.line_items[0], '1000')
        assert pr.purchase_order_id is None, 'fixture drifted: this must be the pulled shape'

        _login(client, admin_user, main_branch)
        resp = client.get('/purchase-requests')
        assert resp.status_code == 200
        assert b'PR-LNK-1' in resp.data, 'the requisition row did not render'
        assert b'PO-LNK-1' in resp.data, 'the PO column did not name the linked order'

    def test_a_requisition_on_two_orders_names_both(
            self, client, db_session, admin_user, main_branch):
        """A header FK can only ever hold one id. Splitting a requisition across
        two purchase orders is ordinary, and the column must show both."""
        pr = _pr(db_session, main_branch, admin_user, 'PR-LNK-2')
        _po_pulling(db_session, main_branch, admin_user, 'PO-LNK-2A',
                    pr.line_items[0], '400')
        _po_pulling(db_session, main_branch, admin_user, 'PO-LNK-2B',
                    pr.line_items[0], '600')

        _login(client, admin_user, main_branch)
        data = client.get('/purchase-requests').data
        assert b'PO-LNK-2A' in data
        assert b'PO-LNK-2B' in data

    def test_an_untouched_requisition_shows_a_dash(
            self, client, db_session, admin_user, main_branch):
        """CONTROL. The column must not simply print something for every row.

        A SIBLING requisition on the same page IS ordered, so the page really
        does carry a PO number -- the untouched row must not borrow it. Without
        that sibling the assertion is nearly vacuous: an empty database has no
        order for any row to show, and a column that printed the first link it
        could find for every row would still pass.
        """
        ordered = _pr(db_session, main_branch, admin_user, 'PR-LNK-3A')
        _po_pulling(db_session, main_branch, admin_user, 'PO-LNK-3',
                    ordered.line_items[0], '1000')
        _pr(db_session, main_branch, admin_user, 'PR-LNK-3B')

        _login(client, admin_user, main_branch)
        data = client.get('/purchase-requests').data
        assert b'PR-LNK-3B' in data, 'the requisition row did not render'
        assert b'PO-LNK-3' in data, (
            'the sibling row lost its order -- this control proves nothing '
            'unless the page really does carry a PO number somewhere')
        assert 'PO-LNK-3' not in _row_for(data, 'PR-LNK-3B'), (
            "the unordered requisition borrowed another row's purchase order")
        assert '—' in _row_for(data, 'PR-LNK-3B'), (
            'the unordered requisition did not render an em dash')

    def test_a_cancelled_order_does_not_count(
            self, client, db_session, admin_user, main_branch):
        """CONTROL. Cancelling releases the line -- the same reason allocation is
        derived and never stored -- so a cancelled order must not be named."""
        pr = _pr(db_session, main_branch, admin_user, 'PR-LNK-4')
        _po_pulling(db_session, main_branch, admin_user, 'PO-LNK-4',
                    pr.line_items[0], '1000', status='cancelled')
        _login(client, admin_user, main_branch)
        data = client.get('/purchase-requests').data
        assert b'PR-LNK-4' in data, 'the requisition row did not render'
        assert b'PO-LNK-4' not in data, 'a cancelled order was named'


class TestTheDetailPage:

    def test_it_names_the_purchase_order_too(
            self, client, db_session, admin_user, main_branch):
        """detail.html carries the identical header-FK read and must change with
        the list -- fixing one and not the other is how the two disagree."""
        pr = _pr(db_session, main_branch, admin_user, 'PR-LNK-5')
        _po_pulling(db_session, main_branch, admin_user, 'PO-LNK-5',
                    pr.line_items[0], '1000')

        _login(client, admin_user, main_branch)
        resp = client.get('/purchase-requests/%d' % pr.id)
        assert resp.status_code == 200
        assert b'PR-LNK-5' in resp.data, 'the requisition did not render'
        assert b'PO-LNK-5' in resp.data, 'the detail page did not name the linked order'
