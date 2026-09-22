"""The PR list's Order Status column: has this requisition been ordered, and from whom.

Owner request 2026-09-18: drop the Note column and replace it with a meaningful
order-status column showing the vendor -- pending when there is no order yet,
partially ordered and to which vendor, ordered from vendor under PO.

WHY A COLUMN AND NOT THE STATUS BADGE
-------------------------------------
The list already carries a Status badge that reads "Ordered" / "Partially
Ordered", and a PO # column, and an "ordered chip" saying much the same thing was
deliberately deleted on 2026-09-06 as duplication (see
test_pr_list_chain_columns.py, which forbids that chip's class by name). This
column earns its place on one thing neither of those can say: the VENDOR.

It is also not the badge reworded. `recompute_pr_status` lets DELIVERY OUTRANK
ORDERING -- a fully ordered requisition that has been received stores 'received'
-- so a column driven off `pr.status` would report neither ordered nor partially
ordered for exactly the rows furthest along. The tests below pin that difference
directly, because it is the whole reason the column is computed from the order
links instead.

Assertions are scoped to APPLIED attributes (`class="order-state ..."`), never a
bare class name: the inline <style> block at the end of the template contains
those names, so a bare-substring assertion could never fail.
"""
from datetime import date
from decimal import Decimal

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.purchase_requests]


