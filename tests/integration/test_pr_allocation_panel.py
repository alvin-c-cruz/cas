"""The requisition detail page says, PER LINE, where the goods got to.

Owner request 2026-09-06: "this should show what PO each line item was ordered
on, and if there is still pending request that needs ordering."

The requisition's own line table answers what was ASKED. It cannot answer what
happened next -- a line may be split across two orders, half delivered, or still
entirely unordered while its siblings are complete. The panel answers that, and
is kept SEPARATE from the line table on purpose: that table is the document
somebody signed, and it should not change shape as the goods move.

Every figure is derived (allocation_panel_rows), never stored, and only
COMMITTED orders and receipts count -- a draft order or an unapproved receipt
must never report a line as ordered or delivered.
"""
from datetime import date
from decimal import Decimal
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.purchase_requests]


@pytest.fixture(autouse=True)
def modules_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'purchase_requests', 'receiving_reports'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _vendor(db_session):
    from app.vendors.models import Vendor
    v = Vendor.query.filter_by(code='ALLOC-V').first()
    if v is None:
        v = Vendor(code='ALLOC-V', name='Allocation Vendor')
        db_session.add(v); db_session.commit()
    return v


def _pr(db_session, branch, quantities, number='ALLOC-PR-1'):
    from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
    pr = PurchaseRequest(branch_id=branch.id, pr_number=number,
                         request_date=date(2026, 9, 6), status='approved',
                         approved_by_id=1, reason='Site needs cement')
    for n, q in enumerate(quantities, start=1):
        pr.line_items.append(PurchaseRequestItem(
            line_number=n, description=f'Item {n}',
            quantity=(Decimal(q) if q is not None else None)))
    db_session.add(pr); db_session.commit()
    return pr


def _order(db_session, branch, pr_item, qty, number='ALLOC-PO-1', status='approved'):
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    v = _vendor(db_session)
    po = PurchaseOrder(branch_id=branch.id, po_number=number,
                       order_date=date(2026, 9, 6), status=status,
                       vendor_id=v.id, vendor_name=v.name)
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description='Item', quantity=Decimal(qty),
        source_pr_item_id=pr_item.id))
    db_session.add(po); db_session.commit()
    return po


def _receive(db_session, branch, po, qty, number='ALLOC-RR-1', status='approved'):
    from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
    v = _vendor(db_session)
    rr = ReceivingReport(branch_id=branch.id, rr_number=number,
                         receipt_date=date(2026, 9, 6), status=status,
                         vendor_id=v.id, vendor_name=v.name)
    rr.line_items.append(ReceivingReportItem(
        line_number=1, purchase_order_item_id=po.line_items[0].id,
        received_quantity=Decimal(qty)))
    db_session.add(rr); db_session.commit()
    return rr


def _rows(pr):
    from app.purchase_requests.allocation import allocation_panel_rows
    return allocation_panel_rows(pr)


class TestTheNumbers:

    def test_a_partly_ordered_line_reports_what_is_left(self, db_session, main_branch):
        """THE question asked: is there anything still to order?"""
        pr = _pr(db_session, main_branch, ['100'])
        _order(db_session, main_branch, pr.line_items[0], '50')
        row = _rows(pr)[0]
        assert row['requested'] == Decimal('100')
        assert row['ordered'] == Decimal('50')
        assert row['open_qty'] == Decimal('50')
        assert row['is_open'] is True

    def test_a_fully_ordered_line_has_nothing_outstanding(self, db_session, main_branch):
        pr = _pr(db_session, main_branch, ['100'], number='ALLOC-PR-FULL')
        _order(db_session, main_branch, pr.line_items[0], '100',
               number='ALLOC-PO-FULL')
        row = _rows(pr)[0]
        assert row['open_qty'] == Decimal('0')
        assert row['is_open'] is False

    def test_an_unordered_line_shows_its_whole_quantity_outstanding(
            self, db_session, main_branch):
        pr = _pr(db_session, main_branch, ['100'], number='ALLOC-PR-NONE')
        row = _rows(pr)[0]
        assert row['ordered'] == Decimal('0')
        assert row['open_qty'] == Decimal('100')

    def test_delivery_is_reported_per_line(self, db_session, main_branch):
        pr = _pr(db_session, main_branch, ['100'], number='ALLOC-PR-RECV')
        po = _order(db_session, main_branch, pr.line_items[0], '100',
                    number='ALLOC-PO-RECV')
        _receive(db_session, main_branch, po, '40', number='ALLOC-RR-RECV')
        row = _rows(pr)[0]
        assert row['received'] == Decimal('40')
        assert row['fully_received'] is False

    def test_lines_are_independent(self, db_session, main_branch):
        """The realistic case: one line done, its sibling untouched."""
        pr = _pr(db_session, main_branch, ['10', '5'], number='ALLOC-PR-MIX')
        _order(db_session, main_branch, pr.line_items[0], '10',
               number='ALLOC-PO-MIX')
        first, second = _rows(pr)
        assert first['open_qty'] == Decimal('0') and first['is_open'] is False
        assert second['open_qty'] == Decimal('5') and second['is_open'] is True


