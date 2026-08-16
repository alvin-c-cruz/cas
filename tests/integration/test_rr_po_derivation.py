"""The PO(s) an RR touches are derived from its lines, not from a header column.

These tests passing WITHOUT reading the header FK is what let Task 6 drop it. It is
now gone (migration rrmulti_0001), so the receipt's orders can only come from its
lines -- and the one test here that anchored on a lying header column has been
deleted rather than weakened, its job now done by the schema itself.
"""
from datetime import date
from decimal import Decimal
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]


def _approved_po(db_session, branch, vendor, number, qty=100):
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    po = PurchaseOrder(branch_id=branch.id, po_number=number, order_date=date(2026, 7, 11),
                       vendor_id=vendor.id, vendor_name=vendor.name, status='approved',
                       vat_treatment='inclusive')
    po.line_items.append(PurchaseOrderItem(line_number=1, description='Cement',
                                           quantity=Decimal(str(qty)), unit_price=Decimal('10'),
                                           amount=Decimal(str(qty * 10))))
    po.calculate_totals()
    db_session.add(po); db_session.commit()
    return po


def _make_draft_rr(db_session, branch, header_po, poi_and_qty, number):
    """poi_and_qty: list of (purchase_order_item, received_qty) -- one RR line per pair.
    header_po supplies only the vendor snapshot: there is no header PO column any
    more (dropped in rrmulti_0001), so the receipt's orders come from its lines."""
    from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
    rr = ReceivingReport(branch_id=branch.id, rr_number=number, receipt_date=date(2026, 7, 11),
                         vendor_id=header_po.vendor_id,
                         vendor_name=header_po.vendor_name, status='draft')
    for i, (poi, qty) in enumerate(poi_and_qty, start=1):
        rr.line_items.append(ReceivingReportItem(line_number=i,
                                                 purchase_order_item_id=poi.id,
                                                 received_quantity=Decimal(str(qty))))
    db_session.add(rr); db_session.commit()
    return rr


@pytest.fixture
def rr_one_po(db_session, main_branch, vl_vendor):
    po = _approved_po(db_session, main_branch, vl_vendor, number='PO-A')
    return _make_draft_rr(db_session, main_branch, po,
                          [(po.line_items[0], 10)], number='RR-DERIV-0001')


@pytest.fixture
def rr_two_pos(db_session, main_branch, vl_vendor):
    po_a = _approved_po(db_session, main_branch, vl_vendor, number='PO-A')
    po_b = _approved_po(db_session, main_branch, vl_vendor, number='PO-B')
    return _make_draft_rr(db_session, main_branch, po_a,
                          [(po_a.line_items[0], 10), (po_b.line_items[0], 5)],
                          number='RR-DERIV-0002')


@pytest.fixture
def rr_two_lines_one_po(db_session, main_branch, vl_vendor):
    from app.purchase_orders.models import PurchaseOrderItem
    po = _approved_po(db_session, main_branch, vl_vendor, number='PO-A')
    po.line_items.append(PurchaseOrderItem(line_number=2, description='Sand',
                                           quantity=Decimal('50'), unit_price=Decimal('5'),
                                           amount=Decimal('250')))
    db_session.add(po); db_session.commit()
    return _make_draft_rr(db_session, main_branch, po,
                          [(po.line_items[0], 10), (po.line_items[1], 5)],
                          number='RR-DERIV-0003')


class TestDerivation:

    def test_one_po_reports_that_po(self, db_session, rr_one_po):
        assert [po.po_number for po in rr_one_po.purchase_orders] == ['PO-A']
        assert rr_one_po.po_number_display == 'PO-A'

    def test_two_pos_are_both_listed_and_deduped(self, db_session, rr_two_pos):
        assert [po.po_number for po in rr_two_pos.purchase_orders] == ['PO-A', 'PO-B']
        assert rr_two_pos.po_number_display == '2 POs'

    def test_two_lines_from_ONE_po_report_that_po_once(self, db_session, rr_two_lines_one_po):
        """Control: dedupe must not collapse to 'many' just because there are 2 lines."""
        assert [po.po_number for po in rr_two_lines_one_po.purchase_orders] == ['PO-A']
        assert rr_two_lines_one_po.po_number_display == 'PO-A'

    # `test_header_column_is_ignored_when_it_disagrees_with_the_lines` lived here.
    # It built a receipt whose header FK named PO-H while its only line drew on
    # PO-L, so a header-reading `purchase_orders` failed it. That column no longer
    # exists (rrmulti_0001), so the receipt has no header PO to disagree with the
    # lines and the anchor is unbuildable -- deleted rather than weakened, because
    # what it proved is now guaranteed by the schema.


@pytest.fixture
def rr_no_lines(db_session, main_branch, vl_vendor):
    """A fresh draft with no lines yet -- the zero-PO shape the detail page must not mangle."""
    po = _approved_po(db_session, main_branch, vl_vendor, number='PO-A')
    return _make_draft_rr(db_session, main_branch, po, [], number='RR-DERIV-0005')


@pytest.fixture(autouse=True)
def rr_modules_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'receiving_reports'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


class TestDetailPageLabel:
    """The detail page's PO cell: singular/plural on COUNT, and a dash when there is nothing.

    The label used to pluralize on `!= 1`, so a zero-PO draft read "Purchase Orders:" followed
    by empty space; the list page has always fallen back to an em dash.
    """

    def _cell(self, client, rr):
        resp = client.get(f'/receiving-reports/{rr.id}')
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        start = body.index('<strong>Purchase Order')
        return body[start:body.index('</div>', start)]

    def test_no_pos_reads_singular_with_a_dash(self, client, accountant_user, main_branch,
                                               rr_no_lines):
        _login(client, accountant_user, main_branch)
        cell = self._cell(client, rr_no_lines)
        assert '<strong>Purchase Order:</strong>' in cell     # singular, not "Orders"
        assert '\u2014' in cell                               # em dash, as on the list page

    def test_one_po_reads_singular_with_the_number(self, client, accountant_user, main_branch,
                                                   rr_one_po):
        _login(client, accountant_user, main_branch)
        cell = self._cell(client, rr_one_po)
        assert '<strong>Purchase Order:</strong>' in cell
        assert '>PO-A</a>' in cell and '\u2014' not in cell

    def test_two_pos_read_plural_with_both_numbers(self, client, accountant_user, main_branch,
                                                   rr_two_pos):
        _login(client, accountant_user, main_branch)
        cell = self._cell(client, rr_two_pos)
        assert '<strong>Purchase Orders:</strong>' in cell    # plural only above one
        assert '>PO-A</a>' in cell and '>PO-B</a>' in cell and '\u2014' not in cell