@pytest.fixture(autouse=True)
def modules_enabled(db_session):
    """Purchase Requisitions is an optional, per-user module and off by default,
    so without this the list route is a 404."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'purchase_requests', 'receiving_reports'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _vendor(db_session, code, name):
    from app.vendors.models import Vendor
    v = Vendor.query.filter_by(code=code).first()
    if v is None:
        v = Vendor(code=code, name=name)
        db_session.add(v); db_session.commit()
    return v


def _pr(db_session, branch, number, quantities=(Decimal('10'),), status='approved'):
    """A requisition with one line per entry in `quantities` (None = unquantified)."""
    from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
    pr = PurchaseRequest(branch_id=branch.id, pr_number=number,
                         request_date=date(2026, 9, 18), status=status,
                         reason='Site needs cement')
    for i, qty in enumerate(quantities, start=1):
        pr.line_items.append(PurchaseRequestItem(
            line_number=i, description='Cement %d' % i, quantity=qty, uom_text='bag'))
    db_session.add(pr); db_session.commit()
    return pr


def _order(db_session, branch, pr, number, vendor, lines, status='approved'):
    """An order pulling `lines` = [(pr_line_index, qty), ...] off the requisition."""
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    po = PurchaseOrder(branch_id=branch.id, po_number=number,
                       order_date=date(2026, 9, 18), status=status,
                       vendor_id=(vendor.id if vendor else None),
                       vendor_name=(vendor.name if vendor else None))
    for n, (idx, qty) in enumerate(lines, start=1):
        po.line_items.append(PurchaseOrderItem(
            line_number=n, description='Cement', quantity=qty,
            source_pr_item_id=pr.line_items[idx].id))
    db_session.add(po); db_session.commit()
    return po


def _cell(client, pr):
    """The rendered Order Status cell for one requisition."""
    body = client.get('/purchase-requests').data.decode()
    assert pr.pr_number in body, 'the requisition is not on the page at all'
    return body


class TestTheColumnReplacedNote:

    def test_the_header_says_order_status(self, client, admin_user, main_branch,
                                          db_session):
        pr = _pr(db_session, main_branch, 'OS-HDR')
        _login(client, admin_user, main_branch)
        body = _cell(client, pr)
        assert '<th>Order Status</th>' in body
        assert '<th>Note</th>' not in body

    def test_the_note_text_is_no_longer_rendered_in_the_row(
            self, client, admin_user, main_branch, db_session):
        """The reason text itself must be gone from the row, not merely the
        header -- otherwise the column was renamed rather than replaced."""
        pr = _pr(db_session, main_branch, 'OS-TEXT')
        _login(client, admin_user, main_branch)
        body = _cell(client, pr)
        assert 'Site needs cement' not in body

    def test_the_deleted_ordered_chip_is_not_resurrected(
            self, client, admin_user, main_branch, db_session):
        """A chip-shaped version of this was tried and rejected on 2026-09-06.
        Whatever this column renders must not reintroduce that class."""
        vendor = _vendor(db_session, 'OS-V1', 'Acme Supply')
        pr = _pr(db_session, main_branch, 'OS-CHIP')
        _order(db_session, main_branch, pr, 'PO-OS-CHIP', vendor, [(0, Decimal('10'))])
        _login(client, admin_user, main_branch)
        assert 'pr-ordered-chip' not in _cell(client, pr)


class TestTheThreeStates:

    def test_a_requisition_with_no_order_reads_pending(
            self, client, admin_user, main_branch, db_session):
        pr = _pr(db_session, main_branch, 'OS-PEND')
        _login(client, admin_user, main_branch)
        assert 'class="order-state order-state--pending">Pending<' in _cell(client, pr)

    def test_a_fully_ordered_requisition_reads_ordered_with_its_vendor(
            self, client, admin_user, main_branch, db_session):
        vendor = _vendor(db_session, 'OS-V2', 'Acme Supply')
        pr = _pr(db_session, main_branch, 'OS-FULL')
        _order(db_session, main_branch, pr, 'PO-OS-FULL', vendor, [(0, Decimal('10'))])
        _login(client, admin_user, main_branch)
        body = _cell(client, pr)
        assert 'class="order-state order-state--ordered">Ordered<' in body
        assert 'Acme Supply' in body

    def test_a_part_ordered_line_reads_partially_ordered_with_its_vendor(
            self, client, admin_user, main_branch, db_session):
        """Four bags ordered of ten requested."""
        vendor = _vendor(db_session, 'OS-V3', 'Beta Hardware')
        pr = _pr(db_session, main_branch, 'OS-PART')
        _order(db_session, main_branch, pr, 'PO-OS-PART', vendor, [(0, Decimal('4'))])
        _login(client, admin_user, main_branch)
        body = _cell(client, pr)
        assert 'class="order-state order-state--partial">Partially ordered<' in body
        assert 'Beta Hardware' in body

    def test_one_line_of_two_ordered_reads_partially_ordered(
            self, client, admin_user, main_branch, db_session):
        vendor = _vendor(db_session, 'OS-V4', 'Gamma Trading')
        pr = _pr(db_session, main_branch, 'OS-2LINE',
                 quantities=(Decimal('10'), Decimal('5')))
        _order(db_session, main_branch, pr, 'PO-OS-2LINE', vendor, [(0, Decimal('10'))])
        _login(client, admin_user, main_branch)
        assert 'order-state--partial' in _cell(client, pr)

    def test_both_lines_ordered_reads_ordered(
            self, client, admin_user, main_branch, db_session):
        vendor = _vendor(db_session, 'OS-V5', 'Delta Depot')
        pr = _pr(db_session, main_branch, 'OS-2DONE',
                 quantities=(Decimal('10'), Decimal('5')))
        _order(db_session, main_branch, pr, 'PO-OS-2DONE', vendor,
               [(0, Decimal('10')), (1, Decimal('5'))])
        _login(client, admin_user, main_branch)
        assert 'order-state--ordered' in _cell(client, pr)


class TestSeveralVendors:

    def test_two_orders_from_two_vendors_name_both(
            self, client, admin_user, main_branch, db_session):
        """A requisition split across suppliers is the case the Status badge and
        the PO # column between them cannot express."""
        v1 = _vendor(db_session, 'OS-V6', 'Acme Supply')
        v2 = _vendor(db_session, 'OS-V7', 'Zenith Metals')
        pr = _pr(db_session, main_branch, 'OS-SPLIT',
                 quantities=(Decimal('10'), Decimal('5')))
        _order(db_session, main_branch, pr, 'PO-OS-S1', v1, [(0, Decimal('10'))])
        _order(db_session, main_branch, pr, 'PO-OS-S2', v2, [(1, Decimal('5'))])
        _login(client, admin_user, main_branch)
        body = _cell(client, pr)
        assert 'order-state--ordered' in body
        assert 'Acme Supply' in body and 'Zenith Metals' in body

    def test_an_order_with_no_vendor_yet_says_so_rather_than_printing_a_blank(
            self, client, admin_user, main_branch, db_session):
        """convert() creates a DRAFT order with no vendor and no prices, so an
        ordered requisition can legitimately have no name to show."""
        pr = _pr(db_session, main_branch, 'OS-NOVEND')
        _order(db_session, main_branch, pr, 'PO-OS-NOVEND', None,
               [(0, Decimal('10'))], status='draft')
        _login(client, admin_user, main_branch)
        body = _cell(client, pr)
        assert 'order-state--ordered' in body
        assert 'vendor not set' in body