class TestTheDocumentLinks:

    def test_the_ordering_po_is_named_against_its_own_line(self, db_session,
                                                           main_branch):
        pr = _pr(db_session, main_branch, ['10', '5'], number='ALLOC-PR-LINK')
        _order(db_session, main_branch, pr.line_items[1], '5',
               number='ALLOC-PO-LINK')
        first, second = _rows(pr)
        assert first['po_links'] == []                     # not this line
        assert [n for _, n in second['po_links']] == ['ALLOC-PO-LINK']

    def test_a_line_split_across_two_orders_names_both(self, db_session, main_branch):
        pr = _pr(db_session, main_branch, ['100'], number='ALLOC-PR-SPLIT')
        _order(db_session, main_branch, pr.line_items[0], '60', number='ALLOC-PO-A')
        _order(db_session, main_branch, pr.line_items[0], '40', number='ALLOC-PO-B')
        row = _rows(pr)[0]
        assert [n for _, n in row['po_links']] == ['ALLOC-PO-A', 'ALLOC-PO-B']
        assert row['ordered'] == Decimal('100')

    def test_the_receiving_report_is_named(self, db_session, main_branch):
        pr = _pr(db_session, main_branch, ['10'], number='ALLOC-PR-RRLINK')
        po = _order(db_session, main_branch, pr.line_items[0], '10',
                    number='ALLOC-PO-RRLINK')
        _receive(db_session, main_branch, po, '10', number='ALLOC-RR-LINK')
        assert [n for _, n in _rows(pr)[0]['rr_links']] == ['ALLOC-RR-LINK']


class TestOnlyCommittedDocumentsCount:

    def test_a_cancelled_order_releases_the_line(self, db_session, main_branch):
        """A cancelled order must not hold the line, or the buyer cannot see it
        needs reordering."""
        pr = _pr(db_session, main_branch, ['10'], number='ALLOC-PR-CXL')
        po = _order(db_session, main_branch, pr.line_items[0], '10',
                    number='ALLOC-PO-CXL')
        po.status = 'cancelled'; db_session.commit()
        row = _rows(pr)[0]
        assert row['ordered'] == Decimal('0')
        assert row['open_qty'] == Decimal('10')
        assert row['po_links'] == []

    @pytest.mark.parametrize('rr_status', ['draft', 'submitted', 'cancelled'])
    def test_an_uncommitted_receipt_delivers_nothing(self, db_session, main_branch,
                                                     rr_status):
        pr = _pr(db_session, main_branch, ['10'], number=f'ALLOC-PR-{rr_status}')
        po = _order(db_session, main_branch, pr.line_items[0], '10',
                    number=f'ALLOC-PO-{rr_status}')
        _receive(db_session, main_branch, po, '10',
                 number=f'ALLOC-RR-{rr_status}', status=rr_status)
        row = _rows(pr)[0]
        assert row['received'] == Decimal('0')
        assert row['rr_links'] == []


class TestAnUnquantifiedLine:

    def test_open_qty_is_none_not_zero(self, db_session, main_branch):
        """A line with no quantity has no ceiling. Reporting 0 outstanding would
        read as "nothing left to order", which is a claim the data cannot make."""
        pr = _pr(db_session, main_branch, [None], number='ALLOC-PR-NOQTY')
        row = _rows(pr)[0]
        assert row['open_qty'] is None
        assert row['is_open'] is True          # untouched, so still needs ordering


class TestThePanelRenders:

    def test_the_page_shows_the_panel_and_its_figures(self, client, accountant_user,
                                                      main_branch, db_session):
        pr = _pr(db_session, main_branch, ['100'], number='ALLOC-PR-VIEW')
        _order(db_session, main_branch, pr.line_items[0], '50',
               number='ALLOC-PO-VIEW')
        _login(client, accountant_user, main_branch)
        body = client.get(f'/purchase-requests/{pr.id}').data.decode()
        assert 'Ordering &amp; Delivery' in body
        assert 'Still to order' in body
        assert 'ALLOC-PO-VIEW' in body

    def test_it_says_how_many_lines_still_need_ordering(self, client, accountant_user,
                                                        main_branch, db_session):
        pr = _pr(db_session, main_branch, ['10', '5'], number='ALLOC-PR-COUNT')
        _order(db_session, main_branch, pr.line_items[0], '10',
               number='ALLOC-PO-COUNT')
        _login(client, accountant_user, main_branch)
        body = client.get(f'/purchase-requests/{pr.id}').data.decode()
        assert 'line still needs ordering' in body

    def test_a_fully_ordered_requisition_says_so(self, client, accountant_user,
                                                 main_branch, db_session):
        pr = _pr(db_session, main_branch, ['10'], number='ALLOC-PR-DONE')
        _order(db_session, main_branch, pr.line_items[0], '10',
               number='ALLOC-PO-DONE')
        _login(client, accountant_user, main_branch)
        body = client.get(f'/purchase-requests/{pr.id}').data.decode()
        assert 'Every line is fully ordered.' in body


class TestTheTwoSectionsAreDistinguishable:
    """The two tables sit adjacent and carry similar-looking numbers, so each
    needs to say what it IS (owner request 2026-09-06).

    Both use the shared .card-header component rather than a bare <h3>, which
    draws the divider rule and carries a subtitle. Asserted because the visual
    difference is the whole point of the change and nothing else would fail if
    a refactor dropped the headers back to plain headings.
    """

    def test_both_sections_carry_a_titled_header(self, client, accountant_user,
                                                 main_branch, db_session):
        pr = _pr(db_session, main_branch, ['10'], number='ALLOC-PR-HDR')
        _order(db_session, main_branch, pr.line_items[0], '5',
               number='ALLOC-PO-HDR')
        _login(client, accountant_user, main_branch)
        body = client.get(f'/purchase-requests/{pr.id}').data.decode()
        assert 'card-title">Requested Items' in body
        assert 'card-title">Ordering &amp; Delivery' in body

    def test_each_header_says_what_its_table_is(self, client, accountant_user,
                                                main_branch, db_session):
        """The subtitles are what separate "what was asked" from "what has
        happened since" -- without them the two headings alone read as two
        equally-authoritative lists of quantities."""
        pr = _pr(db_session, main_branch, ['10'], number='ALLOC-PR-SUB')
        _login(client, accountant_user, main_branch)
        body = client.get(f'/purchase-requests/{pr.id}').data.decode()
        assert 'What this requisition asked for' in body
        assert 'from purchase orders and receiving reports' in body

    def test_the_header_chips_the_outstanding_count(self, client, accountant_user,
                                                    main_branch, db_session):
        pr = _pr(db_session, main_branch, ['10', '5'], number='ALLOC-PR-CHIP')
        _order(db_session, main_branch, pr.line_items[0], '10',
               number='ALLOC-PO-CHIP')
        _login(client, accountant_user, main_branch)
        body = client.get(f'/purchase-requests/{pr.id}').data.decode()
        assert '1 still to order' in body

    def test_a_finished_requisition_chips_fully_ordered(self, client, accountant_user,
                                                        main_branch, db_session):
        pr = _pr(db_session, main_branch, ['10'], number='ALLOC-PR-CHIPOK')
        _order(db_session, main_branch, pr.line_items[0], '10',
               number='ALLOC-PO-CHIPOK')
        _login(client, accountant_user, main_branch)
        body = client.get(f'/purchase-requests/{pr.id}').data.decode()
        assert 'Fully ordered' in body
        assert 'still to order' not in body