class TestACancelledOrderReleasesTheRequisition:
    """COMMITTED_PO governs this column as it governs every allocation sum:
    cancelling an order releases its lines, so the requisition is open again."""

    def test_a_cancelled_order_leaves_the_requisition_pending(
            self, client, admin_user, main_branch, db_session):
        vendor = _vendor(db_session, 'OS-V8', 'Acme Supply')
        pr = _pr(db_session, main_branch, 'OS-CANC')
        _order(db_session, main_branch, pr, 'PO-OS-CANC', vendor,
               [(0, Decimal('10'))], status='cancelled')
        _login(client, admin_user, main_branch)
        body = _cell(client, pr)
        assert 'order-state--pending' in body
        assert 'Acme Supply' not in body


class TestTheColumnIsNotTheStatusBadge:
    """The point of computing this from the order links. In
    recompute_pr_status delivery outranks ordering, so these rows' stored status
    says nothing about how far the ORDERING got."""

    def test_a_received_requisition_still_reads_ordered(
            self, client, admin_user, main_branch, db_session):
        from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
        vendor = _vendor(db_session, 'OS-V9', 'Acme Supply')
        pr = _pr(db_session, main_branch, 'OS-RECD')
        po = _order(db_session, main_branch, pr, 'PO-OS-RECD', vendor,
                    [(0, Decimal('10'))])
        rr = ReceivingReport(branch_id=main_branch.id, rr_number='RR-OS-RECD',
                             receipt_date=date(2026, 9, 18), status='approved',
                             vendor_id=vendor.id, vendor_name=vendor.name)
        rr.line_items.append(ReceivingReportItem(
            line_number=1, purchase_order_item_id=po.line_items[0].id,
            received_quantity=Decimal('10')))
        db_session.add(rr); db_session.commit()

        from app.purchase_requests.allocation import recompute_pr_status
        recompute_pr_status(pr)
        db_session.commit()
        assert pr.status == 'received', 'precondition: delivery outranks ordering'

        _login(client, admin_user, main_branch)
        body = _cell(client, pr)
        assert 'class="order-state order-state--ordered">Ordered<' in body


class TestTheHelperItself:
    """Unit-level, for the shapes the rendered page cannot show cheaply."""

    def test_an_empty_id_list_costs_no_query(self, app, db_session):
        from app.purchase_requests.allocation import order_status_for_pr_ids
        assert order_status_for_pr_ids([]) == {}
        assert order_status_for_pr_ids(None) == {}

    def test_a_none_in_the_id_list_is_ignored(self, app, db_session, main_branch):
        from app.purchase_requests.allocation import order_status_for_pr_ids
        pr = _pr(db_session, main_branch, 'OS-HELP-NONE')
        out = order_status_for_pr_ids([pr.id, None])
        assert set(out) == {pr.id}

    def test_a_requisition_with_no_lines_is_pending(self, app, db_session, main_branch):
        """Nothing to order, so nothing is outstanding -- but it must not read
        'ordered' just because no line is open."""
        from app.purchase_requests.allocation import order_status_for_pr_ids
        pr = _pr(db_session, main_branch, 'OS-HELP-EMPTY', quantities=())
        assert order_status_for_pr_ids([pr.id])[pr.id]['state'] == 'pending'

    def test_an_unquantified_line_is_open_until_an_order_references_it(
            self, app, db_session, main_branch):
        """pr_line_is_open's own rule: a quantity comparison says nothing about a
        line with no quantity, so the test is whether anything references it."""
        from app.purchase_requests.allocation import order_status_for_pr_ids
        vendor = _vendor(db_session, 'OS-V10', 'Acme Supply')
        pr = _pr(db_session, main_branch, 'OS-HELP-NOQTY', quantities=(None,))
        assert order_status_for_pr_ids([pr.id])[pr.id]['state'] == 'pending'

        _order(db_session, main_branch, pr, 'PO-OS-NOQTY', vendor, [(0, None)])
        assert order_status_for_pr_ids([pr.id])[pr.id]['state'] == 'ordered'

    def test_an_order_line_carrying_no_quantity_still_counts_as_a_reference(
            self, app, db_session, main_branch):
        """The reason _has_committed_reference exists separately from the sum: a
        referencing order line may itself carry zero or None."""
        from app.purchase_requests.allocation import order_status_for_pr_ids
        vendor = _vendor(db_session, 'OS-V11', 'Acme Supply')
        pr = _pr(db_session, main_branch, 'OS-HELP-ZERO', quantities=(None,))
        _order(db_session, main_branch, pr, 'PO-OS-ZERO', vendor, [(0, Decimal('0'))])
        assert order_status_for_pr_ids([pr.id])[pr.id]['state'] == 'ordered'

    def test_vendors_are_sorted_and_deduplicated(self, app, db_session, main_branch):
        from app.purchase_requests.allocation import order_status_for_pr_ids
        v1 = _vendor(db_session, 'OS-V12', 'Zenith Metals')
        v2 = _vendor(db_session, 'OS-V13', 'Acme Supply')
        pr = _pr(db_session, main_branch, 'OS-HELP-SORT',
                 quantities=(Decimal('10'), Decimal('5'), Decimal('2')))
        _order(db_session, main_branch, pr, 'PO-OS-SORT1', v1, [(0, Decimal('10'))])
        _order(db_session, main_branch, pr, 'PO-OS-SORT2', v2, [(1, Decimal('5'))])
        _order(db_session, main_branch, pr, 'PO-OS-SORT3', v1, [(2, Decimal('2'))])
        got = order_status_for_pr_ids([pr.id])[pr.id]
        assert got['vendors'] == ['Acme Supply', 'Zenith Metals']

    def test_over_ordering_a_line_does_not_leave_it_open(
            self, app, db_session, main_branch):
        """Requested minus ordered goes negative, which is not positive, so the
        line is closed -- the same arithmetic pr_line_is_open uses."""
        from app.purchase_requests.allocation import order_status_for_pr_ids
        vendor = _vendor(db_session, 'OS-V14', 'Acme Supply')
        pr = _pr(db_session, main_branch, 'OS-HELP-OVER')
        _order(db_session, main_branch, pr, 'PO-OS-OVER', vendor, [(0, Decimal('25'))])
        assert order_status_for_pr_ids([pr.id])[pr.id]['state'] == 'ordered'

    def test_two_part_orders_summing_to_the_request_close_the_line(
            self, app, db_session, main_branch):
        from app.purchase_requests.allocation import order_status_for_pr_ids
        vendor = _vendor(db_session, 'OS-V15', 'Acme Supply')
        pr = _pr(db_session, main_branch, 'OS-HELP-SUM')
        _order(db_session, main_branch, pr, 'PO-OS-SUM1', vendor, [(0, Decimal('6'))])
        assert order_status_for_pr_ids([pr.id])[pr.id]['state'] == 'partial'
        _order(db_session, main_branch, pr, 'PO-OS-SUM2', vendor, [(0, Decimal('4'))])
        assert order_status_for_pr_ids([pr.id])[pr.id]['state'] == 'ordered'

    def test_a_requisition_nobody_asked_about_is_absent_not_pending(
            self, app, db_session, main_branch):
        """The map is keyed by what was asked for, so a caller's .get() miss is
        distinguishable from a genuine 'pending'."""
        from app.purchase_requests.allocation import order_status_for_pr_ids
        pr = _pr(db_session, main_branch, 'OS-HELP-ABSENT')
        other = _pr(db_session, main_branch, 'OS-HELP-ASKED')
        out = order_status_for_pr_ids([other.id])
        assert pr.id not in out
